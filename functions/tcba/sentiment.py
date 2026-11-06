"""Skor sentimen judul berita.

Utama  : Azure AI Language (Sentiment Analysis, tier F0 gratis 5.000 dokumen/bulan).
Cadangan: leksikon sederhana bahasa Indonesia (dipakai jika endpoint/kunci kosong,
          kuota habis, atau bahasa tidak didukung). Kolom `method` mencatat sumber skor.
"""
from __future__ import annotations

import re
import time

import requests

from . import config

POS = {"naik", "tumbuh", "laba", "untung", "positif", "meningkat", "melonjak", "rekor", "ekspansi",
       "menguat", "dividen", "cuan", "kinerja", "solid", "efisiensi", "akuisisi", "investasi",
       "pertumbuhan", "lonjak", "hijau", "optimis", "membaik", "tertinggi", "sukses", "inovasi"}
NEG = {"turun", "rugi", "anjlok", "merosot", "negatif", "melemah", "tekanan", "beban", "utang",
       "gangguan", "denda", "phk", "koreksi", "jatuh", "terkoreksi", "lesu", "terendah", "sengketa",
       "kasus", "gagal", "defisit", "merah", "pesimis", "lambat", "krisis", "pangkas", "boncos"}
_TOK = re.compile(r"[a-zA-Z]+")


def lexicon_score(text: str) -> dict:
    toks = [t.lower() for t in _TOK.findall(text or "")]
    p = sum(t in POS for t in toks)
    n = sum(t in NEG for t in toks)
    tot = p + n
    pos, neg = (p / tot, n / tot) if tot else (0.0, 0.0)
    neu = 1.0 - max(pos, neg) if tot else 1.0
    label = "positive" if p > n else "negative" if n > p else "neutral"
    return {"sentiment": label, "pos": pos, "neu": neu, "neg": neg, "score": pos - neg, "method": "lexicon"}


def _azure_batch(texts: list[str]) -> list[dict]:
    url = config.LANGUAGE_ENDPOINT.rstrip("/") + "/language/:analyze-text?api-version=2023-04-01"
    body = {"kind": "SentimentAnalysis", "parameters": {"modelVersion": "latest"},
            "analysisInput": {"documents": [{"id": str(i), "language": "id", "text": t[:5000]}
                                            for i, t in enumerate(texts)]}}
    for attempt in range(4):
        r = requests.post(url, json=body, timeout=30,
                          headers={"Ocp-Apim-Subscription-Key": config.LANGUAGE_KEY})
        if r.status_code == 429:                     # kena rate limit F0 -> tunggu lalu ulangi
            time.sleep(15 * (attempt + 1))
            continue
        r.raise_for_status()
        res = r.json()["results"]
        out: list[dict | None] = [None] * len(texts)
        for d in res.get("documents", []):
            c = d["confidenceScores"]
            out[int(d["id"])] = {"sentiment": d["sentiment"], "pos": c["positive"], "neu": c["neutral"],
                                 "neg": c["negative"], "score": c["positive"] - c["negative"],
                                 "method": "azure_language"}
        for e in res.get("errors", []):               # mis. bahasa tidak didukung -> leksikon
            out[int(e["id"])] = lexicon_score(texts[int(e["id"])]) | {"method": "lexicon_fallback"}
        return [o if o is not None else lexicon_score(t) for o, t in zip(out, texts)]
    raise RuntimeError("Azure AI Language: terlalu banyak 429 (kuota/rate limit)")


def score_texts(texts: list[str]) -> list[dict]:
    if not texts:
        return []
    if not (config.LANGUAGE_ENDPOINT and config.LANGUAGE_KEY):
        return [lexicon_score(t) for t in texts]
    out: list[dict] = []
    for i in range(0, len(texts), 10):              # maks 10 dokumen per permintaan
        chunk = texts[i:i + 10]
        try:
            out.extend(_azure_batch(chunk))
        except Exception:
            out.extend(lexicon_score(t) | {"method": "lexicon_fallback"} for t in chunk)
        time.sleep(config.SENTIMENT_SLEEP_SECONDS)   # jaga di bawah batas permintaan/menit F0
    return out
