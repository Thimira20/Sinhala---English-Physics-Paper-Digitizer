"""
Fetch and vendor frontend libraries locally into static/vendor/.
No CDN requests at runtime.
"""
from pathlib import Path
import urllib.request
import json
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VENDOR_DIR = PROJECT_ROOT / "static" / "vendor"
VENDOR_DIR.mkdir(parents=True, exist_ok=True)
FONTS_DIR = VENDOR_DIR / "fonts"
FONTS_DIR.mkdir(parents=True, exist_ok=True)

PACKAGES = {
    "easymde": "2.18.0",
    "marked": "14.1.2",
    "marked-katex-extension": "5.1.2",
    "katex": "0.16.11",
    "dompurify": "3.1.6",
    "@fontsource/inter": "5.3.0"
}

FILES = [
    ("easymde", f"https://cdn.jsdelivr.net/npm/easymde@{PACKAGES['easymde']}/dist/easymde.min.js", VENDOR_DIR / "easymde.min.js"),
    ("easymde", f"https://cdn.jsdelivr.net/npm/easymde@{PACKAGES['easymde']}/dist/easymde.min.css", VENDOR_DIR / "easymde.min.css"),
    ("marked", f"https://cdn.jsdelivr.net/npm/marked@{PACKAGES['marked']}/marked.min.js", VENDOR_DIR / "marked.min.js"),
    ("marked-katex-extension", f"https://cdn.jsdelivr.net/npm/marked-katex-extension@{PACKAGES['marked-katex-extension']}/lib/index.umd.js", VENDOR_DIR / "marked-katex-extension.umd.js"),
    ("katex", f"https://cdn.jsdelivr.net/npm/katex@{PACKAGES['katex']}/dist/katex.min.js", VENDOR_DIR / "katex.min.js"),
    ("katex", f"https://cdn.jsdelivr.net/npm/katex@{PACKAGES['katex']}/dist/katex.min.css", VENDOR_DIR / "katex.min.css"),
    ("dompurify", f"https://cdn.jsdelivr.net/npm/dompurify@{PACKAGES['dompurify']}/dist/purify.min.js", VENDOR_DIR / "purify.min.js"),
]

def download_file(url: str, dest: Path) -> None:
    print(f"Downloading {url} -> {dest.name}")
    req = urllib.request.Request(url, headers={"User-Agent": "PhysicsDigitizerVendorFetcher/1.0"})
    with urllib.request.urlopen(req) as resp, open(dest, "wb") as f:
        f.write(resp.read())

def fetch_katex_fonts():
    api_url = f"https://data.jsdelivr.com/v1/packages/npm/katex@{PACKAGES['katex']}?structure=flat"
    req = urllib.request.Request(api_url, headers={"User-Agent": "PhysicsDigitizerVendorFetcher/1.0"})
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
            woff2_files = [
                f["name"] for f in data["files"]
                if f["name"].startswith("/dist/fonts/") and f["name"].endswith(".woff2")
            ]
            print(f"Downloading {len(woff2_files)} KaTeX woff2 font files...")
            for font_path in woff2_files:
                font_name = Path(font_path).name
                dest = FONTS_DIR / font_name
                if not dest.exists():
                    font_url = f"https://cdn.jsdelivr.net/npm/katex@{PACKAGES['katex']}{font_path}"
                    download_file(font_url, dest)
    except Exception as e:
        print(f"Warning: could not fetch all KaTeX fonts: {e}")

def fetch_inter_fonts():
    static_fonts_dir = PROJECT_ROOT / "static" / "fonts"
    static_fonts_dir.mkdir(parents=True, exist_ok=True)
    inter_weights = ["400", "500", "600", "700"]
    for w in inter_weights:
        dest = static_fonts_dir / f"inter-latin-{w}-normal.woff2"
        if not dest.exists():
            url = f"https://cdn.jsdelivr.net/npm/@fontsource/inter@{PACKAGES['@fontsource/inter']}/files/inter-latin-{w}-normal.woff2"
            try:
                download_file(url, dest)
            except Exception as e:
                print(f"Warning: could not fetch Inter {w}: {e}")

def main():
    print("Fetching vendored frontend assets...")
    for pkg, url, dest in FILES:
        if not dest.exists():
            download_file(url, dest)
        else:
            print(f"Already exists: {dest.name}")
    fetch_katex_fonts()
    fetch_inter_fonts()

    versions_txt = VENDOR_DIR / "VERSIONS.txt"
    lines = [f"{pkg}=={ver}\n" for pkg, ver in sorted(PACKAGES.items())]
    versions_txt.write_text("".join(lines), encoding="utf-8")
    print(f"Vendor fetch complete. Recorded in {versions_txt}")

if __name__ == "__main__":
    main()
