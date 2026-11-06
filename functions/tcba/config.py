"""Konfigurasi proyek TCBA Kelompok 7.

Semua nilai bisa diganti lewat environment variable (App Settings di Azure Function,
atau file config/project.env saat lokal), sehingga kode tidak perlu diubah.
"""
import os

# Emiten yang dianalisis. 'yahoo' = simbol Yahoo Finance, 'news_query' = kata kunci berita.
TICKERS = {
    "TLKM": {"name": "Telkom Indonesia", "yahoo": "TLKM.JK",
             "news_query": '"Telkom Indonesia" OR TLKM OR Telkomsel'},
    "ISAT": {"name": "Indosat Ooredoo Hutchison", "yahoo": "ISAT.JK",
             "news_query": 'Indosat OR ISAT OR "Indosat Ooredoo Hutchison"'},
    "EXCL": {"name": "XL Axiata / XLSmart", "yahoo": "EXCL.JK",
             "news_query": '"XL Axiata" OR XLSmart OR EXCL'},
}
MARKET_INDEX = {"JKSE": "^JKSE"}          # IHSG sebagai pembanding pasar

# Rasio target yang diprediksi arah perubahannya: ROE_TTM, ROA_TTM, atau NPM_TTM.
TARGET_RATIO = os.getenv("TARGET_RATIO", "roe_ttm")
# Ambang "stabil" dalam poin persentase (pp): |delta| <= ambang -> 'stabil'.
# "auto" = kuantil ke-33 dari |delta| historis -> tiga kelas kira-kira seimbang (wajib dijelaskan di laporan).
STABLE_THRESHOLD_PP = {
    "roe_ttm": os.getenv("STABLE_PP_ROE", "auto"),
    "roa_ttm": os.getenv("STABLE_PP_ROA", "auto"),
    "npm_ttm": os.getenv("STABLE_PP_NPM", "auto"),
}

# Batas pemakaian Azure AI Language (F0 = 5.000 dokumen/bulan gratis).
SENTIMENT_MAX_NEW_PER_RUN = int(os.getenv("SENTIMENT_MAX_NEW_PER_RUN", "150"))
SENTIMENT_MAX_PER_TICKER_QUARTER = int(os.getenv("SENTIMENT_MAX_PER_TICKER_QUARTER", "25"))
SENTIMENT_SLEEP_SECONDS = float(os.getenv("SENTIMENT_SLEEP_SECONDS", "3.2"))

LANGUAGE_ENDPOINT = os.getenv("LANGUAGE_ENDPOINT", "")
LANGUAGE_KEY = os.getenv("LANGUAGE_KEY", "")

# Nama container (filesystem) di ADLS Gen2.
BRONZE, SILVER, GOLD = "bronze", "silver", "gold"

HTTP_TIMEOUT = 30
USER_AGENT = "Mozilla/5.0 (TCBA-Kelompok7 academic project; contact via course)"
