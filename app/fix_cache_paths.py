"""Fix cache paths for HuggingFace models"""
import os
import shutil
from pathlib import Path

def fix_cache_paths():
    """Create proper cache structure for HuggingFace"""
    
    # Define paths
    gcs_mount = "/cache"
    hf_home = os.environ.get("HF_HOME", "/cache/huggingface")
    transformers_cache = os.environ.get("TRANSFORMERS_CACHE", "/cache/huggingface")
    
    print(f"Fixing cache paths...")
    print(f"GCS mount: {gcs_mount}")
    print(f"HF_HOME: {hf_home}")
    print(f"TRANSFORMERS_CACHE: {transformers_cache}")
    
    # Check if GCS is mounted
    if not os.path.exists(gcs_mount):
        print(f"ERROR: GCS mount {gcs_mount} does not exist!")
        return False
    
    # Check what's in the GCS mount
    print(f"\nContents of {gcs_mount}:")
    for item in os.listdir(gcs_mount):
        print(f"  - {item}")
    
    # Create symlinks if needed
    if gcs_mount != hf_home and os.path.exists(f"{gcs_mount}/huggingface"):
        print(f"\nCreating symlink: {hf_home} -> {gcs_mount}/huggingface")
        os.makedirs(os.path.dirname(hf_home), exist_ok=True)
        if os.path.exists(hf_home) and not os.path.islink(hf_home):
            shutil.rmtree(hf_home)
        if not os.path.exists(hf_home):
            os.symlink(f"{gcs_mount}/huggingface", hf_home)
    
    # Also create ~/.cache/huggingface symlink
    home_cache = os.path.expanduser("~/.cache/huggingface")
    if not os.path.exists(home_cache) and os.path.exists(f"{gcs_mount}/huggingface"):
        print(f"\nCreating symlink: {home_cache} -> {gcs_mount}/huggingface")
        os.makedirs(os.path.dirname(home_cache), exist_ok=True)
        os.symlink(f"{gcs_mount}/huggingface", home_cache)
    
    # Verify the model exists
    model_paths = [
        f"{hf_home}/hub/models--nanonets--Nanonets-OCR-s",
        f"{transformers_cache}/models--nanonets--Nanonets-OCR-s",
        f"{gcs_mount}/huggingface/hub/models--nanonets--Nanonets-OCR-s",
    ]
    
    print(f"\nChecking for model:")
    model_found = False
    for path in model_paths:
        if os.path.exists(path):
            print(f"  ✓ Found at: {path}")
            model_found = True
            # Check contents
            if os.path.exists(f"{path}/snapshots"):
                snapshots = os.listdir(f"{path}/snapshots")
                print(f"    Snapshots: {snapshots}")
        else:
            print(f"  ✗ Not at: {path}")
    
    return model_found

if __name__ == "__main__":
    fix_cache_paths()