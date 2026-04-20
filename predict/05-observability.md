# 05 — Observability

Everything under `app/observability/`. Four modules: `logging.py`, `middleware.py`, `metrics.py`, `cache.py`.

## Structured logging (`logging.py`)

`configure_logging(level, *, json_format)` is called once from `create_app()` (`app/main.py:65`). The `json_format` flag is derived from `settings.app_env != "development"`, so:

- **Local dev:** human-readable `ASCTIME LEVEL NAME | MESSAGE`
- **Anywhere else:** JSON output via `pythonjsonlogger.json.JsonFormatter` with field rename `asctime → ts`, `levelname → level`.

Behavior:

- Clears all existing handlers on the root logger.
- Attaches a single `StreamHandler(sys.stdout)`.
- Sets root log level from the `LOG_LEVEL` env var.
- **Quiets `uvicorn.access` to WARNING** — our middleware emits one structured entry per request, so we don't want uvicorn's duplicate access log.
- Uses a module-level `_CONFIGURED` flag to no-op on re-entry (e.g. hot reload).

JSON log entry (what ships to stdout in non-dev):

```json
{"ts": "2026-04-18 23:00:00,000", "level": "INFO",
 "name": "riseballs_predict.request",
 "message": "request", "request_id": "abc123...",
 "method": "POST", "path": "/v1/matchups/predict",
 "route": "/v1/matchups/predict", "status": 200, "duration_ms": 87.42}
```

## Request middleware (`middleware.py`)

`RequestLoggingMiddleware` (extends Starlette's `BaseHTTPMiddleware`) runs on every request:

1. **Request ID:** reads `x-request-id` header or generates a `uuid.uuid4().hex`. Stashes on `request.state.request_id` so downstream handlers can log with it.
2. **Timing:** `start = time.perf_counter()`.
3. **Downstream:** `await call_next(request)` — any exception is caught via the `try/finally` pattern, forcing `status_code=500` if the response never materialized.
4. **Metrics:** on every request, calls `metrics_registry().record(route_template, status_code, duration_ms)`. `route_template` is the FastAPI path template (e.g. `/v1/matchups/predict`) pulled from `request.scope["route"]` — NOT the literal URL, so metrics don't explode across dynamic segments.
5. **Access log:** one `logger.info("request", extra={...})` per request with `request_id, method, path, route, status, duration_ms`.
6. **Response header:** echoes `x-request-id` back on the response (wrapped in `contextlib.suppress(Exception)` in case the response is already gone).

The logger name is fixed as `"riseballs_predict.request"` (not `__name__`) so log aggregators can filter to access-only entries easily.

## In-process metrics (`metrics.py`)

Lightweight replacement for Prometheus client in V1. Intended to be swapped out once a production host scrapes metrics properly.

### `MetricsRegistry`

```python
class MetricsRegistry:
    _counts: dict[(route, status), int]
    _latency: dict[route, _LatencyBucket]

    def record(self, route, status, duration_ms): ...
    def snapshot(self) -> dict: ...
```

Threadsafe via `threading.Lock`. Accessed as a process singleton through `metrics_registry()` which is `@lru_cache(maxsize=1)`-wrapped.

### `_LatencyBucket`

Sorted reservoir of up to **1000 samples** per route. Uses `bisect.insort` to keep samples sorted, and drops the oldest when full. Percentile is computed by indexing `samples[int(len(samples) * p)]`.

Percentiles reported: p50, p95, p99.

### Snapshot format

Surfaced via `GET /v1/metrics`:

```json
{
  "requests": [
    { "route": "/v1/matchups/predict", "status": 200, "count": 142 },
    { "route": "/v1/matchups/predict", "status": 503, "count": 1 }
  ],
  "latency": [
    { "route": "/v1/matchups/predict",
      "sample_size": 142,
      "p50_ms": 85.2, "p95_ms": 220.5, "p99_ms": 340.1 }
  ]
}
```

`reset()` exists for tests only.

## TTL cache (`cache.py`)

`TTLCache` powers the `/v1/matchups/predict` response cache. Instance created in `create_app()`:

```python
app.state.prediction_cache = TTLCache(ttl_seconds=300.0, max_entries=512)
```

### Implementation

- Backed by an `OrderedDict[str, tuple[float, Any]]` — the tuple is `(expires_at_monotonic, value)`.
- Uses `time.monotonic()` for expiry (immune to wall-clock jumps).
- LRU ordering via `move_to_end` on reads and writes.
- Evicts oldest entries when `len > max_entries`.
- Every op takes a `threading.Lock`.

### API

```python
cache.get(key: str) -> Any | None      # returns None on miss or expired
cache.put(key: str, value: Any) -> None
cache.snapshot() -> dict               # size, hits, misses, evictions, hit_rate
cache.clear() -> None                  # tests
```

`CacheStats` (hits / misses / evictions) is updated inline on every op.

### Per-process only

Each uvicorn worker maintains its own copy. For V1, this is acceptable — Rails tolerates some cache dispersion because the underlying features are stable within a 5-minute window. Swap for Redis if multi-worker consistency becomes required.

### Key scope

The predict router (`app/api/routers/predictions.py:22-25`) scopes the key on `model_version`:

```
predict|<win_model_version>|<team_a_id>|<team_b_id>|<game_date>|<home_id>
```

So a retrain + artifact swap invalidates every cached prediction without a manual flush.

### What's cached

| Endpoint | Cached? |
|---|---|
| `POST /v1/matchups/predict` | Yes (5-minute TTL) |
| `POST /v1/matchups/keys-to-victory` | No — rebuilt per call |
| `POST /v1/matchups/scenarios` | No |
| `POST /v1/games/explain-loss` | No |
| `GET /v1/models/current` | No (reads loaded artifacts directly) |
| `GET /v1/metrics` | No |
| `GET /v1/health`, `/v1/ready` | No |

Only the predict endpoint gets the cache because it's the highest-volume surface (Rails scoreboard polls every matchup card).

## Tests

- `tests/test_observability.py` — TTL cache behavior (put/get, expiry, LRU eviction), metrics registry counts + percentiles.
- `tests/integration/test_phase6_phase7_endpoints.py` — verifies predict-endpoint cache hit/miss via repeated POSTs.

## Related docs

- [01-endpoints.md](01-endpoints.md) — which endpoints participate in the cache + metrics surface
- [07-config-and-deployment.md](07-config-and-deployment.md) — env vars for cache TTL, log level, CORS
- [../operations/runbook.md](../operations/runbook.md) — incident response using `/v1/metrics` + logs
- [../pipelines/07-prediction-pipeline.md](../pipelines/07-prediction-pipeline.md) — upstream Rails client behavior on predict failures
