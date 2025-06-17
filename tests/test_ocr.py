"""OCR service tests for Gnosis OCR Service"""
import pytest
import torch
from unittest.mock import Mock, patch, MagicMock
from PIL import Image
import numpy as np
import tempfile
import fitz  # PyMuPDF

from app.ocr_service import OCRService
from app.models import ProcessingStatus


class TestOCRService:
    @pytest.fixture
    def ocr_service(self):
        """Create OCR service instance"""
        return OCRService()
        
    @pytest.fixture
    def mock_model(self):
        """Create mock model"""
        model = Mock()
        model.eval = Mock()
        model.to = Mock(return_value=model)
        model.generate = Mock(return_value=torch.tensor([[1, 2, 3]]))
        return model
        
    @pytest.fixture
    def mock_processor(self):
        """Create mock processor"""
        processor = Mock()
        processor.return_value = {
            'input_ids': torch.tensor([[1, 2, 3]]),
            'attention_mask': torch.tensor([[1, 1, 1]])
        }
        processor.batch_decode = Mock(return_value=["Extracted text content"])
        return processor
        
    def test_initialization_success(self, ocr_service, mock_model, mock_processor):
        """Test successful OCR service initialization"""
        with patch('app.ocr_service.AutoModel.from_pretrained', return_value=mock_model):
            with patch('app.ocr_service.AutoProcessor.from_pretrained', return_value=mock_processor):
                with patch('app.ocr_service.torch.cuda.is_available', return_value=True):
                    asyncio.run(ocr_service.initialize())
                    
                    assert ocr_service.model_loaded is True
                    assert ocr_service.model is not None
                    assert ocr_service.processor is not None
                    assert ocr_service.device.type == "cuda"
                    
    def test_initialization_cpu_fallback(self, ocr_service, mock_model, mock_processor):
        """Test OCR service initialization with CPU fallback"""
        with patch('app.ocr_service.AutoModel.from_pretrained', return_value=mock_model):
            with patch('app.ocr_service.AutoProcessor.from_pretrained', return_value=mock_processor):
                with patch('app.ocr_service.torch.cuda.is_available', return_value=False):
                    asyncio.run(ocr_service.initialize())
                    
                    assert ocr_service.device.type == "cpu"
                    
    def test_is_ready(self, ocr_service):
        """Test service readiness check"""
        assert ocr_service.is_ready() is False
        
        ocr_service.model_loaded = True
        ocr_service.model = Mock()
        assert ocr_service.is_ready() is True
        
    def test_get_gpu_info(self, ocr_service):
        """Test GPU info retrieval"""
        with patch('app.ocr_service.torch.cuda.is_available', return_value=False):
            info = ocr_service.get_gpu_info()
            assert info['available'] is False
            
        with patch('app.ocr_service.torch.cuda.is_available', return_value=True):
            with patch('app.ocr_service.torch.cuda.get_device_name', return_value="NVIDIA T4"):
                with patch('app.ocr_service.torch.cuda.device_count', return_value=1):
                    info = ocr_service.get_gpu_info()
                    assert info['available'] is True
                    assert info['device_name'] == "NVIDIA T4"
                    
    @patch('app.ocr_service.storage_service')
    async def test_process_document_success(self, mock_storage, ocr_service, mock_model, mock_processor):
        """Test successful document processing"""
        # Setup
        ocr_service.model = mock_model
        ocr_service.processor = mock_processor
        ocr_service.model_loaded = True
        ocr_service.device = torch.device("cpu")
        
        # Create test PDF
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
            doc = fitz.new()
            page = doc.new_page()
            page.insert_text((100, 100), "Test content")
            doc.save(tmp.name)
            tmp_path = tmp.name
            
        # Mock storage operations
        mock_storage.update_session_status = Mock()
        mock_storage.update_session_metadata = Mock()
        mock_storage.save_page_image = Mock()
        mock_storage.save_page_result = Mock()
        mock_storage.save_combined_result = Mock()
        mock_storage.get_session_file_path = Mock(return_value="/tmp/metadata.json")
        
        # Mock image extraction
        test_image = Image.new('RGB', (100, 100), color='white')
        with patch.object(ocr_service, '_extract_pdf_pages', return_value=[test_image]):
            result = await ocr_service.process_document("test-session", tmp_path)
            
        assert result['status'] == 'completed'
        assert result['total_pages'] == 1
        assert len(result['results']) == 1
        
        # Verify storage calls
        mock_storage.update_session_status.assert_called()
        mock_storage.save_page_image.assert_called_once()
        mock_storage.save_page_result.assert_called_once()
        
    async def test_extract_pdf_pages(self, ocr_service):
        """Test PDF page extraction"""
        # Create test PDF
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
            doc = fitz.new()
            for i in range(3):
                page = doc.new_page()
                page.insert_text((100, 100), f"Page {i+1}")
            doc.save(tmp.name)
            tmp_path = tmp.name
            
        pages = await ocr_service._extract_pdf_pages(tmp_path)
        
        assert len(pages) == 3
        assert all(isinstance(page, Image.Image) for page in pages)
        
    def test_preprocess_image(self, ocr_service):
        """Test image preprocessing"""
        # Create test image
        test_image = Image.new('RGB', (200, 200), color='white')
        
        processed = ocr_service._preprocess_image(test_image)
        
        assert isinstance(processed, Image.Image)
        assert processed.mode == 'L'  # Should be grayscale
        
    def test_postprocess_text(self, ocr_service):
        """Test text post-processing"""
        input_text = """
        Test  text  with   extra   spaces
        
        
        Some LaTeX: \\\\(x^2\\\\) and \\\\[y^3\\\\]
        
        More content here
        """
        
        processed = ocr_service._postprocess_text(input_text)
        
        assert "Test text with extra spaces" in processed
        assert "$x^2$" in processed  # LaTeX converted
        assert "$$y^3$$" in processed
        assert processed.count('\n\n') < input_text.count('\n\n')  # Reduced whitespace
        
    async def test_process_page(self, ocr_service, mock_model, mock_processor):
        """Test single page processing"""
        ocr_service.model = mock_model
        ocr_service.processor = mock_processor
        ocr_service.device = torch.device("cpu")
        
        test_image = Image.new('RGB', (100, 100), color='white')
        
        with patch.object(ocr_service, '_preprocess_image', return_value=test_image):
            result = await ocr_service._process_page(test_image)
            
        assert isinstance(result, str)
        assert len(result) > 0
        
    async def test_cleanup(self, ocr_service):
        """Test service cleanup"""
        ocr_service.model = Mock()
        ocr_service.processor = Mock()
        ocr_service.model_loaded = True
        
        await ocr_service.cleanup()
        
        assert ocr_service.model is None
        assert ocr_service.processor is None
        assert ocr_service.model_loaded is False


# Import asyncio for async tests
import asyncio

if __name__ == "__main__":
    pytest.main([__file__])