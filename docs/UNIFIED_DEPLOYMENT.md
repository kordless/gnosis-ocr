# 🚀 UNIFIED DEPLOYMENT SCRIPT

## 📁 **Organized Structure**

Your deployment scripts are now properly organized:

```
gnosis-ocr/
├── scripts/
│   ├── deploy.ps1               # 🎯 MAIN DEPLOYMENT SCRIPT
│   ├── deploy-cloudrun.sh       # Bash Cloud Run deployment  
│   └── setup-gcp-permissions.sh # GCP permissions setup
├── docs/
│   └── SETUP_DEPLOYMENT.md      # Documentation
├── .env.cloudrun.example        # Template (committed)
├── .env.cloudrun               # Your config (gitignored)
└── cloudbuild.yaml             # Automated Cloud Build
```

## 🎯 **One Script - All Deployments**

**`scripts/deploy.ps1`** now handles everything:

### **Local Development**
```powershell
./scripts/deploy.ps1 -Target local
```
- Uses `Dockerfile` with GPU support
- Runs with `docker run` locally
- Available at `http://localhost:7799`

### **Staging Environment**  
```powershell
./scripts/deploy.ps1 -Target staging
```
- Uses `Dockerfile.cloudrun` (CPU optimized)
- Pushes to `gcr.io/PROJECT/gnosis-ocr:staging-TAG`
- Ready for staging deployment

### **Cloud Run with GPU** 
```powershell
./scripts/deploy.ps1 -Target cloudrun
```
- ✅ **Builds** with `Dockerfile.cloudrun` 
- ✅ **Pushes** to GCR
- ✅ **Deploys** to Cloud Run with:
  - NVIDIA L4 GPU
  - 16Gi memory
  - GCS bucket mount (`gs://gnosis-ocr-models` → `/app/cache`)
  - All environment variables
  - Service account permissions

### **Cloud Build** 
```powershell
./scripts/deploy.ps1 -Target cloud
```
- Uses Cloud Build for automated deployment
- Fallback for manual container builds

## 🔧 **Configuration**

The script automatically:
- ✅ **Reads** `.env.cloudrun` for PROJECT_ID and settings
- ✅ **Tags** images appropriately for each target
- ✅ **Authenticates** with GCR
- ✅ **Deploys** with correct configuration

## 🎉 **Benefits**

- **Clean Root Directory** - No more script clutter
- **One Command** - Deploy anywhere with target flag
- **Automatic Config** - Reads from `.env.cloudrun`
- **Full Cloud Run** - Complete deployment with GPU + GCS
- **Organized Docs** - All documentation in `docs/`

## 🚀 **Quick Start**

```powershell
# 1. Create environment config
cp .env.cloudrun.example .env.cloudrun
# Edit PROJECT_ID in .env.cloudrun

# 2. Deploy to Cloud Run with GPU + GCS buckets
./scripts/deploy.ps1 -Target cloudrun

# Done! 🎯
```

**Your deployment is now enterprise-grade with one unified script!** ⚡
