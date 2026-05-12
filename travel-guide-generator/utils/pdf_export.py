"""Export HTML to PDF using Chrome headless."""
import subprocess
from pathlib import Path


def html_to_pdf(html_path: str, pdf_path: str) -> bool:
    """Convert HTML file to PDF using Chrome headless."""
    chrome_paths = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium-browser",
    ]

    chrome = None
    for path in chrome_paths:
        if Path(path).exists():
            chrome = path
            break

    if not chrome:
        raise FileNotFoundError(
            "Chrome not found. Please install Google Chrome or Chromium."
        )

    cmd = [
        chrome,
        "--headless",
        "--disable-gpu",
        "--no-sandbox",
        "--print-to-pdf-no-header",
        f"--print-to-pdf={pdf_path}",
        f"file://{html_path}",
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        raise RuntimeError("PDF generation timed out")
