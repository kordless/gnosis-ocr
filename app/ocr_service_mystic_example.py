"""
Example: Integrating Mystic with OCR Service
This shows how to modify ocr_service.py to use Mystic decorators.
"""

# Original imports
from typing import List, Dict, Any, Tuple
import base64
import io
import time
import logging
from PIL import Image
import torch
from transformers import AutoModel, AutoProcessor

# Add Mystic integration
from app.mystic_integration import mystic_aware

logger = logging.getLogger(__name__)


class OCRService:
    """OCR service with Mystic integration for performance optimization."""
    
    def __init__(self, model_name: str = "nanonets/Nanonets-OCR-s"):
        self.model_name = model_name
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self._load_model()
    
    def _load_model(self):
        """Load the OCR model and processor."""
        logger.info(f"Loading model {self.model_name} on {self.device}")
        self.model = AutoModel.from_pretrained(
            self.model_name,
            trust_remote_code=True
        ).to(self.device)
        self.processor = AutoProcessor.from_pretrained(
            self.model_name,
            trust_remote_code=True
        )
        logger.info("Model loaded successfully")
    
    @mystic_aware  # Add caching and performance tracking
    async def process_image(self, image_data: bytes) -> Dict[str, Any]:
        """
        Process an image and extract text using OCR.
        
        This function benefits from Mystic's caching - identical images
        will return cached results instantly instead of re-processing.
        
        Args:
            image_data: Raw image bytes
            
        Returns:
            Dictionary containing extracted text and metadata
        """
        try:
            # Load image
            image = Image.open(io.BytesIO(image_data))
            
            # Process with model
            result = await self._run_ocr(image)
            
            return {
                "success": True,
                "text": result["text"],
                "confidence": result["confidence"],
                "processing_time": result["processing_time"],
                "image_size": image.size,
                "cached": False  # Mystic will override this if cached
            }
            
        except Exception as e:
            logger.error(f"OCR processing failed: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    @mystic_aware  # Track performance of core OCR function
    async def _run_ocr(self, image: Image.Image) -> Dict[str, Any]:
        """
        Core OCR processing logic.
        
        Benefits from Mystic:
        - Performance tracking to identify slow images
        - Automatic retry on transient failures
        - Circuit breaker for GPU issues
        """
        start_time = time.time()
        
        # Prepare image for model
        inputs = self.processor(image, return_tensors="pt").to(self.device)
        
        # Run inference
        with torch.no_grad():
            outputs = self.model(**inputs)
        
        # Extract text
        text = self.processor.batch_decode(outputs.logits)[0]
        
        processing_time = time.time() - start_time
        
        return {
            "text": text,
            "confidence": 0.95,  # Placeholder - real model might provide this
            "processing_time": processing_time
        }
    
    @mystic_aware  # Add mocking capability for tests
    async def validate_image(self, image_data: bytes) -> Tuple[bool, str]:
        """
        Validate image before processing.
        
        In tests, Mystic can mock this to always return True,
        avoiding complex image validation logic.
        """
        try:
            image = Image.open(io.BytesIO(image_data))
            
            # Check image format
            if image.format not in ['JPEG', 'PNG', 'BMP', 'TIFF']:
                return False, f"Unsupported format: {image.format}"
            
            # Check image size
            width, height = image.size
            if width * height > 25_000_000:  # 25 megapixels
                return False, "Image too large"
            
            if width < 10 or height < 10:
                return False, "Image too small"
            
            return True, "Valid"
            
        except Exception as e:
            return False, f"Invalid image: {str(e)}"
    
    @mystic_aware  # Monitor batch processing performance
    async def process_batch(self, images: List[bytes]) -> List[Dict[str, Any]]:
        """
        Process multiple images in batch.
        
        Mystic helps by:
        - Identifying if batch processing is actually faster
        - Caching individual results within batches
        - Tracking optimal batch sizes
        """
        results = []
        
        for i, image_data in enumerate(images):
            logger.info(f"Processing image {i+1}/{len(images)}")
            result = await self.process_image(image_data)
            results.append(result)
        
        return results


# Example: Using Mystic for different environments
def create_ocr_service(environment: str = "production") -> OCRService:
    """
    Create OCR service with environment-specific configuration.
    
    Claude can instruct Mystic to:
    - In development: Mock expensive GPU operations
    - In testing: Use cached results for deterministic tests
    - In production: Cache results for 1 hour
    """
    service = OCRService()
    
    if environment == "development":
        # Mystic can be configured to mock slow operations
        logger.info("Development mode: Mystic mocking enabled")
    elif environment == "testing":
        # Mystic can provide deterministic results
        logger.info("Testing mode: Mystic deterministic mode")
    else:
        # Production: full caching and optimization
        logger.info("Production mode: Mystic optimization enabled")
    
    return service


# Example usage showing Mystic benefits
async def demo_mystic_benefits():
    """Demonstrate how Mystic improves the OCR service."""
    
    service = create_ocr_service("production")
    
    # First call - normal processing
    with open("sample.jpg", "rb") as f:
        image_data = f.read()
    
    print("First call (no cache):")
    start = time.time()
    result1 = await service.process_image(image_data)
    print(f"Time: {time.time() - start:.2f}s")
    
    # Second call - Mystic returns cached result
    print("\nSecond call (cached by Mystic):")
    start = time.time()
    result2 = await service.process_image(image_data)
    print(f"Time: {time.time() - start:.2f}s")  # Should be ~0.00s
    
    # With Mystic, you can ask Claude:
    # - "Show me the slowest OCR operations"
    # - "Add 30-minute caching to process_image"
    # - "Mock the OCR model in test environment"
    # - "Show me images that fail validation"
    # - "Track batch processing performance"
