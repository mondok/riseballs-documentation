# Riseballs — System Documentation

End-to-end reference for the Riseballs platform: a college baseball stats, standings, and prediction site. Three cooperating services share one Postgres database.

This documentation is a **knowledge graph**: every subsystem file cross-links to the pipelines it participates in and the references it depends on. Use the index below to enter at any angle.

---

## Services (the three apps)

| App | Lang / stack | Role | Docs |
|-----|--------------|------|------|
| `riseballs` | Rails 8 + Sidekiq + React (in-repo SPA) | API, web, cron, all write paths via ActiveJob | [rails/](rails/) |
| `riseballs-scraper` | Java 21 / Spring Boot 3.4 | Heavy scraping, reconciliation, roster/coach augment, writes directly to Postgres via JPA | [scraper/](scraper/) |
| `riseballs-predict` | Python 3.12 / FastAPI + XGBoost | Win-probability, expected-runs, keys-to-victory, scenario explanations | [predict/](predict/) |

Rails is the orchestrator. It owns cron (Sidekiq cron), owns the HTTP surface, and delegates heavy scraping/reconciliation to the Java scraper over the internal Dokku network (`http://riseballs-scraper.web:8080`). It calls the Python predict service over HTTP for live predictions (`PREDICT_SERVICE_URL`).

See [architecture/00-system-overview.md](architecture/00-system-overview.md) for the big picture and [architecture/01-service-boundaries.md](architecture/01-service-boundaries.md) for the "who owns what" split.

---

## Documentation layout

### [architecture/](architecture/) — the big picture

- [00-system-overview.md](architecture/00-system-overview.md) — three services, shared DB, request diagram
- [01-service-boundaries.md](architecture/01-service-boundaries.md) — who owns what writes, what reads
- [02-data-flow.md](architecture/02-data-flow.md) — end-to-end journey of a game record from scrape to screen

### [rails/](rails/) — the Rails app (riseballs)

- [01-models.md](rails/01-models.md) — every ActiveRecord model, associations, callbacks
- [02-database-schema.md](rails/02-database-schema.md) — table-by-table reference with indexes and FKs
- [03-entity-relationships.md](rails/03-entity-relationships.md) — Mermaid ER diagram with narrative
- [04-api-endpoints.md](rails/04-api-endpoints.md) — every controller action, params, response
- [05-routes.md](rails/05-routes.md) — flat routes table
- [06-ingestion-services.md](rails/06-ingestion-services.md) — Athletics/WMT/Cloudflare/AI/NCAA box score + schedule services
- [07-parsers.md](rails/07-parsers.md) — box score and PBP parser internals
- [08-matching-services.md](rails/08-matching-services.md) — `TeamGameMatcher`, shell link preservation, doubleheader logic
- [09-analytics-services.md](rails/09-analytics-services.md) — `GameStatsExtractor`, `PlayerStatsCalculator`, `WarCalculator`, `RpiService`
- [10-scenario-service.md](rails/10-scenario-service.md) — `ConferenceScenarioService` clinch/elimination math + bracket builder
- [11-external-clients.md](rails/11-external-clients.md) — `JavaScraperClient`, `PredictServiceClient`
- [12-jobs.md](rails/12-jobs.md) — every ActiveJob with trigger, schedule, side effects
- [13-rake-tasks.md](rails/13-rake-tasks.md) — every rake task grouped by purpose
- [14-schedule.md](rails/14-schedule.md) — consolidated cron table + trigger chains
- [15-frontend-overview.md](rails/15-frontend-overview.md) — React stack, routing, API wrapper
- [16-frontend-pages.md](rails/16-frontend-pages.md) — every React page
- [17-frontend-components.md](rails/17-frontend-components.md) — reusable components

### [scraper/](scraper/) — the Java scraper (riseballs-scraper)

- [00-overview.md](scraper/00-overview.md) — stack, deployment, "bypasses Ruby quality gates" hazard
- [01-controllers.md](scraper/01-controllers.md) — every REST controller
- [02-services.md](scraper/02-services.md) — `ScrapeOrchestrator`, `TeamScheduleSyncService`, `StandingsOrchestrator`, roster services
- [03-parsers.md](scraper/03-parsers.md) — box score / schedule parsers + `OpponentResolver` full decision tree
- [04-reconciliation.md](scraper/04-reconciliation.md) — schedule, WMT cancelled, NCAA date reconciliation flows
- [05-repositories-and-data.md](scraper/05-repositories-and-data.md) — JPA repositories and "who writes what"
- [06-scheduled-jobs.md](scraper/06-scheduled-jobs.md) — concurrency model (virtual threads + semaphore)
- [07-config-and-deployment.md](scraper/07-config-and-deployment.md) — `application.yml`, Dockerfile, Dokku

### [predict/](predict/) — the Python predict service (riseballs-predict)

- [00-overview.md](predict/00-overview.md) — FastAPI + XGBoost stack
- [01-endpoints.md](predict/01-endpoints.md) — every route with request/response schemas
- [02-feature-engineering.md](predict/02-feature-engineering.md) — 5 feature builders, 168+15 features
- [03-ml-and-artifacts.md](predict/03-ml-and-artifacts.md) — XGBoost hyperparams, isotonic calibration, versioning
- [04-explain-engine.md](predict/04-explain-engine.md) — keys-to-victory + scenario analysis + why engine
- [05-observability.md](predict/05-observability.md) — logging, metrics, TTL cache
- [06-schemas.md](predict/06-schemas.md) — pydantic models
- [07-config-and-deployment.md](predict/07-config-and-deployment.md) — settings, Dockerfile, Dokku

### [pipelines/](pipelines/) — end-to-end flows

Pipelines are the horizontal view. Each one traces a user-visible feature (or data promise) across all three services.

- [01-game-pipeline.md](pipelines/01-game-pipeline.md) — `GamePipelineJob` (every 15 min): sync, match, backfill, cleanup
- [02-pbp-pipeline.md](pipelines/02-pbp-pipeline.md) — PBP proactive + lazy + reparse paths
- [03-boxscore-pipeline.md](pipelines/03-boxscore-pipeline.md) — box score fetch fallback chain + discovery gate
- [04-standings-pipeline.md](pipelines/04-standings-pipeline.md) — Java scrape → ConferenceStanding → scenarios → bracket
- [05-roster-pipeline.md](pipelines/05-roster-pipeline.md) — WMT vs Sidearm bio vs WordPress; profile URL discovery
- [06-reconciliation-pipeline.md](pipelines/06-reconciliation-pipeline.md) — schedule + NCAA date + dedup
- [07-prediction-pipeline.md](pipelines/07-prediction-pipeline.md) — GameDetail → PredictServiceClient → feature builders → model → JSON

### [reference/](reference/) — cross-cutting reference

- [matching-and-fallbacks.md](reference/matching-and-fallbacks.md) — every fallback chain in one table
- [slug-and-alias-resolution.md](reference/slug-and-alias-resolution.md) — Rails `TeamMatcher` + Java `OpponentResolver` side by side
- [conference-tournaments.md](reference/conference-tournaments.md) — format and seeding per conference
- [glossary.md](reference/glossary.md) — the terms (Shell, Locked, Quality gate, team_games vs Game, …)

### [operations/](operations/) — run the system

- [deployment.md](operations/deployment.md) — Dokku remotes, deploy commands, restart behavior
- [database-access.md](operations/database-access.md) — tunnels, `dokku enter` vs `dokku run`
- [runbook.md](operations/runbook.md) — common operator tasks ("PBP missing", "score wrong", "game duplicated")

### [reviews/](reviews/) — audit trail of what was fixed

Three review agents (coverage, accuracy, navigability) audited the docs after initial generation. Their reports + the fix summary are preserved for traceability.

- [00-summary.md](reviews/00-summary.md) — what was found and what was fixed
- [01-coverage-gaps.md](reviews/01-coverage-gaps.md) — gap analysis
- [02-accuracy-spot-check.md](reviews/02-accuracy-spot-check.md) — source spot-check
- [03-knowledge-graph.md](reviews/03-knowledge-graph.md) — navigability review

---

## Reading paths

**"I'm new, what's the system do?"**
→ [architecture/00-system-overview.md](architecture/00-system-overview.md) → [architecture/02-data-flow.md](architecture/02-data-flow.md) → [reference/glossary.md](reference/glossary.md)

**"How does `/api/games/:id/play_by_play` actually work?"**
→ [rails/04-api-endpoints.md](rails/04-api-endpoints.md) (controller action) → [pipelines/02-pbp-pipeline.md](pipelines/02-pbp-pipeline.md) (full flow) → [rails/07-parsers.md](rails/07-parsers.md) (parser internals)

**"Why did this game get duplicated?"**
→ [pipelines/06-reconciliation-pipeline.md](pipelines/06-reconciliation-pipeline.md) → [rails/08-matching-services.md](rails/08-matching-services.md) → [operations/runbook.md](operations/runbook.md)

**"What runs at 3 AM?"**
→ [rails/14-schedule.md](rails/14-schedule.md) → [rails/12-jobs.md](rails/12-jobs.md)

**"How do I add a new conference to standings?"**
→ [pipelines/04-standings-pipeline.md](pipelines/04-standings-pipeline.md) → [scraper/03-parsers.md](scraper/03-parsers.md) (`OpponentResolver`) → [rails/10-scenario-service.md](rails/10-scenario-service.md)

**"I need to change a prediction feature."**
→ [pipelines/07-prediction-pipeline.md](pipelines/07-prediction-pipeline.md) → [predict/02-feature-engineering.md](predict/02-feature-engineering.md) → [predict/03-ml-and-artifacts.md](predict/03-ml-and-artifacts.md)

**"Something is broken in production."**
→ [operations/runbook.md](operations/runbook.md) → [operations/database-access.md](operations/database-access.md)

---

## Documentation conventions

- File paths are absolute within each repo (`app/services/team_game_matcher.rb:42`). The `:line` suffix points at the method or constant referenced.
- Mermaid diagrams are embedded as code fences; GitHub renders them natively.
- Every "known hazard" or "gotcha" is called out inline with **bold** near the relevant component, not buried in a separate file.
- "Legacy / fallback only" tags mean the component still exists but is not the primary path (e.g., Cloudflare Playwright services — the Java scraper is primary).

---

## Scope disclaimers

- This tree snapshots the system as of ~2026-04-18. Fast-moving areas: PBP repair paths, NCAA date reconciliation, matcher stabilization (GH issues #44–#48).
- The project's `how_things_work.md` files (in `riseballs/`, `riseballs-predict/`, and `riseballs-parent/`) are the living logs — they are narrative and sometimes ahead of this tree. When they conflict with this documentation, those are authoritative for recent changes and this tree is authoritative for the architectural shape.
- Anything tagged **DEPRECATED** is still in the codebase but should not be used going forward (e.g., `AiWebSearchBoxScoreService`, `AiExtractionFetcher`).
