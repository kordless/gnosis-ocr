"""Configuration management for Gnosis OCR Service"""
import os
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings with environment variable support"""
    
    # Server Configuration
    host: str = Field(default="0.0.0.0", env="HOST")
    port: int = Field(default=7799, env="PORT")
    
    # OCR Settings
    max_file_size: int = Field(default=524288000, env="MAX_FILE_SIZE")  # 500MB with chunked streaming
    session_timeout: int = Field(default=3600, env="SESSION_TIMEOUT")  # 1 hour
    max_pages: int = Field(default=500, env="MAX_PAGES")
    allowed_extensions: set[str] = {".pdf"}
    
    # GPU Configuration
    cuda_visible_devices: str = Field(default="0", env="CUDA_VISIBLE_DEVICES")
    torch_cuda_arch_list: str = Field(default="7.0;7.5;8.0;8.6", env="TORCH_CUDA_ARCH_LIST")
    
    # Model Settings
    model_name: str = Field(default="nanonets/Nanonets-OCR-s", env="MODEL_NAME")
    max_new_tokens: int = Field(default=8192, env="MAX_NEW_TOKENS")
    batch_size: int = Field(default=1, env="BATCH_SIZE")
    device: str = Field(default="cuda", env="DEVICE")
    
    # Storage
    storage_path: str = Field(default="/tmp/ocr_sessions", env="STORAGE_PATH")
    cleanup_interval: int = Field(default=300, env="CLEANUP_INTERVAL")  # 5 minutes
    
    # Logging
    log_level: str = Field(default="INFO", env="LOG_LEVEL")
    
    # Redis (optional)
    redis_url: Optional[str] = Field(default=None, env="REDIS_URL")
    
    # Database (optional)
    database_url: Optional[str] = Field(default=None, env="DATABASE_URL")
    
    # Security
    cors_origins: list[str] = Field(
        default=["*"],
        env="CORS_ORIGINS"
    )
    
    # API Keys (optional)
    api_key: Optional[str] = Field(default=None, env="API_KEY")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


# Create global settings instance
settings = Settings()


# Helper functions
def get_storage_path(session_hash: str, subdir: str = "") -> str:
    """Get the storage path for a session"""
    base_path = os.path.join(settings.storage_path, session_hash)
    if subdir:
        return os.path.join(base_path, subdir)
    return base_path


def get_session_file_path(session_hash: str, filename: str, subdir: str = "") -> str:
    """Get the full path for a file in a session"""
    return os.path.join(get_storage_path(session_hash, subdir), filename)


def validate_file_extension(filename: str) -> bool:
    """Check if file extension is allowed"""
    ext = os.path.splitext(filename)[1].lower()
    return ext in settings.allowed_extensions


def format_file_size(size_bytes: int) -> str:
    """Format file size in human readable format"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} TB"