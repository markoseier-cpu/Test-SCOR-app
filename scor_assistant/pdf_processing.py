"""PDF-i valideerimine, SHA-256 räsi ja teksti eraldamine lehekülgede kaupa (PyMuPDF).

Leheküljenumbrid on PDF-faili füüsilised leheküljed alates 1-st ("PDF lk X"),
mitte dokumendile trükitud numbrid.
"""

from __future__ import annotations

import hashlib
import re
import statistics
import unicodedata
from dataclasses import dataclass, field
from typing import Callable

import pymupdf as fitz  # PyMuPDF

EXTRACTION_VERSION = "pdf-extract-v1"

# Lehekülg loetakse tekstita leheks, kui sellel on alla selle arvu mittetühje märke.
MIN_CHARS_PER_PAGE = 20
# Kui tekstiga lehti on alla selle osakaalu, loetakse dokument skannituks.
MIN_TEXT_PAGE_RATIO = 0.10

OCR_MESSAGE = (
    "PDF-ist ei õnnestunud masinloetavat teksti eraldada. Tõenäoliselt on tegemist skannitud "
    "(pildina salvestatud) dokumendiga. Rakendus ei tee OCR-i. Loo PDF-ist tekstikihiga versioon "
    "(nt OCRmyPDF: `ocrmypdf --language eng sisend.pdf valjund.pdf` või Adobe Acrobat → "
    "„Recognize Text”) ja laadi see uuesti üles."
)


class PdfError(Exception):
    """Üldine PDF-i töötlemise viga (sõnum on kasutajale mõeldud)."""


class InvalidPdfError(PdfError):
    pass


class NoTextError(PdfError):
    pass


@dataclass
class PageText:
    page_no: int  # 1-põhine PDF-i leheküljenumber
    text: str
    has_table: bool = False
    headings: list[str] = field(default_factory=list)  # usaldusväärselt tuvastatud pealkirjad

    @property
    def char_count(self) -> int:
        return len(self.text.strip())


@dataclass
class ExtractionResult:
    pages: list[PageText]
    page_count: int
    empty_pages: list[int]
    table_pages: list[int]
    toc_available: bool
    warnings: list[str]

    @property
    def text_pages(self) -> int:
        return self.page_count - len(self.empty_pages)

    @property
    def total_chars(self) -> int:
        return sum(p.char_count for p in self.pages)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def validate_upload(filename: str, data: bytes, max_mb: int) -> None:
    """Kontrollib laiendit, suurust ja PDF-i päist enne töötlemist."""
    if not filename.lower().endswith(".pdf"):
        raise InvalidPdfError(f"Fail „{filename}” ei ole PDF (laiend peab olema .pdf).")
    size_mb = len(data) / (1024 * 1024)
    if len(data) == 0:
        raise InvalidPdfError("Fail on tühi (0 baiti).")
    if size_mb > max_mb:
        raise InvalidPdfError(
            f"Fail on {size_mb:.1f} MB, lubatud on kuni {max_mb} MB (seadistus SCOR_MAX_UPLOAD_MB)."
        )
    # PDF-i päis peab olema faili alguse lähedal (spetsifikatsioon lubab eelnevat prügi kuni 1024 baiti)
    if b"%PDF-" not in data[:1024]:
        raise InvalidPdfError(f"Fail „{filename}” ei ole kehtiv PDF (puudub %PDF- päis).")


_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_HYPHEN_BREAK_RE = re.compile(r"([a-zäöüõšž])-\n([a-zäöüõšž])")
_SPACES_RE = re.compile(r"[ \t ]+")
_MANY_NL_RE = re.compile(r"\n{3,}")


def clean_text(text: str) -> str:
    """Konservatiivne puhastus: ei muuda suurtähti, koode, lühendeid ega kirjavahemärke koodides.

    - Unicode NFC normaliseerimine (ligatuurid nagu "ﬁ" → "fi" NFKC-ga EI tehta, et mitte muuta
      sümboleid; ligatuurid asendatakse eraldi).
    - Juhtmärkide eemaldamine, tühikute kokkusurumine.
    - Reavahetusel poolitatud väiketäheliste sõnade liitmine ("ful-\\nfillment" → "fulfillment").
      Suurtähtede/numbritega koode (nt "sP1-") ei liideta.
    """
    text = unicodedata.normalize("NFC", text)
    text = text.replace("ﬁ", "fi").replace("ﬂ", "fl").replace("ﬀ", "ff")
    text = text.replace("­", "")  # pehme poolitusmärk
    text = _CTRL_RE.sub(" ", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _HYPHEN_BREAK_RE.sub(r"\1\2", text)
    lines = [_SPACES_RE.sub(" ", ln).strip() for ln in text.split("\n")]
    text = "\n".join(lines)
    text = _MANY_NL_RE.sub("\n\n", text)
    return text.strip()


def _rects_overlap(a, b, min_ratio: float = 0.5) -> bool:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix = max(0.0, min(ax1, bx1) - max(ax0, bx0))
    iy = max(0.0, min(ay1, by1) - max(ay0, by0))
    area = max(1e-6, (ax1 - ax0) * (ay1 - ay0))
    return (ix * iy) / area >= min_ratio


def _table_to_text(page, table) -> str:
    """Tabeli read kujul "lahter | lahter".

    Lahtri tekst loetakse otse lahtri ristkülikust (`page.get_textbox`), sest see säilitab
    märgid ja punktid koodides (nt "XQ1.2") usaldusväärsemalt kui tabeli üldine eraldus.
    Tühjad (liidetud lahtrite tõttu tekkinud) lahtrid jäetakse välja.
    """
    out = []
    for row in table.rows:
        cells = []
        for bbox in row.cells:
            if bbox is None:
                continue
            txt = clean_text(page.get_textbox(fitz.Rect(bbox))).replace("\n", " ")
            if txt:
                cells.append(txt)
        if cells:
            out.append(" | ".join(cells))
    return "\n".join(out)


def _page_text(page, extract_tables: bool) -> tuple[str, bool]:
    """Tagastab lehekülje teksti lugemisjärjekorras; tabelid ridadena "lahter | lahter"."""
    tables = []
    if extract_tables:
        try:
            tables = list(page.find_tables().tables)
        except Exception:  # tabelituvastus on heuristiline; vea korral kasuta tavateksti
            tables = []
    if not tables:
        return page.get_text("text", sort=True), False

    items: list[tuple[float, float, str]] = []
    table_rects = [tuple(t.bbox) for t in tables]
    for t in tables:
        ttxt = _table_to_text(page, t)
        if ttxt:
            items.append((t.bbox[1], t.bbox[0], "[Tabel]\n" + ttxt + "\n[/Tabel]"))
    for b in page.get_text("blocks", sort=True):
        x0, y0, x1, y1, btxt, _bno, btype = b[:7]
        if btype != 0:  # pildiplokk
            continue
        if any(_rects_overlap((x0, y0, x1, y1), r) for r in table_rects):
            continue
        items.append((y0, x0, btxt))
    items.sort(key=lambda it: (round(it[0], 1), it[1]))
    return "\n".join(it[2] for it in items), True


def _font_headings(page, body_size: float) -> list[str]:
    """Pealkirjad fondi suuruse järgi: lühike rida, märgatavalt suurem kui põhitekst."""
    heads: list[str] = []
    try:
        d = page.get_text("dict")
    except Exception:
        return heads
    for block in d.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = [s for s in line.get("spans", []) if s.get("text", "").strip()]
            if not spans:
                continue
            txt = clean_text("".join(s["text"] for s in spans))
            size = max(s.get("size", 0) for s in spans)
            if (
                body_size > 0
                and size >= body_size * 1.25
                and 3 <= len(txt) <= 120
                and re.search(r"[A-Za-zÄÖÜÕäöüõ]", txt)
            ):
                heads.append(txt)
    return heads


def _body_font_size(doc, sample_pages: int = 30) -> float:
    sizes: list[float] = []
    for i in range(min(sample_pages, doc.page_count)):
        try:
            d = doc[i].get_text("dict")
        except Exception:
            continue
        for block in d.get("blocks", []):
            for line in block.get("lines", []):
                for s in line.get("spans", []):
                    n = len(s.get("text", "").strip())
                    if n:
                        sizes.extend([round(s.get("size", 0), 1)] * min(n, 50))
    return statistics.median(sizes) if sizes else 0.0


def open_pdf(data: bytes):
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise InvalidPdfError(f"PDF-i ei saa avada: fail on vigane või ei ole PDF ({exc}).") from exc
    if doc.needs_pass:
        doc.close()
        raise InvalidPdfError("PDF on parooliga kaitstud. Eemalda parool ja laadi fail uuesti üles.")
    if doc.page_count == 0:
        doc.close()
        raise InvalidPdfError("PDF-is ei ole ühtegi lehekülge.")
    return doc


def extract_pages(
    data: bytes,
    extract_tables: bool = True,
    progress: Callable[[int, int], None] | None = None,
) -> ExtractionResult:
    """Eraldab teksti lehekülgede kaupa. Tõstab NoTextError, kui tekst puudub (OCR vajalik)."""
    doc = open_pdf(data)
    try:
        toc = doc.get_toc(simple=True)  # [[level, title, page], ...]
        toc_by_page: dict[int, list[str]] = {}
        for _lvl, title, pno in toc:
            if pno >= 1 and title.strip():
                toc_by_page.setdefault(pno, []).append(clean_text(title))
        body_size = 0.0 if toc_by_page else _body_font_size(doc)

        pages: list[PageText] = []
        n = doc.page_count
        for i in range(n):
            page = doc[i]
            raw, has_table = _page_text(page, extract_tables)
            text = clean_text(raw)
            if toc_by_page:
                heads = toc_by_page.get(i + 1, [])
            else:
                heads = _font_headings(page, body_size)
            pages.append(PageText(page_no=i + 1, text=text, has_table=has_table, headings=heads))
            if progress:
                progress(i + 1, n)
    finally:
        doc.close()

    empty = [p.page_no for p in pages if p.char_count < MIN_CHARS_PER_PAGE]
    tables = [p.page_no for p in pages if p.has_table]
    text_pages = n - len(empty)
    if text_pages == 0 or text_pages / n < MIN_TEXT_PAGE_RATIO:
        raise NoTextError(OCR_MESSAGE)

    warnings: list[str] = []
    if empty:
        shown = ", ".join(map(str, empty[:20])) + (" …" if len(empty) > 20 else "")
        warnings.append(
            f"{len(empty)} lehekülge ei sisalda masinloetavat teksti (PDF lk {shown}). "
            "Need võivad olla tühjad, pildid või skannid ega ole otsitavad."
        )
    if tables:
        warnings.append(
            f"Tabeleid tuvastati {len(tables)} leheküljel. Tabelite tekst on eraldatud ridadena "
            "„lahter | lahter”; keeruliste (liidetud lahtritega või mitmetasandiliste) tabelite "
            "eraldamist tasub allikavaates PDF-i leheküljega võrrelda."
        )
    return ExtractionResult(
        pages=pages,
        page_count=n,
        empty_pages=empty,
        table_pages=tables,
        toc_available=bool(toc_by_page),
        warnings=warnings,
    )


def render_page_png(pdf_path, page_no: int, dpi: int = 110, highlight: str | None = None) -> bytes:
    """Renderdab PDF-i lehekülje PNG-pildiks (lokaalne leheküljevaade). Soovi korral tõstab
    esile allikakatkendi alguse."""
    with fitz.open(pdf_path) as doc:
        if not 1 <= page_no <= doc.page_count:
            raise PdfError(f"PDF lk {page_no} ei ole olemas.")
        page = doc[page_no - 1]
        if highlight:
            for needle in _highlight_needles(highlight):
                rects = page.search_for(needle)
                if rects:
                    for r in rects[:3]:
                        annot = page.add_highlight_annot(r)
                        annot.update()
                    break
        pix = page.get_pixmap(dpi=dpi)
        return pix.tobytes("png")


def _highlight_needles(text: str) -> list[str]:
    lines = [ln.strip() for ln in text.split("\n") if len(ln.strip()) >= 12]
    needles = []
    for ln in lines[:3]:
        needles.append(ln[:60])
    return needles
