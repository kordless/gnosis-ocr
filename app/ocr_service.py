"""
OCR Service - Refactored to work with the external job management system.
Its sole responsibilities are loading the model and running inference on an image.
"""
import os
os.environ['HF_HOME'] = os.environ.get('MODEL_CACHE_PATH', '/app/cache')
os.environ['HF_DATASETS_CACHE'] = os.environ.get('MODEL_CACHE_PATH', '/app/cache')

import gc
import torch
if not hasattr(torch.compiler, 'is_compiling'):
    torch.compiler.is_compiling = lambda: False
import threading
import time
from typing import Dict, Any, Union, List
from PIL import Image
import numpy as np
from transformers import AutoModelForImageTextToText, AutoProcessor, AutoTokenizer
import structlog

from app.config import settings

logger = structlog.get_logger()

class OCRService:
    """Service for performing OCR on images using a pre-loaded model."""
    
    def __init__(self):
        self.model = None
        self.processor = None
        self.tokenizer = None
        self.device = None
        self._model_loaded = False
        self._loading_lock = threading.Lock()

        logger.info("OCR Service initialized - starting background model loading.")
        threading.Thread(target=self.load_model, daemon=True).start()

    def load_model(self):
        """Loads the OCR model and processor from Hugging Face."""
        with self._loading_lock:
            if self._model_loaded:
                return
            
            logger.info("🔄 Starting model loading...")
            try:
                self.device = torch.device("cuda" if torch.cuda.is_available() and settings.device == "cuda" else "cpu")
                logger.info(f"Using device: {self.device}")

                hf_home = os.environ.get('HF_HOME')
                
                model_kwargs = {
                    "torch_dtype": "auto", 
                    "device_map": "auto", 
                    "local_files_only": False,
                    "cache_dir": hf_home, 
                    "trust_remote_code": True
                }
                processor_kwargs = {
                    "local_files_only": False, 
                    "cache_dir": hf_home, 
                    "trust_remote_code": True, 
                    "use_fast": True
                }
                
                # Load model
                self.model = AutoModelForImageTextToText.from_pretrained(settings.model_name, **model_kwargs)
                self.model.eval()
                
                # Load processor
                self.processor = AutoProcessor.from_pretrained(settings.model_name, **processor_kwargs)
                
                # Load tokenizer separately (as in reference)
                self.tokenizer = AutoTokenizer.from_pretrained(settings.model_name, **processor_kwargs)
                
                self._model_loaded = True
                logger.info("✅ Model loading completed successfully.")
            
            except Exception as e:
                logger.error(f"❌ Background model loading failed: {e}", exc_info=True)
                self._model_loaded = False

    def is_ready(self) -> bool:
        """Check if the model is loaded and ready for inference."""
        if not self._model_loaded:
            # Wait a bit for model to load if it's still loading
            max_wait = 30  # seconds
            wait_interval = 0.5
            waited = 0
            
            while not self._model_loaded and waited < max_wait:
                time.sleep(wait_interval)
                waited += wait_interval
                
            if not self._model_loaded:
                logger.error("Model failed to load within timeout period")
                
        return self._model_loaded

    def get_health_status(self) -> Dict[str, Any]:
        """Returns the current status of the model."""
        return {
            "model_loaded": self._model_loaded,
            "device": str(self.device) if self.device else "N/A",
        }

    def run_ocr_on_image(self, image: Image.Image) -> Dict[str, Any]:
        """Runs OCR on a single image. Intended for local/testing use."""
        # This method is less critical but should also wait
        if not self.is_ready():
            logger.warning("Model not ready in run_ocr_on_image, waiting...")
        results = self._process_batch_sync([image])
        return results[0] if results else None

    def run_ocr_on_batch(self, image_batch: List[Image.Image], progress_callback=None) -> List[Dict[str, Any]]:
        """Runs OCR on a batch of images. This is the primary method for cloud processing.
        
        Args:
            image_batch: List of PIL Image objects to process
            progress_callback: Optional callback function(status, message, percent) for progress updates
            
        Returns:
            List of dicts with 'text' key and optionally 'progress_info' for status updates
        """
        # Wait for model to be ready instead of failing
        if not self._model_loaded:
            logger.info("OCR model not ready, waiting for it to load...")
            
            # Notify that we're waiting for model
            if progress_callback:
                progress_callback("loading", "Waiting for OCR model to load...", 0)
            
            max_wait = 300  # 5 minutes max wait
            wait_interval = 1.0
            waited = 0
            
            while not self._model_loaded and waited < max_wait:
                time.sleep(wait_interval)
                waited += wait_interval
                
                # Update progress while waiting
                if int(waited) % 5 == 0:  # Update every 5 seconds
                    percent = min(int((waited / 60) * 100), 90)  # Cap at 90% during loading
                    if progress_callback:
                        progress_callback("loading", f"Loading OCR model... ({waited}s elapsed)", percent)
                    logger.info(f"Still waiting for model to load... ({waited}s elapsed)")
            
            if not self._model_loaded:
                if progress_callback:
                    progress_callback("failed", "OCR model failed to load", 0)
                raise RuntimeError(f"OCR model failed to load after {max_wait} seconds")
                
            logger.info("Model loaded, proceeding with OCR")
            if progress_callback:
                progress_callback("processing", "Model loaded, starting OCR processing...", 100)
            
        return self._process_batch_sync(image_batch, progress_callback)

    def _process_batch_sync(self, image_batch: List[Image.Image], progress_callback=None) -> List[Dict[str, Any]]:
        """Synchronous core OCR processing logic for a batch of images."""
        try:
            batch_size = len(image_batch)
            
            # Use the detailed prompt from the reference implementation
            prompt_text = """Extract the text from the above document as if you were reading it naturally. Return the tables in html format. Return the equations in LaTeX representation. If there is an image in the document and image caption is not present, add a small description of the image inside the <img></img> tag; otherwise, add the image caption inside <img></img>. Watermarks should be wrapped in brackets. Ex: <watermark>OFFICIAL COPY</watermark>. Page numbers should be wrapped in brackets. Ex: <page_number>14</page_number> or <page_number>9/22</page_number>. Prefer using ☐ and ☑ for check boxes."""
            
            # Process each image separately to match reference implementation
            results = []
            
            for idx, image in enumerate(image_batch):
                # Update progress for each image
                if progress_callback and batch_size > 1:
                    percent = int((idx / batch_size) * 100)
                    progress_callback("processing", f"Processing image {idx + 1} of {batch_size}...", percent)
                # Create messages for each image following reference format
                messages = [
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": [
                        {"type": "image"},
                        {"type": "text", "text": prompt_text},
                    ]},
                ]
                
                # Apply chat template
                text = self.processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
                
                # Process inputs
                inputs = self.processor(text=[text], images=[image], padding=True, return_tensors="pt")
                
                if self.device.type == "cuda":
                    inputs = {k: v.to(self.device) for k, v in inputs.items()}
                
                with torch.no_grad():
                    # Generate with higher token limit as in reference
                    output_ids = self.model.generate(**inputs, max_new_tokens=15000, do_sample=False)
                
                # Extract only NEW tokens as in reference implementation
                generated_ids = [output_ids[0][len(inputs['input_ids'][0]):]]
                
                # Decode only the generated tokens
                output_text = self.processor.batch_decode(generated_ids, skip_special_tokens=True, clean_up_tokenization_spaces=True)
                
                logger.debug(f"Generated text for image: {output_text}")
                # Get the text
                text = output_text[0] if output_text else ""
                
                results.append({"text": text.strip()})
            
            return results
            
        except Exception as e:
            logger.error(f"Error during batch processing: {str(e)}", exc_info=True)
            raise
        finally:
            # Clear memory after processing
            if self.device.type == "cuda":
                torch.cuda.empty_cache()
            gc.collect()

# Global instance of the service that will be imported by other parts of the application.
ocr_service = OCRService()
