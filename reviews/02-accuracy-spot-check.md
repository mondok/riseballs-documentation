# Accuracy Spot-Check

## Method

I spot-checked ~30 non-trivial claims across the documentation, targeting claims that would materially mislead a reader or lead to a bad fix. Verification sources:

- `riseballs/config/initializers/sidekiq.rb` for cron expressions
- `riseballs/config/routes.rb` for Rails routes
- `riseballs/app/models/game.rb`, `cached_game.rb` for model claims
- `riseballs/app/controllers/api/*.rb`, `admin/*.rb` for endpoints and line ranges
- `riseballs/app/jobs/*.rb` for job retry/trigger behavior
- `riseballs/app/services/boxscore_fetch_service.rb` for fallback chains
- Java controllers under `riseballs-scraper/src/main/java/com/riseballs/scraper/**/*Controller.java`
- `riseballs-scraper/src/main/java/com/riseballs/scraper/reconciliation/schedule/OpponentResolver.java`
- `riseballs-predict/app/api/routers/*.py` and `riseballs-predict/app/observability/cache.py`
- `riseballs/db/schema.rb` for constraint verification

## Verified claims

- All 12 cron expressions in `rails/14-schedule.md` match `config/initializers/sidekiq.rb` exactly (cron string, class name, and the one `active_job: false` entry for `StuckScheduleRecoveryJob`).
- `PbpOnFinalJob`: `retry_on PbpNotReadyError, wait: :polynomially_longer, attempts: 5` — verified at `pbp_on_final_job.rb:6`.
- `Game#enqueue_pbp_refresh_if_finalized` at `game.rb:241-244`, with `after_update_commit` at `game.rb:17` — matches.
- `Admin::JobsController` `ALLOWED_EMAIL = "matt.mondok@gmail.com"` hard-coded at `admin/jobs_controller.rb:3`.
- `Admin::JobsController::JOBS` has 17 entries across 4 categories (`pipeline`, `java_scraper`, `rankings`, `data_quality`) — verified.
- `LiveGameSyncJob` / `TeamScheduleSyncJob` classes do not exist as declared classes in the codebase (grep returns no `class LiveGameSyncJob` / `class TeamScheduleSyncJob`), matching the doc's "will error if clicked" warning.
- `GameDedupJob` uses Ruby-computed cutoff: `Date.current - LOOKBACK_DAYS.days` with `LOOKBACK_DAYS = 14` — verified at `game_dedup_job.rb:7,21`.
- `GamePipelineJob#full_sync?` is `now.hour == 3 && now.min < 15` — verified at `game_pipeline_job.rb:43-46`.
- `GamePipelineJob` full sync HTTP timeout = 900 seconds — verified at `game_pipeline_job.rb:53`.
- `ScheduleReconciliationJob` triggers `BoxScoreBackfillJob.perform_later` only when `created + uncancelled + date_corrected + score_corrected + finalized > 0` — verified at `schedule_reconciliation_job.rb:42-45`.
- All Rails route paths in `rails/04-api-endpoints.md` (`/api/games/:id`, `/api/games/batch`, `/api/games/:id/boxscore`, `/api/games/:id/play_by_play`, `/api/games/:id/team_stats`, `/api/games/:id/prediction`, `/api/scoreboard/predictions`, `/api/standings`, `/api/rpi`, `/api/stats`, `/api/live_stats/*`, `/admin/jobs`, `/admin/recalculate_rpi`) exist in `routes.rb`.
- Java scraper base paths: `/api/scrape`, `/api/reconcile`, `/api/reconcile/schedule`, `/api/reconcile/ncaa-dates`, `/api/roster`, `/api/games`, `/api/schedule`, `/api/team-schedule`, `/api/standings`, `/api/metrics` — all verified.
- Scraper batch caps: `/api/scrape/boxscores` caps at 500, `/api/scrape/pbp/batch` caps at 500 — verified at `ScrapeController.java:72,125`.
- `TeamScheduleSyncController` uses `Semaphore(MAX_CONCURRENT=5)` and `Thread.sleep(500)` — verified at lines 26,49,57.
- `ScheduleReconciliationOrchestrator` uses `Semaphore(5)` and 500ms rate limit — verified at lines 44,45,92.
- `StandingsController` default season=2026 and division=d1 — verified at `StandingsController.java:28,38,47,48`.
- `NcaaDateReconciliationResult` shape `(dateCorrected, duplicatesRemoved, ncaaWrong, flaggedForReview, skipped, noChange, errors, dryRun, elapsedMs)` matches the record at lines 3-13.
- `CachedGameRepository` extends `JpaRepository<CachedGame, Long>` — confirms the "bypasses Ruby quality gate" hazard.
- `CachedGame.pbp_quality_ok?` thresholds (single-period >20 plays, `periods[0...-1]` same-team detection, >50% garbage plays) — verified in `cached_game.rb:165-216`.
- Decision regex `\(([WLS])[,)]/i` — verified in `athletics_box_score_service.rb:454`, `stat_broadcast_service.rb:368`, `sidearm_parser.rb:124`, `presto_sports_parser.rb:115`.
- `db/schema.rb` `idx_team_games_schedule` is UNIQUE on `(team_slug, game_date, opponent_slug, game_number)` — verified at schema.rb:513.
- `db/schema.rb` `idx_games_natural_key` is UNIQUE on `(game_date, home_team_slug, away_team_slug, game_number)` — verified at schema.rb:235.
- `team_games.game_id` FK has no `on_delete:` cascade (default RESTRICT) — verified at schema.rb:585.
- Box score discovery gate logic at `games_controller.rb:112-120` — verified: rejects when `@game_record.scheduled?` and linescore R row has `home + visit > 0`.
- Score-match gate at `games_controller.rb:121-133` — verified.
- Negative-cache write `Rails.cache.write("pbp_miss:#{gid}", true, expires_in: 5.minutes)` — verified at `games_controller.rb:191`.
- Java has zero `@Scheduled` annotations — grep returned no matches, confirming "all cron lives in Rails" claim.
- Predict TTL cache `TTLCache(ttl_seconds=300.0, max_entries=512)` — verified at `main.py:77` and `observability/cache.py:16-17`.
- Predict cache key scopes on `model_version` — verified at `routers/predictions.py:22-25`.
- Predict `/v1/health`, `/v1/ready`, `/v1/matchups/predict`, `/v1/matchups/keys-to-victory`, `/v1/matchups/scenarios`, `/v1/games/explain-loss`, `/v1/models/current`, `/v1/metrics` all exist with the prefixes claimed (health: no prefix, predictions: `/matchups`, scenarios: `/matchups`, explanations: `/games`, models: `/models`).
- `SCENARIOS` tuple in `explain/scenario_analysis.py:137-180` contains exactly 7 entries, so 14 scenarios (7 × 2 teams) is correct.
- `_confidence_band` at `services/prediction_service.py:122-127` matches documented thresholds (low < 10, medium < 20 or decisiveness < 0.05, else high).
- OpponentResolver resolution order (alias → slug → parenthetical strip → name match → suffix strip → state abbreviation) matches the code at `OpponentResolver.java:108-207`.
- `GameCreationService` match order (1. ncaa_contest_id, 2. date + sorted teams + game_number, 3. date + sorted teams) — verified at `GameCreationService.java:23-24, 94, 106, 119`.

## Factual errors

### Error 1: Box score fallback chain is wrong

- **Doc:** `reference/matching-and-fallbacks.md` lines 7-23; `pipelines/03-boxscore-pipeline.md` lines 9-32 (mermaid) and lines 303; `reference/matching-and-fallbacks.md` line 303 (summary table).
- **Claim:** The documented chain is `athletics (Sidearm HTML) -> WMT -> Cloudflare Playwright -> AI LLM extraction -> nil`. The pipeline diagram tries `AthleticsBoxScoreService` first, then falls back to `WmtBoxScoreService`, `CloudflareBoxScoreService`, `AiBoxScoreService`. The summary table lists `Box score | Athletics | WMT | Cloudflare (legacy) | AI LLM`.
- **Reality:** `BoxscoreFetchService.fetch` tries fetchers in this order: **(1) WMT API, (2) local scraper, (3) Playwright HTML, (4) plain HTTP, (5) rediscovery, (6) AI extraction**. WMT is first, not Athletics. There is no separate "Athletics" first step — Sidearm HTML is fetched via local-scraper / Playwright / plain-HTTP on existing `GameTeamLink.box_score_url` rows. `CloudflareBoxScoreService` is only called from inside `try_ai_extraction`, not as a standalone Playwright step.
- **Source:** `riseballs/app/services/boxscore_fetch_service.rb:5-54` (the `fetch` method showing the 1-6 ordering), and lines 391-395 where `CloudflareBoxScoreService.fetch` appears inside `try_ai_extraction`.
- **Severity:** critical — the reader will assume the primary source is Athletics and miss that WMT is tried first and that two Sidearm-HTML fetch variants (local scraper, Playwright HTML) precede plain HTTP.

### Error 2: `SidearmHelper#sidearm_find_all_box_score_urls` does not exist

- **Doc:** `pipelines/03-boxscore-pipeline.md` line 44.
- **Claim:** "`AthleticsBoxScoreService`... Uses `SidearmHelper#sidearm_find_all_box_score_urls` with `TeamAlias` integration."
- **Reality:** `grep -rn "sidearm_find_all_box_score_urls" riseballs/app` returns no results. The helper method does not exist in the codebase under that name.
- **Source:** `Grep` for `sidearm_find_all_box_score_urls` in `riseballs/app` — zero hits.
- **Severity:** medium — misleads a reader looking for URL-discovery internals; the real discovery code is inline in `BoxscoreFetchService#discover_urls` / `BoxscoreUrlDiscoveryService` (and probably SidearmHelper has a different method name).

### Error 3: System overview sequence diagram labels team-schedule sync as `/api/scrape`

- **Doc:** `architecture/00-system-overview.md` line 126 (mermaid sequence in "Write: anatomy of a game result").
- **Claim:** `Rails->>Scraper: POST /api/scrape (team schedules)`.
- **Reality:** `GamePipelineJob` posts to `/api/team-schedule/sync-all`, not `/api/scrape`. `/api/scrape` is for box scores and PBP. See `game_pipeline_job.rb:51` and `TeamScheduleSyncController.java:22,37`.
- **Source:** `riseballs/app/jobs/game_pipeline_job.rb:51` (posts to `${base}/api/team-schedule/sync-all`); `riseballs-scraper/.../TeamScheduleSyncController.java:22`.
- **Severity:** medium — would send a new engineer to the wrong controller in Java.

### Error 4: Wrong cross-reference path for PBP pipeline

- **Doc:** `rails/01-models.md` line 122 (Game model callbacks section).
- **Claim:** "see `pipelines/04-pbp-pipeline.md`".
- **Reality:** The PBP pipeline file is `pipelines/02-pbp-pipeline.md`. `pipelines/04-*.md` is the standings pipeline.
- **Source:** `riseballs-documentation/pipelines/02-pbp-pipeline.md` exists; `pipelines/04-standings-pipeline.md` is the 04 file.
- **Severity:** minor — broken internal link.

### Error 5: `current_user_optional` file path uses `apps/` instead of `app/`

- **Doc:** `rails/04-api-endpoints.md` line 41.
- **Claim:** "`apps/controllers/api/base_controller.rb:7-15`".
- **Reality:** The path is `app/controllers/api/base_controller.rb:7-15`. Rails uses `app/`, not `apps/`.
- **Source:** `riseballs/app/controllers/api/base_controller.rb:7-15` exists; there is no `apps/` directory.
- **Severity:** minor — would trip up an IDE jump-to-file shortcut.

### Error 6: `Admin::BoxscoresController#update_url` mischaracterized

- **Doc:** `rails/04-api-endpoints.md` lines 658-667.
- **Claim:** "Find-or-initialize a `GameTeamLink` for the home team, set `box_score_url`, save."
- **Reality:** The controller first tries `game.game_team_links.find { |l| l.box_score_url.present? }` (any existing URL-bearing link across either team) and only falls back to `find_or_initialize_by(team_slug: game.home_team_slug)` if none is found. So for an away-team link that already has a URL, the update hits that away-team row, not home.
- **Source:** `riseballs/app/controllers/admin/boxscores_controller.rb:35-38`.
- **Severity:** medium — a reader debugging why an update touched the away team's row would not predict this from the docs.

### Error 7: Boxscore pipeline omits rediscovery step

- **Doc:** `pipelines/03-boxscore-pipeline.md` mermaid diagram lines 9-32 and summary table line 303.
- **Claim:** The chain goes Athletics -> WMT -> Cloudflare -> AI.
- **Reality:** Between the Sidearm fetch variants and AI, `BoxscoreFetchService.fetch` runs `try_rediscovery(game, seo_slugs)` (step 5) via `BoxscoreUrlDiscoveryService.discover_all_candidates` before falling back to AI. This is a significant behavioral step omitted from the diagram.
- **Source:** `riseballs/app/services/boxscore_fetch_service.rb:44-47`, `412-457`.
- **Severity:** medium — changing URL discovery without knowing about this fallback risks breaking recovery for games with wrong cached URLs.

### Error 8: PBP pipeline mermaid "on-demand" path shows WMT gated only on athletics failure

- **Doc:** `pipelines/02-pbp-pipeline.md` Path B mermaid lines 103-117.
- **Claim:** Diagram shows WMT tried only after `AthlGate` fails (PBP quality gate).
- **Reality:** The controller at `games_controller.rb:181` tries WMT when `!best_pbp || !CachedGame.send(:pbp_quality_ok?, best_pbp)` AND a `game_record` exists. The `game_record` guard is not represented in the diagram — if we only have `gid` (no Game row), the WMT fallback is skipped. Furthermore, before the athletics attempt can even happen, `seo_slugs` must be derivable from a cached athl_boxscore; a game with no cached boxscore and no `seo_names` in `teams` will skip athletics entirely and go straight to WMT (if `game_record` exists). The diagram oversimplifies both gates.
- **Source:** `riseballs/app/controllers/api/games_controller.rb:173-184`.
- **Severity:** medium — the doc reader may expect WMT to fire for games lacking a Game row; it doesn't.

### Error 9: `rails/04-api-endpoints.md` wrongly counts `PER_PAGE = 25` as the only pagination for `/api/stats`

- **Doc:** `rails/04-api-endpoints.md` line 442.
- **Claim:** `Pagination: PER_PAGE = 25`.
- **Reality:** `Api::StatsController` has `PER_PAGE = 25` but `per_page` is also derived from `params[:per_page]` (capped at `PER_PAGE` by `.clamp`). Actually — let me leave this one, it's defensible. *Retracting* — the doc says `PER_PAGE = 25` which is the constant. It is accurate as written.
- **Source:** (withdrawn)
- **Severity:** n/a (not flagged).

### Error 10: `rails/04-api-endpoints.md` endpoint for `Api::RpiController` describes default `d2` but this is flagged as only "notable difference"

- **Doc:** `rails/04-api-endpoints.md` line 420.
- **Claim:** "`division` (default `"d2"` — note: DIFFERENT default than most other endpoints)".
- **Reality:** Confirmed at `rpi_controller.rb:3` — `(params[:division] || "d2").downcase`. Doc is accurate.
- **Source:** n/a — retracting.
- **Severity:** n/a (not flagged; this checked out).

### Error 11: Admin::JobsController docs list "TeamScheduleSyncJob" and "LiveGameSyncJob" as "legacy labels" but admin UI description also claims they exist

- **Doc:** `rails/14-schedule.md` line 130 correctly warns they do not exist. But `rails/04-api-endpoints.md` line 641 lists them in the "Notable job classes" list alongside real jobs, without warning.
- **Claim:** "Notable job classes: `TeamScheduleSyncJob`, `LiveGameSyncJob`, `BoxScoreBackfillJob`, ..."
- **Reality:** `TeamScheduleSyncJob` and `LiveGameSyncJob` classes do not exist (`grep -rn "class LiveGameSyncJob" app` returns no match; same for `TeamScheduleSyncJob`). The `enqueue` action will raise `NameError: uninitialized constant TeamScheduleSyncJob` on click.
- **Source:** `riseballs/app/jobs/` directory listing shows no such files; the schedule doc (`rails/14-schedule.md:130`) documents this as a known issue.
- **Severity:** medium — the endpoints doc lists them as normal entries with no warning, contradicting the schedule doc's warning.

## Summary

- **~31 non-trivial claims verified**; **7 factual errors found** (Errors 1, 2, 3, 4, 5, 6, 7, 8, 11 above; Errors 9 and 10 were retracted during verification).
- Corrected count of actual errors: **9 findings flagged**.
- **Severity breakdown:**
  - Critical: 1 (Error 1 — wrong boxscore fallback order, the primary reference chart for operators debugging box score issues)
  - Medium: 6 (Errors 2, 3, 6, 7, 8, 11)
  - Minor: 2 (Errors 4, 5)
- **Most impactful to fix:** Error 1 (boxscore fallback) and Error 7 (rediscovery step missing) — together they misrepresent the core box score flow. Both rooted in `reference/matching-and-fallbacks.md` and `pipelines/03-boxscore-pipeline.md`; worth a single pass across both files.
- **Everything else checked (cron expressions, line ranges, job retry configs, route paths, schema indexes, predict cache config, quality gate thresholds, scraper endpoint shapes) passed verification.**
