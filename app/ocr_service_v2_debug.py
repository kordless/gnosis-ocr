"""OCR Service with enhanced debugging for cache issues"""
import os
import io
import gc
import json
import torch
import base64
import traceback
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
from datetime import datetime
from PIL import Image
import pdf2image
import numpy as np
from transformers import AutoModelForImageTextToText, AutoProcessor, AutoTokenizer, AutoConfig
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
        
        # Force offline mode
        os.environ["HF_DATASETS_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["HF_HUB_OFFLINE"] = "1"
        
    def _debug_cache_structure(self):
        """Debug the cache directory structure"""
        debug_info = {
            "environment": {},
            "cache_structure": {},
            "model_files": {}
        }
        
        # Check environment variables
        env_vars = [
            "HF_HOME", "TRANSFORMERS_CACHE", "HUGGINGFACE_HUB_CACHE",
            "MODEL_CACHE_PATH", "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"
        ]
        for var in env_vars:
            debug_info["environment"][var] = os.environ.get(var, "NOT SET")
        
        # Check cache directories
        cache_paths = [
            "/cache",
            "/cache/huggingface",
            "/cache/huggingface/hub",
            f"/cache/huggingface/hub/models--{settings.model_name.replace('/', '--')}"
        ]
        
        for path in cache_paths:
            if os.path.exists(path):
                debug_info["cache_structure"][path] = {
                    "exists": True,
                    "is_dir": os.path.isdir(path),
                    "contents": []
                }
                if os.path.isdir(path):
                    try:
                        contents = os.listdir(path)[:20]  # First 20 items
                        debug_info["cache_structure"][path]["contents"] = contents
                    except Exception as e:
                        debug_info["cache_structure"][path]["error"] = str(e)
            else:
                debug_info["cache_structure"][path] = {"exists": False}
        
        # Check specific model directory
        model_dir = Path(f"/cache/huggingface/hub/models--{settings.model_name.replace('/', '--')}")
        if model_dir.exists():
            # Check refs
            refs_dir = model_dir / "refs"
            if refs_dir.exists():
                debug_info["model_files"]["refs"] = {}
                for ref_file in refs_dir.iterdir():
                    try:
                        with open(ref_file) as f:
                            debug_info["model_files"]["refs"][ref_file.name] = f.read().strip()
                    except Exception as e:
                        debug_info["model_files"]["refs"][ref_file.name] = f"Error: {e}"
            
            # Check snapshots
            snapshots_dir = model_dir / "snapshots"
            if snapshots_dir.exists():
                debug_info["model_files"]["snapshots"] = {}
                for snapshot in snapshots_dir.iterdir():
                    if snapshot.is_dir():
                        files = list(snapshot.iterdir())
                        debug_info["model_files"]["snapshots"][snapshot.name] = {
                            "file_count": len(files),
                            "files": [f.name for f in files[:20]],
                            "total_size": sum(f.stat().st_size for f in files if f.is_file())
                        }
        
        return debug_info
    
    def load_model(self):
        """Load the OCR model with enhanced debugging"""
        if self._model_loaded:
            logger.debug("Model already loaded")
            return
        
        try:
            logger.info("Starting model load process...")
            
            # Debug cache structure
            debug_info = self._debug_cache_structure()
            logger.info("Cache debug info", debug_info=debug_info)
            
            # Set device
            if torch.cuda.is_available() and settings.device == "cuda":
                self.device = torch.device("cuda")
                logger.info(f"Using GPU: {torch.cuda.get_device_name(0)}")
            else:
                self.device = torch.device("cpu")
                logger.info("Using CPU")
            
            # Try different cache configurations
            cache_configs = [
                {
                    "cache_dir": "/cache/huggingface",
                    "local_files_only": True,
                    "trust_remote_code": True,
                },
                {
                    "cache_dir": "/cache/huggingface/hub",
                    "local_files_only": True,
                    "trust_remote_code": True,
                },
                {
                    # Let it use default paths
                    "local_files_only": True,
                    "trust_remote_code": True,
                }
            ]
            
            loaded = False
            for i, cache_config in enumerate(cache_configs):
                try:
                    logger.info(f"Trying cache config {i+1}/{len(cache_configs)}", config=cache_config)
                    
                    # Remove any .no_exist files
                    if "cache_dir" in cache_config:
                        model_dir = os.path.join(
                            cache_config["cache_dir"], 
                            "hub" if not cache_config["cache_dir"].endswith("hub") else "",
                            f"models--{settings.model_name.replace('/', '--')}"
                        )
                        no_exist_file = os.path.join(model_dir, ".no_exist")
                        if os.path.exists(no_exist_file):
                            logger.warning(f"Removing .no_exist blocker: {no_exist_file}")
                            try:
                                os.remove(no_exist_file)
                            except Exception as e:
                                logger.error(f"Failed to remove .no_exist: {e}")
                    
                    # Try loading tokenizer first
                    logger.info("Loading tokenizer...")
                    tokenizer = AutoTokenizer.from_pretrained(
                        settings.model_name,
                        **cache_config
                    )
                    logger.info("✅ Tokenizer loaded successfully")
                    
                    # Try loading processor
                    logger.info("Loading processor...")
                    self.processor = AutoProcessor.from_pretrained(
                        settings.model_name,
                        **cache_config
                    )
                    logger.info("✅ Processor loaded successfully")
                    
                    # Try loading model
                    logger.info("Loading model...")
                    self.model = AutoModelForImageTextToText.from_pretrained(
                        settings.model_name,
                        torch_dtype=torch.float16 if self.device.type == "cuda" else torch.float32,
                        device_map="auto" if self.device.type == "cuda" else None,
                        **cache_config
                    )
                    logger.info("✅ Model loaded successfully")
                    
                    if self.device.type == "cuda":
                        self.model = self.model.to(self.device)
                    
                    loaded = True
                    break
                    
                except Exception as e:
                    logger.error(f"Failed with config {i+1}: {str(e)}")
                    continue
            
            if not loaded:
                raise Exception("Failed to load model with any cache configuration")
            
            self._model_loaded = True
            logger.info("Model initialization complete")
            
        except Exception as e:
            logger.error("Failed to initialize model", error=str(e), traceback=traceback.format_exc())
            # Include debug info in the error for visibility
            error_with_debug = {
                "error": str(e),
                "cache_debug": self._debug_cache_structure()
            }
            raise Exception(f"Model loading failed: {json.dumps(error_with_debug, indent=2)}")
    
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
            images = pdf2image.convert_from_bytes(
                pdf_content,
                dpi=300,
                fmt='PNG',
                thread_count=4
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
    
    def clear_memory(self):
        """Clear GPU memory"""
        if self.device and self.device.type == "cuda":
            torch.cuda.empty_cache()
        gc.collect()

# Global instance
ocr_service = OCRService()