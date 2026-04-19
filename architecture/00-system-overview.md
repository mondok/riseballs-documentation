# System Overview

Riseballs is four cooperating services: three share one Postgres database (Rails, Java scraper, Python predict) and a fourth stateless overlay (`riseballs-live`) is called directly by the browser.

```mermaid
flowchart LR
    User[Browser] -->|HTTPS| Rails
    User -->|HTTPS<br/>GET /scoreboard?date=| Live[riseballs-live<br/>Java 21 / Spring Boot<br/>stateless, no DB]
    Rails[riseballs<br/>Rails 8 + Sidekiq + React SPA] -->|HTTP /api/reconcile/*<br/>/api/roster/*| Scraper[riseballs-scraper<br/>Java 21 / Spring Boot]
    Rails -->|HTTP /v1/matchups/*| Predict[riseballs-predict<br/>Python 3.12 / FastAPI + XGBoost]
    Rails <-->|ActiveRecord / JPA<br/>same DB| DB[(Postgres<br/>riseballs_db)]
    Scraper <-->|JPA write path| DB
    Predict -->|read-only| DB
    Scraper -->|Jsoup / HttpClient| External[(Sidearm, WMT,<br/>NCAA, WordPress)]
    Live -->|NCAA D1+D2 GraphQL<br/>ESPN public scoreboard| ExternalLive[(NCAA sdataprod,<br/>ESPN site.api)]
    Rails -->|legacy, preferred path<br/>is Java scraper| External
```

---

## Why four services

| Concern | Why it's in this service |
|---------|--------------------------|
| **HTTP surface** | Rails — single Devise auth, single SPA mount, everything authoritative users hit |
| **Cron** | Rails (Sidekiq cron) — unified scheduling point (see [rails/14-schedule.md](../rails/14-schedule.md)) |
| **Heavy scraping + reconciliation** | Java (`riseballs-scraper`) — JVM concurrency (virtual threads + semaphores) handles 592 teams' schedule pages in one pass far more reliably than Ruby with Sidekiq workers; Jsoup is also the strongest HTML parser available |
| **Roster/coach augmentation** | Java (`riseballs-scraper`) — Sidearm bio pages, WordPress, WMT all hit from one service so URL discovery + parsing + update lives together |
| **Predictions** | Python (`riseballs-predict`) — XGBoost + isotonic calibration + scipy/numpy feature engineering is painful to replicate in Ruby; Python ecosystem is the natural fit |
| **Live-score overlay** | Java (`riseballs-live`, shipped 2026-04-19, [live/](../live/)) — stateless proxy that reconciles NCAA (D1+D2) + ESPN public feeds into a single scoreboard payload. No DB, no Redis, no internal hostnames. Browser calls it directly in parallel with Rails and merges client-side for the live-game overlay. |

Rails is the front door and the orchestrator. `riseballs-scraper` is a scraper that happens to have a JPA write path. `riseballs-predict` is a pure read-compute-respond service. `riseballs-live` is a read-only public proxy isolated from every other component (see [live/00-overview.md](../live/00-overview.md) for the charter).

---

## Shared state

Only three of the four services share the Postgres database (`riseballs_db` in prod, `riseballs_local` in dev): Rails, the Java scraper (`riseballs-scraper`), and Python predict. Only Rails and `riseballs-scraper` write; Python reads. `riseballs-live` has **no database access at all** — its container doesn't have a `DATABASE_URL`, doesn't have a `REDIS_URL`, and can't reach `riseballs-scraper.web` or the internal Rails hostname (see its charter in `riseballs-live/CLAUDE.md`).

**Writes are not symmetric.** See [architecture/01-service-boundaries.md](01-service-boundaries.md) for the detailed split, but the headline hazard:

> **Java writes bypass Ruby quality gates.** When `GameStatsWriter` inserts a `player_game_stat` row, no Rails callback fires. When the Java scraper stores PBP in `cached_games`, `CachedGame.pbp_quality_ok?` is not invoked. Quality validation is Ruby code; the Java path has to replicate it or skip it, and today it mostly skips it.

This is a known live hazard, not a bug to fix in one PR. It shapes how operators debug data issues — always check both write paths.

---

## Deployment shape

All four services run on a single self-hosted Dokku box (`ssh.edentechapps.com` / `ssh.mondokhealth.com`). One app per service:

| Dokku app | Git remote | Internal hostname | Public URL |
|-----------|-----------|------------------|-----------|
| `riseballs` | `dokku` (main branch) | `riseballs.web:3000` | `riseballs.com` (Cloudflare tunnel) |
| `riseballs-scraper` | `dokku` | `riseballs-scraper.web:8080` | internal only |
| `riseballs-predict` | `dokku` | `riseballs-predict.web:8080` | internal only |
| `riseballs-live` | `dokku` (`mondok/riseballs-live`) | `riseballs-live.web:8080` | `live.riseballs.com` (Cloudflare tunnel) |

Services reach each other by internal Dokku hostname. `dokku run` one-off containers **cannot** reach other Dokku apps (the internal network is only attached to `web`/`worker` containers) — that's why `dokku enter` is required for any rake task that calls Java. See [operations/database-access.md](../operations/database-access.md).

`riseballs-live` is the only other publicly-exposed service. It routes `live.riseballs.com` through a Cloudflare tunnel Published Application Route to `http://localhost:80` → container port 8080. CORS is hardcoded to the riseballs.com domains + localhost dev (see [live/03-deployment.md](../live/03-deployment.md)).

Cloudflare tunnel fronts the public sites (`edentechapps` / `mondokhealth` tunnel), handling SSL termination. No Let's Encrypt on Dokku.

---

## Request: anatomy of the scoreboard

The `/scoreboard` page is the most multi-service read path in the system. It pulls authoritative game data from Rails and merges a live overlay from `riseballs-live` on the client:

```mermaid
sequenceDiagram
    participant User as Browser
    participant Rails
    participant Live as riseballs-live
    participant DB as Postgres
    participant Ext as NCAA + ESPN

    par in parallel
        User->>Rails: GET /api/scoreboard?date=YYYY-MM-DD
        Rails->>DB: Game + team_games + team metadata
        Rails-->>User: games[] incl. gameID="rb_<id>",<br/>ncaaContestId, gameNumber
    and
        User->>Live: GET live.riseballs.com/scoreboard?date=
        Live->>Live: Caffeine cache: fresh 30s / stale 5m / neg 10s
        alt cache miss
            Live->>Ext: NCAA D1+D2 + ESPN in parallel<br/>12s joint timeout
            Ext-->>Live: raw feeds
            Live->>Live: SlugResolver + ScoreboardReconciler
        end
        Live-->>User: events[] incl. ncaaContestId, homeSlug, awaySlug,<br/>state, scores, currentInning
    end
    User->>User: lib/liveOverlay.js merges by<br/>ncaaContestId → (slug pair, gameNumber) → reversed
```

The merge rules are documented in [reference/matching-and-fallbacks.md](../reference/matching-and-fallbacks.md). The overlay only overrides scores/state on non-final games; finals always win from Rails.

## Request: anatomy of a game page

Tracing a user viewing a game page (`/games/:id`):

```mermaid
sequenceDiagram
    participant User
    participant Rails
    participant Scraper as Java scraper
    participant Predict
    participant DB as Postgres
    participant External as Sidearm/WMT

    User->>Rails: GET /games/:id (React SPA)
    Rails-->>User: HTML shell
    User->>Rails: GET /api/games/:id
    Rails->>DB: load Game + teams + snapshots
    Rails-->>User: game JSON

    par in parallel
        User->>Rails: GET /api/games/:id/boxscore
        Rails->>DB: CachedGame.fetch
        alt cache hit
            Rails-->>User: cached boxscore
        else cache miss
            Rails->>External: AthleticsBoxScoreService.fetch
            External-->>Rails: HTML
            Rails->>Rails: parse + quality gate
            Rails->>DB: CachedGame.store
            Rails-->>User: boxscore JSON
        end
    and
        User->>Rails: GET /api/games/:id/play_by_play
        Note over Rails: Same cache-first waterfall<br/>(see pipelines/02-pbp-pipeline.md)
        Rails-->>User: PBP JSON
    and
        User->>Rails: GET /api/games/:id/prediction
        alt played game
            Rails-->>User: 204 No Content
        else upcoming
            Rails->>Predict: /v1/matchups/predict + keys-to-victory (parallel)
            Predict->>DB: read features
            Predict-->>Rails: prediction + keys
            Rails-->>User: combined JSON
        end
    end
```

The scraper is not on the read path — Rails serves everything the browser sees. Rails calls the scraper for reconciliation and roster augmentation from background jobs, not request threads.

---

## Write: anatomy of a game result

Tracing new game data from "team just finished playing" to "it shows on scoreboard":

```mermaid
sequenceDiagram
    participant Cron as Sidekiq cron
    participant Rails
    participant Scraper as Java scraper
    participant DB as Postgres
    participant External as Sidearm/WMT

    Cron->>Rails: GamePipelineJob (every 15 min)
    Rails->>Scraper: POST /api/team-schedule/sync-all<br/>(3 AM full; per-team otherwise)
    Scraper->>External: fetch 592 team schedule pages
    External-->>Scraper: HTML
    Scraper->>Scraper: TeamScheduleSyncService<br/>normalize opponent + game_number<br/>snapshot game_id links
    Scraper->>DB: upsert team_games<br/>restore game_id links

    Rails->>Rails: TeamGameMatcher.match_scheduled<br/>(create shell Games)
    Rails->>Rails: TeamGameMatcher.match_all<br/>(update shells with scores)

    Rails->>Rails: BoxScoreBackfillJob<br/>(for games just gone final)
    Rails->>External: AthleticsBoxScoreService.fetch
    External-->>Rails: boxscore HTML
    Rails->>Rails: parse + quality gate
    Rails->>DB: CachedGame.store + PlayerGameStat upsert

    Rails->>Rails: Game after_update_commit<br/>(state flipped to final)
    Rails->>Rails: PbpOnFinalJob enqueued
    Rails->>External: athletics PBP fetch (retries w/ polynomial backoff)
    External-->>Rails: PBP HTML/JSON
    Rails->>Rails: PBP quality gate
    Rails->>DB: CachedGame.store (athl_play_by_play)
```

Every 15 minutes the pipeline re-runs. Daily at ~3 AM the reconciliation jobs go through all 592 schedules in depth (see [pipelines/06-reconciliation-pipeline.md](../pipelines/06-reconciliation-pipeline.md)).

---

## Where to go next

- [architecture/01-service-boundaries.md](01-service-boundaries.md) — the "who writes what" table in detail
- [architecture/02-data-flow.md](02-data-flow.md) — full end-to-end journey of a game record, cradle to screen
- [live/](../live/) — the stateless `riseballs-live` overlay service
- [pipelines/](../pipelines/) — one doc per major pipeline
- [reference/glossary.md](../reference/glossary.md) — vocabulary (Shell, Locked, quality gate, etc.)
