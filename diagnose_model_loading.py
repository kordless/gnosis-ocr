#!/usr/bin/env python3
"""
Diagnose what files the Nanonets model is trying to load
"""
import os
import sys
import logging
from pathlib import Path

# Set up logging to see what HuggingFace is doing
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger()

# Force offline mode
os.environ["HF_DATASETS_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_CACHE"] = os.path.expanduser("~/.cache/huggingface")
os.environ["HF_HOME"] = os.path.expanduser("~/.cache/huggingface")

print("Environment variables set:")
for key in ["HF_DATASETS_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_HUB_OFFLINE", "TRANSFORMERS_CACHE", "HF_HOME"]:
    print(f"  {key}={os.environ.get(key)}")

print("\nAttempting to load Nanonets model components...")

model_name = "nanonets/Nanonets-OCR-s"

# Try to load each component separately to see what fails
print(f"\n1. Trying to load tokenizer for {model_name}...")
try:
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(
        model_name,
        local_files_only=True,
        trust_remote_code=True,
        cache_dir=os.environ["TRANSFORMERS_CACHE"]
    )
    print("✅ Tokenizer loaded successfully!")
except Exception as e:
    print(f"❌ Tokenizer failed: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()

print(f"\n2. Trying to load processor for {model_name}...")
try:
    from transformers import AutoProcessor
    processor = AutoProcessor.from_pretrained(
        model_name,
        local_files_only=True,
        trust_remote_code=True,
        cache_dir=os.environ["TRANSFORMERS_CACHE"]
    )
    print("✅ Processor loaded successfully!")
except Exception as e:
    print(f"❌ Processor failed: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()

print(f"\n3. Trying to load config for {model_name}...")
try:
    from transformers import AutoConfig
    config = AutoConfig.from_pretrained(
        model_name,
        local_files_only=True,
        trust_remote_code=True,
        cache_dir=os.environ["TRANSFORMERS_CACHE"]
    )
    print("✅ Config loaded successfully!")
    print(f"   Model type: {config.model_type}")
except Exception as e:
    print(f"❌ Config failed: {type(e).__name__}: {e}")

print(f"\n4. Checking cache structure...")
cache_dir = Path(os.environ["TRANSFORMERS_CACHE"])
model_dir = cache_dir / "hub" / f"models--{model_name.replace('/', '--')}"

if model_dir.exists():
    print(f"Model directory exists: {model_dir}")
    
    # Check refs
    refs_dir = model_dir / "refs"
    if refs_dir.exists():
        print("\nRefs:")
        for ref_file in refs_dir.iterdir():
            with open(ref_file) as f:
                commit = f.read().strip()
                print(f"  {ref_file.name} -> {commit}")
    
    # Check snapshots
    snapshots_dir = model_dir / "snapshots"
    if snapshots_dir.exists():
        print("\nSnapshots:")
        for snapshot in snapshots_dir.iterdir():
            if snapshot.is_dir():
                print(f"\n  {snapshot.name}:")
                files = list(snapshot.iterdir())
                for file in sorted(files)[:20]:  # First 20 files
                    if file.is_file():
                        size_mb = file.stat().st_size / (1024**2)
                        print(f"    {file.name} ({size_mb:.2f} MB)")

print("\n5. Checking for remote code files...")
# Nanonets model uses trust_remote_code, so it might need additional Python files
snapshot_dir = model_dir / "snapshots"
if snapshot_dir.exists():
    for snapshot in snapshot_dir.iterdir():
        if snapshot.is_dir():
            py_files = list(snapshot.glob("*.py"))
            if py_files:
                print(f"\nPython files in {snapshot.name}:")
                for py_file in py_files:
                    print(f"  - {py_file.name}")
            else:
                print(f"\n⚠️ No Python files found in {snapshot.name}")
                print("  This might be why trust_remote_code is failing!")

print("\n6. Looking for image processor files...")
for snapshot in snapshots_dir.iterdir() if snapshots_dir.exists() else []:
    if snapshot.is_dir():
        image_proc_files = list(snapshot.glob("*image*processor*"))
        video_proc_files = list(snapshot.glob("*video*processor*"))
        if image_proc_files or video_proc_files:
            print(f"\nProcessor files in {snapshot.name}:")
            for f in image_proc_files + video_proc_files:
                print(f"  - {f.name}")