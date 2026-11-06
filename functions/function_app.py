"""Azure Function App — Kelompok 7 TCBA (Python v2 programming model).

Endpoint (prefix /api):
  Dipanggil ADF (butuh function key):
    POST ingest_market | ingest_fx | ingest_news | bronze_to_silver | build_gold | ml_retrain
  API publik untuk dashboard (anonim, hanya baca):
    GET  health | predictions | backtest | retrain_log | metrics | ratios | prices
  API prediksi on-demand (butuh function key):
    POST predict
"""
import json
import logging
import re

import azure.functions as func

from tcba import api, gold, jobs, silver
from tcba.lake import Lake

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)
_lake = None


def lake() -> Lake:
    global _lake
    if _lake is None:
        _lake = Lake()
    return _lake


def _json(obj, status: int = 200) -> func.HttpResponse:
    return func.HttpResponse(json.dumps(obj, ensure_ascii=False, default=str), status_code=status,
                             mimetype="application/json")


def _body(req: func.HttpRequest) -> dict:
    try:
        return req.get_json() or {}
    except ValueError:
        return {}


def _run(name: str, fn):
    try:
        out = fn()
        logging.info("%s -> %s", name, json.dumps(out, default=str)[:2000])
        # ADF Azure Function activity menganggap HTTP 200 = sukses; 500 = gagal (lalu retry).
        return _json(out, 500 if out.get("status") == "failed" else 200)
    except Exception as e:
        logging.exception("%s gagal", name)
        return _json({"job": name, "status": "failed", "error": str(e)}, 500)


# ----------------------------------------------------------------------------- jobs (ADF)
@app.route(route="ingest_market", methods=["POST"])
def ingest_market(req: func.HttpRequest) -> func.HttpResponse:
    days = int(_body(req).get("days", 10))
    return _run("ingest_market", lambda: jobs.ingest_market(lake(), days=days))


@app.route(route="ingest_fx", methods=["POST"])
def ingest_fx(req: func.HttpRequest) -> func.HttpResponse:
    days = int(_body(req).get("days", 15))
    return _run("ingest_fx", lambda: jobs.ingest_fx(lake(), days=days))


@app.route(route="ingest_news", methods=["POST"])
def ingest_news(req: func.HttpRequest) -> func.HttpResponse:
    return _run("ingest_news", lambda: jobs.ingest_news(lake()))


@app.route(route="bronze_to_silver", methods=["POST"])
def bronze_to_silver(req: func.HttpRequest) -> func.HttpResponse:
    max_new = _body(req).get("max_new_sentiment")
    return _run("bronze_to_silver", lambda: silver.run_silver(lake(), None if max_new is None else int(max_new)))


@app.route(route="build_gold", methods=["POST"])
def build_gold(req: func.HttpRequest) -> func.HttpResponse:
    return _run("build_gold", lambda: gold.build_features(lake()))


@app.route(route="ml_retrain", methods=["POST"])
def ml_retrain(req: func.HttpRequest) -> func.HttpResponse:
    trigger = re.sub(r"[^a-zA-Z0-9_]", "", str(_body(req).get("trigger", "manual")))[:40] or "manual"
    from tcba import retrain  # import berat (azure-ai-ml) hanya saat dibutuhkan
    return _run("ml_retrain", lambda: retrain.submit(trigger))


# ----------------------------------------------------------------------------- API dashboard (publik, read-only)
def _api(name: str, req: func.HttpRequest) -> func.HttpResponse:
    try:
        status, payload = api.ROUTES[name](lake(), dict(req.params))
        return _json(payload, status)
    except Exception as e:
        logging.exception("api %s gagal", name)
        return _json({"error": str(e)}, 500)


@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def health(req): return _api("health", req)


@app.route(route="predictions", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def predictions(req): return _api("predictions", req)


@app.route(route="backtest", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def backtest(req): return _api("backtest", req)


@app.route(route="retrain_log", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def retrain_log(req): return _api("retrain_log", req)


@app.route(route="metrics", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def metrics(req): return _api("metrics", req)


@app.route(route="ratios", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def ratios(req): return _api("ratios", req)


@app.route(route="prices", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def prices(req): return _api("prices", req)


@app.route(route="predict", methods=["POST"])
def predict(req: func.HttpRequest) -> func.HttpResponse:
    try:
        status, payload = api.predict(lake(), _body(req))
        return _json(payload, status)
    except Exception as e:
        logging.exception("predict gagal")
        return _json({"error": str(e)}, 500)
