"""Hübriidotsing: semantiline (NumPy koosinussarnasus) + märksõnaotsing (BM25 koodide toega).

Tulemused ühendatakse Reciprocal Rank Fusion meetodiga (Cormack, Clarke, Büttcher, 2009,
"Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods", SIGIR '09),
k = 60. Skoorid on ainult järjestamiseks – need EI OLE vastuse õigsuse tõenäosus.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

import numpy as np

from .storage import ChunkRecord

RRF_K = 60

# Sõna-token: tähed/numbrid, mis võivad sisaldada punkte, sidekriipse või kaldkriipse koodide sees
# (nt "sP1.1", "RL.1.1", "BP.012", "O2C", "make-to-order").
_WORD_RE = re.compile(r"[0-9A-Za-zÀ-ÖØ-öø-ÿŠšŽžÕõ]+(?:[.\-/][0-9A-Za-zÀ-ÖØ-öø-ÿŠšŽžÕõ]+)*")
# Protsessikoodi / mõõdiku koodi kuju: 1–4 tähte, valikuline punkt, number, valikulised .numbrid
_CODE_RE = re.compile(r"(?<![\w.])([A-Za-z]{1,4}\.?\d+(?:\.\d+)*)(?![\w])")
# Lühend: vähemalt 2 suurtähte (võib sisaldada numbreid), nt SCOR, OFCT, ASCM, C2C
_ACRONYM_RE = re.compile(r"(?<![\w.])([A-Z][A-Z0-9]{1,9})(?![\w]|\.\d)")

STOPWORDS = {
    # inglise
    "the", "a", "an", "of", "and", "or", "in", "on", "for", "to", "is", "are", "what", "which", "how",
    "does", "do", "this", "that", "with", "by", "be", "as", "it", "its", "from", "at", "find", "describe",
    "described", "document",
    # eesti
    "ja", "ning", "või", "on", "ei", "kas", "mis", "mida", "milline", "millised", "milliseid", "kuidas",
    "see", "selle", "selles", "seda", "need", "neid", "kus", "kui", "dokument", "dokumendis", "dokumendi",
    "leia", "kirjeldatakse", "kirjeldatud", "käsitleb", "protsessi", "mõiste",
}


def tokenize(text: str) -> list[str]:
    """Väiketähtedega tokenid. Liittokeni (nt "sp1.1") korral lisatakse ka selle osad."""
    out: list[str] = []
    for m in _WORD_RE.finditer(text):
        tok = m.group(0).lower()
        out.append(tok)
        if any(ch in tok for ch in ".-/"):
            out.extend(p for p in re.split(r"[.\-/]", tok) if p)
    return out


def extract_codes(text: str) -> list[str]:
    """Küsimuses olevad protsessikoodid ja lühendid täpseks (tõstutundlikuks) vasteks."""
    codes = [m.group(1) for m in _CODE_RE.finditer(text)]
    codes += [m.group(1) for m in _ACRONYM_RE.finditer(text) if m.group(1) not in codes]
    return list(dict.fromkeys(codes))


def code_pattern(code: str) -> re.Pattern:
    """Täpne vaste: "XQ1.2" ei sobitu "XQ1.21" ega "AXQ1.2"-ga."""
    return re.compile(r"(?<![\w.])" + re.escape(code) + r"(?![\w]|\.\d)")


@dataclass
class SearchHit:
    chunk: ChunkRecord
    rank: int                      # lõplik järjekoht (1 = parim)
    fused_score: float             # RRF skoor – ainult järjestamiseks
    semantic_rank: int | None
    keyword_rank: int | None
    exact_codes: list[str]         # küsimuse koodid, mis lõigus täpselt esinevad
    exact_score: float = 0.0       # täpse koodivaste tugevus (esinemised + pealkirjavaste)


class BM25:
    """Okapi BM25 (Robertson & Zaragoza, 2009, "The Probabilistic Relevance Framework: BM25 and
    Beyond"), k1 = 1.5, b = 0.75."""

    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tf = [Counter(d) for d in docs]
        self.len = np.array([len(d) for d in docs], dtype=np.float32)
        self.avgdl = float(self.len.mean()) if len(docs) else 0.0
        self.postings: dict[str, list[tuple[int, int]]] = {}
        for i, c in enumerate(self.tf):
            for t, f in c.items():
                self.postings.setdefault(t, []).append((i, f))
        df = {t: len(p) for t, p in self.postings.items()}
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def scores(self, query: list[str]) -> np.ndarray:
        s = np.zeros(len(self.tf), dtype=np.float32)
        if not self.tf or self.avgdl == 0:
            return s
        for t in set(query):
            idf = self.idf.get(t)
            if idf is None:
                continue
            for i, f in self.postings[t]:
                denom = f + self.k1 * (1 - self.b + self.b * self.len[i] / self.avgdl)
                s[i] += idf * f * (self.k1 + 1) / denom
        return s


class HybridSearcher:
    def __init__(self, chunks: list[ChunkRecord], vectors: np.ndarray | None):
        self.chunks = chunks
        self.vectors = vectors
        self.bm25 = BM25([tokenize(c.text) for c in chunks])

    def keyword_ranking(self, query: str, limit: int
                        ) -> tuple[list[int], dict[int, list[str]], dict[int, float]]:
        q_tokens = [t for t in tokenize(query) if t not in STOPWORDS]
        scores = self.bm25.scores(q_tokens)
        codes = extract_codes(query)
        exact: dict[int, list[str]] = {}
        exact_score: dict[int, float] = {}
        if codes:
            pats = [(c, code_pattern(c)) for c in codes]
            top = float(scores.max()) if len(scores) else 0.0
            for i, ch in enumerate(self.chunks):
                found, strength = [], 0.0
                for c, p in pats:
                    n = len(p.findall(ch.text))
                    if n:
                        found.append(c)
                        # esinemiste arv (max 3) + lisakaal, kui kood on jaotise pealkirjas
                        strength += min(n, 3) + (2.0 if ch.section and p.search(ch.section) else 0.0)
                if found:
                    exact[i] = found
                    exact_score[i] = strength
                    # Täpse koodi vaste tõstetakse märksõnaedetabeli tippu
                    scores[i] += (top + 1.0) * strength
        order = [int(i) for i in np.argsort(-scores, kind="stable") if scores[i] > 0]
        return order[:limit], exact, exact_score

    def semantic_ranking(self, query_vec: np.ndarray | None, limit: int) -> list[int]:
        if query_vec is None or self.vectors is None or len(self.chunks) == 0:
            return []
        q = np.asarray(query_vec, dtype=np.float32).reshape(-1)
        n = np.linalg.norm(q)
        if n == 0:
            return []
        sims = self.vectors @ (q / n)
        return [int(i) for i in np.argsort(-sims, kind="stable")[:limit]]

    def search(self, query: str, query_vec: np.ndarray | None, top_k: int = 8,
               candidate_k: int = 30, extra_keyword_query: str | None = None) -> list[SearchHit]:
        sem = self.semantic_ranking(query_vec, candidate_k)
        kw_query = query if not extra_keyword_query else f"{query} {extra_keyword_query}"
        kw, exact, strength = self.keyword_ranking(kw_query, candidate_k)
        sem_rank = {idx: r + 1 for r, idx in enumerate(sem)}
        kw_rank = {idx: r + 1 for r, idx in enumerate(kw)}
        fused: dict[int, float] = {}
        for ranks in (sem_rank, kw_rank):
            for idx, r in ranks.items():
                fused[idx] = fused.get(idx, 0.0) + 1.0 / (RRF_K + r)
        # Täpse koodivastega lõigud eelistatakse (koodiküsimustes on täpne vaste olulisim tõend).
        ordered = sorted(fused, key=lambda i: (-strength.get(i, 0.0), -fused[i]))
        hits: list[SearchHit] = []
        seen_text: set[str] = set()
        for idx in ordered:
            ch = self.chunks[idx]
            key = " ".join(ch.text.split())
            if key in seen_text:  # korduvate lõikude eemaldamine
                continue
            seen_text.add(key)
            hits.append(SearchHit(ch, len(hits) + 1, fused[idx], sem_rank.get(idx), kw_rank.get(idx),
                                  exact.get(idx, []), strength.get(idx, 0.0)))
            if len(hits) >= top_k:
                break
        return hits
