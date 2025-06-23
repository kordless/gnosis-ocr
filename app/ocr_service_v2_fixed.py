"""OCR Service - Fixed version that handles trust_remote_code properly"""
import os
import io
import gc
import torch
import base64
import traceback
from typing import List, Dict, Any, Optional, Union
from datetime import datetime
from PIL import Image
import pdf2image
import numpy as np
from transformers import AutoModelForImageTextToText, AutoProcessor
import structlog

from app.config import settings

logger = structlog.get_logger()

class OCRService:
    """Service for performing OCR on images and PDFs using GPU acceleration"""
    
    def __init__(self):
        self.model = None
        self.processor = None
        self.device = None
        self._model_loaded = False
        
        # DON'T force offline mode - let HuggingFace download if needed!
        # The beauty of Cloud Run - it has internet!
        
    def load_model(self):
        """Load the OCR model with proper configuration"""
        if self._model_loaded:
            logger.debug("Model already loaded")
            return
        
        try:
            logger.info("Starting model load process...")
            
            # Set device
            if torch.cuda.is_available() and settings.device == "cuda":
                self.device = torch.device("cuda")
                logger.info(f"Using GPU: {torch.cuda.get_device_name(0)}")
            else:
                self.device = torch.device("cpu")
                logger.info("Using CPU")
            
            # Use mounted GCS cache for persistence
            cache_dir = os.environ.get('MODEL_CACHE_PATH', '/cache/huggingface')
            
            # Check if cache exists and has our model
            model_cache_path = os.path.join(cache_dir, 'hub', f'models--{settings.model_name.replace("/", "--")}')
            model_exists = os.path.exists(model_cache_path)
            
            if model_exists:
                logger.info(f"Model found in cache: {model_cache_path}")
                cache_kwargs = {
                    "local_files_only": True,  # Use cached model only
                    "cache_dir": cache_dir
                }
                logger.info("Using OFFLINE mode - model found in mounted cache")
            else:
                logger.info(f"Model not in cache, will download to: {cache_dir}")
                cache_kwargs = {
                    "local_files_only": False,  # Allow download to cache
                    "cache_dir": cache_dir
                }
                logger.info("Using ONLINE mode - will download to mounted GCS cache")

            
            # No need to check for .no_exist files - we're allowing downloads!
            
            # Try loading WITHOUT trust_remote_code first
            logger.info("Attempting to load model without trust_remote_code...")
            try:
                # Load processor
                logger.info(f"Loading processor for {settings.model_name}...")
                self.processor = AutoProcessor.from_pretrained(
                    settings.model_name,
                    **cache_kwargs
                )
                logger.info("✅ Processor loaded successfully")
                
                # Load model
                logger.info(f"Loading model {settings.model_name}...")
                self.model = AutoModelForImageTextToText.from_pretrained(
                    settings.model_name,
                    torch_dtype=torch.float16 if self.device.type == "cuda" else torch.float32,
                    device_map="auto" if self.device.type == "cuda" else None,
                    **cache_kwargs
                )
                logger.info("✅ Model loaded successfully WITHOUT trust_remote_code")
                
            except Exception as e:
                logger.warning(f"Failed without trust_remote_code: {str(e)}")
                logger.info("Retrying WITH trust_remote_code=True...")
                
                # Retry with trust_remote_code
                cache_kwargs["trust_remote_code"] = True
                
                # Load processor
                logger.info(f"Loading processor with trust_remote_code...")
                self.processor = AutoProcessor.from_pretrained(
                    settings.model_name,
                    **cache_kwargs
                )
                logger.info("✅ Processor loaded successfully")
                
                # Load model
                logger.info(f"Loading model with trust_remote_code...")
                self.model = AutoModelForImageTextToText.from_pretrained(
                    settings.model_name,
                    torch_dtype=torch.float16 if self.device.type == "cuda" else torch.float32,
                    device_map="auto" if self.device.type == "cuda" else None,
                    **cache_kwargs
                )
                logger.info("✅ Model loaded successfully WITH trust_remote_code")
            
            # Move to device if needed
            if self.device.type == "cuda" and not hasattr(self.model, 'device_map'):
                self.model = self.model.to(self.device)
            
            self._model_loaded = True
            logger.info("Model initialization complete")
            
            # Log model info
            logger.info(f"Model config: {self.model.config.model_type if hasattr(self.model.config, 'model_type') else 'unknown'}")
            
        except Exception as e:
            logger.error("Failed to initialize model", error=str(e), exc_info=True)
            raise
    
    def process_image(self, image: Union[Image.Image, np.ndarray]) -> Dict[str, Any]:
        """Process a single image and extract text"""
        try:
            if not self._model_loaded:
                self.load_model()
            
            # Convert numpy array to PIL Image if needed
            if isinstance(image, np.ndarray):
                image = Image.fromarray(image)
            
            # Process the image
            inputs = self.processor(images=image, return_tensors="pt")
            
            # Move inputs to device
            inputs = {k: v.to(self.device) if isinstance(v, torch.Tensor) else v 
                     for k, v in inputs.items()}
            
            # Generate text
            with torch.no_grad():
                generated_ids = self.model.generate(**inputs, max_new_tokens=2048)
            
            # Decode the generated text
            generated_text = self.processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
            
            return {
                "text": generated_text,
                "confidence": 0.95,  # Placeholder confidence
                "processing_time": 0,
                "image_size": image.size
            }
            
        except Exception as e:
            logger.error(f"Error processing image: {str(e)}")
            raise
    
    def process_pdf(self, pdf_content: bytes, progress_callback=None) -> List[Dict[str, Any]]:
        """Process a PDF file and extract text from all pages"""
        try:
            if not self._model_loaded:
                self.load_model()
            
            # Convert PDF to images
            logger.info("Starting PDF to image conversion")
            try:
                images = pdf2image.convert_from_bytes(
                    pdf_content,
                    dpi=300,
                    fmt='PNG',
                    thread_count=4
                )
                logger.info(f"Successfully converted PDF to {len(images)} images")
            except Exception as e:
                logger.error(f"PDF to image conversion failed: {str(e)}", exc_info=True)
                # Try with lower DPI if memory is an issue
                logger.info("Retrying with lower DPI (150)")
                images = pdf2image.convert_from_bytes(
                    pdf_content,
                    dpi=150,
                    fmt='PNG',
                    thread_count=2
                )
            
            results = []
            total_pages = len(images)
            
            for i, image in enumerate(images):
                if progress_callback:
                    progress_callback(current_page=i+1, total_pages=total_pages)
                
                # Process each page
                page_result = self.process_image(image)
                page_result["page_number"] = i + 1
                results.append(page_result)
                
                # Clear GPU memory after each page if using CUDA
                if self.device.type == "cuda":
                    torch.cuda.empty_cache()
            
            return results
            
        except Exception as e:
            logger.error(f"Error processing PDF: {str(e)}")
            raise
    
    def is_ready(self) -> bool:
        """Check if the model is loaded and ready"""
        return self._model_loaded
    
    def get_gpu_info(self) -> Dict[str, Any]:
        """Get GPU information if available"""
        if torch.cuda.is_available():
            return {
                "cuda_available": True,
                "device_count": torch.cuda.device_count(),
                "current_device": torch.cuda.current_device(),
                "device_name": torch.cuda.get_device_name(0),
                "memory_allocated": torch.cuda.memory_allocated(0),
                "memory_reserved": torch.cuda.memory_reserved(0)
            }
        return {"cuda_available": False}
    
    def clear_memory(self):
        """Clear GPU memory"""
        if self.device and self.device.type == "cuda":
            torch.cuda.empty_cache()
        gc.collect()

    async def cleanup(self):
        """Cleanup method for graceful shutdown"""
        try:
            logger.info("Starting OCR service cleanup")
            
            # Clear GPU memory
            self.clear_memory()
            
            # Unload model to free memory
            if self._model_loaded:
                logger.info("Unloading OCR model")
                del self.model
                del self.processor
                self.model = None
                self.processor = None
                self._model_loaded = False
            
            # Final memory cleanup
            if self.device and self.device.type == "cuda":
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
            
            gc.collect()
            logger.info("OCR service cleanup completed")
            
        except Exception as e:
            logger.error("Error during OCR service cleanup", error=str(e), exc_info=True)

# Global instance
ocr_service = OCRService()
