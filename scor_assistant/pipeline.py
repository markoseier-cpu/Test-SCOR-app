"""Küsimuse töövoog: (järelküsimuse täpsustamine) → uus dokumendiotsing → vastus.

Iga küsimuse jaoks tehakse alati uus otsing. Varasemaid vastuseid ei kasutata allikana.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .answering import AnswerResult, ChatModel, answer, rewrite_followup
from .indexing import Embedder
from .search import HybridSearcher
from .storage import Storage


@dataclass
class QueryConfig:
    llm_model: str
    embed_model: str
    top_k: int = 8
    candidate_k: int = 30
    num_ctx: int = 8192
    answer_tokens: int = 1024
    temperature: float = 0.1


def load_searcher(storage: Storage, doc_id: str) -> HybridSearcher:
    state = storage.get_index_state(doc_id)
    if state is None:
        raise ValueError("Dokument on indekseerimata.")
    return HybridSearcher(storage.get_chunks(doc_id), storage.load_vectors(state))


def ask(
    question: str,
    searcher: HybridSearcher,
    embedder: Embedder,
    llm: ChatModel,
    cfg: QueryConfig,
    history: list[dict] | None = None,
    on_stage: Callable[[str], None] | None = None,
    on_token: Callable[[str], None] | None = None,
) -> AnswerResult:
    """Tagastab alati AnswerResult'i. Vea korral on `error` täidetud ja `hits` sisaldab otsingutulemusi,
    kui otsing jõudis valmis."""
    stage = on_stage or (lambda _m: None)
    hits = []
    search_query = question
    try:
        if history:
            stage("Täpsustan järelküsimuse tähendust vestluse põhjal…")
            search_query = rewrite_followup(llm, cfg.llm_model, history, question, cfg.num_ctx)
        stage("Otsin dokumendist sobivaid lõike…")
        query_vec = None
        semantic_error = None
        try:
            query_vec = embedder.embed(cfg.embed_model, [search_query])[0]
        except Exception as exc:  # märksõnaotsing töötab ka ilma embedding-mudelita
            semantic_error = exc
        extra = question if search_query != question else None
        hits = searcher.search(search_query, query_vec, cfg.top_k, cfg.candidate_k, extra_keyword_query=extra)
        if semantic_error is not None:
            raise semantic_error
        stage("Koostan vastust kohaliku keelemudeliga…")
        return answer(question, hits, llm, cfg.llm_model, cfg.num_ctx, cfg.answer_tokens, cfg.temperature,
                      history, search_query, on_token)
    except Exception as exc:
        return AnswerResult(question, search_query, "", [], [], hits, not_found=False, warnings=[],
                            error=str(exc) or exc.__class__.__name__)
