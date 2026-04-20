# 02 — Feature Engineering

All feature code lives under `app/features/`. Builders are **pure functions** over frozen dataclasses (`Game`, `TeamBox`, `TeamPitching` from `app/data/models.py`). The warehouse-touching orchestrator is `app/services/feature_service.py`.

## Contract (`app/features/contracts.py`)

```python
FEATURE_SCHEMA_VERSION = "features-v1"

WINDOWS = ("season", "last_20", "last_10", "last_5")

WINDOW_LIMITS = {
  "season":  None,  # filtered by season year instead of N
  "last_20": 20,
  "last_10": 10,
  "last_5":  5,
}
```

A `FeatureSet` is a flat `dict[str, float]` wrapped in a frozen dataclass:

```python
@dataclass(frozen=True, slots=True)
class FeatureSet:
    team_slug: str
    as_of_date: date
    schema_version: str
    games_available: int
    values: dict[str, float]
```

Key naming: `<group>.<window>.<metric>` for team features, `matchup.<metric>` for interaction features. Groups are `strength`, `off`, `pitch`, `def`, `matchup`.

Totals: ~42 team metrics × 4 windows ≈ **168 per team**, plus **15 matchup deltas** → ~351 feature columns in a training row after `team_a__` / `team_b__` / `matchup__` prefixing (see `03-ml-and-artifacts.md`).

`season_for(d)` (line 76): NCAA softball runs Jan–Jun, so calendar year is used as the season key.

## Shared helpers (`app/features/builders/_common.py`)

Underscore-prefixed module: builders import, the orchestrator does not.

| Helper | Purpose |
|---|---|
| `safe_div(num, den, default=0.0)` | Zero-denominator-safe division. Tree models want finite floats — NaNs from `0/0` would silently corrupt training. |
| `filter_to_window(items, *, window, as_of_date)` | Slice a most-recent-first list. `season` → items whose `game_date.year == as_of_date.year`. `last_N` → first N items (caller must pre-sort DESC). |
| `sum_attr(items, attr)` | `sum(getattr(item, attr) for item in items)` as a float. |

## Builders

Each builder is a function `build(...) -> dict[str, float]`. Windows are iterated inside `build`; each window produces one block of keyed metrics. Empty windows return a zero-filled block with consistent keys ("zero-default policy" per `how_things_work.md`).

### `team_strength_features.py`

**Input:** `list[Game]` (team's completed games strictly before `as_of_date`)
**Group:** `strength`

For each game, pull out the team's own score vs opponent's by checking `home_team_slug == team_slug`. Then per window:

| Metric | Formula |
|---|---|
| `games_played` | `len(games_in_window)` |
| `win_pct` | `safe_div(wins, wins + losses, default=0.5)` |
| `runs_for_per_game` | `runs_for / n` |
| `runs_against_per_game` | `runs_against / n` |
| `run_diff_per_game` | `runs_for_pg - runs_against_pg` |
| `pythagorean_pct` | `rf^1.83 / (rf^1.83 + ra^1.83)`; returns 0.5 when both are 0 |
| `recent_form` | `2 * win_pct - 1` in `[-1, 1]` |

**Pythagorean exponent** = **1.83** (line 20). Lower than baseball's 2.0 — softball scoring is higher-variance, so slightly deflated. Revisit once the run model matures.

### `offense_features.py`

**Input:** `list[TeamBox]` (most-recent-first)
**Group:** `off`

Aggregates totals over the window, then computes rates:

| Metric | Formula |
|---|---|
| `games_played` | `n` |
| `runs_per_game`, `hits_per_game`, ... | `total / n` for runs, hits, walks, strikeouts, home runs, extra-base hits, stolen bases |
| `sb_success_rate` | `sb / (sb + cs)` |
| `obp_proxy` | `(H + BB + HBP) / (AB + BB + HBP + SF)` |
| `slg_proxy` | `total_bases / AB` |
| `ops_proxy` | `obp_proxy + slg_proxy` |
| `iso_proxy` | `(total_bases - hits) / AB` |
| `k_rate`, `bb_rate`, `hbp_rate`, `free_base_rate` | `X / (plate_appearances_proxy + sacrifice_bunts)` |

`total_bases`, `extra_base_hits`, and `plate_appearances_proxy` are derived on `TeamBox` (`app/data/models.py:79-92`):

```python
total_bases = singles + 2*doubles + 3*triples + 4*home_runs
pa_proxy    = AB + BB + HBP + SF + sac_bunts
```

OBP/SLG are **proxies** — the local `player_game_stats` data lacks reach-on-error and some PA corrections. "Good enough" for a tabular model (per module docstring).

### `pitching_features.py`

**Input:** `list[TeamPitching]` (per-game pitching totals, derived from `player_game_stats` where `has_pitching=true`)
**Group:** `pitch`

| Metric | Formula |
|---|---|
| `games_played` | `n` |
| `runs_allowed_per_game`, `earned_runs_per_game`, ... | `X / n` for runs, earned runs, hits, walks, K, HR, HBP, WP allowed |
| `whip` | `(BB + H) / innings` |
| `k_per_7` | `K * 7 / innings` (NCAA softball is 7-inning games) |
| `bb_per_7` | `BB * 7 / innings` |
| `k_bb_ratio` | `safe_div(K, BB, default=K)` — defaults to K itself when no walks, avoids inf |
| `opponent_obp_proxy` | `(H + BB + HBP allowed) / batters_faced` |

### `defense_features.py`

**Input:** `list[TeamBox]`, `list[TeamPitching]` aligned by `game_id`
**Group:** `def`

Defense signal comes from two places — errors live on the team's batting row (`fielding_errors`), unearned runs come from the pitching row (`runs_allowed - earned_runs`).

| Metric | Formula |
|---|---|
| `games_with_data` | `max(len(boxes), len(pitching))` |
| `errors_per_game` | `sum(errors) / n_boxes` |
| `unearned_runs_per_game` | `(runs_allowed - earned_runs) / n_pitch` (clamped to ≥0) |
| `unearned_run_share` | `unearned / runs_allowed` |

### `matchup_features.py`

**Input:** team_a `values` dict, team_b `values` dict (both already computed)
**Group:** `matchup`
**Window:** **season only** (per docstring: last-N windows are too noisy for interaction deltas in a ~50-game season)

Interactions subtract a Team B vulnerability from a Team A strength (or vice versa):

| Metric | Computation |
|---|---|
| `matchup.power_edge` | A's `off.season.home_runs_per_game` − B's `pitch.season.home_runs_allowed_per_game` |
| `matchup.xbh_edge` | A's `off.season.extra_base_hits_per_game` − B's `pitch.season.hits_allowed_per_game` |
| `matchup.bb_edge` | A's `off.season.walks_per_game` − B's `pitch.season.walks_allowed_per_game` |
| `matchup.contact_edge` | A's `off.season.strikeouts_per_game` − B's `pitch.season.strikeouts_per_game` (negative = A makes more contact) |
| `matchup.obp_vs_opp_obp` | A's `off.season.obp_proxy` − B's `pitch.season.opponent_obp_proxy` |
| `matchup.slg_vs_opp_whip` | A's `off.season.slg_proxy` − B's `pitch.season.whip` |
| `matchup.win_pct_diff` | A's `strength.season.win_pct` − B's `strength.season.win_pct` |
| `matchup.run_diff_gap` | A's `strength.season.run_diff_per_game` − B's `strength.season.run_diff_per_game` |
| `matchup.pythagorean_gap` | A's `strength.season.pythagorean_pct` − B's `strength.season.pythagorean_pct` |
| `matchup.recent_form_gap` | A's `strength.season.recent_form` − B's `strength.season.recent_form` |
| `matchup.defense_edge` | `-(A errors_pg − B errors_pg)` — flip sign so positive = A advantage |
| `matchup.unearned_run_edge` | `-(A unearned_pg − B unearned_pg)` |
| `matchup.team_a_games_played` | A's `strength.season.games_played` |
| `matchup.team_b_games_played` | B's `strength.season.games_played` |
| `matchup.min_games_played` | `min(team_a_games_played, team_b_games_played)` |

The `*_games_played` fields are reliability metadata used by the `confidence_band` rule in `prediction_service.py`. They're **excluded from swing factors** so they don't appear in the UI as signals (see `_NON_SWING_SUFFIXES` in `prediction_service.py:39`).

## Orchestration (`app/services/feature_service.py`)

```python
_HISTORY_LOOKBACK = 200
```

Point-in-time-safe data pull (line 35):

1. `games_repository.list_games_for_team_before(team_slug, as_of_date, limit=200)` — most-recent-first, **strictly** before the date (no leakage).
2. `boxscores_repository.list_team_boxes_for_games(team_slug, game_ids)` — aggregates `player_game_stats` where `has_batting=true`.
3. `pitching_repository.list_team_pitching_for_games(team_slug, game_ids)` — aggregates where `has_pitching=true`.
4. Sort boxes and pitching DESC by `(game_date, game_id)` so last-N slices work.
5. Run each builder per window, merge values into one `dict[str, float]`.

`build_matchup_features(a, b, as_of_date)`:

1. `build_team_features(a, ...)` and `build_team_features(b, ...)`.
2. `matchup_features.build(team_a.values, team_b.values)`.
3. Return a `MatchupFeatureSet` with both `FeatureSet`s + matchup interactions.

### Data shape gotchas (from `how_things_work.md`)

1. **No flat per-game team box table.** Everything aggregates `player_game_stats` by `(game_id, team_seo_slug)`.
2. **`team_pitching_stats` is season-aggregate only** — not per-game. Per-game pitching is derived from PGS where `has_pitching=true`.
3. **`game_identifiers` is empty locally** — PBP joins fall back to `(team_slug, game_date)`.
4. **Doubleheaders.** Group by `game_id`, never by `(team_slug, game_date)`.
5. **Tournament team slugs** like `no-3-seed-goldey-beacom` are bracket entries, not duplicates — repos return them as-is.

## Versioning

`FEATURE_SCHEMA_VERSION = "features-v1"` is pinned in `contracts.py:18` and referenced by:

- `app/ml/artifacts/saver.py` when stamping training metadata
- `app/services/prediction_service.py` when echoing it in `PredictResponse`
- `app/services/scenario_service.py` / `app/explain/key_to_victory_engine.py` responses

Any change to the metric key set (adding/renaming/removing) **must** bump this constant. The model artifacts pin the trained column order in `features.json`; inference does `reindex(columns=...)` + `fillna(0.0)` so a compatible superset of features won't break old artifacts (`prediction_service.py:103`).

## Related docs

- [03-ml-and-artifacts.md](03-ml-and-artifacts.md) — how features feed XGBoost training + inference
- [06-schemas.md](06-schemas.md) — pydantic shapes for feature-bearing responses
- [07-config-and-deployment.md](07-config-and-deployment.md) — env vars controlling feature windows + DB access
- [../pipelines/07-prediction-pipeline.md](../pipelines/07-prediction-pipeline.md) — how Rails invokes this service per matchup
- [../architecture/02-data-flow.md](../architecture/02-data-flow.md) — upstream warehouse data feeding the builders
