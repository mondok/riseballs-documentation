# 07 — Config and Deployment

## `app/config.py` — complete listing

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: Literal["development", "test", "staging", "production"] = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8080

    log_level: str = "INFO"

    db_url: str | None = None
    warehouse_url: str | None = None

    model_root: Path = Field(default=Path("./models"))
    active_win_model_version: str | None = None
    active_run_model_version: str | None = None
    feature_schema_version: str = "features-v1"

    cors_allow_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

### Every setting

| Field | Env var | Default | Where it's read |
|---|---|---|---|
| `app_env` | `APP_ENV` | `development` | `create_app()` for JSON-log gating |
| `app_host` | `APP_HOST` | `0.0.0.0` | informational; uvicorn actually gets the bind from CLI args |
| `app_port` | `APP_PORT` | `8080` | informational |
| `log_level` | `LOG_LEVEL` | `INFO` | `configure_logging` |
| `db_url` | `DB_URL` | None | `warehouse/connection.py:_build_engine` |
| `warehouse_url` | `WAREHOUSE_URL` | None | **unused in V1** — reserved |
| `model_root` | `MODEL_ROOT` | `./models` | lifespan `load_current`, scripts |
| `active_win_model_version` | `ACTIVE_WIN_MODEL_VERSION` | None | **unused in V1** — loader reads `current/` |
| `active_run_model_version` | `ACTIVE_RUN_MODEL_VERSION` | None | **unused in V1** |
| `feature_schema_version` | `FEATURE_SCHEMA_VERSION` | `features-v1` | informational; actual contract is `app.features.contracts.FEATURE_SCHEMA_VERSION` |
| `cors_allow_origins` | `CORS_ALLOW_ORIGINS` | `["http://localhost:3000", "http://127.0.0.1:3000"]` | `CORSMiddleware` in `create_app()` |

The `_parse_cors_origins` validator splits comma-separated strings from env vars into a list. The `Annotated[..., NoDecode]` tag prevents pydantic-settings from JSON-decoding the raw env value before the validator runs.

`get_settings()` is `@lru_cache`-wrapped so the settings object is resolved once per process. `FastAPI.state.settings` caches it on the app for test-time override.

## `.env.example`

```bash
APP_ENV=development
APP_HOST=0.0.0.0
APP_PORT=8080

LOG_LEVEL=INFO

# Comma-separated allowed CORS origins (Rails dev + prod, etc.)
CORS_ALLOW_ORIGINS=http://localhost:3000,http://127.0.0.1:3000

# Data sources (Phase 2+)
# Local example: postgresql+psycopg://mattmondok@localhost:5432/riseballs_local
DB_URL=
WAREHOUSE_URL=

# Model registry (Phase 7)
MODEL_ROOT=./models
ACTIVE_WIN_MODEL_VERSION=
ACTIVE_RUN_MODEL_VERSION=
FEATURE_SCHEMA_VERSION=features-v1
```

## `Dockerfile`

```dockerfile
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY app ./app
COPY scripts ./scripts

RUN pip install --upgrade pip \
    && pip install .

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

Notes:

- `libgomp1` is the OpenMP runtime XGBoost needs at import time.
- `build-essential` stays installed (not a two-stage build yet) — small footprint win deferred.
- `models/` is **not** copied in — artifacts are shipped separately (e.g. via volume mount or a separate deploy step). In a clean container the service boots in degraded mode and the predict endpoint returns 503 until models land.
- No `HEALTHCHECK` directive; Dokku's zero-downtime deploy relies on `/v1/ready` being polled externally.

## `pyproject.toml`

Project metadata:

```toml
[project]
name = "riseballs-predict"
version = "0.1.0"
requires-python = ">=3.12"
```

Runtime deps (pinned to minima, no upper bounds):

```
fastapi>=0.115
uvicorn[standard]>=0.32
pydantic>=2.9
pydantic-settings>=2.6
pandas>=2.2
numpy>=2.1
scikit-learn>=1.5
xgboost>=2.1
joblib>=1.4
sqlalchemy>=2.0
psycopg[binary]>=3.2
python-json-logger>=3.0
```

Dev extras:

```
pytest>=8.3
pytest-asyncio>=0.24
httpx>=0.27
ruff>=0.7
mypy>=1.13
```

Build backend: `hatchling`. Wheel package: `["app"]`.

Pytest config:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra --strict-markers"
asyncio_mode = "auto"
```

Ruff config:

```toml
[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "SIM"]
ignore = ["E501"]
```

Mypy: strict + `ignore_missing_imports`.

## Local setup

```bash
cd riseballs-predict
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
# edit .env to set DB_URL etc.
```

## Run the API locally

```bash
uvicorn app.main:app --reload --port 8080
```

Then:

```bash
curl http://localhost:8080/v1/health
curl http://localhost:8080/v1/ready
open http://localhost:8080/docs    # FastAPI auto-generated Swagger UI
```

## Run the full test suite against a live DB

```bash
DB_URL="postgresql+psycopg://mattmondok@localhost:5432/riseballs_local" \
MODEL_ROOT=./models \
pytest -v
```

Integration tests in `tests/integration/` exercise real repositories + the full endpoint stack. They're skipped cleanly when `DB_URL` is unset.

## Training a new model

```bash
DB_URL=... python scripts/train_all.py \
  --through-date 2026-04-17 \
  --season-min 2025
```

Writes to `./models/current/{win_probability,run_expectancy}` and copies a snapshot to `./models/archive/<model_version>/`. The running service must be restarted to pick up new artifacts (lifespan loads them once).

## Evaluating the active model against a holdout

```bash
DB_URL=... python scripts/evaluate_latest.py \
  --through-date 2026-04-27 \
  --holdout-from 2026-04-18
```

Prints a JSON report to stdout with overall + slice metrics. Does not retrain.

## Production deployment (Dokku)

Per the parent CLAUDE.md (Dokku at `ssh.edentechapps.com`):

```bash
# Initial setup
ssh dokku@ssh.edentechapps.com apps:create riseballs-predict
ssh dokku@ssh.edentechapps.com config:set --no-restart riseballs-predict \
  APP_ENV=production \
  DB_URL='postgresql+psycopg://...' \
  CORS_ALLOW_ORIGINS='https://riseballs.com' \
  MODEL_ROOT=/app/models
ssh dokku@ssh.edentechapps.com ports:set riseballs-predict http:80:8080
git remote add dokku dokku@ssh.edentechapps.com:riseballs-predict
git push dokku master
```

Port mapping is `http:80:8080` because the Dockerfile exposes 8080.

### How Rails reaches this service in production

Rails client: `riseballs/app/services/predict_service_client.rb`.

| Rails env var | Default | Notes |
|---|---|---|
| `PREDICT_SERVICE_URL` | `http://localhost:8080` | Set to the Dokku app URL in production (e.g. `https://predict.riseballs.com` behind the Cloudflare Tunnel) |
| `PREDICT_SERVICE_TIMEOUT_SECONDS` | `5` | Per-HTTP-call timeout |

The client fans out `/v1/matchups/predict` and `/v1/matchups/keys-to-victory` **in parallel threads** for the bundle view — combined latency is bounded by the slower of the two. The Rails controller returns 204 for any played game (doesn't call predict) and 503 if predict times out or errors.

### CORS

`CORS_ALLOW_ORIGINS` **must** include the production Rails origin. The default only allows localhost Rails dev. Predict is typically called server-side from Rails (no browser CORS involved), but browser-side tooling on `/docs` and any future direct client calls need the origin allowed.

## Further reading

For the narrative — phase-by-phase build history, data-shape gotchas, training baselines, deferred work — see the service's persistent memory file:

`/Users/mattmondok/Code/riseballs-parent/riseballs-predict/how_things_work.md`
