import json
import os
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib import error as urlerror
from urllib import request as urlrequest

from utils.orm.models import LoadRuns

SIGN_API = os.environ["SIGN_API"]

SCENARIOS = {
    "lambda": {"expect": 200, "url": lambda i: f"{SIGN_API}/health"},
    "db": {"expect": 404, "url": lambda i: f"{SIGN_API}/signatures/carga-{i}-{random.randint(1000, 9999)}"},
}


def _hit(url: str, expect: int) -> dict:
    t0 = time.perf_counter()
    try:
        req = urlrequest.Request(url, headers={"User-Agent": "cdts-load"})
        with urlrequest.urlopen(req, timeout=15) as resp:
            status = resp.status
    except urlerror.HTTPError as e:
        status = e.code
    except Exception:
        status = 0
    ms = round((time.perf_counter() - t0) * 1000, 1)
    return {"ms": ms, "ok": status == expect}


def _pct(sorted_ms: list[float], p: float) -> float:
    idx = min(len(sorted_ms) - 1, max(0, round(p / 100 * len(sorted_ms)) - 1))
    return sorted_ms[idx]


def _snapshot(samples: list[dict], total: int, started: float) -> dict:
    lat = sorted(x["ms"] for x in samples)
    oks = sum(1 for x in samples if x["ok"])
    elapsed = round(time.perf_counter() - started, 1)
    return {
        "done": len(samples),
        "total": total,
        "ok": oks,
        "ko": len(samples) - oks,
        "elapsed": elapsed,
        "rps": round(len(samples) / elapsed, 1) if elapsed else 0.0,
        "avg": round(sum(lat) / len(lat), 1) if lat else 0,
        "min": lat[0] if lat else 0,
        "max": lat[-1] if lat else 0,
        "p50": _pct(lat, 50) if lat else 0,
        "p90": _pct(lat, 90) if lat else 0,
        "p95": _pct(lat, 95) if lat else 0,
        "samples": list(samples),
    }


def load_runner(event, context):
    run_id = event["run_id"]
    row = LoadRuns.get_by_id(run_id)
    cfg = json.loads(row.config)
    scenario = SCENARIOS[cfg["scenario"]]
    total, conc = cfg["requests"], cfg["concurrency"]

    samples: list[dict] = []
    lock = threading.Lock()
    started = time.perf_counter()
    last_flush = started

    def work(i: int) -> None:
        nonlocal last_flush
        result = _hit(scenario["url"](i), scenario["expect"])
        flush = None
        with lock:
            samples.append(result)
            now = time.perf_counter()
            if now - last_flush > 1.5:
                last_flush = now
                flush = _snapshot(samples, total, started)
        if flush:
            LoadRuns.update_by_id(run_id, {"results": json.dumps(flush)})

    with ThreadPoolExecutor(max_workers=conc) as pool:
        list(pool.map(work, range(total)))

    final = _snapshot(samples, total, started)
    LoadRuns.update_by_id(run_id, {
        "status": "failed" if final["ko"] else "passed",
        "results": json.dumps(final),
        "finished_at": datetime.now(timezone.utc),
    })
