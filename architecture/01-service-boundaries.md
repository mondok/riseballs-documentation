# Service Boundaries

Who owns what. This doc answers the question "if I want to change X, which service do I edit?"

---

## Write authority matrix

Which service writes to each table:

| Table | Rails | Java scraper | Predict | riseballs-live |
|-------|:-----:|:------------:|:-------:|:-------------:|
| `users`, `follows`, `player_favorites` | ✅ | — | — | — |
| `teams`, `team_aliases` | ✅ (migrations, admin) | ✅ (name/long_name updates) | — | — |
| `players` | ✅ (legacy `RosterService`) | ✅ (primary — `RosterAugmentService`, `WmtRosterService`) | — | — |
| `coaches` | — | ✅ (primary — `CoachAugmentService`) | — | — |
| `games` | ✅ (`TeamGameMatcher`, `GameDedupJob`, `ScoreValidationJob`) | ✅ (`GameCreationService`, reconciliation) | — | — |
| `team_games` | ✅ (matcher updates) | ✅ (primary — `TeamScheduleSyncService`) | — | — |
| `game_team_links` | ✅ (matcher) | ✅ (reconciliation) | — | — |
| `player_game_stats` | ✅ (`GameStatsExtractor`) | ✅ (`GameStatsWriter`) | — | — |
| `plate_appearances`, `pitch_events` | ✅ (`PitchByPitchParser`) | ✅ (`PbpOrchestrator`) | — | — |
| `cached_games` | ✅ (primary — `CachedGame.store` with quality gate) | ✅ (bypass — **no Ruby callbacks fire**) | — | — |
| `cached_schedules`, `cached_api_responses` | ✅ | ✅ | — | — |
| `scraped_pages` | ✅ | ✅ | — | — |
| `conference_sources` | ✅ (rake seed) | — | — | — |
| `conference_standings` | — | ✅ (primary — `StandingsOrchestrator`) | — | — |
| `standings_scrape_logs` | — | ✅ | — | — |
| `game_reviews` | ✅ (`ScoreValidationJob`, admin) | ✅ (reconciliation review flags) | — | — |
| `game_snapshots` | ✅ | — | — | — |
| `player_war_values`, `team_pitching_stats`, `site_metrics` | ✅ (`CalculateRpiJob`, `ComputeD1MetricsJob`) | — | — | — |

Predict never writes. It reads `teams`, `games`, `player_game_stats`, `plate_appearances`, `pitch_events` for feature engineering (see [predict/02-feature-engineering.md](../predict/02-feature-engineering.md)).

`riseballs-live` never reads or writes the DB. It has no `DATABASE_URL` in its container, no JDBC driver, no knowledge of the `teams` or `games` tables. Its slug resolution is driven by two classpath resources baked into the JAR at build time: a `espn_slug_overrides.json` file (163 entries ported from the Ruby `ESPN_SLUG_OVERRIDES` plus three reviewer-added entries — Florida Atlantic, Sam Houston, San Jose State accent) and a `known_slugs.txt` file (594 known D1/D2 slugs). See [live/02-architecture.md](../live/02-architecture.md) "SlugResolver" for the duplication tradeoff.

---

## Read authority: who serves what

Rails is the **authoritative** user-facing service. Every read a browser makes for persisted state goes through a Rails controller. Rails sometimes fans out to Predict for live prediction, and to the Java scraper for admin-triggered scrape actions, but the browser never talks to `riseballs-scraper` or Predict directly.

The **browser does call `riseballs-live`** directly — it's the only sibling that is publicly routable and hit from the SPA. The SPA fetches `live.riseballs.com/scoreboard?date=...` in parallel with `/api/scoreboard` and merges client-side. See `app/javascript/lib/liveOverlay.js` and [reference/matching-and-fallbacks.md](../reference/matching-and-fallbacks.md) (overlay match ladder) for the merge rules; [live/02-architecture.md](../live/02-architecture.md) covers the server side.

| Frontend URL | Backend route | Served by |
|--------------|---------------|-----------|
| `/games/:id` | `/api/games/:id` | Rails |
| `/games/:id` (prediction panel) | `/api/games/:id/prediction` | Rails → Predict |
| `/teams/:slug` | `/api/teams/:slug` | Rails |
| `/standings` | `/api/standings` | Rails |
| `/scoreboard` | `/api/scoreboard` **and** `live.riseballs.com/scoreboard` (parallel) | Rails + `riseballs-live` — merged in the client |
| `/admin/jobs` → "run X" | `/admin/jobs/enqueue` | Rails (enqueues Sidekiq job) |
| `/admin/reviews` | `/admin/reviews` | Rails |

The `/live` SPA page, `/api/live_stats/*` endpoints, StatBroadcast poller, and "Add to Live View" button are **all deleted as of 2026-04-19 (mondok/riseballs#85)**. The live-game overlay work moved entirely to the stateless `riseballs-live` service. Any reference to those in historical docs has been marked deleted in place.

---

## Cron authority

**All cron lives in Rails.** Both Java services have zero `@Scheduled` annotations — `riseballs-scraper` is a pure request/response worker (see [scraper/06-scheduled-jobs.md](../scraper/06-scheduled-jobs.md)) and `riseballs-live` has no concept of time-triggered work beyond the TTL on its Caffeine caches. Rails triggers Java endpoints from scheduled jobs like `ScheduleReconciliationJob` and `NcaaDateReconciliationJob`.

Why: one scheduling point (Sidekiq cron) is easier to reason about and monitor than two. The Java scraper runs as a request/response worker; it just happens to do heavy long-running work inside request handlers (with virtual threads + semaphores). `riseballs-live` is driven by incoming HTTP requests only — if no one hits `/scoreboard`, no upstreams get fetched.

See [rails/14-schedule.md](../rails/14-schedule.md) for the full cron table.

---

## Quality gate authority

`CachedGame.pbp_quality_ok?` (`app/models/cached_game.rb`) is the **single source of truth** for PBP quality validation. It rejects:

- Single stat-groups in non-last innings for multi-period games (teams not split)
- Multiple stat-groups all sharing the same `teamId` (parser failed to distinguish)
- Empty `teams` array for multi-period games
- Garbage plays (>50% bare names without verbs)
- Single-period dumps with >20 plays

This gate fires on `CachedGame.store` and on `CachedGame.store_for_game`. It does **not** run on direct `INSERT` or on bulk upserts.

**Hazard:** The Java scraper writes `cached_games` via JPA, which bypasses this Ruby method entirely. When Java stores PBP, it has to replicate the checks in Java code or not bother. Today there is partial replication but not full — Java PBP writes are a known source of bad cache entries. Mitigation: `pbp:purge_bad` rake task (runs the Ruby gate over every cached row, deletes failures).

See [rails/01-models.md](../rails/01-models.md) `CachedGame` section and [pipelines/02-pbp-pipeline.md](../pipelines/02-pbp-pipeline.md).

---

## Score authority

Scores come from multiple paths; the lock system resolves conflicts:

1. **Java `TeamScheduleSyncService`** writes scores when scraping team schedule pages.
2. **Rails `TeamGameMatcher`** updates `Game.home_score`/`away_score` when linking team_games.
3. **Rails `ScoreValidationJob`** runs at 8:30 AM daily, validates scores against `player_game_stats` sums, and when internally consistent sets `game.locked = true` and auto-corrects.
4. **Rails admin review** (via `GameReview`) approves/dismisses manual corrections.

`game.locked?` is checked by both the matcher (`update_game_scores`) and reconciliation paths. Locked games cannot be overwritten by the matcher or reconciliation — only explicit admin action via `GameReview`.

See [rails/09-analytics-services.md](../rails/09-analytics-services.md) and [rails/08-matching-services.md](../rails/08-matching-services.md).

---

## Slug / alias authority

Three services resolve team slugs from raw names:

| Service | Class | Used by |
|---------|-------|---------|
| Rails | `TeamMatcher` (`app/services/team_matcher.rb`) | controllers fallback (`Api::TeamsController#schedule`), `RosterService`, cached-game lookups |
| Java scraper | `OpponentResolver` (`reconciliation/schedule/OpponentResolver.java`) | `TeamScheduleSyncService`, `StandingsOrchestrator`, schedule parsers |
| `riseballs-live` | `SlugResolver` (`client/SlugResolver.java`) | `EspnScoreboardClient`, `ScoreboardReconciler` — maps ESPN team names/abbreviations to canonical slugs before reconciliation |

The first two consult the `team_aliases` table in Postgres. `riseballs-live` has no DB access — instead, it loads classpath resources at startup: `espn_slug_overrides.json` (163 entries, a compile-time copy of the Ruby `ESPN_SLUG_OVERRIDES` plus three manually added entries — Florida Atlantic, Sam Houston, San Jose State accent) and `known_slugs.txt` (594 D1/D2 slugs). This duplication is intentional prison-safe duplication: changes to ESPN slug overrides have to be made in both Rails and `riseballs-live`.

All three strip suffixes ("University", "State"). Java scraper has parenthetical-suffix stripping ("Lee University (Tenn.)" → "Lee University"). See [reference/slug-and-alias-resolution.md](../reference/slug-and-alias-resolution.md) for the side-by-side decision tree.

**Ambiguous names** (MC, Southeastern, Concordia, Saint Mary's) are **not** resolved via global aliases. They are resolved by setting `team_slug` directly on the `conference_standings` row — the conference is context for disambiguation. Adding a global alias for an ambiguous name would cause standing cross-contamination.

---

## Prediction authority

**Predict service owns:**
- All ML model code
- Feature engineering (5 builders, ~168 + 15 features)
- Artifact storage and versioning (`models/current/` vs `models/archive/<version>/`)
- Prediction caching (5-min TTL keyed on `model_version`)
- Keys-to-victory computation
- Scenario analysis

**Rails owns:**
- The controller (`Api::PredictionsController`) that hides 204 for played games
- The client (`PredictServiceClient`) with timeouts and parallel thread fanout
- Gating on `Game.state` (no prediction calls for `final`/`cancelled`)

**Rails does NOT cache predictions.** The only cache is inside Predict. If Predict restarts, the cache is empty — that's fine, it warms in seconds.

See [pipelines/07-prediction-pipeline.md](../pipelines/07-prediction-pipeline.md).

---

## Legacy / transitional boundaries

Some ownership lines are mid-migration:

| Area | Today | Intended |
|------|-------|----------|
| Roster ingestion | Rails `RosterService` (legacy) + Java `RosterAugmentService` (new) | Java only — Rails `RosterService` deprecated |
| Cloudflare Playwright scraping | `CloudflareBoxScoreService`, `CloudflareScheduleService` in Rails | Java scraper (local HTTP + Jsoup) — Rails Cloudflare fallbacks discouraged per user preference |
| AI fallback (boxscore) | `AiBoxScoreService` + `AiWebSearchBoxScoreService` (the latter DEAD) | Removed entirely; Java scraper + source-of-truth scraping only |
| Doubleheader matching | Shell-link preservation in Java + matcher tiebreaking in Rails | Same — this is stable now (GH issues #44–#48) |
| ESPN live ingest | `riseballs-live` service only (stateless, public). | Stable. Ruby `EspnScoreboardService` was deleted in Phase 8 (mondok/riseballs-live#1); nothing else on the Rails side touches ESPN. |
| StatBroadcast / Sidearm live stats (`/live` tab, `/api/live_stats/*`, `addToLiveView`) | **Deleted.** All machinery (controllers, services, clients, routes, SPA page, button) removed in mondok/riseballs#85 parts 1-3. | Stays deleted. The replacement is the `riseballs-live` overlay on the existing scoreboard. |

When in doubt: new scraping logic goes in the Java scraper, not Rails. See user preference in project memory.
