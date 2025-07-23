"""
Gnosis OCR-S - Clean FastAPI Web Application
"""

__version__ = "0.1.0"
__author__ = "Gnosis Team"

# Import key components for easy access
from app.config import settings
from app.storage_service import StorageService

__all__ = [
    "settings",
    "StorageService",
    "__version__",
    "__author__"
]

