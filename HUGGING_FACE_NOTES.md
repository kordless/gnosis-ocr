# HuggingFace Offline Mode & GCS FUSE Mount Analysis

## 🔍 Research Summary

### Key Discoveries

#### 1. HuggingFace Offline Mode Issues
- **Problem**: Even with `HF_HUB_OFFLINE=1` and `local_files_only=True`, HuggingFace still attempts HTTP HEAD requests
- **Root Cause**: Library tries to verify metadata even in offline mode
- **Impact**: Causes failures in truly air-gapped environments

#### 2. Our Mount Configuration Analysis

**Current Setup:**
```bash
# Cloud Run Deployment
--add-volume name=model-cache,type=cloud-storage,bucket=gnosis-ocr-models
--add-volume-mount volume=model-cache,mount-path=/cache

# Environment Variables
MODEL_CACHE_PATH=/cache/huggingface
HF_HOME=/cache/huggingface
TRANSFORMERS_CACHE=/cache/huggingface
```

**Previous OCR Service Issue (FIXED):**
```python
# WRONG - Using ephemeral storage
cache_kwargs = {
    "local_files_only": False,
    "cache_dir": "/tmp/hf_cache"  # Ephemeral!
}
```

**New Fixed Version:**
```python
# CORRECT - Using mounted GCS cache
cache_dir = os.environ.get('MODEL_CACHE_PATH', '/cache/huggingface')
model_cache_path = os.path.join(cache_dir, 'hub', f'models--{model_name.replace("/", "--")}')

if os.path.exists(model_cache_path):
    # Use offline mode with cached model
    cache_kwargs = {"local_files_only": True, "cache_dir": cache_dir}
else:
    # Download to persistent cache
    cache_kwargs = {"local_files_only": False, "cache_dir": cache_dir}
```

## 🎯 GCS FUSE Mount Behavior

### How It Works
1. **Bidirectional**: Files written to `/cache` are automatically saved to `gnosis-ocr-models` bucket
2. **Persistent**: Downloads persist across container restarts
3. **Automatic**: No manual upload/download needed
4. **Performance**: First access may be slower, subsequent reads are cached

### Answer to Your Questions

> **"Would it be possible to mount it and then download from HuggingFace automatically?"**
**YES!** This is exactly how it should work.

> **"Would that not save the files on the cloud storage device?"**
**YES!** Files written to the FUSE mount ARE saved to GCS bucket permanently.

## 🔧 Recommended Architecture

### Optimal Setup
```
Cloud Run Container:
├── /cache (GCS FUSE mount to gnosis-ocr-models bucket)
│   └── huggingface/
│       └── hub/
│           └── models--nanonets--Nanonets-OCR-s/
│               ├── refs/main
│               ├── snapshots/
│               └── blobs/
└── /tmp/storage (ephemeral for sessions)
```

### Smart Caching Strategy
1. **First Deploy**: Download models to mounted `/cache` → Saves to GCS bucket
2. **Subsequent Deploys**: Use cached models from GCS mount → Fast startup
3. **Offline Capability**: Works offline after first download

## 🚀 Implementation Benefits

### Performance
- **Cold Start**: Models load from GCS cache (fast after first download)
- **Warm Start**: Models already in memory
- **Bandwidth**: No repeated downloads

### Cost Efficiency
- **Storage**: Pay for bucket storage vs repeated downloads
- **Egress**: Minimal after initial download
- **Time**: Faster container startup

### Reliability
- **Offline Capable**: Works without internet after cache population
- **Version Control**: Specific model versions cached
- **Disaster Recovery**: Models persist in GCS bucket

## 📋 Action Items

### Immediate Fixes ✅
- [x] Fix OCR service to use mounted cache instead of `/tmp`
- [x] Add intelligent cache detection logic
- [x] Implement fallback download strategy

### Recommended Enhancements
- [ ] Pre-populate cache bucket with models during CI/CD
- [ ] Add cache warming endpoint for forced model download
- [ ] Implement cache validation and health checks
- [ ] Add metrics for cache hit/miss rates

## 🔬 Technical Validation

### Environment Variables (Current)
```bash
# Correct paths
MODEL_CACHE_PATH=/cache/huggingface
HF_HOME=/cache/huggingface
TRANSFORMERS_CACHE=/cache/huggingface

# Force offline when appropriate
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
```

### Cache Structure
```
/cache/huggingface/
├── hub/
│   └── models--nanonets--Nanonets-OCR-s/
│       ├── refs/main (contains commit hash)
│       ├── snapshots/{commit_hash}/
│       │   ├── config.json
│       │   ├── preprocessor_config.json
│       │   ├── tokenizer.json
│       │   └── pytorch_model.bin
│       └── blobs/ (deduplicated file storage)
└── datasets/ (if needed)
```

## 🎉 Expected Behavior After Fix

1. **First Container Start**:
   - Check `/cache/huggingface` for models
   - Not found → Download from HuggingFace to mounted cache
   - Files automatically saved to GCS bucket
   - Model loads successfully

2. **Subsequent Container Starts**:
   - Check `/cache/huggingface` for models
   - Found → Load from cache (offline mode)
   - Fast startup, no downloads

3. **Disaster Recovery**:
   - New region/project → Mount same bucket
   - Models immediately available
   - No re-download needed

## 🔧 Deployment Script Enhancement

Consider adding cache validation to deployment:

```bash
# Optional: Pre-warm cache bucket
gsutil -m cp -r ~/.cache/huggingface/* gs://gnosis-ocr-models/huggingface/

# Verify cache mount in deployment
gcloud run deploy gnosis-ocr \
  --add-volume name=model-cache,type=cloud-storage,bucket=gnosis-ocr-models \
  --add-volume-mount volume=model-cache,mount-path=/cache \
  --set-env-vars "MODEL_CACHE_PATH=/cache/huggingface"
```

This architecture provides the best of both worlds: automatic model caching with GCS persistence and intelligent offline/online mode switching.