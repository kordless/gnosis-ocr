# 🔧 HuggingFace Online Mode & Deployment Script Fixes

## 🚨 Issues Found

### 1. **Forced Offline Mode in Deployment Scripts**
The deployment scripts were **forcing HuggingFace into offline mode**, preventing downloads:

```bash
# WRONG - Forces offline mode
HF_DATASETS_OFFLINE=1
TRANSFORMERS_OFFLINE=1  
HF_HUB_OFFLINE=1
```

This contradicted our new intelligent caching strategy that needs to download models when not found in cache.

### 2. **Inconsistent Cache Paths**
Some paths were pointing to `/cache` instead of `/cache/huggingface`:

```bash
# INCONSISTENT
MODEL_CACHE_PATH=/cache          # Should be /cache/huggingface
HF_HOME=/cache                   # Should be /cache/huggingface
TRANSFORMERS_CACHE=/cache        # Should be /cache/huggingface
```

## ✅ Fixes Applied

### 1. **OCR Service Updates**
**File**: `app/ocr_service_v2_fixed.py`

**Before**:
```python
cache_kwargs = {
    "local_files_only": False,
    "cache_dir": "/tmp/hf_cache"  # Ephemeral!
}
```

**After**:
```python
cache_dir = os.environ.get('MODEL_CACHE_PATH', '/cache/huggingface')
model_cache_path = os.path.join(cache_dir, 'hub', f'models--{model_name.replace("/", "--")}')

if os.path.exists(model_cache_path):
    # Use offline mode with cached model
    cache_kwargs = {"local_files_only": True, "cache_dir": cache_dir}
else:
    # Download to persistent cache
    cache_kwargs = {"local_files_only": False, "cache_dir": cache_dir}
```

### 2. **Deployment Script Updates**

#### **PowerShell Script**: `scripts/build-deploy-v2.ps1`

**Before**:
```bash
--set-env-vars "RUNNING_IN_CLOUD=true,STORAGE_PATH=/tmp/storage,GCS_BUCKET_NAME=gnosis-ocr-storage,MODEL_BUCKET_NAME=gnosis-ocr-models,MODEL_CACHE_PATH=/cache,HF_HOME=/cache,TRANSFORMERS_CACHE=/cache,HUGGINGFACE_HUB_CACHE=/cache/hub,PYTORCH_TRANSFORMERS_CACHE=/cache,PYTORCH_PRETRAINED_BERT_CACHE=/cache,HF_DATASETS_OFFLINE=1,TRANSFORMERS_OFFLINE=1,HF_HUB_OFFLINE=1,HF_HUB_DISABLE_SYMLINKS_WARNING=1"
```

**After**:
```bash
--set-env-vars "RUNNING_IN_CLOUD=true,STORAGE_PATH=/tmp/storage,GCS_BUCKET_NAME=gnosis-ocr-storage,MODEL_BUCKET_NAME=gnosis-ocr-models,MODEL_CACHE_PATH=/cache/huggingface,HF_HOME=/cache/huggingface,TRANSFORMERS_CACHE=/cache/huggingface,HUGGINGFACE_HUB_CACHE=/cache/huggingface,HF_HUB_DISABLE_SYMLINKS_WARNING=1"
```

#### **Bash Script**: `deploy-debug.sh`

**Before**:
```bash
--set-env-vars "RUNNING_IN_CLOUD=true,STORAGE_PATH=/tmp/storage,GCS_BUCKET_NAME=gnosis-ocr-storage,MODEL_BUCKET_NAME=gnosis-ocr-models,MODEL_CACHE_PATH=/cache/huggingface,HF_HOME=/cache/huggingface,TRANSFORMERS_CACHE=/cache/huggingface,HUGGINGFACE_HUB_CACHE=/cache/huggingface/hub,HF_DATASETS_OFFLINE=1,TRANSFORMERS_OFFLINE=1,HF_HUB_OFFLINE=1,HF_HUB_DISABLE_SYMLINKS_WARNING=1"
```

**After**:
```bash
--set-env-vars "RUNNING_IN_CLOUD=true,STORAGE_PATH=/tmp/storage,GCS_BUCKET_NAME=gnosis-ocr-storage,MODEL_BUCKET_NAME=gnosis-ocr-models,MODEL_CACHE_PATH=/cache/huggingface,HF_HOME=/cache/huggingface,TRANSFORMERS_CACHE=/cache/huggingface,HUGGINGFACE_HUB_CACHE=/cache/huggingface,HF_HUB_DISABLE_SYMLINKS_WARNING=1"
```

## 🎯 Key Changes Summary

### **Removed**:
- ❌ `HF_DATASETS_OFFLINE=1`
- ❌ `TRANSFORMERS_OFFLINE=1`  
- ❌ `HF_HUB_OFFLINE=1`
- ❌ `PYTORCH_TRANSFORMERS_CACHE=/cache` (wrong path)
- ❌ `PYTORCH_PRETRAINED_BERT_CACHE=/cache` (wrong path)

### **Updated**:
- ✅ `MODEL_CACHE_PATH=/cache/huggingface` (consistent path)
- ✅ `HF_HOME=/cache/huggingface` (consistent path)
- ✅ `TRANSFORMERS_CACHE=/cache/huggingface` (consistent path)
- ✅ `HUGGINGFACE_HUB_CACHE=/cache/huggingface` (consistent path)

### **Kept**:
- ✅ `HF_HUB_DISABLE_SYMLINKS_WARNING=1` (reduces noise)

## 🚀 Expected Behavior Now

### **First Deployment**:
1. Container starts
2. OCR service checks `/cache/huggingface/hub/models--nanonets--Nanonets-OCR-s/`
3. **Not found** → Downloads from HuggingFace to mounted cache
4. Files automatically saved to GCS bucket `gnosis-ocr-models`
5. Model loads successfully

### **Subsequent Deployments**:
1. Container starts  
2. OCR service checks `/cache/huggingface/hub/models--nanonets--Nanonets-OCR-s/`
3. **Found** → Uses offline mode with cached model
4. Fast startup, no downloads needed

### **Logs to Expect**:
```
Starting model load process...
Model not in cache, will download to: /cache/huggingface
Using ONLINE mode - will download to mounted GCS cache
Loading processor for nanonets/Nanonets-OCR-s...
✅ Processor loaded successfully
Loading model nanonets/Nanonets-OCR-s...
✅ Model loaded successfully WITHOUT trust_remote_code
Model initialization complete
```

**Next deployment**:
```
Starting model load process...
Model found in cache: /cache/huggingface/hub/models--nanonets--Nanonets-OCR-s
Using OFFLINE mode - model found in mounted cache
✅ Model loaded successfully WITHOUT trust_remote_code
Model initialization complete
```

## 🎉 Benefits of This Fix

1. **Smart Caching**: Downloads only when needed, uses cache when available
2. **Cost Optimization**: No repeated downloads after first deployment
3. **Faster Startup**: Subsequent deployments load from cache instantly
4. **Persistent Storage**: Models stored permanently in GCS bucket
5. **Offline Capability**: Works offline after initial download
6. **Reduced Bandwidth**: Saves Cloud Run egress costs

The system now properly utilizes the expensive GCS FUSE mount for intelligent model caching while allowing initial downloads when needed!