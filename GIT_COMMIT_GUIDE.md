# Git Commit Guide for Gnosis OCR V2 Release

## Important Files to Commit (Production Ready)

### Core Application Files
```bash
git add README.md                    # Updated with V2 features
git add LICENSE                      # Apache 2.0 license
git add .gitignore                   # Updated exclusions

# V2 Application Code
git add app/main_v2.py              # FastAPI V2 with chunked upload
git add app/ocr_service_v2_fixed.py # Fixed OCR service with intelligent caching
git add app/storage_service_v2.py   # Cloud storage integration
git add app/config.py               # Updated configuration
git add app/models.py               # Data models

# V2 Docker Configuration
git add Dockerfile.lean             # Production lean build
git add docker-compose.v2.yml       # V2 development setup

# V2 Frontend
git add static/index.html           # Updated UI with chunked upload
git add static/script.js            # WebSocket + chunked upload logic

# Deployment Scripts
git add scripts/build-deploy-v2.ps1 # Complete deployment automation
git add scripts/deploy-v2-clean.ps1 # Quick deployment

# Documentation
git add DEPLOYMENT_GUIDE.md         # Cloud Run deployment
git add API_DOCUMENTATION.md        # API reference
git add HUGGINGFACE_ONLINE.md      # Caching strategy
git add MIGRATION_GUIDE.md          # V1 to V2 migration
```

## Files to Exclude (Now in .gitignore)

### Version Backups
- `*_versions/` - All file version backups created by tools
- `.*_versions/` - Hidden version directories

### Debug/Diagnostic Scripts
- `check_*.ps1` - Cache checking scripts
- `debug_*.py` - Debug utilities
- `fix_*.ps1` - Temporary fix scripts
- `verify_*.ps1` - Verification scripts

### Temporary Files
- `.env.example.v2` - Old environment template
- `run_debug.py` - Debug runner
- `test_*.py` (except in tests/) - Temporary test files

## Quick Commit Commands

### Stage Core V2 Files
```bash
# Core application
git add README.md LICENSE .gitignore
git add app/main_v2.py app/ocr_service_v2_fixed.py app/storage_service_v2.py
git add app/config.py app/models.py

# Docker and deployment
git add Dockerfile.lean docker-compose.v2.yml
git add scripts/build-deploy-v2.ps1 scripts/deploy-v2-clean.ps1

# Frontend
git add static/index.html static/script.js

# Documentation
git add *GUIDE.md HUGGINGFACE_ONLINE.md
```

### Commit V2 Release
```bash
git commit -m "feat: Gnosis OCR V2 Production Release

- ✅ Chunked streaming upload (500MB support)
- ✅ WebSocket real-time progress tracking  
- ✅ Intelligent HuggingFace model caching
- ✅ GCS FUSE integration for persistence
- ✅ Cloud Run GPU deployment ready
- ✅ Apache 2.0 license
- ✅ Comprehensive documentation
- ✅ Error resilience and retry logic

Major improvements:
- Cloud Run 32MB limit bypass via 1MB chunks
- Smart online/offline model caching strategy
- Production-ready deployment automation
- Enterprise-grade file handling (500MB PDFs)
- Real-time upload/processing progress
- Session isolation and security"
```

## What's Now Ignored

The updated `.gitignore` will automatically exclude:
- All `*_versions/` backup directories
- Debug and diagnostic PowerShell scripts
- Temporary test files outside `/tests/`
- Environment file versions
- PowerShell command artifacts

This keeps the repository clean and focused on production-ready code while preserving your development history in the ignored backup directories.
