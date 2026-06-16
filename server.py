"""FastAPI server — single entry point for all inbound events.

Two types of callers:
  1. Telegram (POST /telegram)  — button taps and rejection-reason text replies
  2. Cloud Scheduler             — daily pipeline cron and hourly publish cron

Run locally:
    uvicorn server:app --reload --port 8080

Deploy to Cloud Run:
    See deploy.sh (one command after first-time infra setup).
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI, HTTPException, Request, Response

app = FastAPI(title="Marketing Agent", version="1.0.0")
log = logging.getLogger("server")
logging.basicConfig(level=logging.INFO)

# Cloud Scheduler sends a secret token in a header so random callers can't
# trigger the pipeline. Set SCHEDULER_SECRET in your .env / Secret Manager.
SCHEDULER_SECRET = os.environ.get("SCHEDULER_SECRET", "")


# -----------------------------------------------------------------------
# Health-check (Cloud Run requires a 200 on the root for startup probes)
# -----------------------------------------------------------------------
@app.get("/")
async def health():
    return {"status": "ok"}


# -----------------------------------------------------------------------
# Telegram webhook
# -----------------------------------------------------------------------
@app.post("/telegram")
async def telegram_webhook(request: Request):
    """Telegram sends every bot update here in real time."""
    update = await request.json()
    log.info("telegram update: %s", str(update)[:200])
    try:
        from marketing_agent.approval import handle_update
        result = handle_update(update)
    except Exception as exc:
        log.exception("approval handler error")
        # Always return 200 to Telegram — a 5xx makes it retry every 60 s.
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "result": result}


# -----------------------------------------------------------------------
# Cloud Scheduler endpoints
# -----------------------------------------------------------------------
def _check_scheduler_auth(request: Request):
    if not SCHEDULER_SECRET:
        return  # auth disabled in dev
    token = request.headers.get("X-Scheduler-Token", "")
    if token != SCHEDULER_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")


@app.post("/run/pipeline")
async def run_pipeline(request: Request):
    """Called by Cloud Scheduler at 07:00 IST daily.

    Routes to the Phase 2 multi-agent department by default, or the Phase 1 linear
    baseline when PIPELINE_MODE=phase1.
    """
    _check_scheduler_auth(request)
    from marketing_agent import config
    mode = config.PIPELINE_MODE
    log.info("daily pipeline triggered (mode=%s)", mode)
    try:
        if mode == "phase1":
            from marketing_agent.pipeline import run_daily_pipeline
            result = await run_daily_pipeline()
        else:
            from marketing_agent.orchestrator import run_department_pipeline
            result = await run_department_pipeline()
    except Exception as exc:
        log.exception("pipeline error")
        return Response(status_code=500, content=str(exc))
    log.info("pipeline done: %s", result)
    return result


@app.post("/run/publish")
async def run_publish(request: Request):
    """Called by Cloud Scheduler every hour."""
    _check_scheduler_auth(request)
    log.info("publish cron triggered")
    try:
        from marketing_agent.publish_runner import run_due_publishes
        result = run_due_publishes()
    except Exception as exc:
        log.exception("publish error")
        return Response(status_code=500, content=str(exc))
    log.info("publish done: %s", result)
    return result


@app.post("/run/retry")
async def run_retry(request: Request):
    """Called by Cloud Scheduler every ~5 min — the durable publish-retry poll."""
    _check_scheduler_auth(request)
    log.info("retry poll triggered")
    try:
        from marketing_agent.agents.monitor import run_due_retries
        result = run_due_retries()
    except Exception as exc:
        log.exception("retry error")
        return Response(status_code=500, content=str(exc))
    log.info("retry done: %s", result)
    return result


@app.post("/run/monitor")
async def run_monitor_endpoint(request: Request):
    """Called by Cloud Scheduler (e.g. daily) — performance outcome digest."""
    _check_scheduler_auth(request)
    log.info("monitor triggered")
    try:
        from marketing_agent.agents.monitor import run_monitor
        result = run_monitor()
    except Exception as exc:
        log.exception("monitor error")
        return Response(status_code=500, content=str(exc))
    log.info("monitor done: %s", result)
    return result
