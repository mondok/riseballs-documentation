# 00 — Overview

## Purpose

`riseballs-predict` is a standalone **Python / FastAPI** HTTP service that owns:

1. Feature engineering over the shared riseballs Postgres warehouse
2. Win-probability + run-expectancy ML (XGBoost)
3. Deterministic explanations (why a team lost)
4. Scenario perturbations + keys-to-victory (how a team could win)
5. Model-artifact registry + observability surface

It is a **read-only consumer** of the warehouse — it never writes back. The Java scraper (`riseballs-scraper`) owns writes; the Rails app (`riseballs`) owns the UI and calls this service over HTTP.

Root: `/Users/mattmondok/Code/riseballs-parent/riseballs-predict/`

## Stack

From `pyproject.toml`:

| Layer | Choice | Version (min) |
|---|---|---|
| Language | Python | 3.12 |
| Web framework | FastAPI | 0.115 |
| ASGI server | uvicorn[standard] | 0.32 |
| Schemas / settings | pydantic / pydantic-settings | 2.9 / 2.6 |
| DB client | SQLAlchemy 2 + psycopg[binary] | 2.0 / 3.2 |
| ML | XGBoost, scikit-learn | 2.1 / 1.5 |
| Data wrangling | pandas, numpy | 2.2 / 2.1 |
| Logging | python-json-logger | 3.0 |
| Tests | pytest, pytest-asyncio, httpx | 8.3 / 0.24 / 0.27 |
| Lint | ruff | 0.7 |
| Types | mypy (strict) | 1.13 |

## Directory layout

```
riseballs-predict/
  app/
    main.py                   # FastAPI entry point (create_app, lifespan)
    config.py                 # Settings (pydantic-settings)
    api/routers/              # FastAPI routers
      health.py               # /v1/health, /v1/ready
      predictions.py          # POST /v1/matchups/predict
      explanations.py         # POST /v1/games/explain-loss
      scenarios.py            # POST /v1/matchups/scenarios, /keys-to-victory
      models.py               # GET /v1/models/current
      metrics.py              # GET /v1/metrics
    data/
      models.py               # Frozen dataclass DTOs (Team, Game, TeamBox, TeamPitching, PlateAppearance)
      warehouse/connection.py # SQLAlchemy engine + warehouse_connection ctx + ping()
      repositories/           # teams, games, boxscores, pitching, play_by_play repos
    features/
      contracts.py            # FEATURE_SCHEMA_VERSION, WINDOWS, FeatureSet/MatchupFeatureSet dataclasses
      builders/               # per-group feature builders (pure functions)
    ml/
      datasets/               # dataset_builder, labels, time-split
      models/                 # WinProbabilityModel, RunExpectancyModel (XGBoost wrappers)
      evaluation/             # metrics + slice metrics
      artifacts/              # paths, loader, saver
      training/pipeline.py    # train_all orchestrator
    explain/
      categories.py           # explain-loss scorer catalog (taxonomy: explain-v1)
      why_engine.py           # rank + summarize reasons
      scenario_analysis.py    # perturbation engine (taxonomy: scenarios-v1)
      key_to_victory_engine.py# filter positive deltas → keys (taxonomy: keys-v1)
    services/                 # orchestrators: feature_service, prediction_service,
                              #                explanation_service, scenario_service,
                              #                model_registry_service
    schemas/                  # pydantic request/response models
    observability/            # cache (TTL LRU), logging, metrics registry, middleware
  scripts/
    train_all.py              # CLI: build dataset + train both models + save artifacts
    evaluate_latest.py        # CLI: score the active model on a holdout window + slices
  models/                     # Artifact tree (see 03-ml-and-artifacts.md)
    current/                  # Live models (win_probability/, run_expectancy/)
    archive/                  # Prior versions keyed on model_version
  tests/                      # pytest (unit + integration/)
  Dockerfile                  # python:3.12-slim, uvicorn on :8080
  pyproject.toml
  README.md
  how_things_work.md          # Persistent service memory
  .env.example
```

## Entry point

`app/main.py` defines `create_app()` which returns a configured FastAPI app. The module-level `app = create_app()` is what uvicorn imports.

Lifespan (`app/main.py:28-60`) runs on startup:

1. Ping the warehouse if `DB_URL` is set — sets `app.state.warehouse_ready`.
2. Attempt to load model artifacts from `settings.model_root` via `load_current(...)`. On success, sets `app.state.model_artifacts` + `app.state.models_ready = True`. On `ArtifactsNotFoundError`, logs a warning and starts in degraded mode.
3. Flips `app.state.ready = True`.

Middleware + routers wired in `create_app()`:

- `RequestLoggingMiddleware` — request-id propagation, structured access log, latency → metrics registry.
- `CORSMiddleware` — restricted to `settings.cors_allow_origins` (defaults to Rails dev hosts).
- Routers under `/v1/`: `health`, `predictions`, `explanations`, `scenarios`, `models`, `metrics`.

Application state fields:

| Field | Type | Meaning |
|---|---|---|
| `settings` | `Settings` | Cached config |
| `ready` | bool | Process-level "up" |
| `warehouse_ready` | bool | DB ping succeeded at startup |
| `models_ready` | bool | Artifacts loaded at startup |
| `model_artifacts` | `LoadedArtifacts \| None` | Live models |
| `prediction_cache` | `TTLCache` | 5-minute LRU (ttl=300s, max=512) |

## Deployment

`Dockerfile`:

- Base: `python:3.12-slim`
- Installs `build-essential libgomp1` (OpenMP runtime for XGBoost)
- Copies `pyproject.toml`, `README.md`, `app/`, `scripts/` and runs `pip install .`
- Exposes port `8080`
- `CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]`

Dokku deploy (expected pattern from the parent CLAUDE.md): push to `dokku` remote; port mapping `http:80:8080`. The `CORS_ALLOW_ORIGINS` env var must be set to include the prod Rails origin.

The Rails app reaches the service via `PREDICT_SERVICE_URL` (default `http://localhost:8080`) with a 5-second timeout (`PREDICT_SERVICE_TIMEOUT_SECONDS`). See `riseballs/app/services/predict_service_client.rb`.

## Environment variables

Defined on `Settings` (`app/config.py:9-42`):

| Var | Default | Notes |
|---|---|---|
| `APP_ENV` | `development` | One of `development`, `test`, `staging`, `production`. Drives JSON-vs-human logs. |
| `APP_HOST` | `0.0.0.0` | Bind host (uvicorn) |
| `APP_PORT` | `8080` | Bind port |
| `LOG_LEVEL` | `INFO` | |
| `DB_URL` | unset | SQLAlchemy URL to the riseballs warehouse. Example: `postgresql+psycopg://mattmondok@localhost:5432/riseballs_local` |
| `WAREHOUSE_URL` | unset | Reserved; not read in V1 code path |
| `MODEL_ROOT` | `./models` | Artifact tree root |
| `ACTIVE_WIN_MODEL_VERSION` | unset | Reserved; loader pulls `current/` unconditionally in V1 |
| `ACTIVE_RUN_MODEL_VERSION` | unset | Reserved |
| `FEATURE_SCHEMA_VERSION` | `features-v1` | Pinned to the code contract |
| `CORS_ALLOW_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | Comma-separated; parsed by `_parse_cors_origins` validator |

`Settings` reads from `.env` (see `.env.example` for the template).

## Cross-references

- `01-endpoints.md` — every FastAPI route with schema + caching + Rails call sites
- `02-feature-engineering.md` — builders + the features contract
- `03-ml-and-artifacts.md` — models, training, artifact tree
- `04-explain-engine.md` — explain-loss + scenarios + keys
- `05-observability.md` — cache, metrics, logging, middleware
- `06-schemas.md` — pydantic schemas
- `07-config-and-deployment.md` — config full dump + Docker + how Rails reaches this
- Source-of-truth narrative: `/Users/mattmondok/Code/riseballs-parent/riseballs-predict/how_things_work.md`
