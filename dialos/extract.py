"""Document text extraction.

Pure-stdlib readers for text, DOCX, XLSX and PPTX; optional external tools for
the rest, detected at runtime:
  pdftotext / pdftoppm (poppler)  PDF text, and page images for OCR
  tesseract                       OCR for scanned PDF pages
  soffice (LibreOffice)           legacy .doc/.xls/.ppt, RTF and OpenDocument

extract() returns (text, notes). Notes say plainly what could not be read.
"""
import io
import re
import shutil
import subprocess
import tempfile
import threading
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

MAX_PART_BYTES = 200 * 1024 * 1024   # decompressed size cap per XML part
MAX_SHEETS = 60
MAX_SLIDES = 2000
PDF_MAX_PAGES = 2000
OCR_MAX_PAGES = 40
OCR_PAGE_TIMEOUT = 60
LO_TIMEOUT = 180
MIN_PAGE_CHARS = 10
MIN_ALNUM_RATIO = 0.3

TEXT_EXTS = {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".jsonl", ".xml", ".html", ".htm", ".yaml", ".yml",
             ".toml", ".ini", ".cfg", ".conf", ".log", ".py", ".js", ".ts", ".tsx", ".jsx", ".c", ".h", ".cpp", ".hpp",
             ".cs", ".java", ".go", ".rs", ".rb", ".php", ".sh", ".bash", ".ps1", ".psm1", ".bat", ".sql", ".css",
             ".scss", ".lua", ".r", ".swift", ".kt", ".tex", ".rst", ".eml", ".srt", ".vtt", ".diff", ".patch", ".env",
             ".gitignore", ".dockerfile", ".makefile", ".tf", ".bicep", ".gradle", ".properties"}
OOXML_EXTS = {".docx", ".xlsx", ".pptx"}
LEGACY_EXTS = {".doc", ".xls", ".ppt", ".rtf", ".odt", ".ods", ".odp"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}

_ocr_sem = threading.Semaphore(2)
_lo_sem = threading.Semaphore(1)


def capabilities() -> dict:
    return {"pdf": bool(shutil.which("pdftotext")),
            "ocr": bool(shutil.which("tesseract") and shutil.which("pdftoppm")),
            "legacy_office": bool(shutil.which("soffice") or shutil.which("libreoffice"))}


def kind_of(name: str) -> str:
    ext = Path(name).suffix.lower()
    base = Path(name).name.lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext == ".pdf":
        return "pdf"
    if ext in OOXML_EXTS:
        return "ooxml"
    if ext in LEGACY_EXTS:
        return "legacy"
    if ext in TEXT_EXTS or base in ("makefile", "dockerfile", "readme", "license"):
        return "text"
    return "unknown"


def _read_part(z: zipfile.ZipFile, name: str) -> bytes:
    info = z.getinfo(name)
    if info.file_size > MAX_PART_BYTES:
        raise ValueError(f"{name} is {info.file_size:,} bytes unpacked, over the safety cap")
    return z.read(name)


def _t(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


# ---------------------------------------------------------------- DOCX
def extract_docx(raw: bytes):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        root = ET.fromstring(_read_part(z, "word/document.xml"))

    def para(p):
        out = []
        for el in p.iter():
            n = _t(el.tag)
            if n == "t" and el.text:
                out.append(el.text)
            elif n in ("tab",):
                out.append("\t")
            elif n in ("br", "cr"):
                out.append("\n")
        return "".join(out)

    body = next((c for c in root if _t(c.tag) == "body"), root)
    lines = []
    for child in body:
        n = _t(child.tag)
        if n == "p":
            lines.append(para(child))
        elif n == "tbl":
            for row in child.iter():
                if _t(row.tag) == "tr":
                    cells = [" ".join(para(p) for p in c if _t(p.tag) == "p") for c in row if _t(c.tag) == "tc"]
                    lines.append(" | ".join(x.strip() for x in cells))
            lines.append("")
    return "\n".join(lines).strip() + "\n", ["headers, footers, comments and text boxes are not included"]


# ---------------------------------------------------------------- XLSX
def _col_index(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def extract_xlsx(raw: bytes):
    notes = []
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names = set(z.namelist())
        shared = []
        if "xl/sharedStrings.xml" in names:
            for si in ET.fromstring(_read_part(z, "xl/sharedStrings.xml")):
                shared.append("".join(t.text or "" for t in si.iter() if _t(t.tag) == "t"))
        wb = ET.fromstring(_read_part(z, "xl/workbook.xml"))
        rels = {}
        if "xl/_rels/workbook.xml.rels" in names:
            for r in ET.fromstring(_read_part(z, "xl/_rels/workbook.xml.rels")):
                rels[r.get("Id")] = r.get("Target")
        sheets = []
        for s in wb.iter():
            if _t(s.tag) == "sheet":
                rid = next((v for k, v in s.attrib.items() if k.endswith("}id")), None)
                target = rels.get(rid, "")
                target = target.lstrip("/")
                path = target if target.startswith("xl/") else "xl/" + target
                sheets.append((s.get("name", "Sheet"), path))
        if len(sheets) > MAX_SHEETS:
            notes.append(f"only the first {MAX_SHEETS} of {len(sheets)} sheets were read")
            sheets = sheets[:MAX_SHEETS]
        out = []
        for name, path in sheets:
            if path not in names:
                notes.append(f"sheet {name!r} could not be found in the file")
                continue
            out.append(f"## Sheet: {name}")
            for row in ET.fromstring(_read_part(z, path)).iter():
                if _t(row.tag) != "row":
                    continue
                cells = {}
                for c in row:
                    if _t(c.tag) != "c":
                        continue
                    t = c.get("t")
                    v = next((x.text for x in c if _t(x.tag) == "v"), None)
                    if t == "s" and v is not None:
                        try:
                            v = shared[int(v)]
                        except (ValueError, IndexError):
                            v = ""
                    elif t == "inlineStr":
                        v = "".join(x.text or "" for x in c.iter() if _t(x.tag) == "t")
                    elif t == "b":
                        v = "TRUE" if v == "1" else "FALSE"
                    if v not in (None, ""):
                        cells[_col_index(c.get("r", "A1"))] = str(v).replace("\t", " ").replace("\n", " ")
                if cells:
                    out.append("\t".join(cells.get(i, "") for i in range(max(cells) + 1)))
            out.append("")
    notes.append("dates appear as serial numbers and formulas as their last computed value")
    return "\n".join(out), notes


# ---------------------------------------------------------------- PPTX
def extract_pptx(raw: bytes):
    out = []
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        slides = sorted((n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                        key=lambda n: int(re.findall(r"\d+", n)[-1]))[:MAX_SLIDES]
        for i, n in enumerate(slides, 1):
            out.append(f"## Slide {i}")
            for p in ET.fromstring(_read_part(z, n)).iter():
                if _t(p.tag) == "p":
                    text = "".join(t.text or "" for t in p.iter() if _t(t.tag) == "t").strip()
                    if text:
                        out.append(text)
            note = f"ppt/notesSlides/notesSlide{re.findall(r'[0-9]+', n)[-1]}.xml"
            if note in z.namelist():
                nt = [" ".join(t.text or "" for t in p.iter() if _t(t.tag) == "t").strip()
                      for p in ET.fromstring(_read_part(z, note)).iter() if _t(p.tag) == "p"]
                nt = [x for x in nt if x and not x.isdigit()]
                if nt:
                    out.append("Notes: " + " ".join(nt))
            out.append("")
    return "\n".join(out), ["pictures and charts are not described"]


# ---------------------------------------------------------------- PDF
def _page_thin(text: str) -> bool:
    s = text.strip()
    if len(s) < MIN_PAGE_CHARS:
        return True
    return sum(c.isalnum() for c in s) / len(s) < MIN_ALNUM_RATIO


def _run(cmd, timeout, input_bytes=None):
    return subprocess.run(cmd, input=input_bytes, capture_output=True, timeout=timeout, check=False)


def extract_pdf(raw: bytes):
    if not shutil.which("pdftotext"):
        raise ValueError("PDF text extraction needs pdftotext (poppler-utils), which is not installed")
    notes = []
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "in.pdf"
        src.write_bytes(raw)
        full = _run(["pdftotext", "-layout", str(src), "-"], 300)
        if full.returncode != 0:
            raise ValueError("pdftotext could not read this PDF: " + full.stderr.decode("utf-8", "replace")[:200])
        pages = full.stdout.decode("utf-8", "replace").split("\f")
        if pages and not pages[-1].strip():
            pages.pop()
        if len(pages) > PDF_MAX_PAGES:
            notes.append(f"only the first {PDF_MAX_PAGES} of {len(pages)} pages were read")
            pages = pages[:PDF_MAX_PAGES]
        can_ocr = capabilities()["ocr"]
        thin = [i for i, p in enumerate(pages) if _page_thin(p)]
        ocr_done = 0
        if thin and can_ocr:
            for i in thin[:OCR_MAX_PAGES]:
                text = _ocr_page(src, i + 1, td)
                if text and not _page_thin(text):
                    pages[i] = text
                    ocr_done += 1
            if len(thin) > OCR_MAX_PAGES:
                notes.append(f"{len(thin) - OCR_MAX_PAGES} more scanned pages were not OCR'd (limit {OCR_MAX_PAGES})")
        elif thin:
            notes.append(f"{len(thin)} page(s) look scanned or image-only; install tesseract to read them")
        if ocr_done:
            notes.append(f"{ocr_done} scanned page(s) were read with OCR and may contain errors")
    return "\n".join(f"--- page {i} ---\n{p.strip()}\n" for i, p in enumerate(pages, 1)), notes


def _ocr_page(pdf: Path, page: int, td: str) -> str:
    prefix = str(Path(td) / f"p{page}")
    with _ocr_sem:
        try:
            r = _run(["pdftoppm", "-f", str(page), "-l", str(page), "-r", "200", "-png", str(pdf), prefix], OCR_PAGE_TIMEOUT)
            imgs = sorted(Path(td).glob(f"p{page}*.png"))
            if r.returncode != 0 or not imgs:
                return ""
            t = _run(["tesseract", str(imgs[0]), "stdout"], OCR_PAGE_TIMEOUT)
            return t.stdout.decode("utf-8", "replace") if t.returncode == 0 else ""
        except subprocess.TimeoutExpired:
            return ""
        finally:
            for f in Path(td).glob(f"p{page}*.png"):
                f.unlink(missing_ok=True)


# ---------------------------------------------------------------- legacy via LibreOffice
def extract_legacy(name: str, raw: bytes):
    exe = shutil.which("soffice") or shutil.which("libreoffice")
    if not exe:
        raise ValueError(f"{Path(name).suffix} files need LibreOffice, which is not installed on this server")
    ext = Path(name).suffix.lower()
    target = {".doc": "docx", ".rtf": "docx", ".odt": "docx", ".xls": "xlsx", ".ods": "xlsx", ".ppt": "pptx", ".odp": "pptx"}[ext]
    with _lo_sem, tempfile.TemporaryDirectory() as td:
        src = Path(td) / ("in" + ext)
        src.write_bytes(raw)
        profile = Path(td) / "profile"
        r = _run([exe, f"-env:UserInstallation=file://{profile}", "--headless", "--convert-to", target,
                  "--outdir", td, str(src)], LO_TIMEOUT)
        out = Path(td) / ("in." + target)
        if r.returncode != 0 or not out.exists():
            raise ValueError("LibreOffice could not convert this file")
        data = out.read_bytes()
    return {"docx": extract_docx, "xlsx": extract_xlsx, "pptx": extract_pptx}[target](data)


# ---------------------------------------------------------------- entry
def extract(name: str, raw: bytes):
    """(text, notes). Raises ValueError with a readable reason on failure."""
    kind, ext = kind_of(name), Path(name).suffix.lower()
    try:
        if kind == "text":
            if b"\x00" in raw[:8192]:
                raise ValueError("this looks like a binary file, not text")
            return raw.decode("utf-8", "replace"), []
        if kind == "ooxml":
            return {".docx": extract_docx, ".xlsx": extract_xlsx, ".pptx": extract_pptx}[ext](raw)
        if kind == "pdf":
            return extract_pdf(raw)
        if kind == "legacy":
            return extract_legacy(name, raw)
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as e:
        raise ValueError(f"the file is damaged or not a real {ext} document ({type(e).__name__})")
    except subprocess.TimeoutExpired:
        raise ValueError("reading this file took too long")
    raise ValueError(f"{('%s files' % ext) if ext else 'this kind of file'} cannot be read")
