"""OCR processing service using Nanonets-OCR-s model with new storage architecture"""
import os
import gc
import json
import asyncio
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
from datetime import datetime
import torch
from transformers import AutoModelForImageTextToText, AutoTokenizer, AutoProcessor
from PIL import Image
import fitz  # PyMuPDF
import cv2
import numpy as np
import structlog
from io import BytesIO

# DEBUG MODE: Set to True to skip inference and just extract/save images
DEBUG_SKIP_INFERENCE = False

from app.config import settings
from app.models import ProcessingStatus
from app.storage_service_v2 import StorageService

logger = structlog.get_logger()


class OCRService:
    """Handles OCR processing using the Nanonets model with new storage architecture"""
    
    def __init__(self, storage_service: Optional[StorageService] = None):
        self.model = None
        self.tokenizer = None
        self.processor = None
        self.device = None
        self.model_loaded = False
        self.storage_service = storage_service
        
    async def initialize(self):
        """Initialize the OCR model"""
        try:
            logger.info("🚀 HARIN DEBUG: Starting OCR initialization with cache bypass fix", model=settings.model_name)
            
            # Check GPU availability
            if torch.cuda.is_available() and settings.device == "cuda":
                self.device = torch.device("cuda")
                gpu_name = torch.cuda.get_device_name(0)
                logger.info("GPU available", device=gpu_name)
            else:
                self.device = torch.device("cpu")
                logger.warning("GPU not available, using CPU")
            
            # Get cache configuration from storage service if available
            cache_kwargs = {
                "local_files_only": os.environ.get("HF_DATASETS_OFFLINE", "1") == "1" or os.environ.get("TRANSFORMERS_OFFLINE", "1") == "1",
                "trust_remote_code": True,
                "cache_dir": os.environ.get("HF_HOME", os.environ.get("TRANSFORMERS_CACHE", "/cache/huggingface"))
            }
            
            logger.info(f"🔧 CACHE KWARGS: {cache_kwargs}")
            
            if self.storage_service:
                # Use storage service cache configuration
                cache_config = self.storage_service.get_cache_config()
                cache_kwargs.update(cache_config)
                
                # CLOUD RUN FIX: List cache directory and bypass verification
                cache_dir = cache_config.get('cache_dir')
                logger.info(f"🔍 CACHE DEBUG: Checking cache directory", cache_dir=cache_dir)
                
                try:
                    if os.path.exists(cache_dir):
                        contents = os.listdir(cache_dir)
                        logger.info(f"📁 CACHE CONTENTS: {contents[:10]}")  # First 10 items
                        hub_path = os.path.join(cache_dir, 'hub')
                        if os.path.exists(hub_path):
                            hub_contents = os.listdir(hub_path)
                            logger.info(f"🏢 HUB CONTENTS: {hub_contents[:10]}")
                    else:
                        logger.error(f"❌ CACHE DIR MISSING: {cache_dir}")
                except Exception as e:
                    logger.error(f"💥 CACHE CHECK FAILED: {e}")
                
                # Force proceed anyway - let HF handle cache
                logger.info("🚀 BYPASSING cache verification - Cloud Run mode")
                
                logger.info("Using storage service cache", cache_dir=cache_config.get('cache_dir'))
            
            logger.info("Loading tokenizer and processor from LOCAL CACHE ONLY", 
                       model=settings.model_name, cache_kwargs=cache_kwargs)
            
            # For Cloud Run, we need to be very explicit about offline mode
            if os.environ.get("RUNNING_IN_CLOUD") == "true":
                # Force offline mode
                os.environ["HF_DATASETS_OFFLINE"] = "1"
                os.environ["TRANSFORMERS_OFFLINE"] = "1"
                os.environ["HF_HUB_OFFLINE"] = "1"
                
                # CRITICAL: Prevent HuggingFace from trying to download and corrupting cache
                os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
                os.environ["HF_HUB_DISABLE_DOWNLOAD_PROGRESS"] = "1"
                
                # Remove any .no_exist files that block cache usage
                cache_dir = cache_kwargs.get('cache_dir', '/cache/huggingface')
                model_dir = os.path.join(cache_dir, 'hub', f'models--{settings.model_name.replace("/", "--")}')
                no_exist_file = os.path.join(model_dir, '.no_exist')
                if os.path.exists(no_exist_file):
                    logger.warning(f"Found .no_exist blocker file, removing: {no_exist_file}")
                    try:
                        os.remove(no_exist_file)
                    except Exception as e:
                        logger.error(f"Failed to remove .no_exist: {e}")
                
            # Load tokenizer and processor (these are lightweight)
            try:
                self.tokenizer = AutoTokenizer.from_pretrained(settings.model_name, **cache_kwargs)
                logger.info("✅ Tokenizer loaded successfully")
            except Exception as e:
                logger.error(f"❌ Tokenizer loading failed: {e}")
                raise
                
            try:
                self.processor = AutoProcessor.from_pretrained(settings.model_name, **cache_kwargs)
                logger.info("✅ Processor loaded successfully")
            except Exception as e:
                logger.error(f"❌ Processor loading failed: {e}")
                raise
            
            logger.info("Loading model weights - this may take a moment")
            
            # Load model with proper configuration
            model_kwargs = {
                # CLOUD RUN FIX: Override for production
                "local_files_only": os.environ.get("HF_LOCAL_FILES_ONLY", "True").lower() == "true",
                "trust_remote_code": True,
                # Memory optimization settings
                "low_cpu_mem_usage": True,
                "device_map": "auto"
            }
            
            logger.info(f"🔧 MODEL KWARGS: {model_kwargs}")
            
            # Add cache directory if available
            if self.storage_service:
                model_kwargs.update(self.storage_service.get_cache_config())
            
            # Set dtype based on device
            if self.device.type == "cuda":
                model_kwargs["torch_dtype"] = torch.float16
            else:
                model_kwargs["torch_dtype"] = torch.float32
            
            # For CUDA, use memory-efficient loading
            if self.device.type == "cuda":
                # Conservative memory limit to avoid OOM
                model_kwargs["max_memory"] = {0: "5GB"}  # Reduced from 6GB for safety
                logger.info("Using GPU with memory limit", max_memory="5GB")
            
            logger.info("Loading model with LOCAL CACHE ONLY settings", 
                       local_files_only=True, device=self.device.type)
            
            self.model = AutoModelForImageTextToText.from_pretrained(
                settings.model_name,
                **model_kwargs
            )
            
            # Set model to evaluation mode
            self.model.eval()
            self.model_loaded = True
            
            logger.info("OCR model initialized successfully")
            
        except Exception as e:
            logger.error("Failed to initialize OCR model", error=str(e))
            raise
            
    def is_ready(self) -> bool:
        """Check if the service is ready to process"""
        return self.model_loaded and self.model is not None
        
    def get_gpu_info(self) -> Dict[str, Any]:
        """Get GPU information"""
        if torch.cuda.is_available():
            return {
                'available': True,
                'device_name': torch.cuda.get_device_name(0),
                'device_count': torch.cuda.device_count(),
                'current_device': torch.cuda.current_device(),
                'memory_allocated': torch.cuda.memory_allocated(),
                'memory_reserved': torch.cuda.memory_reserved()
            }
        return {'available': False}
        
    async def process_document(self, session_hash: str, file_content: bytes, 
                             storage_service: StorageService) -> Dict[str, Any]:
        """Process a PDF document using the new storage architecture"""
        try:
            # Update storage service for this session
            self.storage_service = storage_service
            
            # Save status as processing
            await self._update_status(
                session_hash,
                ProcessingStatus.PROCESSING,
                progress=0.0,
                message="Starting document processing"
            )
            
            # Phase 1: Extract all pages from PDF first (this is fast)
            logger.info("Starting PDF extraction - model NOT loaded yet", session_hash=session_hash)
            await self._update_status(
                session_hash,
                ProcessingStatus.PROCESSING,
                progress=0.0,
                message="Extracting pages from PDF"
            )
            
            # Extract pages WITHOUT loading any ML models
            pages = await self._extract_pdf_pages_from_bytes(file_content)
            total_pages = len(pages)
            
            # Update metadata
            await storage_service.save_session_metadata(session_hash, {
                'total_pages': total_pages,
                'extraction_complete': True
            })
            
            # Save all page images first
            logger.info("Saving extracted page images", session_hash=session_hash, total_pages=total_pages)
            for idx, page_image in enumerate(pages):
                page_num = idx + 1
                progress = (idx / total_pages) * 20  # 20% for extraction
                
                await self._update_status(
                    session_hash,
                    ProcessingStatus.PROCESSING,
                    progress=progress,
                    message=f"Saving page {page_num} of {total_pages}"
                )
                
                image_bytes = self._image_to_bytes(page_image)
                await storage_service.save_page_image(session_hash, page_num, image_bytes)
            
            logger.info("All pages extracted and saved. NOW checking if we should load model.", session_hash=session_hash)
            
            # DEBUG MODE: Skip inference entirely
            if DEBUG_SKIP_INFERENCE:
                logger.info("🚨 DEBUG MODE ACTIVE: Skipping inference, returning mock results", session_hash=session_hash)
                return await self._create_debug_results(session_hash, pages)
            
            # Phase 2: Initialize model if needed (AFTER all extraction is done)
            if not self.is_ready():
                logger.info("Model not loaded, initializing now...", session_hash=session_hash)
                await self._update_status(
                    session_hash,
                    ProcessingStatus.PROCESSING,
                    progress=20.0,
                    message="Loading OCR model (this may take a moment)..."
                )
                await self.initialize()
                logger.info("OCR model loaded successfully", session_hash=session_hash)
            
            # Phase 3: Process OCR on all pages
            logger.info("Starting OCR processing", session_hash=session_hash)
            results = []
            combined_text = []
            
            for idx, page_image in enumerate(pages):
                page_num = idx + 1
                progress = 20 + ((idx / total_pages) * 80)  # 80% for OCR
                
                # Update progress
                await self._update_status(
                    session_hash,
                    ProcessingStatus.PROCESSING,
                    progress=progress,
                    message=f"Processing OCR for page {page_num} of {total_pages}",
                    current_page=page_num
                )
                
                # Process OCR with extensive logging
                logger.info("🔍 STARTING OCR for page", session_hash=session_hash, page=page_num)
                try:
                    page_text = await self._process_page(page_image)
                    logger.info("✅ OCR COMPLETED for page", session_hash=session_hash, page=page_num)
                except Exception as ocr_error:
                    logger.error("💥 OCR FAILED for page", session_hash=session_hash, page=page_num, error=str(ocr_error))
                    page_text = f"[OCR ERROR on page {page_num}]: {str(ocr_error)}"
                
                # Save page result
                await storage_service.save_page_result(session_hash, page_num, page_text)
                
                results.append({
                    'page_number': page_num,
                    'text': page_text
                })
                combined_text.append(f"## Page {page_num}\n\n{page_text}")
                
                # Clean up memory periodically
                if idx % 10 == 0:
                    gc.collect()
                    if self.device.type == "cuda":
                        torch.cuda.empty_cache()
                        
            # Save combined result
            combined_markdown = "\n\n---\n\n".join(combined_text)
            await storage_service.save_combined_result(session_hash, combined_markdown)
            
            # Save final metadata
            metadata = {
                'model': settings.model_name,
                'device': self.device.type,
                'total_pages': total_pages,
                'processed_at': datetime.utcnow().isoformat(),
                'status': 'completed'
            }
            
            if self.device.type == "cuda":
                metadata['gpu_name'] = torch.cuda.get_device_name(0)
                
            await storage_service.save_session_metadata(session_hash, metadata)
                
            # Update status to completed
            await self._update_status(
                session_hash,
                ProcessingStatus.COMPLETED,
                progress=100.0,
                message="Processing completed successfully"
            )
            
            logger.info("Document processing completed", 
                       session_hash=session_hash, 
                       total_pages=total_pages)
            
            return {
                'status': 'completed',
                'total_pages': total_pages,
                'results': results
            }
            
        except Exception as e:
            logger.error("Error processing document", 
                        session_hash=session_hash, 
                        error=str(e))
            
            await self._update_status(
                session_hash,
                ProcessingStatus.FAILED,
                message=f"Processing failed: {str(e)}"
            )
            raise
    
    async def _update_status(self, session_hash: str, status: ProcessingStatus, 
                           progress: float = 0.0, message: str = "", 
                           current_page: Optional[int] = None):
        """Update session status using new storage service"""
        status_data = {
            'status': status.value,
            'progress': progress,
            'message': message,
            'updated_at': datetime.utcnow().isoformat()
        }
        if current_page is not None:
            status_data['current_page'] = current_page
            
        await self.storage_service.save_file(
            json.dumps(status_data, indent=2),
            'status.json',
            session_hash
        )
            
    async def _create_debug_results(self, session_hash: str, pages: List) -> Dict[str, Any]:
        """Create mock results for debug mode (no inference)"""
        try:
            logger.info("🔧 Creating debug results without inference", session_hash=session_hash)
            total_pages = len(pages)
            results = []
            combined_text = []
            
            for idx, page_image in enumerate(pages):
                page_num = idx + 1
                progress = 20 + ((idx / total_pages) * 80)  # 80% for "processing"
                
                logger.info(f"🔧 DEBUG: Mock processing page {page_num}/{total_pages}", session_hash=session_hash)
                
                # Update progress
                await self._update_status(
                    session_hash,
                    ProcessingStatus.PROCESSING,
                    progress=progress,
                    message=f"DEBUG: Mock processing page {page_num} of {total_pages}",
                    current_page=page_num
                )
                
                # Create mock text with image info
                mock_text = f"[DEBUG MODE] This is mock OCR text for page {page_num}.\n\nImage size: {page_image.size}\nImage mode: {page_image.mode}\n\nInference was skipped to debug image extraction and status endpoints."
                
                # Save page result
                await self.storage_service.save_page_result(session_hash, page_num, mock_text)
                
                results.append({
                    'page_number': page_num,
                    'text': mock_text
                })
                combined_text.append(f"## Page {page_num}\n\n{mock_text}")
            
            # Save combined result
            combined_markdown = "\n\n---\n\n".join(combined_text)
            await self.storage_service.save_combined_result(session_hash, combined_markdown)
            
            # Update status to completed
            await self._update_status(
                session_hash,
                ProcessingStatus.COMPLETED,
                progress=100.0,
                message="DEBUG: Mock processing completed successfully"
            )
            
            logger.info("🎉 DEBUG: Mock processing completed successfully", session_hash=session_hash, total_pages=total_pages)
            
            return {
                'status': 'completed',
                'total_pages': total_pages,
                'results': results
            }
            
        except Exception as e:
            logger.error("💥 Error in debug mode processing", session_hash=session_hash, error=str(e))
            await self._update_status(
                session_hash,
                ProcessingStatus.FAILED,
                message=f"DEBUG processing failed: {str(e)}"
            )
            raise
    
    async def _extract_pdf_pages_from_bytes(self, pdf_content: bytes) -> List[Image.Image]:
        """Extract pages from PDF bytes as PIL images"""
        pages = []
        
        # Open PDF from bytes
        pdf_document = fitz.open(stream=pdf_content, filetype="pdf")
        
        try:
            for page_num in range(min(len(pdf_document), settings.max_pages)):
                page = pdf_document[page_num]
                
                # Render page at high resolution
                mat = fitz.Matrix(2.0, 2.0)  # 2x scaling for better quality
                pix = page.get_pixmap(matrix=mat)
                
                # Convert to PIL Image
                img_data = pix.tobytes("png")
                img = Image.open(BytesIO(img_data))
                
                # Convert to RGB if necessary
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                    
                pages.append(img)
                
        finally:
            pdf_document.close()
            
        return pages
        
    async def _process_page(self, image: Image.Image) -> str:
        """Process a single page with OCR"""
        try:
            logger.info("🔧 _process_page: Starting page processing", image_size=image.size)
            
            # Check if processor is initialized
            if self.processor is None:
                logger.error("💥 Processor not initialized!")
                raise RuntimeError("Processor not initialized")
                
            logger.info("✅ Processor is initialized")
            
            # Preprocess image if needed
            logger.info("🔧 Starting image preprocessing")
            image = self._preprocess_image(image)
            logger.info("✅ Image preprocessing completed", processed_size=image.size)
            
            # Process with model
            logger.info("🔧 Processing image with processor", image_size=image.size)
            try:
                # Format messages for the model (based on reference implementation)
                logger.info("🔧 Creating prompt and messages")
                prompt = """Extract the text from the above document as if you were reading it naturally. Return the tables in html format. Return the equations in LaTeX representation. If there is an image in the document and image caption is not present, add a small description of the image inside the <img></img> tag; otherwise, add the image caption inside <img></img>. Watermarks should be wrapped in brackets. Ex: <watermark>OFFICIAL COPY</watermark>. Page numbers should be wrapped in brackets. Ex: <page_number>14</page_number> or <page_number>9/22</page_number>. Prefer using ☐ and ☑ for check boxes."""
                
                messages = [
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": [
                        {"type": "image"},
                        {"type": "text", "text": prompt},
                    ]},
                ]
                
                # Apply chat template
                logger.info("🔧 Applying chat template")
                text = self.processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
                logger.info("✅ Chat template applied successfully")
                
                logger.info("🔧 Processing inputs with processor (THIS MAY HANG)")
                inputs = self.processor(text=[text], images=[image], padding=True, return_tensors="pt")
                logger.info("✅ Processor completed successfully")
                
            except Exception as proc_error:
                logger.error("💥 Processor failed", error=str(proc_error), exc_info=True)
                raise
                
            if inputs is None:
                logger.error("💥 Processor returned None!")
                raise ValueError("Processor returned None")
            
            logger.info("✅ Inputs created successfully")
            
            # Move inputs to device
            try:
                logger.info("🔧 Moving inputs to device", device=self.device)
                inputs = {k: v.to(self.device) if hasattr(v, 'to') else v for k, v in inputs.items()}
                logger.info("✅ Inputs moved to device successfully")
            except Exception as move_error:
                logger.error("💥 Failed to move inputs to device", error=str(move_error))
                raise
            
            logger.info("🔧 Starting model.generate() - THIS IS WHERE IT LIKELY HANGS")
            with torch.no_grad():
                output_ids = self.model.generate(
                    **inputs,
                    max_new_tokens=settings.max_new_tokens,
                    do_sample=False
                )
            logger.info("✅ model.generate() completed successfully!")
                
            # Extract only the generated tokens (based on reference implementation)
            # inputs is a dict with 'input_ids' key
            generated_ids = [
                output_ids[len(input_ids):] 
                for input_ids, output_ids in zip(inputs['input_ids'], output_ids)
            ]
            
            # Decode the output
            output_text = self.processor.batch_decode(
                generated_ids, 
                skip_special_tokens=True,
                clean_up_tokenization_spaces=True
            )
            generated_text = output_text[0]
            
            # Post-process the text
            processed_text = self._postprocess_text(generated_text)
            
            return processed_text
            
        except Exception as e:
            logger.error("Error processing page", error=str(e), exc_info=True)
            return f"Error processing page: {str(e)}"
            
    def _preprocess_image(self, image: Image.Image) -> Image.Image:
        """Preprocess image for better OCR results"""
        # Convert PIL to numpy array
        img_array = np.array(image)
        
        # Apply basic image enhancements
        # Convert to grayscale
        if len(img_array.shape) == 3:
            gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
        else:
            gray = img_array
            
        # Apply adaptive thresholding for better contrast
        enhanced = cv2.adaptiveThreshold(
            gray, 255, 
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            11, 2
        )
        
        # Denoise
        denoised = cv2.fastNlMeansDenoising(enhanced)
        
        # Convert back to PIL Image
        return Image.fromarray(denoised)
        
    def _postprocess_text(self, text: str) -> str:
        """Post-process OCR output"""
        # Clean up common OCR artifacts
        text = text.strip()
        
        # Fix common LaTeX equation formatting
        text = text.replace('\\\\(', '$')
        text = text.replace('\\\\)', '$')
        text = text.replace('\\\\[', '$$')
        text = text.replace('\\\\]', '$$')
        
        # Remove excessive whitespace
        lines = text.split('\n')
        cleaned_lines = []
        for line in lines:
            line = line.strip()
            if line:
                cleaned_lines.append(line)
                
        return '\n\n'.join(cleaned_lines)
        
    def _image_to_bytes(self, image: Image.Image) -> bytes:
        """Convert PIL Image to bytes"""
        buffer = BytesIO()
        image.save(buffer, format='PNG')
        return buffer.getvalue()
        
    async def cleanup(self):
        """Clean up resources"""
        if self.model is not None:
            del self.model
            self.model = None
            
        if self.tokenizer is not None:
            del self.tokenizer
            self.tokenizer = None
            
        if self.processor is not None:
            del self.processor
            self.processor = None
            
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            
        self.model_loaded = False
        logger.info("OCR service cleaned up")


# Global OCR service instance
ocr_service = OCRService()