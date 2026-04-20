# 06 — Schemas

All pydantic request/response models live under `app/schemas/`. Four files, one per domain.

## `prediction.py`

**Used by:** `POST /v1/matchups/predict` (`predictions.py`), `POST /v1/matchups/scenarios` + `/keys-to-victory` (reuses `MatchupContext`).

### `MatchupContext`

```python
class MatchupContext(BaseModel):
    home_team_id: str | None = None    # Defaults to team_a_id if omitted
    neutral_site: bool = False
    division: str | None = None        # "d1" | "d2" — slice metadata only
```

### `PredictRequest`

```python
class PredictRequest(BaseModel):
    team_a_id: str
    team_b_id: str
    game_date: date
    context: MatchupContext = Field(default_factory=MatchupContext)
```

No custom validators — pydantic handles `date` parsing from ISO strings.

### `SwingFactor`

```python
class SwingFactor(BaseModel):
    code: str                           # matchup feature name (post-prefix)
    title: str                          # Title-Cased code
    advantage_team_id: str | None       # team_a_id if value >= 0 else team_b_id
    importance: float                   # normalized [0, 1]
    summary: str
```

### `Prediction`

```python
class Prediction(BaseModel):
    team_a_win_probability: float       # rounded to 4 decimals
    team_b_win_probability: float       # 1 - team_a
    team_a_expected_runs: float         # rounded to 2 decimals
    team_b_expected_runs: float
    confidence_band: str                # "low" | "medium" | "high"
```

### `PredictResponse`

```python
class PredictResponse(BaseModel):
    model_version: str
    feature_schema_version: str
    prediction: Prediction
    swing_factors: list[SwingFactor]    # up to 5
```

---

## `explanation.py`

**Used by:** `POST /v1/games/explain-loss`.

### `ExplainLossRequest`

```python
class ExplainLossRequest(BaseModel):
    game_id: int
```

### `ReasonEvidence`

```python
class ReasonEvidence(BaseModel):
    model_config = {"extra": "allow"}
```

Defined for future typing but not currently referenced on the response — the live schema uses a raw `dict[str, float | int]`. The open-extra config lets new evidence fields land without a schema revision.

### `Reason`

```python
class Reason(BaseModel):
    code: str
    title: str
    importance: float = Field(..., ge=0.0, le=1.0)
    score: float = Field(..., ge=0.0, le=1.0)
    summary: str
    evidence: dict[str, float | int]
```

`importance` and `score` are range-validated.

### `ExplainLossResponse`

```python
class ExplainLossResponse(BaseModel):
    game_id: int
    losing_team_id: str
    winning_team_id: str
    losing_score: int
    winning_score: int
    taxonomy_version: str               # "explain-v1"
    summary: str
    reasons: list[Reason]               # up to 5; empty if nothing decisive
```

---

## `scenario.py`

**Used by:** `POST /v1/matchups/scenarios`, `POST /v1/matchups/keys-to-victory`. Re-imports `MatchupContext` from `prediction.py`.

### `ScenariosRequest`

```python
class ScenariosRequest(BaseModel):
    team_a_id: str
    team_b_id: str
    game_date: date
    context: MatchupContext = Field(default_factory=MatchupContext)
```

Same shape as `PredictRequest` — the Rails client reuses a single payload.

### `ScenarioItem`

```python
class ScenarioItem(BaseModel):
    code: str                           # e.g. "avoid_free_bases"
    title: str
    team_id: str                        # team this scenario applies to
    baseline_win_probability: float
    scenario_win_probability: float
    win_probability_delta: float        # signed
    summary: str
```

### `ScenariosResponse`

```python
class ScenariosResponse(BaseModel):
    taxonomy_version: str               # "scenarios-v1"
    model_version: str
    feature_schema_version: str
    baseline_team_a_win_probability: float
    baseline_team_b_win_probability: float
    scenarios: list[ScenarioItem]       # 14 items (7 scenarios × 2 teams)
```

### `KeyToVictoryItem`

```python
class KeyToVictoryItem(BaseModel):
    code: str
    title: str
    importance: float = Field(..., ge=0.0, le=1.0)
    win_probability_delta: float        # always positive (filter pass)
    summary: str
```

### `TeamKeysPayload`

```python
class TeamKeysPayload(BaseModel):
    team_id: str
    keys_to_victory: list[KeyToVictoryItem]   # up to 5, can be empty
```

### `KeysToVictoryResponse`

```python
class KeysToVictoryResponse(BaseModel):
    taxonomy_version: str               # "keys-v1"
    model_version: str
    feature_schema_version: str
    team_a: TeamKeysPayload
    team_b: TeamKeysPayload
```

---

## `model.py`

**Used by:** `GET /v1/models/current`.

### `ModelMetrics`

```python
class ModelMetrics(BaseModel):
    model_config = {"extra": "allow"}
```

Defined for future typing; the live `ModelInfo` uses a raw `dict[str, object]` on `metrics` for forward compat with new slice families.

### `ModelInfo`

```python
class ModelInfo(BaseModel):
    model_version: str
    feature_schema_version: str
    trained_through_date: str | None = None
    train_rows: int | None = None
    validation_rows: int | None = None
    test_rows: int | None = None
    metrics: dict[str, object] = Field(default_factory=dict)
    git_sha: str | None = None
    artifact_created_at: str | None = None
```

`metrics` carries nested per-split metrics plus optional `test_slices`. Intentionally loose — adding a new slice family doesn't require a schema rev.

### `CurrentModelsResponse`

```python
class CurrentModelsResponse(BaseModel):
    status: str                         # "active" | "no_active_model"
    win_probability: ModelInfo | None = None
    run_expectancy: ModelInfo | None = None
```

When `status == "no_active_model"`, both info blocks are `null` — lets Rails render "Predictions unavailable" with a reason.

---

## Health schemas (inline in router)

Defined directly in `app/api/routers/health.py`, not under `app/schemas/`:

```python
class HealthResponse(BaseModel):
    status: str

class ReadyResponse(BaseModel):
    status: str
    ready: bool
    warehouse_ready: bool
    models_ready: bool
```

No corresponding `schemas/` file exists for these.

---

## Schema → endpoint map

| Schema | Endpoint(s) | Direction |
|---|---|---|
| `PredictRequest` | `POST /v1/matchups/predict` | in |
| `PredictResponse` (+ `Prediction`, `SwingFactor`) | `POST /v1/matchups/predict` | out |
| `MatchupContext` | All matchup endpoints | in (nested) |
| `ExplainLossRequest` | `POST /v1/games/explain-loss` | in |
| `ExplainLossResponse` (+ `Reason`) | `POST /v1/games/explain-loss` | out |
| `ScenariosRequest` | `/scenarios`, `/keys-to-victory` | in |
| `ScenariosResponse` (+ `ScenarioItem`) | `POST /v1/matchups/scenarios` | out |
| `KeysToVictoryResponse` (+ `TeamKeysPayload`, `KeyToVictoryItem`) | `POST /v1/matchups/keys-to-victory` | out |
| `CurrentModelsResponse` (+ `ModelInfo`) | `GET /v1/models/current` | out |
| `HealthResponse` | `GET /v1/health` | out |
| `ReadyResponse` | `GET /v1/ready` | out |

## Versioning surface

Every write-heavy response carries at least two version fields so Rails can detect drift:

- `feature_schema_version` — `"features-v1"` (pinned in `app/features/contracts.py`)
- `model_version` — per-training-run string (e.g. `win-prob-2026-04-17-xgb-...`)
- `taxonomy_version` — one of `"explain-v1"`, `"scenarios-v1"`, `"keys-v1"` depending on endpoint

Bumping any of these is the contract for adding/removing fields in the corresponding response.

## Related docs

- [01-endpoints.md](01-endpoints.md) — endpoints each schema is bound to
- [02-feature-engineering.md](02-feature-engineering.md) — source of `feature_schema_version` pin
- [03-ml-and-artifacts.md](03-ml-and-artifacts.md) — source of `model_version` pin
- [../rails/11-external-clients.md](../rails/11-external-clients.md) — Ruby consumer of these payloads
