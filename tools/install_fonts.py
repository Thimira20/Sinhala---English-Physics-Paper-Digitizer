"""
Download and install static Noto Sans Sinhala & Noto Sans fonts per-user (no admin rights required).
Registers fonts in Windows registry under HKCU and broadcasts WM_FONTCHANGE.
Also mirrors fonts to static/fonts/ for browser @font-face.
"""
from pathlib import Path
import os
import shutil
import urllib.request
import winreg
import ctypes

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ASSETS_FONTS_DIR = PROJECT_ROOT / "assets" / "fonts"
STATIC_FONTS_DIR = PROJECT_ROOT / "static" / "fonts"
ASSETS_FONTS_DIR.mkdir(parents=True, exist_ok=True)
STATIC_FONTS_DIR.mkdir(parents=True, exist_ok=True)

FONTS = [
    {
        "filename": "NotoSansSinhala-Regular.ttf",
        "reg_name": "Noto Sans Sinhala (TrueType)",
        "url": "https://raw.githubusercontent.com/googlefonts/noto-fonts/main/hinted/ttf/NotoSansSinhala/NotoSansSinhala-Regular.ttf"
    },
    {
        "filename": "NotoSansSinhala-Bold.ttf",
        "reg_name": "Noto Sans Sinhala Bold (TrueType)",
        "url": "https://raw.githubusercontent.com/googlefonts/noto-fonts/main/hinted/ttf/NotoSansSinhala/NotoSansSinhala-Bold.ttf"
    },
    {
        "filename": "NotoSans-Regular.ttf",
        "reg_name": "Noto Sans (TrueType)",
        "url": "https://raw.githubusercontent.com/googlefonts/noto-fonts/main/hinted/ttf/NotoSans/NotoSans-Regular.ttf"
    },
    {
        "filename": "NotoSans-Bold.ttf",
        "reg_name": "Noto Sans Bold (TrueType)",
        "url": "https://raw.githubusercontent.com/googlefonts/noto-fonts/main/hinted/ttf/NotoSans/NotoSans-Bold.ttf"
    },
    {
        "filename": "NotoSans-Italic.ttf",
        "reg_name": "Noto Sans Italic (TrueType)",
        "url": "https://raw.githubusercontent.com/googlefonts/noto-fonts/main/hinted/ttf/NotoSans/NotoSans-Italic.ttf"
    }
]

OFL_URL = "https://raw.githubusercontent.com/googlefonts/noto-fonts/main/OFL.txt"

def download_file(url: str, dest: Path) -> None:
    print(f"Downloading {dest.name}...")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    with urllib.request.urlopen(req) as resp, open(dest, "wb") as f:
        f.write(resp.read())

def get_user_fonts_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        local_app_data = str(Path.home() / "AppData" / "Local")
    user_fonts = Path(local_app_data) / "Microsoft" / "Windows" / "Fonts"
    user_fonts.mkdir(parents=True, exist_ok=True)
    return user_fonts

def install_font_in_windows(font_path: Path, reg_name: str) -> bool:
    """Installs font for current user via HKCU registry without admin privileges."""
    try:
        user_fonts_dir = get_user_fonts_dir()
        target_path = user_fonts_dir / font_path.name
        
        # Copy to user fonts directory if not already there
        if not target_path.exists() or target_path.stat().st_size != font_path.stat().st_size:
            shutil.copy2(font_path, target_path)

        # Register in HKCU\Software\Microsoft\Windows NT\CurrentVersion\Fonts
        key_path = r"Software\Microsoft\Windows NT\CurrentVersion\Fonts"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, reg_name, 0, winreg.REG_SZ, str(target_path))
        return True
    except Exception as e:
        print(f"Warning: Could not register font {font_path.name}: {e}")
        return False

def broadcast_font_change():
    """Broadcasts WM_FONTCHANGE to inform all top-level windows of new fonts."""
    HWND_BROADCAST = 0xFFFF
    WM_FONTCHANGE = 0x001D
    SMTO_ABORTIFHUNG = 0x0002
    result = ctypes.c_ulong()
    try:
        ctypes.windll.user32.SendMessageTimeoutW(
            HWND_BROADCAST, WM_FONTCHANGE, 0, 0, SMTO_ABORTIFHUNG, 1000, ctypes.byref(result)
        )
    except Exception as e:
        print(f"Warning broadcasting WM_FONTCHANGE: {e}")

def main():
    print("=== Noto Sans & Noto Sans Sinhala Font Setup ===")
    
    # 1. Download fonts to assets/fonts/
    for font_info in FONTS:
        dest = ASSETS_FONTS_DIR / font_info["filename"]
        if not dest.exists():
            download_file(font_info["url"], dest)
        else:
            print(f"Cached in assets: {dest.name}")

    # OFL license
    ofl_dest = ASSETS_FONTS_DIR / "OFL.txt"
    if not ofl_dest.exists():
        try:
            download_file(OFL_URL, ofl_dest)
        except Exception as e:
            print(f"Note: Could not download OFL.txt: {e}")

    # 2. Mirror to static/fonts/
    for font_info in FONTS:
        src = ASSETS_FONTS_DIR / font_info["filename"]
        static_dest = STATIC_FONTS_DIR / font_info["filename"]
        if src.exists() and (not static_dest.exists() or static_dest.stat().st_size != src.stat().st_size):
            shutil.copy2(src, static_dest)

    # 3. Install per-user in Windows
    installed_count = 0
    for font_info in FONTS:
        src = ASSETS_FONTS_DIR / font_info["filename"]
        if src.exists():
            if install_font_in_windows(src, font_info["reg_name"]):
                installed_count += 1

    if installed_count > 0:
        broadcast_font_change()
        print(f"Successfully registered {installed_count} fonts for current user in Windows.")
    print("Font setup complete.")

if __name__ == "__main__":
    main()
