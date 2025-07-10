# 🚀 QUICK DEPLOYMENT SETUP

## 📋 **SETUP STEPS**

### 1. **Create Environment File**
```bash
# Copy the example
cp .env.cloudrun.example .env.cloudrun

# Edit with your project ID
nano .env.cloudrun
```

**Update this line:**
```bash
PROJECT_ID=your-actual-project-id-here
```

**Get your project ID:**
```bash
gcloud config get-value project
```

### 2. **Set Permissions (One Time)**
```bash
chmod +x scripts/setup-gcp-permissions.sh
./scripts/setup-gcp-permissions.sh
```

### 3. **Deploy**

**Option A: Automated**
```bash
gcloud builds submit --config cloudbuild.yaml
```

**Option B: Manual**
```bash
chmod +x deploy-cloudrun.sh
./deploy-cloudrun.sh
```

## 🔒 **Security Note**

- ✅ `.env.cloudrun` is in `.gitignore` (your PROJECT_ID stays private)
- ✅ `.env.cloudrun.example` is committed (template for others)
- ✅ Local development doesn't need `.env.cloudrun` (uses docker-compose.yml)

## 🎯 **What Each Method Does**

### **Cloud Build** (Recommended)
- Uses your current gcloud project automatically
- Builds in Google Cloud (faster, more reliable)
- No local Docker build needed

### **Manual Script**
- Reads PROJECT_ID from `.env.cloudrun`
- Builds locally then pushes
- Good for debugging

## ⚡ **Ready to Deploy!**
Your `.env.cloudrun` contains all the GPU + GCS configuration needed for instant deployment! 🚀
