"""OCR Service - Offline-only version that assumes model is pre-loaded"""

# ALLOW ONLINE MODE - HYBRID APPROACH
import os
# Remove offline restrictions - allow downloads when needed
# os.environ['HF_HUB_OFFLINE'] = '1'
# os.environ['TRANSFORMERS_OFFLINE'] = '1' 
# os.environ['HF_DATASETS_OFFLINE'] = '1'
# os.environ['HF_OFFLINE'] = '1'


# Set HuggingFace home to our cache directory - ALWAYS use consistent path
# Use HF_HOME (the new standard) instead of deprecated TRANSFORMERS_CACHE
os.environ['HF_HOME'] = os.environ.get('MODEL_CACHE_PATH', '/app/cache')
os.environ['HF_DATASETS_CACHE'] = os.environ.get('MODEL_CACHE_PATH', '/app/cache')



import io
import gc
import torch
import base64
import traceback
import threading
import uuid
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
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
        self._loading = False
        self._download_progress = {"status": "not_started", "progress": 0, "message": ""}
        
        # Job management for production-grade processing
        self.jobs = {}  # Store all jobs by ID {job_id: {status, data, result, created, etc}}
        self.job_queue = []  # Queue for when model not ready
        self.executor = ThreadPoolExecutor(max_workers=2)
        
        # Model loading strategy based on environment
        if os.environ.get('RUNNING_IN_CLOUD') == 'true':
            # Cloud Run: Lazy loading to avoid memory issues during uploads
            logger.info("OCR Service initialized for cloud - model will load when first job is processed")
        else:
            # Local: Eager loading in background thread for immediate availability
            logger.info("OCR Service initialized for local - starting background model loading")
            threading.Thread(target=self._background_load, daemon=True).start()

    def _background_load(self):
        """Background model loading with job queue processing"""
        self._loading = True
        try:
            logger.info("🔄 Starting background model loading...")
            self.load_model()  # Your existing load_model code
            self._model_loaded = True
            logger.info("✅ Background model loading completed successfully")
            
            # Process any queued jobs
            logger.info(f"📋 Processing {len(self.job_queue)} queued jobs...")
            for job_id in list(self.job_queue):
                self.process_job_async(job_id)
                self.job_queue.remove(job_id)
                
        except Exception as e:
            logger.error(f"❌ Background model loading failed: {e}")
            self._model_loaded = False
        finally:
            self._loading = False

    def health_check(self):
        """Health check endpoint (docext pattern)"""
        return {
            "model_loaded": self._model_loaded,
            "loading": self._loading,
            "status": "ready" if self._model_loaded else "loading" if self._loading else "failed"
        }

    def get_model_status(self):
        """Get the current model loading status"""
        return {
            "loaded": self._model_loaded,
            "status": self._download_progress.get("status", "not_started"),
            "message": self._download_progress.get("message", "")
        }

        
    def load_model(self):
        """Load the OCR model from local cache only - no downloads allowed"""
        if self._model_loaded:
            logger.debug("Model already loaded")
            return
        
        try:
            logger.info("Starting offline model load process...")
            self._download_progress = {"status": "loading", "progress": 0, "message": "Checking local cache..."}
            
            # Set device - debug NVIDIA/CUDA detection
            logger.info(f"CUDA available: {torch.cuda.is_available()}")
            logger.info(f"Settings device: {settings.device}")
            logger.info(f"CUDA_VISIBLE_DEVICES: {os.environ.get('CUDA_VISIBLE_DEVICES', 'not set')}")
            logger.info(f"PyTorch version: {torch.__version__}")
            logger.info(f"PyTorch CUDA compiled version: {torch.version.cuda}")
            
            # Check nvidia-smi equivalent
            try:
                import subprocess
                result = subprocess.run(['nvidia-smi'], capture_output=True, text=True, timeout=10)
                logger.info(f"nvidia-smi exit code: {result.returncode}")
                if result.stdout:
                    logger.info(f"nvidia-smi output: {result.stdout[:500]}")
                if result.stderr:
                    logger.info(f"nvidia-smi stderr: {result.stderr[:200]}")
            except Exception as e:
                logger.info(f"nvidia-smi failed: {e}")
            
            if torch.cuda.is_available() and settings.device == "cuda":
                self.device = torch.device("cuda")
                logger.info(f"Using GPU: {torch.cuda.get_device_name(0)}")
            else:
                self.device = torch.device("cpu")
                logger.info("Using CPU")
            
            # Use mounted cache directory - DEFAULT TO /app/cache which is what Docker uses!
            cache_dir = os.environ.get('MODEL_CACHE_PATH', '/app/cache')
            
            # DETAILED LOGGING - Let's see what's actually happening
            logger.info(f"=== CACHE DIRECTORY INVESTIGATION ===")
            logger.info(f"Environment MODEL_CACHE_PATH: {os.environ.get('MODEL_CACHE_PATH')}")
            logger.info(f"Environment HF_HOME: {os.environ.get('HF_HOME')}")
            logger.info(f"Using cache_dir: {cache_dir}")
            logger.info(f"cache_dir exists: {os.path.exists(cache_dir)}")
            
            # Runtime debug - what's actually in the cache?
            try:
                hub_contents = os.listdir(os.path.join(cache_dir, 'hub'))
                logger.info(f"Hub contents at runtime: {hub_contents}")
            except Exception as e:
                logger.warning(f"Could not list hub contents: {e}")

            
            if os.path.exists(cache_dir):
                cache_contents = os.listdir(cache_dir)
                logger.info(f"cache_dir contents: {cache_contents}")
                
                # Check for hub directory
                hub_path = os.path.join(cache_dir, 'hub')
                if os.path.exists(hub_path):
                    hub_contents = os.listdir(hub_path)
                    logger.info(f"hub directory exists with contents: {hub_contents}")
                else:
                    logger.warning(f"hub directory does NOT exist at: {hub_path}")
            
            # Let HuggingFace handle cache resolution - don't manually check paths!
            logger.info(f"Model name from settings: {settings.model_name}")
            logger.info("Letting HuggingFace resolve cache location...")

            self._download_progress = {"status": "loading", "progress": 20, "message": "Loading model from cache..."}
            
            # Load model FIRST (like the working code does)
            logger.info("Loading model from local cache...")
            
            # Define kwargs OUTSIDE try block so they're available in except
            # Use HF_HOME for cache_dir to ensure proper path resolution
            hf_home = os.environ.get('HF_HOME', cache_dir)
            
            # Smart device mapping based on available VRAM
            if self.device.type == "cuda":
                vram_gb = torch.cuda.get_device_properties(0).total_memory / 1024**3
                model_memory_needed = 3.5  # float16 approximate size
                
                if vram_gb > model_memory_needed + 1.0:  # 1GB buffer for operations
                    device_map = None
                    offload_folder = None
                    logger.info(f"Model will fit in {vram_gb:.1f}GB VRAM, using direct GPU loading")
                else:
                    # Use sequential split with disk offloading for better stability
                    device_map = "sequential"
                    offload_folder = os.path.join(cache_dir, "offload")
                    os.makedirs(offload_folder, exist_ok=True)
                    logger.info(f"Only {vram_gb:.1f}GB VRAM available, using sequential split with disk offload")
                    logger.info(f"Offload folder: {offload_folder}")
            else:
                device_map = None  # CPU only
                offload_folder = None
                logger.info("Using CPU only")
            
            # Note: Flash Attention removed - using standard attention for maximum compatibility
            flash_attn_available = False
            logger.info("ℹ️  Using standard attention implementation")

            
            model_kwargs = {
                "torch_dtype": "auto",
                "device_map": "auto", 
                "local_files_only": False,  # Allow downloads when needed
                "cache_dir": hf_home,  # Use HF_HOME to match download location
                "trust_remote_code": True,  # Need this for Nanonets model
                "force_download": False,  # Don't re-download if cache exists
                "resume_download": False  # Don't resume partial downloads
            }

            
            processor_kwargs = {
                "local_files_only": False,  # Allow downloads when needed
                "cache_dir": hf_home,  # Use HF_HOME to match download location
                "trust_remote_code": True,  # Need this for Nanonets model
                "force_download": False,  # Don't re-download if cache exists
                "resume_download": False,  # Don't resume partial downloads
                "use_fast": True,  # Use fast image processor for better performance
                "min_pixels": 256 * 28 * 28,  # ~200K pixels - memory optimization
                "max_pixels": 1280 * 28 * 28   # ~1M pixels - prevent memory explosion
            }

            
            try:
                logger.info(f"Attempting to load model with kwargs: {model_kwargs}")
                self.model = AutoModelForImageTextToText.from_pretrained(
                    settings.model_name,
                    **model_kwargs
                )
                self.model.eval()
                logger.info("✅ Model loaded successfully from cache")



                self._download_progress = {"status": "loading", "progress": 60, "message": "Loading processor from cache..."}
                
                # Now load processor AFTER model (following working pattern)
                logger.info(f"Loading processor with kwargs: {processor_kwargs}")
                self.processor = AutoProcessor.from_pretrained(
                    settings.model_name,
                    **processor_kwargs
                )
                logger.info("✅ Processor loaded successfully from cache")


                
                # Optional: Load tokenizer separately (like working code)
                try:
                    from transformers import AutoTokenizer
                    self.tokenizer = AutoTokenizer.from_pretrained(
                        settings.model_name,
                        **processor_kwargs
                    )
                    logger.info("✅ Tokenizer loaded successfully from cache")
                except Exception as tok_e:
                    logger.warning(f"Tokenizer load skipped: {str(tok_e)}")
                    self.tokenizer = None
                
            except RuntimeError as e:
                if "can't move a model" in str(e).lower() and "offloaded" in str(e).lower():
                    logger.error("Accelerate offloading error detected!")
                    logger.error("This happens when model was partially downloaded or cache was moved.")
                    logger.error("Solution: Delete cache and re-download, or use device_map='auto'")
                    raise RuntimeError(
                        "Model has offloaded layers and cannot be moved. "
                        "This usually means the cache is corrupted or was moved after download. "
                        "Please rebuild the Docker image or delete /app/cache and re-download."
                    ) from e
                else:
                    raise
            except Exception as e:
                logger.warning(f"Failed without trust_remote_code: {str(e)}")
                logger.info("Retrying WITH trust_remote_code=True...")

                
                # Retry with trust_remote_code - model first
                model_kwargs["trust_remote_code"] = True
                processor_kwargs["trust_remote_code"] = True
                # Ensure memory optimizations are preserved in retry

                if "min_pixels" not in processor_kwargs:
                    processor_kwargs["min_pixels"] = 256 * 28 * 28
                    processor_kwargs["max_pixels"] = 1280 * 28 * 28
                
                try:
                    self.model = AutoModelForImageTextToText.from_pretrained(
                        settings.model_name,
                        **model_kwargs
                    )
                    self.model.eval()
                    logger.info("✅ Model loaded successfully with trust_remote_code")

                    
                    self.processor = AutoProcessor.from_pretrained(
                        settings.model_name,
                        **processor_kwargs
                    )
                    logger.info("✅ Processor loaded successfully with trust_remote_code")

                except RuntimeError as e:
                    if "can't move a model" in str(e).lower() and "offloaded" in str(e).lower():
                        logger.error("Accelerate offloading error on retry!")
                        raise RuntimeError(
                            "Critical: Model cache is corrupted. Please rebuild the container."
                        ) from e
                    else:
                        raise

                
                # Optional: Load tokenizer separately (like working code)
                try:
                    from transformers import AutoTokenizer
                    self.tokenizer = AutoTokenizer.from_pretrained(
                        settings.model_name,
                        **processor_kwargs
                    )
                    logger.info("✅ Tokenizer loaded successfully with trust_remote_code")
                except Exception as tok_e:
                    logger.warning(f"Tokenizer load skipped: {str(tok_e)}")
                    self.tokenizer = None


            
            # Move to device if needed
            # if self.device.type == "cuda":
            #     self.model = self.model.to(self.device)



            
            self._model_loaded = True
            self._download_progress = {"status": "completed", "progress": 100, "message": "Model ready for use"}
            
            logger.info("Offline model initialization complete")
            logger.info(f"Model type: {self.model.config.model_type if hasattr(self.model.config, 'model_type') else 'unknown'}")
            
        except Exception as e:
            error_msg = f"Failed to load model from cache: {str(e)}"
            logger.error(error_msg, exc_info=True)
            self._download_progress = {"status": "failed", "progress": 0, "message": error_msg}
            raise

    
    def process_image(self, image: Union[Image.Image, np.ndarray]) -> Dict[str, Any]:
        """Process a single image and extract text"""
        import time  # Import at function start to avoid scope issues
        try:
            if not self._model_loaded:
                if self._loading:
                    # Wait for background loading to complete
                    logger.info("⏳ Model still loading in background, waiting for completion...")
                    while self._loading and not self._model_loaded:
                        time.sleep(1)
                    if not self._model_loaded:
                        raise RuntimeError("Model loading failed")
                    logger.info("✅ Background model loading completed, proceeding with image processing")
                else:
                    # For cloud environments, start loading now when inference is needed
                    if os.environ.get('RUNNING_IN_CLOUD') == 'true':
                        logger.info("🔄 Starting model loading for cloud inference...")
                        threading.Thread(target=self._background_load, daemon=True).start()
                        # Wait for loading to complete
                        while self._loading and not self._model_loaded:
                            time.sleep(1)
                        if not self._model_loaded:
                            raise RuntimeError("Model loading failed")
                    else:
                        raise RuntimeError("Model not loaded and not loading")
            
            # Convert numpy array to PIL Image if needed
            if isinstance(image, np.ndarray):
                image = Image.fromarray(image)
            
            # Process the image - Qwen2.5-VL requires chat template format
            messages = [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": [
                    {"type": "image"},
                    {"type": "text", "text": "Extract the text from the above document as if you were reading it naturally. Return the tables in html format. Return the equations in LaTeX representation. If there is an image in the document and image caption is not present, add a small description of the image inside the <img></img> tag; otherwise, add the image caption inside <img></img>. Watermarks should be wrapped in brackets. Ex: <watermark>OFFICIAL COPY</watermark>. Page numbers should be wrapped in brackets. Ex: <page_number>14</page_number> or <page_number>9/22</page_number>. Prefer using ☐ and ☑ for check boxes."},


                ]},
            ]
            
            # Inputs are already on correct device thanks to device_map optimization
            logger.info(f"Using optimized device mapping - inputs should be on {self.device}")
            
            # Apply chat template and process inputs
            text = self.processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            inputs = self.processor(text=[text], images=[image], padding=True, return_tensors="pt")
            
            # Move inputs to GPU if model is on GPU
            if self.device.type == "cuda":
                logger.info(f"Moving inputs to GPU device: {self.device}")
                inputs = {k: v.to(self.device) if isinstance(v, torch.Tensor) else v for k, v in inputs.items()}
            else:
                logger.info("Model on CPU, keeping inputs on CPU")


            
            # Generate text with memory optimization for 12GB GPU
            logger.info(f"🔍 Starting OCR extraction for image size: {image.size}")
            logger.info(f"🔍 Chat template applied, input tensor shapes: {[(k, v.shape if hasattr(v, 'shape') else len(v)) for k, v in inputs.items()]}")
            
            with torch.no_grad():
                # Use gradient checkpointing and reduce max tokens for memory efficiency
                logger.info("🔍 Generating text with model...")
                generated_ids = self.model.generate(
                    **inputs, 
                    max_new_tokens=2048,  # Increased back to 2048 for complete text extraction
                    do_sample=False,     # Deterministic generation saves memory
                    use_cache=True,      # Enable KV cache for efficiency
                    pad_token_id=self.model.config.eos_token_id,  # Prevent padding issues
                    temperature=None,    # Explicitly disable temperature for deterministic generation
                    top_p=None,         # Disable top_p sampling
                    top_k=None          # Disable top_k sampling
                )
                logger.info(f"🔍 Generation complete, output shape: {generated_ids.shape}")
            
            # Decode the generated text (processor can handle GPU tensors)
            logger.info("🔍 Decoding generated tokens...")
            generated_text = self.processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
            
            # Debug: Log raw generated text before cleaning (using ERROR level to guarantee visibility)
            logger.error(f"[DEBUG] Raw generated text length: {len(generated_text)}")
            logger.error(f"[DEBUG] Raw text preview: {generated_text[:200]}")
            
            # Strip the chat template from the output
            # The model outputs the entire conversation, we only want the assistant's response
            if "assistant\n" in generated_text:
                generated_text = generated_text.split("assistant\n", 1)[1]
                logger.info(f"🔍 After assistant split (first 200 chars): {generated_text[:200]}")
            
            # Remove any remaining system/user prompts that might have leaked through
            lines = generated_text.split('\n')
            cleaned_lines = []
            for line in lines:
                if line.strip() and not line.startswith('system') and not line.startswith('user') and not line.startswith('assistant'):
                    cleaned_lines.append(line)
            generated_text = '\n'.join(cleaned_lines)
            
            # Debug: Check if cleaning removed everything
            logger.error(f"[DEBUG] After cleaning, text length: {len(generated_text.strip())}")
            if not generated_text.strip():
                logger.error("[DEBUG] CRITICAL: Text cleaning resulted in empty content!")
                logger.warning("🚨 Text cleaning resulted in empty content! Using raw output.")
                # Fallback to less aggressive cleaning
                generated_text = self.processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
                if "assistant\n" in generated_text:
                    generated_text = generated_text.split("assistant\n", 1)[1]
            
            # Log extraction results
            text_length = len(generated_text)
            text_preview = generated_text[:200] + "..." if text_length > 200 else generated_text
            logger.info(f"🔍 OCR extraction complete! Text length: {text_length} chars")
            logger.info(f"🔍 Text preview: {text_preview}")
            
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
        import time  # Import at function start to avoid scope issues
        try:
            if not self._model_loaded:
                if self._loading:
                    # Wait for background loading to complete
                    logger.info("⏳ Model still loading in background, waiting for completion...")
                    while self._loading and not self._model_loaded:
                        time.sleep(1)
                    if not self._model_loaded:
                        raise RuntimeError("Model loading failed")
                    logger.info("✅ Background model loading completed, proceeding with PDF processing")
                else:
                    raise RuntimeError("Model not loaded and not loading")
            
            # Convert PDF to images
            logger.info("Starting PDF to image conversion")
            images = pdf2image.convert_from_bytes(
                pdf_content,
                dpi=150,  # Use 150 DPI for memory efficiency with 12GB GPU
                fmt='PNG',
                thread_count=2
            )
            logger.info(f"Successfully converted PDF to {len(images)} images")
            
            results = []
            total_pages = len(images)
            
            for i, image in enumerate(images):
                current_page = i + 1
                
                # Update progress BEFORE processing
                if progress_callback:
                    if asyncio.iscoroutinefunction(progress_callback):
                        # Run async callback in thread-safe way
                        loop = asyncio.get_event_loop()
                        loop.create_task(progress_callback(current_page=current_page, total_pages=total_pages))
                    else:
                        progress_callback(current_page=current_page, total_pages=total_pages)
                
                logger.info(f"🔍 Processing page {current_page}/{total_pages}")
                
                # Process each page
                page_result = self.process_image(image)
                page_result["page_number"] = current_page
                results.append(page_result)

                
                logger.info(f"✅ Completed page {current_page}/{total_pages}")
                
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

    def _extract_images_from_raw_file(self, raw_filename, session_id, file_type, job, job_id):
        """Extract images from raw PDF file in background thread"""
        try:
            from app.storage_service import StorageService
            storage_service = StorageService(user_email=job.get('user_email'))
            
            # Update job progress
            job['progress'] = {
                "current_step": "extracting",
                "message": "Extracting images from PDF...",
                "percent": 10
            }
            self._update_job_status_gcs(job_id, 'processing', 'Extracting images from PDF...')
            
            # Load raw file from storage
            raw_file_data = asyncio.run(storage_service.get_file(raw_filename, session_id))
            
            if file_type == "pdf":
                import pdf2image
                import io
                
                logger.info(f"Converting PDF to images for session {session_id}")
                
                # Update progress
                job['progress']['message'] = "Converting PDF to images..."
                job['progress']['percent'] = 20
                self._update_job_status_gcs(job_id, 'processing', 'Converting PDF to images...')
                
                # Convert PDF to images
                images = pdf2image.convert_from_bytes(
                    raw_file_data,
                    dpi=150,
                    fmt='PNG',
                    thread_count=2
                )
                
                page_count = len(images)
                logger.info(f"Extracted {page_count} pages from PDF")
                
                # Update progress
                job['progress']['message'] = f"Saving {page_count} page images..."
                job['progress']['percent'] = 30
                self._update_job_status_gcs(job_id, 'processing', f'Saving {page_count} page images...')
                
                page_images = []
                for i, image in enumerate(images):
                    image_filename = f"page_{i+1:03d}.png"
                    
                    # Convert PIL image to bytes
                    img_buffer = io.BytesIO()
                    image.save(img_buffer, format='PNG')
                    image_bytes = img_buffer.getvalue()
                    
                    # Save image to storage
                    asyncio.run(storage_service.save_file(image_bytes, image_filename, session_id))
                    page_images.append(image_filename)
                    
                    # Update progress incrementally
                    progress = 30 + (i + 1) / page_count * 20  # 30-50%
                    job['progress']['percent'] = progress
                    job['progress']['message'] = f"Saved image {i+1}/{page_count}"
                    
                    # Update status every 10 pages to avoid too many updates
                    if i % 10 == 0 or i == page_count - 1:
                        self._update_job_status_gcs(job_id, 'processing', f'Saved image {i+1}/{page_count}')
                
                return page_images
            else:
                # For single images, save as page_001
                image_filename = f"page_001.png"
                asyncio.run(storage_service.save_file(raw_file_data, image_filename, session_id))
                return [image_filename]
                
        except Exception as e:
            logger.error(f"Failed to extract images from {raw_filename}: {e}")
            job['status'] = 'failed'
            job['error'] = f"Failed to extract images: {str(e)}"
            raise

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

    def submit_job(self, file_reference, job_type="image", user_email=None, session_id=None):
        """Submit OCR job with file reference instead of binary data"""
        from datetime import datetime
        # Import here to avoid circular imports
        from app.storage_service import StorageService

        
        job_id = str(uuid.uuid4())
        
        # Create job record with file reference
        job_data = {
            "status": "queued",
            "type": job_type,
            "file_reference": file_reference,  # Store file reference instead of binary data
            "user_email": user_email,  # Store user context
            "session_id": session_id,  # Store session context
            "created": datetime.utcnow().isoformat(),
            "result": None,
            "error": None,
            "progress": {
                "current_step": "queued",
                "message": "Job queued, waiting for model to be ready",
                "current_page": 0,
                "total_pages": file_reference.get("page_count", 1) if isinstance(file_reference, dict) else 1,
                "percent": 0
            }
        }

        
        self.jobs[job_id] = job_data
        
        # CRITICAL FIX: Persist job to GCS immediately
        try:
            # Create storage service with user context
            storage_service = StorageService(user_email=user_email)

            # Only persist to GCS in cloud mode
            if os.environ.get('RUNNING_IN_CLOUD') == 'true':
                storage_service.force_cloud_mode()
                
                # Save job metadata to GCS using job_id as session_hash
                
                # Calculate file size from file_reference if available
                file_size = 0
                if isinstance(file_reference, dict) and 'page_count' in file_reference:
                    file_size = file_reference.get('page_count', 0) * 1024  # Rough estimate
                
                job_metadata = {
                    'job_id': job_id,
                    'job_type': job_type,
                    'status': 'queued',
                    'created_at': datetime.utcnow().isoformat(),
                    'file_size': file_size
                }
            
            # Use existing session_id or create new one
            # (this runs in main thread, not ThreadPoolExecutor)
            try:
                loop = asyncio.get_event_loop()
                
                if session_id:
                    # Use existing session from upload
                    used_session_id = session_id
                else:
                    # Create new session if none provided
                    session_task = loop.create_task(storage_service.create_session(job_metadata, session_hash=job_id))
                    used_session_id = job_id
                
                # Save initial status to the session
                status_data = {
                    'status': 'queued',
                    'progress': 0.0,
                    'message': 'Job queued, waiting for model to be ready',
                    'updated_at': datetime.utcnow().isoformat()
                }
                status_task = loop.create_task(storage_service.save_file(
                    json.dumps(status_data, indent=2).encode('utf-8'),
                    'status.json',
                    used_session_id
                ))

            except RuntimeError:
                # If no event loop in this thread, skip GCS persistence for now
                logger.warning(f"No event loop available for job {job_id} GCS persistence")

            
            logger.info(f"✅ Job {job_id} persisted to GCS")
            
        except Exception as e:
            logger.error(f"❌ Failed to persist job {job_id} to GCS: {e}")
            # Continue anyway - job is still in memory

        
        if not self._model_loaded:
            if self._loading:
                # Queue the job until model ready
                self.job_queue.append(job_id)
                logger.info(f"📋 Job {job_id} queued - model still loading")
            else:
                # For cloud environments, start loading now when job submitted
                if os.environ.get('RUNNING_IN_CLOUD') == 'true':
                    logger.info(f"🔄 Starting model loading for cloud job {job_id}...")
                    threading.Thread(target=self._background_load, daemon=True).start()
                    # Queue the job until model ready
                    self.job_queue.append(job_id)
                    logger.info(f"📋 Job {job_id} queued - model loading started")
                else:
                    # Model failed to load
                    job_data["status"] = "failed"
                    job_data["error"] = "Model failed to load"
                    logger.error(f"❌ Job {job_id} failed - model not loaded")
        else:
            # Process immediately if model ready
            self.process_job_async(job_id)
            logger.info(f"🚀 Job {job_id} submitted for immediate processing")
        
        return job_id
    
    def process_job_async(self, job_id):
        """Process job in background thread"""
        def _process():
            try:
                job = self.jobs[job_id]
                job['status'] = 'processing'
                logger.info(f"🔄 Processing job {job_id}")
                
                # Update GCS with processing status
                self._update_job_status_gcs(job_id, 'processing', 'Starting OCR processing...')

                
                # Handle file reference - check if we need to extract images
                file_reference = job['file_reference']
                session_id = file_reference['session_id']
                
                # Check if we have pre-extracted page images or need to extract from raw file
                if 'page_images' in file_reference:
                    page_images = file_reference['page_images']
                elif 'raw_file' in file_reference:
                    # Extract images from raw file in background
                    logger.info(f"Extracting images from raw file: {file_reference['raw_file']}")
                    page_images = self._extract_images_from_raw_file(
                        file_reference['raw_file'], 
                        session_id, 
                        file_reference['file_type'],
                        job,
                        job_id
                    )
                else:
                    raise RuntimeError("No page images or raw file found in file reference")
                
                # Initialize storage service
                from app.storage_service import StorageService
                storage_service = StorageService(user_email=job.get('user_email'))
                
                if job['type'] == "image":
                    # Single image processing
                    job['progress'] = {
                        "current_step": "processing",
                        "message": "Processing image...",
                        "current_page": 1,
                        "total_pages": 1,
                        "percent": 50
                    }
                    
                    # Load image from storage
                    image_filename = page_images[0]
                    image_data = asyncio.run(storage_service.get_file(image_filename, session_id))
                    
                    from PIL import Image
                    import io
                    image = Image.open(io.BytesIO(image_data))
                    result = self.process_image(image)
                    
                elif job['type'] == "pdf":
                    # PDF images already extracted during upload, load from storage
                    total_pages = len(page_images)
                    job['progress'] = {
                        "current_step": "processing",
                        "message": f"Processing {total_pages} pages...",
                        "current_page": 0,
                        "total_pages": total_pages,
                        "percent": 10
                    }
                    
                    logger.info(f"Loading {total_pages} pre-extracted images from storage")
                    
                    # Process images already extracted and saved during upload
                    result = []
                    from PIL import Image
                    import io
                    
                    # Create progress callback to update job status
                    def progress_callback(current_page, total_pages):
                        percent = int((current_page / total_pages) * 80) + 10 if total_pages > 0 else 50
                        job['progress'] = {
                            "current_step": "processing",
                            "message": f"Processing OCR on page {current_page} of {total_pages}...",
                            "current_page": current_page,
                            "total_pages": total_pages,
                            "percent": percent
                        }
                    
                    for i, image_filename in enumerate(page_images):
                        current_page = i + 1
                        progress_callback(current_page, total_pages)
                        
                        logger.info(f"🔍 Processing page {current_page}/{total_pages} - {image_filename}")
                        
                        # Load image from storage
                        image_data = asyncio.run(storage_service.get_file(image_filename, session_id))
                        image = Image.open(io.BytesIO(image_data))
                        
                        # Process the loaded image
                        page_result = self.process_image(image)
                        page_result["page_number"] = current_page
                        result.append(page_result)
                        
                        # Clear GPU memory after each page
                        if self.device.type == "cuda":
                            torch.cuda.empty_cache()

                    
                else:
                    raise ValueError(f"Unknown job type: {job['type']}")
                
                # Final completion
                job['status'] = 'completed'
                job['result'] = result
                job['completed'] = datetime.utcnow().isoformat()
                job['progress'] = {
                    "current_step": "completed",
                    "message": "Processing complete!",
                    "current_page": job['progress'].get('total_pages', 1),
                    "total_pages": job['progress'].get('total_pages', 1),
                    "percent": 100
                }
                logger.info(f"✅ Job {job_id} completed successfully")
                
                # Update GCS with completion status
                self._update_job_status_gcs(job_id, 'completed', 'Processing complete!')
                
                # CRITICAL: Save the actual OCR results to storage
                try:
                    from app.storage_service import StorageService
                    
                    # Get job context
                    user_email = job.get('user_email')
                    session_id = job.get('session_id', job_id)
                    
                    # Create storage service
                    storage_service = StorageService(user_email=user_email)
                    if os.environ.get('RUNNING_IN_CLOUD') == 'true':
                        storage_service.force_cloud_mode()
                    
                    # Create new event loop for this thread
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    
                    try:
                        if job['type'] == "image":
                            # Save single image result
                            text_content = result.get('text', '')
                            loop.run_until_complete(storage_service.save_page_result(
                                session_id, 1, text_content
                            ))
                            # Also save as combined output
                            loop.run_until_complete(storage_service.save_combined_result(
                                session_id, text_content
                            ))
                            logger.info(f"📝 Saved image OCR results to storage for session {session_id}")
                            
                        elif job['type'] == "pdf":
                            # Save individual page results and combined output
                            combined_text = []
                            for i, page_result in enumerate(result):
                                page_num = i + 1
                                text_content = page_result.get('text', '')
                                # Save individual page
                                loop.run_until_complete(storage_service.save_page_result(
                                    session_id, page_num, text_content
                                ))
                                # Add to combined with page marker
                                combined_text.append(f"--- Page {page_num} ---\n{text_content}\n")
                            
                            # Save combined markdown
                            combined_markdown = '\n'.join(combined_text)
                            loop.run_until_complete(storage_service.save_combined_result(
                                session_id, combined_markdown
                            ))
                            logger.info(f"📝 Saved PDF OCR results ({len(result)} pages) to storage for session {session_id}")
                            
                    finally:
                        loop.close()
                        
                except Exception as e:
                    logger.error(f"⚠️ Failed to save OCR results to storage: {e}")
                    # Don't fail the job, just log the error


                
            except Exception as e:
                job['status'] = 'failed'
                job['error'] = str(e)
                job['progress'] = {
                    "current_step": "failed",
                    "message": f"Processing failed: {str(e)}",
                    "current_page": job['progress'].get('current_page', 0),
                    "total_pages": job['progress'].get('total_pages', 0),
                    "percent": 0
                }
                logger.error(f"❌ Job {job_id} failed: {e}")
                
                # Update GCS with error status
                self._update_job_status_gcs(job_id, 'failed', f'Processing failed: {str(e)}')

        
        self.executor.submit(_process)
    
    def _update_job_status_gcs(self, job_id, status, message):
        """Helper method to update job status in GCS"""
        try:
            from app.storage_service import StorageService
            from datetime import datetime
            
            # Get job data to extract user and session context
            job = self.jobs.get(job_id, {})
            user_email = job.get('user_email')
            session_id = job.get('session_id', job_id)  # Use session_id if available, fallback to job_id
            
            # Create storage service with user context
            storage_service = StorageService(user_email=user_email)

            if os.environ.get('RUNNING_IN_CLOUD') == 'true':
                storage_service.force_cloud_mode()
            
            # Get current job data for progress info
            progress_data = job.get('progress', {})
            
            # Create status update
            status_data = {
                'status': status,
                'progress': progress_data.get('percent', 0),
                'current_page': progress_data.get('current_page', 0),
                'total_pages': progress_data.get('total_pages', 0),
                'message': message,
                'updated_at': datetime.utcnow().isoformat()
            }
            
            # Save to session directory (not job_id directory)
            try:
                # Create new event loop for this thread
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                # Run the save operation using session_id
                loop.run_until_complete(storage_service.save_file(
                    json.dumps(status_data, indent=2).encode('utf-8'),
                    'status.json',
                    session_id
                ))

            finally:
                # Clean up the loop
                try:
                    loop.close()
                except:
                    pass

            
            logger.debug(f"📝 Updated job {job_id} status in GCS: {status}")
            
        except Exception as e:
            logger.error(f"❌ Failed to update job {job_id} status in GCS: {e}")
    
    def get_job_status(self, job_id):
        """Get job result by ID - check memory first, then GCS"""
        # First check in-memory jobs
        if job_id in self.jobs:
            return self.jobs[job_id]
        
        # If not in memory, try to load from GCS (container restart recovery)
        try:
            from app.storage_service import StorageService
            
            # Try to load job status from GCS
            storage_service = StorageService(user_email=None)  # Anonymous fallback
            if os.environ.get('RUNNING_IN_CLOUD') == 'true':
                storage_service.force_cloud_mode()
            
            # Try to get status file - create new event loop if needed
            try:
                # Try to get existing loop first
                loop = asyncio.get_event_loop()
                status_content = loop.run_until_complete(storage_service.get_file('status.json', job_id))
            except RuntimeError:
                # No event loop, create a new one
                loop = asyncio.new_event_loop()
                try:
                    asyncio.set_event_loop(loop)
                    status_content = loop.run_until_complete(storage_service.get_file('status.json', job_id))
                finally:
                    loop.close()

            
            if status_content:
                status_data = json.loads(status_content.decode('utf-8'))
                logger.info(f"🔄 Recovered job {job_id} status from GCS: {status_data.get('status')}")
                
                # Reconstruct basic job data
                recovered_job = {
                    "status": status_data.get('status', 'unknown'),
                    "progress": {
                        "current_step": status_data.get('status', 'unknown'),
                        "message": status_data.get('message', 'Recovered from storage'),
                        "current_page": status_data.get('current_page', 0),
                        "total_pages": status_data.get('total_pages', 0),
                        "percent": status_data.get('progress', 0)
                    },
                    "result": None,  # Result would need separate recovery
                    "created": "unknown",
                    "type": "unknown"
                }
                
                return recovered_job
                
        except Exception as e:
            logger.debug(f"Could not recover job {job_id} from GCS: {e}")
        
        # Not found anywhere
        return {"status": "not_found"}



# Global instance
ocr_service = OCRService()
