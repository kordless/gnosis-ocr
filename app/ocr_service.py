"""OCR processing service using Nanonets-OCR-s model"""
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

from app.config import settings, get_session_file_path
from app.models import ProcessingStatus
from app.storage_service import storage_service

logger = structlog.get_logger()


class OCRService:
    """Handles OCR processing using the Nanonets model"""
    
    def __init__(self):
        self.model = None
        self.tokenizer = None
        self.processor = None
        self.device = None
        self.model_loaded = False
        
    async def initialize(self):
        """Initialize the OCR model"""
        try:
            logger.info("Initializing OCR model", model=settings.model_name)
            
            # Check GPU availability
            if torch.cuda.is_available() and settings.device == "cuda":
                self.device = torch.device("cuda")
                gpu_name = torch.cuda.get_device_name(0)
                logger.info("GPU available", device=gpu_name)
            else:
                self.device = torch.device("cpu")
                logger.warning("GPU not available, using CPU")
                
            # Load model and processor (following reference implementation)
            logger.info("Loading model weights")
            
            # Load tokenizer and processor
            self.tokenizer = AutoTokenizer.from_pretrained(settings.model_name)
            self.processor = AutoProcessor.from_pretrained(settings.model_name)
            
            # Load model with proper configuration
            model_kwargs = {
                "torch_dtype": torch.float16 if self.device.type == "cuda" else torch.float32,
                "device_map": "auto"
            }
            
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
        
    async def process_document(self, session_hash: str, file_path: str) -> Dict[str, Any]:
        """Process a PDF document"""
        # Initialize on first use if needed
        if not self.is_ready():
            logger.info("OCR service not initialized, initializing now...")
            await self.initialize()
            
        try:
            # Update status to processing
            storage_service.update_session_status(
                session_hash, 
                ProcessingStatus.PROCESSING,
                progress=0.0,
                message="Starting document processing"
            )
            
            # Phase 1: Extract all pages from PDF
            logger.info("Extracting pages from PDF", session_hash=session_hash)
            storage_service.update_session_status(
                session_hash, 
                ProcessingStatus.PROCESSING,
                progress=0.0,
                message="Extracting pages from PDF"
            )
            
            pages = await self._extract_pdf_pages(file_path)
            total_pages = len(pages)
            storage_service.update_session_metadata(session_hash, {'total_pages': total_pages})
            
            # Save all page images first
            logger.info("Saving page images", session_hash=session_hash, total_pages=total_pages)
            for idx, page_image in enumerate(pages):
                page_num = idx + 1
                progress = (idx / total_pages) * 30  # 30% for extraction
                
                storage_service.update_session_status(
                    session_hash,
                    ProcessingStatus.PROCESSING,
                    progress=progress,
                    message=f"Extracting page {page_num} of {total_pages}"
                )
                
                image_bytes = self._image_to_bytes(page_image)
                await storage_service.save_page_image(session_hash, page_num, image_bytes)
            
            # Phase 2: Process OCR on all pages
            logger.info("Starting OCR processing", session_hash=session_hash)
            results = []
            combined_text = []
            
            for idx, page_image in enumerate(pages):
                page_num = idx + 1
                progress = 30 + ((idx / total_pages) * 70)  # 70% for OCR
                
                # Update progress
                storage_service.update_session_status(
                    session_hash,
                    ProcessingStatus.PROCESSING,
                    progress=progress,
                    message=f"Processing OCR for page {page_num} of {total_pages}",
                    current_page=page_num
                )
                
                # Process OCR
                logger.info("Processing page OCR", session_hash=session_hash, page=page_num)
                page_text = await self._process_page(page_image)
                
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
            
            # Save metadata
            metadata = {
                'model': settings.model_name,
                'device': self.device.type,
                'total_pages': total_pages,
                'processed_at': datetime.utcnow().isoformat()
            }
            
            if self.device.type == "cuda":
                metadata['gpu_name'] = torch.cuda.get_device_name(0)
                
            metadata_path = get_session_file_path(
                session_hash, 'metadata.json', 'output'
            )
            with open(metadata_path, 'w') as f:
                json.dump(metadata, f, indent=2)
                
            # Update status to completed
            storage_service.update_session_status(
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
            
            storage_service.update_session_status(
                session_hash,
                ProcessingStatus.FAILED,
                message=f"Processing failed: {str(e)}"
            )
            raise
            
    async def _extract_pdf_pages(self, pdf_path: str) -> List[Image.Image]:
        """Extract pages from PDF as PIL images"""
        pages = []
        
        # Open PDF
        pdf_document = fitz.open(pdf_path)
        
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
            # Check if processor is initialized
            if self.processor is None:
                raise RuntimeError("Processor not initialized")
                
            # Preprocess image if needed
            image = self._preprocess_image(image)
            
            # Process with model
            logger.debug("Processing image with processor", image_size=image.size)
            try:
                # Format messages for the model (based on reference implementation)
                prompt = """Extract the text from the above document as if you were reading it naturally. Return the tables in html format. Return the equations in LaTeX representation. If there is an image in the document and image caption is not present, add a small description of the image inside the <img></img> tag; otherwise, add the image caption inside <img></img>. Watermarks should be wrapped in brackets. Ex: <watermark>OFFICIAL COPY</watermark>. Page numbers should be wrapped in brackets. Ex: <page_number>14</page_number> or <page_number>9/22</page_number>. Prefer using ☐ and ☑ for check boxes."""
                
                messages = [
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": [
                        {"type": "image"},
                        {"type": "text", "text": prompt},
                    ]},
                ]
                
                # Apply chat template
                text = self.processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
                inputs = self.processor(text=[text], images=[image], padding=True, return_tensors="pt")
            except Exception as proc_error:
                logger.error("Processor failed", error=str(proc_error), exc_info=True)
                raise
                
            if inputs is None:
                raise ValueError("Processor returned None")
            
            # Move inputs to device
            try:
                inputs = {k: v.to(self.device) if hasattr(v, 'to') else v for k, v in inputs.items()}
            except Exception as move_error:
                logger.error("Failed to move inputs to device", error=str(move_error))
                raise
            
            with torch.no_grad():
                output_ids = self.model.generate(
                    **inputs,
                    max_new_tokens=settings.max_new_tokens,
                    do_sample=False
                )
                
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