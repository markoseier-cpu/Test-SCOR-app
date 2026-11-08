"""SCOR 11 dokumendiassistent – lokaalne RAG-rakendus.

Moodulid:
    config          – seadistused (.env / keskkonnamuutujad)
    pdf_processing  – PDF-i valideerimine, räsi ja tekst lehekülgede kaupa
    chunking        – lõikudeks jagamine ja tokenite hindamine
    storage         – SQLite ja NumPy vektorifailide salvestus
    ollama_client   – kohalik Ollama HTTP-klient
    indexing        – indekseerimine ja indeksi kehtivuse kontroll
    search          – hübriidotsing (semantiline + märksõna)
    answering       – süsteemijuhis, konteksti koostamine, viidete kontroll
"""

__version__ = "1.0.0"
