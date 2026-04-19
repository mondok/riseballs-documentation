# External Service Clients

Rails-side thin clients for the sibling services Rails itself calls.
Since 2026-04-19 there is a third sibling, `riseballs-live`, which
**Rails does not call** — the browser talks to it directly. Rails has
no HTTP client for it and should never grow one.

- **Java scraper** (`riseballs-scraper`) — box score fetching, roster
  augmentation, schedule reconciliation, standings scraping, and the
  game creation gate.
- **Python predict service** (`riseballs-predict`) — matchup prediction
  and keys-to-victory analysis.
- **(out-of-band) `riseballs-live`** — consumed by the browser, not
  Rails. See [live/00-overview.md](../live/00-overview.md).

`StatBroadcast` and `SidearmStats` clients used to live here too; both
were deleted on 2026-04-19 along with the LiveStats controller. See the
deleted entries below.

Both remaining clients are pure HTTP — no shared models, no shared DB,
just JSON over HTTP.

## Table of Contents

- [JavaScraperClient (`app/services/java_scraper_client.rb`)](#javascraperclient)
  - [Base URL & availability gate](#base-url--availability-gate)
  - [Error handling pattern](#error-handling-pattern)
  - [Endpoints](#endpoints)
  - [Caller map: jobs/controllers → endpoints](#caller-map-jobscontrollers--endpoints)
- [PredictServiceClient (`app/services/predict_service_client.rb`)](#predictserviceclient)
  - [Configuration](#configuration)
  - [Error model](#error-model)
  - [`predict_only`](#predict_only)
  - [`bundle_for` — parallel predict + keys](#bundle_for--parallel-predict--keys)
  - [Request payload shape](#request-payload-shape)
  - [Controller surface + 503 handling](#controller-surface--503-handling)

---

## JavaScraperClient

**File:** `app/services/java_scraper_client.rb` (360 LOC)

Client for the Java Spring Boot scraper. Every method is a class method
that returns either a parsed-response hash or `nil` — **never raises**
except for programmer errors. The uniform nil-on-failure contract is
what lets jobs call `JavaScraperClient.method && do_stuff_with(result)`
without defensive rescues at every call site.

### Base URL & availability gate

```ruby
BASE_URL = ENV.fetch("JAVA_SCRAPER_URL", nil)
```

On Dokku production, `JAVA_SCRAPER_URL` is set to the internal network
address `http://riseballs-scraper.web:8080`. Tests override it via
`remove_const` / `const_set` (see `test/services/java_scraper_client_test.rb`).

Every public method starts with:

```ruby
return nil unless available?
```

`available?` is `BASE_URL.present?` (lines 8-10). Local dev without
`JAVA_SCRAPER_URL` set → every call returns nil and callers degrade
gracefully.

Important wrinkle for prod debugging: the hostname
`riseballs-scraper.web` only resolves from running **app containers**
(web/worker). `dokku run` spins up a one-off container outside the app
network and will fail on every call. Use `dokku enter` for anything
that hits the Java scraper (see project `CLAUDE.md`).

### Error handling pattern

Every method uses the same template:

```ruby
def some_method(args)
  return nil unless available?

  resp = HTTParty.post("#{BASE_URL}/api/...",
    body: {...}.to_json,
    headers: { "Content-Type" => "application/json" },
    timeout: N
  )
  return nil unless resp.success?
  resp.parsed_response
rescue Net::ReadTimeout, Net::OpenTimeout, Errno::ECONNREFUSED, StandardError => e
  Rails.logger.warn("JavaScraperClient: <op> failed: #{e.message}")
  nil
end
```

- Non-2xx response → nil (no raise).
- Network errors → rescued, warned, nil.
- `StandardError` at the end catches HTTParty wrapping oddities, JSON
  parse errors, and anything else — Rails never crashes because the
  scraper is flaky.

### Endpoints

| Method                                        | HTTP | Path                                  | Timeout | Purpose                                                                 |
| --------------------------------------------- | ---- | ------------------------------------- | ------- | ----------------------------------------------------------------------- |
| `scrape_game(game_id)`                        | POST | `/api/scrape/boxscore`                | 120s    | Single box score scrape. Returns `data["boxscore"]` when `success`.     |
| `scrape_batch(game_ids)`                      | POST | `/api/scrape/boxscores`               | 600s    | Batched; Java caps at 500 per request so Ruby slices at 400.            |
| `augment_team(team_slug)`                     | POST | `/api/roster/augment`                 | 300s    | Augment one team's players with previous-school / transfer data.        |
| `augment_all`                                 | POST | `/api/roster/augment/all`             | 3600s   | Full run across every team.                                             |
| `augment_coaches(team_slug)`                  | POST | `/api/roster/augment-coaches`         | 300s    | Single-team coach enrichment (contact + socials).                       |
| `augment_all_coaches`                         | POST | `/api/roster/augment-coaches/all`     | 3600s   | Full coach-augment run.                                                 |
| `wmt_sync_team(team_slug)`                    | POST | `/api/roster/wmt-sync`                | 300s    | Pull WMT roster for one team (photos, bios, HS, transfers).             |
| `wmt_sync_all`                                | POST | `/api/roster/wmt-sync/all`            | 3600s   | Full WMT sync.                                                          |
| `reconcile`                                   | POST | `/api/reconcile/schedule`             | 1800s   | Full schedule reconciliation (find cancelled games that were played).   |
| `reconcile_check`                             | POST | `/api/reconcile/schedule/check`       | 1800s   | Dry-run reconciliation — what would change, no writes.                  |
| `compute_d1_metrics`                          | POST | `/api/metrics/compute`                | 600s    | Trigger D1 metrics computation on the Java side.                        |
| `scrape_standings(season:)`                   | POST | `/api/standings/scrape`               | 1800s   | All conference standings for a season.                                  |
| `scrape_standings_division(season:, division:)` | POST | `/api/standings/scrape/division`    | 1800s   | Single division.                                                        |
| `scrape_standings_conference(...)`            | POST | `/api/standings/scrape/conference`    | 300s    | Single conference.                                                      |
| `find_or_create_game(attrs)`                  | POST | `/api/games/find-or-create`           | 15s     | **Game creation gate.** Ruby delegates all `Game` creation to Java so dedup logic lives in one place. Returns `{gameId, created, matchStrategy}`. |
| `find_or_create_games_batch(requests)`        | POST | `/api/games/find-or-create-batch`     | 120s    | Batched creation gate.                                                  |
| `reconcile_ncaa_dates`                        | POST | `/api/reconcile/ncaa-dates`           | 1800s   | Fetch NCAA season GraphQL, correct any mismatched `game_date` by `ncaa_contest_id`. |
| `reconcile_ncaa_dates_check`                  | POST | `/api/reconcile/ncaa-dates/check`     | 1800s   | Dry-run of the above.                                                   |
| `healthy?`                                    | GET  | `/api/scrape/health`                  | 5s      | Health probe. Returns `true` only if `{status: "ok"}`.                  |

Also used by `ScheduleRecoveryService` (not through this client):
`POST /api/team-schedule/sync-team` — see the matching-services doc.

### Caller map: jobs/controllers → endpoints

Pulled from `grep 'JavaScraperClient\.'` across the codebase.

| Caller                                                   | Endpoint(s)                                |
| -------------------------------------------------------- | ------------------------------------------ |
| `GamePipelineJob`                                        | `scrape_batch`                             |
| `Game#before-create` (`app/models/game.rb:157`)          | `find_or_create_game` (gate)               |
| `NcaaGameDiscoveryJob`                                   | `find_or_create_game` (gate; inlined in the job now that Ruby `NcaaScheduleService` is deleted) |
| `BoxScoreBackfillJob`                                    | `scrape_batch` (for missing box scores)    |
| `RefetchMissingPbpJob`                                   | `scrape_batch` (PBP refetch path)          |
| `ScheduleReconciliationJob`                              | `reconcile`                                |
| `NcaaDateReconciliationJob`                              | `reconcile_ncaa_dates`                     |
| `ComputeD1MetricsJob`                                    | `compute_d1_metrics`                       |
| `StandingsRefreshJob`                                    | `scrape_standings(season:)`                |
| `RosterAugmentAllJob`                                    | `augment_all`                              |
| `CoachAugmentAllJob`                                     | `augment_all_coaches`                      |
| `WmtSyncAllJob`                                          | `wmt_sync_all`                             |
| `GhostGameDetectionJob`                                  | Uses `available?` to decide `:unverifiable` vs. scraping. |
| `admin/jobs_controller.rb:164`                           | `healthy?` (admin dashboard)               |
| `lib/tasks/reparse_nuxt_pbp.rake`                        | `scrape_batch`                             |

---

## PredictServiceClient

**File:** `app/services/predict_service_client.rb` (91 LOC)

Thin HTTP client for the Python `riseballs-predict` service. Two things
to know:

1. Unlike `JavaScraperClient`, this client **raises on failure** —
   callers are expected to rescue `PredictServiceClient::Error` and
   surface a 503 to the frontend. The rationale is that predictions
   are synchronous user-facing requests; we want to fail loudly rather
   than silently return nil.
2. The main entry point (`bundle_for`) fans out to two endpoints in
   parallel via `Thread.new`, so combined latency is bounded by the
   slower endpoint, not the sum.

### Configuration

```ruby
DEFAULT_BASE_URL = "http://localhost:8080".freeze
DEFAULT_TIMEOUT = 5
```

Overridable via:

- `PREDICT_SERVICE_URL` — base URL, trailing slash stripped (line 39).
  On Dokku this points to the internal hostname for `riseballs-predict`.
- `PREDICT_SERVICE_TIMEOUT_SECONDS` — per-endpoint timeout in seconds,
  coerced via `.to_i` (line 40). Applies to every HTTP call.

Tests stub the public methods; HTTP is blocked at `test_helper` level
(comment on line 11).

### Error model

Three classes, all under `PredictServiceClient::Error`:

```ruby
class Error < StandardError; end
class TimeoutError < Error; end
class ServiceUnavailable < Error; end
```

- `TimeoutError` — `Net::OpenTimeout`, `Net::ReadTimeout`, any
  `HTTParty::Error` → wrapped and re-raised as `TimeoutError` with
  the underlying message.
- `ServiceUnavailable` — HTTP non-2xx → raised with `"predict service
  returned N"`.

Callers catch both via `rescue PredictServiceClient::TimeoutError,
PredictServiceClient::ServiceUnavailable` or, more broadly,
`PredictServiceClient::Error`.

### `predict_only`

Single-endpoint shortcut for the scoreboard, where only the win
probability + confidence band are needed.

```ruby
PredictServiceClient.predict_only(
  home_team_slug:, away_team_slug:, game_date:, division: nil
)
# → parsed response from POST /v1/matchups/predict
```

### `bundle_for` — parallel predict + keys

```ruby
PredictServiceClient.bundle_for(
  home_team_slug:, away_team_slug:, game_date:, division: nil
)
# → { prediction: ..., keys_to_victory: ... }
```

Implementation (lines 52-62):

```ruby
predict_thread = Thread.new { post_json("/v1/matchups/predict", payload) }
keys_thread    = Thread.new { post_json("/v1/matchups/keys-to-victory", payload) }

{
  prediction:      predict_thread.value,
  keys_to_victory: keys_thread.value
}
```

`Thread#value` propagates exceptions, so a `TimeoutError` in either
thread bubbles up as soon as the main thread calls `.value`. Net
latency ≈ `max(predict_latency, keys_latency) + overhead` rather than
the sum.

### Request payload shape

Both endpoints accept the same body (built by `build_payload`, lines
66-76):

```json
{
  "team_a_id": "<home_team_slug>",
  "team_b_id": "<away_team_slug>",
  "game_date": "YYYY-MM-DD",
  "context": {
    "home_team_id": "<home_team_slug>",
    "division": "d1"
  }
}
```

`context` uses `.compact` so `division: nil` is omitted rather than sent
as `"division": null`.

### Controller surface + 503 handling

`api/predictions_controller.rb`:

- Line 25: uses `PredictServiceClient.bundle_for` for the full matchup
  page.
- Lines 148, 197: uses `PredictServiceClient.predict_only` for
  scoreboard previews (list/batch paths).
- Lines 39, 160, 209: `rescue PredictServiceClient::TimeoutError,
  PredictServiceClient::ServiceUnavailable` (and broader `Error,
  StandardError` on the scoreboard paths) → return a 503 with a
  structured body like `{error: "prediction_unavailable", message: ...}`.

The scoreboard explicitly **does not block the page** on predict
failure: each game's prediction is fetched independently, and a 503
from predict for one game shows a "-" placeholder rather than breaking
the whole scoreboard.

---

## Deleted clients (2026-04-19)

The following classes were removed in mondok/riseballs#85 part 1 and
must not be reintroduced. If any live-score feature needs a new client
wrapper, it belongs in `riseballs-live` (via the browser), not in
Rails.

| Removed | File | Reason |
|---------|------|--------|
| `StatBroadcastService` | `app/services/stat_broadcast_service.rb` | All StatBroadcast live-stats machinery retired; overlay data now via `riseballs-live`. |
| `SidearmStatsService` | `app/services/sidearm_stats_service.rb` | Same. |
| `GameIdentityService` | `app/services/game_identity_service.rb` | Coordinated `sb_event_id` discovery; column dropped. |
| `EspnScoreboardService` | `app/services/espn_scoreboard_service.rb` | ESPN ingestion moved entirely to `riseballs-live` (Phase 8, mondok/riseballs#84). |

No `RiseballsLiveClient` exists on the Rails side. Adding one would
breach the "browser calls it directly" contract; don't propose it.
