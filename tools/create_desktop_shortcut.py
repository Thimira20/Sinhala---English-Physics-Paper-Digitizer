"""
Creates a Windows Desktop Shortcut for the Sinhala & English Physics Paper Digitizer.
SPEC P3-T10: Desktop shortcut creation.
"""
import os
from pathlib import Path
import subprocess

def create_desktop_shortcut(target_path: Path = None, shortcut_name: str = "Sinhala & English Physics Digitizer.lnk") -> bool:
    project_root = Path(__file__).resolve().parent.parent
    if target_path is None:
        dist_exe = project_root / "dist" / "PhysicsDigitizer" / "PhysicsDigitizer.exe"
        if dist_exe.exists():
            target_path = dist_exe
        else:
            target_path = project_root / "run.bat"

    desktop = Path(os.environ.get("USERPROFILE", "")) / "Desktop"
    if not desktop.exists():
        desktop = Path.home() / "Desktop"

    shortcut_file = desktop / shortcut_name

    ps_script = f"""
    $WshShell = New-Object -ComObject WScript.Shell
    $Shortcut = $WshShell.CreateShortcut('{str(shortcut_file)}')
    $Shortcut.TargetPath = '{str(target_path)}'
    $Shortcut.WorkingDirectory = '{str(target_path.parent)}'
    $Shortcut.Description = 'Sinhala & English Physics Paper Digitizer'
    $Shortcut.Save()
    """
    res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], capture_output=True, text=True)
    if res.returncode == 0 and shortcut_file.exists():
        print(f"[OK] Desktop shortcut created at: {shortcut_file}")
        return True
    else:
        print(f"[WARN] PowerShell shortcut creation result: {res.stderr or res.stdout}")
        return False

if __name__ == "__main__":
    create_desktop_shortcut()
