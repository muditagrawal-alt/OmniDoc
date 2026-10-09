"""
Optical character recognition for pages without a text layer (scans, photos, faxes).

Runs the Tesseract command line on a 200 dpi render of the page and keeps, for every
recognised word, its confidence and position. Low-confidence words (the noise Tesseract
produces on photographs) are dropped, and word boxes are mapped back to PDF points so a
citation can later be highlighted on the page. The script of each page is detected first
with Tesseract's OSD, so Hindi, Marathi, Tamil, Bengali and other Indian-language scans
are read with the right language pack; a non-Latin guess is cross-checked against English
and the more confident reading wins. Sideways and upside-down scans are rotated upright.
Everything runs locally.
"""
import os
import re
import shutil
import logging
import subprocess
import tempfile
import threading
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("OmniDoc.OCR")

OCR_DPI = int(os.getenv("OMNIDOC_OCR_DPI", "200"))
# Pages with fewer extractable characters than this are treated as images and OCR'd.
MIN_TEXT_CHARS = int(os.getenv("OMNIDOC_OCR_MIN_CHARS", "25"))
MAX_OCR_PAGES = int(os.getenv("OMNIDOC_OCR_MAX_PAGES", "300"))
# Fixed language packs (e.g. "eng+hin"); empty means detect the script on every page.
FIXED_LANGS = os.getenv("OMNIDOC_OCR_LANGS", "").strip()
MIN_WORD_CONF = float(os.getenv("OMNIDOC_OCR_MIN_CONF", "55"))
TESSERACT_TIMEOUT_S = 120

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}

# Tesseract OSD script names -> language packs. English stays in for mixed pages.
SCRIPT_LANGS = {
    "Latin": ["eng"],
    "Devanagari": ["hin", "mar", "eng"],
    "Bengali": ["ben", "asm", "eng"],
    "Tamil": ["tam", "eng"],
    "Telugu": ["tel", "eng"],
    "Kannada": ["kan", "eng"],
    "Gujarati": ["guj", "eng"],
    "Gurmukhi": ["pan", "eng"],
    "Malayalam": ["mal", "eng"],
    "Oriya": ["ori", "eng"],
    "Arabic": ["urd", "ara", "eng"],
    "Han": ["chi_sim", "chi_tra", "eng"],
    "Japanese": ["jpn", "eng"],
    "Hangul": ["kor", "eng"],
    "Cyrillic": ["rus", "ukr", "eng"],
    "Greek": ["ell", "eng"],
    "Hebrew": ["heb", "eng"],
    "Thai": ["tha", "eng"],
}

_LANGS: Optional[Set[str]] = None
_LANGS_LOCK = threading.Lock()


def tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def _list_languages() -> Set[str]:
    try:
        out = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True, timeout=15)
    except Exception as e:
        logger.warning(f"Could not list Tesseract languages: {e}")
        return set()
    lines = (out.stdout + out.stderr).splitlines()
    return {ln.strip() for ln in lines if ln.strip() and " " not in ln.strip() and not ln.strip().endswith(":")}


def installed_languages() -> Set[str]:
    """Tesseract language packs on this machine (cached)."""
    global _LANGS
    if _LANGS is None:
        with _LANGS_LOCK:
            if _LANGS is None:
                _LANGS = _list_languages() if tesseract_available() else set()
    return _LANGS


def languages_for_script(script: Optional[str]) -> str:
    """Tesseract language string for a detected script, limited to installed packs."""
    installed = installed_languages()
    wanted = SCRIPT_LANGS.get(script or "", ["eng"])
    langs = [lang for lang in wanted if lang in installed] or (["eng"] if "eng" in installed else [])
    return "+".join(langs) or "eng"


def _run(args: List[str]) -> str:
    out = subprocess.run(args, capture_output=True, text=True, timeout=TESSERACT_TIMEOUT_S)
    return out.stdout + ("\n" + out.stderr if out.returncode else "")


def detect_orientation(png_path: str) -> Tuple[Optional[str], float, int]:
    """(script, script confidence, degrees to rotate clockwise) from Tesseract OSD."""
    if "osd" not in installed_languages():
        return None, 0.0, 0
    try:
        text = _run(["tesseract", png_path, "-", "--psm", "0"])
    except Exception as e:
        logger.info(f"Script detection skipped: {e}")
        return None, 0.0, 0
    script = re.search(r"Script:\s*(\w+)", text)
    conf = re.search(r"Script confidence:\s*([\d.]+)", text)
    rotate = re.search(r"Rotate:\s*(\d+)", text)
    orient_conf = re.search(r"Orientation confidence:\s*([\d.]+)", text)
    degrees = int(rotate.group(1)) % 360 if rotate and orient_conf and float(orient_conf.group(1)) >= 2.0 else 0
    return (script.group(1) if script else None), (float(conf.group(1)) if conf else 0.0), degrees


def run_tsv(png_path: str, language: str) -> List[Dict[str, Any]]:
    """Recognised words with confidence and pixel box, grouped ids kept for line building."""
    try:
        tsv = _run(["tesseract", png_path, "-", "-l", language, "--psm", "3", "tsv"])
    except Exception as e:
        logger.warning(f"Tesseract failed ({language}): {e}")
        return []
    words = []
    for line in tsv.splitlines()[1:]:
        cols = line.split("\t")
        if len(cols) < 12 or not cols[11].strip():
            continue
        try:
            conf = float(cols[10])
            words.append({
                "block": int(cols[2]), "par": int(cols[3]), "line": int(cols[4]),
                "conf": conf, "text": cols[11].strip(),
                "x": int(cols[6]), "y": int(cols[7]), "w": int(cols[8]), "h": int(cols[9]),
            })
        except ValueError:
            continue
    return words


def _mean_conf(words: List[Dict[str, Any]]) -> float:
    confs = [w["conf"] for w in words if w["conf"] >= 0]
    return sum(confs) / len(confs) if confs else 0.0


def page_needs_ocr(page: Any, text_chars: int) -> bool:
    """A page with almost no text but some ink (an image or drawings) is a scan."""
    if text_chars >= MIN_TEXT_CHARS:
        return False
    try:
        if page.get_images(full=False):
            return True
        return len(page.get_drawings()) > 20
    except Exception:
        return False


def _unrotate(x: float, y: float, degrees: int, width: float, height: float) -> Tuple[float, float]:
    """
    Maps a point of the upright image back to the original render. The upright image was
    made by rotating the original ``degrees`` clockwise; (width, height) is the original size.
    """
    if degrees == 90:
        return y, height - x
    if degrees == 180:
        return width - x, height - y
    if degrees == 270:
        return width - y, x
    return x, y


_ASCENDERS = set("bdfhiklt0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ!?/\\()[]{}'\"%#&@$€£₹")
_DESCENDERS = set("gjpqy")


def _font_size(text: str, height: float) -> float:
    """
    Font size (points) from a word's box height. The box spans the x-height ("same"),
    the cap height ("Total", "2026") or ascender to descender ("Payment") depending on the
    letters, so the raw height would make lines with descenders look like headings.
    """
    if not re.search(r"[A-Za-z0-9]", text):
        return height / 0.9  # other scripts (Devanagari, ...): the box spans the full line
    tall = any(ch in _ASCENDERS for ch in text)
    deep = any(ch in _DESCENDERS for ch in text)
    return height / (0.95 if tall and deep else 0.72 if tall or deep else 0.5)


def ocr_page(page: Any) -> Optional[Dict[str, Any]]:
    """
    OCRs one PyMuPDF page. Returns {"language", "blocks", "words", "mean_conf", "rotation"}
    where "blocks" mimics page.get_text("dict")["blocks"] (PDF coordinates) and "words" are
    [x0, y0, x1, y1, text] boxes; None if OCR is unavailable or found nothing readable.
    """
    if not tesseract_available():
        return None
    from PIL import Image

    pix = page.get_pixmap(dpi=OCR_DPI)
    width, height = pix.width, pix.height
    scale_x = page.rect.width / float(width)
    scale_y = page.rect.height / float(height)
    tmp = tempfile.mkdtemp(prefix="omnidoc-ocr-")
    try:
        png = os.path.join(tmp, "page.png")
        pix.save(png)
        script, script_conf, degrees = detect_orientation(png)
        if degrees:
            with Image.open(png) as im:
                im.rotate(-degrees, expand=True).save(png)  # PIL rotates counter-clockwise

        language = FIXED_LANGS or languages_for_script(script if script_conf >= 1.0 else None)
        words = run_tsv(png, language)
        if not FIXED_LANGS and language != "eng" and _mean_conf(words) < 75:
            english = run_tsv(png, "eng")
            if _mean_conf(english) > _mean_conf(words) + 5:
                words, language = english, "eng"
        mean = _mean_conf(words)
        words = [w for w in words if w["conf"] >= MIN_WORD_CONF and re.search(r"\w", w["text"])]
        if not words:
            return None

        def to_pdf_box(w: Dict[str, Any]) -> Tuple[float, float, float, float]:
            corners = [_unrotate(x, y, degrees, width, height)
                       for x, y in ((w["x"], w["y"]), (w["x"] + w["w"], w["y"] + w["h"]))]
            xs = [c[0] for c in corners]
            ys = [c[1] for c in corners]
            return (round(min(xs) * scale_x, 1), round(min(ys) * scale_y, 1),
                    round(max(xs) * scale_x, 1), round(max(ys) * scale_y, 1))

        paragraphs: "OrderedDict[Tuple[int, int], OrderedDict[int, List[Dict[str, Any]]]]" = OrderedDict()
        for w in words:
            w["box"] = to_pdf_box(w)
            paragraphs.setdefault((w["block"], w["par"]), OrderedDict()).setdefault(w["line"], []).append(w)

        blocks = []
        for lines in paragraphs.values():
            out_lines = []
            for line_words in lines.values():
                boxes = [w["box"] for w in line_words]
                bbox = (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
                axis = (1, 3) if degrees not in (90, 270) else (0, 2)  # glyph height runs along y unless the page was turned
                sizes = sorted(_font_size(w["text"], w["box"][axis[1]] - w["box"][axis[0]]) for w in line_words)
                size = max(4.0, sizes[len(sizes) // 2])
                text = " ".join(w["text"] for w in line_words)
                out_lines.append({"bbox": bbox, "spans": [{"text": text, "size": round(size, 1), "flags": 0, "font": "OCR"}]})
            blocks.append({"type": 0, "lines": out_lines})
        return {
            "language": language,
            "blocks": blocks,
            "words": [[*w["box"], w["text"]] for w in words],
            "mean_conf": round(mean, 1),
            "rotation": degrees,
        }
    except Exception as e:
        logger.warning(f"OCR failed on page {getattr(page, 'number', '?')}: {e}")
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def open_as_pdf(path: str) -> Any:
    """
    Opens a PDF, or converts an image (PNG, JPEG, TIFF, ...) into an in-memory PDF, so
    parsing, page rendering and highlight coordinates all use the same page geometry.
    """
    import fitz
    ext = os.path.splitext(path)[1].lower()
    if ext in IMAGE_EXTENSIONS:
        try:
            with fitz.open(path) as img:
                pdf_bytes = img.convert_to_pdf()
        except Exception:
            # Formats MuPDF cannot read (e.g. some WebP files): re-encode as PNG first.
            import io
            from PIL import Image
            buf = io.BytesIO()
            with Image.open(path) as im:
                im.convert("RGB").save(buf, format="PNG")
            with fitz.open("png", buf.getvalue()) as img:
                pdf_bytes = img.convert_to_pdf()
        return fitz.open("pdf", pdf_bytes)
    return fitz.open(path)
