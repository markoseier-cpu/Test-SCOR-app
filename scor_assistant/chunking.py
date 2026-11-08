"""Teksti jagamine lõikudeks.

Põhimõtted:
- Lõik ei ületa kunagi lehekülje piiri → iga lõik kuulub täpselt ühele PDF-i leheküljele ja
  allikaviide jääb täpseks.
- Siht ~500–800 tokenit (vaikimisi 650), kattuvus 10–20% (vaikimisi 15%).
- Tokenite arvu hinnatakse heuristiliselt (kohalikku tokenisaatorit ei eeldata). Hinnang on
  ligikaudne: sõnad + kirjavahemärgid, pikkade sõnade puhul lisatokenid.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

CHUNKING_VERSION = "chunk-v1"

_TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)


def estimate_tokens(text: str) -> int:
    """Ligikaudne tokenite arv BPE-tüüpi tokenisaatori jaoks.

    Iga sõna = 1 token + 1 lisatoken iga täiendava 6 märgi kohta; iga kirjavahemärk = 1 token.
    Eestikeelsed pikad liitsõnad tükeldatakse BPE-s tavaliselt mitmeks tokeniks, mistõttu
    pikkade sõnade lisatoken on vajalik. See on hinnang, mitte täpne arv.
    """
    n = 0
    for tok in _TOKEN_RE.findall(text):
        n += 1 + (max(0, len(tok) - 6) // 6)
    return n


@dataclass
class Chunk:
    chunk_index: int
    page_no: int
    text: str
    section: str | None
    token_estimate: int


def _split_units(text: str, max_tokens: int) -> list[str]:
    """Jagab lehekülje teksti üksusteks (lõigud → read → laused), millest ükski ei ületa piiri."""
    units: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        if estimate_tokens(para) <= max_tokens:
            units.append(para)
            continue
        for line in para.split("\n"):
            line = line.strip()
            if not line:
                continue
            if estimate_tokens(line) <= max_tokens:
                units.append(line)
                continue
            # väga pikk rida: lausete kaupa, viimase abinõuna sõnade kaupa
            sentences = re.split(r"(?<=[.!?;])\s+", line)
            for s in sentences:
                if estimate_tokens(s) <= max_tokens:
                    units.append(s)
                else:
                    words = s.split(" ")
                    buf: list[str] = []
                    for w in words:
                        buf.append(w)
                        if estimate_tokens(" ".join(buf)) >= max_tokens:
                            units.append(" ".join(buf))
                            buf = []
                    if buf:
                        units.append(" ".join(buf))
    return units


def chunk_page(text: str, chunk_tokens: int, overlap_ratio: float) -> list[str]:
    """Jagab ühe lehekülje teksti kattuvate lõikudena."""
    text = text.strip()
    if not text:
        return []
    if estimate_tokens(text) <= chunk_tokens:
        return [text]

    overlap_tokens = int(chunk_tokens * overlap_ratio)
    units = _split_units(text, chunk_tokens)
    unit_tokens = [estimate_tokens(u) for u in units]
    chunks: list[str] = []
    start = 0
    while start < len(units):
        end = start
        total = 0
        while end < len(units) and (total + unit_tokens[end] <= chunk_tokens or end == start):
            total += unit_tokens[end]
            end += 1
        chunks.append("\n".join(units[start:end]))
        if end >= len(units):
            break
        # kattuvus: alusta järgmist lõiku nii mitme eelmise üksusega, mis mahuvad overlap_tokens sisse
        back = end
        ov = 0
        while back - 1 > start and ov + unit_tokens[back - 1] <= overlap_tokens:
            back -= 1
            ov += unit_tokens[back]
        start = back if back > start else end
    return chunks


def build_chunks(pages, chunk_tokens: int, overlap_ratio: float) -> list[Chunk]:
    """Loob lõigud kõikidest lehekülgedest. `pages` on PageText-laadsed objektid
    (page_no, text, headings).

    Jaotise pealkiri: viimane enne lõiku (samal või varasemal leheküljel) usaldusväärselt
    tuvastatud pealkiri (PDF-i sisukord/järjehoidjad või selgelt suurem font). Kui lõigu enda
    tekstis on pealkiri, kasutatakse seda. Kui pealkirja pole leitud, jääb väärtus tühjaks.
    """
    out: list[Chunk] = []
    current_section: str | None = None
    idx = 0
    for page in pages:
        headings = [h for h in (getattr(page, "headings", []) or []) if h]
        page_texts = chunk_page(page.text, chunk_tokens, overlap_ratio)
        if headings and not any(h in page.text for h in headings):
            # Sisukorra pealkiri, mille täpset asukohta tekstis ei leitud: eeldame lehe algust.
            current_section = headings[0]
        for ctext in page_texts:
            section = current_section
            for h in headings:
                if h in ctext:
                    section = h
            out.append(
                Chunk(
                    chunk_index=idx,
                    page_no=page.page_no,
                    text=ctext,
                    section=section,
                    token_estimate=estimate_tokens(ctext),
                )
            )
            idx += 1
            # uuenda jooksvat pealkirja selle lõigu viimase leitud pealkirjaga
            for h in headings:
                if h in ctext:
                    current_section = h
        if headings:
            current_section = headings[-1]
    return out
