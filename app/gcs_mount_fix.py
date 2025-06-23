"""Fix GCS mount issues by creating proper directory structure"""
import os
import subprocess
import time

def diagnose_and_fix_mount():
    """Diagnose and fix GCS mount issues"""
    
    print("=== GCS Mount Diagnosis ===")
    
    # Check /cache
    if os.path.exists("/cache"):
        print(f"✓ /cache exists")
        
        # List contents with details
        result = subprocess.run(["ls", "-la", "/cache"], capture_output=True, text=True)
        print(f"\nContents of /cache:\n{result.stdout}")
        
        # Check if huggingface is accessible
        hf_path = "/cache/huggingface"
        if os.path.exists(hf_path):
            print(f"\n✓ {hf_path} exists")
            if os.path.isdir(hf_path):
                print(f"  It's a directory")
                try:
                    contents = os.listdir(hf_path)
                    print(f"  Contents: {contents[:5]}...")
                except Exception as e:
                    print(f"  ERROR accessing contents: {e}")
        else:
            print(f"\n✗ {hf_path} does not exist")
            
            # Try different access methods
            print("\nTrying alternative access methods...")
            
            # Method 1: Direct stat
            try:
                stat_result = os.stat("/cache/huggingface")
                print(f"  stat() succeeded: {stat_result}")
            except Exception as e:
                print(f"  stat() failed: {e}")
            
            # Method 2: Walk the directory
            try:
                for root, dirs, files in os.walk("/cache"):
                    print(f"  Walk: {root}")
                    print(f"    Dirs: {dirs[:5]}")
                    print(f"    Files: {files[:5]}")
                    if len(dirs) > 0 or len(files) > 0:
                        break
            except Exception as e:
                print(f"  Walk failed: {e}")
            
            # Method 3: Try to enter the directory
            try:
                original_cwd = os.getcwd()
                os.chdir("/cache")
                print(f"  Changed to /cache")
                
                # Now try to access huggingface
                if os.path.exists("huggingface"):
                    print(f"  ./huggingface exists from /cache")
                    os.chdir("huggingface")
                    print(f"  Changed to huggingface")
                    contents = os.listdir(".")
                    print(f"  Contents: {contents[:5]}")
                    
                os.chdir(original_cwd)
            except Exception as e:
                print(f"  chdir method failed: {e}")
                try:
                    os.chdir(original_cwd)
                except:
                    pass
    
    # Check mount status
    print("\n=== Mount Information ===")
    mount_result = subprocess.run(["mount"], capture_output=True, text=True)
    gcs_mounts = [line for line in mount_result.stdout.split('\n') if 'gcsfuse' in line or '/cache' in line]
    for mount in gcs_mounts:
        print(f"  {mount}")
    
    # Check environment
    print("\n=== Environment ===")
    for key in ["HF_HOME", "TRANSFORMERS_CACHE", "MODEL_CACHE_PATH"]:
        print(f"  {key}={os.environ.get(key, 'NOT SET')}")
    
    return True

if __name__ == "__main__":
    diagnose_and_fix_mount()