import os
import shutil
import datetime
import logging

def create_backup():
    # 1. Setup paths
    source_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(source_dir)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_folder_name = f"RPT_Viewer_Backup_{timestamp}"
    target_dir = os.path.join(parent_dir, backup_folder_name)
    
    # 2. Files/Folders to exclude
    # We exclude generated artifacts because they can be rebuilt from source
    exclude_dirs = {'.venv', '__pycache__', '.pytest_cache', '.git', '.nicegui', 'dist', 'build'}
    exclude_exts = {'.exe', '.pyc'}
    
    print(f"--- Starting Backup ---")
    print(f"Source: {source_dir}")
    print(f"Target: {target_dir}")
    
    try:
        if not os.path.exists(target_dir):
            os.makedirs(target_dir)
            
        for item in os.listdir(source_dir):
            if any(item.endswith(ext) for ext in exclude_exts):
                print(f" (i) Skipping excluded file: {item}")
                continue
                
            s = os.path.join(source_dir, item)
            d = os.path.join(target_dir, item)
            
            if os.path.isdir(s):
                if item in exclude_dirs:
                    print(f" (i) Skipping excluded directory: {item}")
                    continue
                shutil.copytree(s, d, dirs_exist_ok=True)
                print(f" [+] Copied directory: {item}")
            else:
                shutil.copy2(s, d)
                print(f" [+] Copied file: {item}")
        
        print(f"\n--- SUCCESS ---")
        print(f"Backup created at: {target_dir}")
        print(f"To restore: Copy contents back to a new folder and run 'uv sync'.")
        
    except Exception as e:
        print(f"\n[!] ERROR during backup: {e}")

if __name__ == "__main__":
    create_backup()
