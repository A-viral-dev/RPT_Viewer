import os
import subprocess
import sys
import shutil
import multiprocessing

def build():
    # 1. Ensure pyinstaller is installed
    try:
        import PyInstaller
    except ImportError:
        print("PyInstaller not found. Installing with uv...")
        # uv is significantly faster than pip for bootstrapping
        subprocess.check_call(["uv", "pip", "install", "pyinstaller"])

    # 2. Identify the NiceGUI path to include its assets
    import nicegui
    nicegui_path = os.path.dirname(nicegui.__file__)
    
    # 3. Define the build command with "EXTREME SPEED" optimizations
    # --noupx: Skips slow compression (Solves most "stuck" builds on Windows)
    # --exclude-module: Strips heavy, slow-to-analyze modules like pygments
    
    exclusions = [
        "matplotlib", "scipy", "tkinter", "tcl", "tk", "notebook", "IPython", 
        "PIL", "jedi", "PyQt5", "PyQt6", "PySide2", "PySide6", 
        "unittest", "test", "pydoc", "pygments"
    ]
    
    # On Windows, the path separator is ';' for --add-data
    add_data_path = f"{nicegui_path}{os.pathsep}nicegui"
    
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "main.py",
        "--onefile",
        "--name", "RPT_Data_Viewer",
        "--add-data", add_data_path,
        "--noconfirm",
        "--noupx",             # FASTER: Skips compression
        "--log-level", "INFO"  # Show progress to see where it's working
    ]
    
    for mod in exclusions:
        cmd.extend(["--exclude-module", mod])
    
    # Speed up PyInstaller by skipping compression check if it's already fast
    
    print(f"Running command: {' '.join(cmd)}")
    
    try:
        subprocess.check_call(cmd)
        print("\n" + "="*30)
        print("BUILD SUCCESSFUL!")
        print(f"Your standalone EXE is in: {os.path.join(os.getcwd(), 'dist', 'RPT_Data_Viewer.exe')}")
        print("="*30)
    except subprocess.CalledProcessError as e:
        print(f"Build failed with error: {e}")

if __name__ == "__main__":
    build()
