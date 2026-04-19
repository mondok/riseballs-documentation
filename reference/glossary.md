# Glossary

The vocabulary used across this codebase. Alphabetical.

---

### Alias
A row in `team_aliases` mapping an alternate name (`alias_name`) to a canonical `team_slug`. See [slug-and-alias-resolution.md](slug-and-alias-resolution.md).

### AliasTable
Informal synonym for `team_aliases`. When docs say "resolve through the alias table", they mean consulting `team_aliases` during slug resolution.

### Ambiguous name
A team-name string that could match multiple teams (e.g., `MC`, `Southeastern`). Resolved contextually per-row, NOT via global `TeamAlias`. See [slug-and-alias-resolution.md](slug-and-alias-resolution.md).

### Augment (roster / coach)
Update-only path that adds bio data (hometown, high school, photos, social) to existing `players` / `coaches` rows. Never creates or deletes. Lives in Java scraper. See [pipelines/05-roster-pipeline.md](../pipelines/05-roster-pipeline.md).

### Backfill
Catching up missing historical data. Distinct from live ingest. Examples: `BoxScoreBackfillJob`, `rake backfill_missing_pbp`, `rake stats:backfill_pitch_counts`.

### Blob cache
`cached_games` table — stores raw payload in its native shape, keyed by `(data_type, source_url, team_slug, game_date, opponent_slug, ncaa_contest_id)`. Contrast with normalized tables (`player_game_stats`, `plate_appearances`, `pitch_events`).

### Boxscore
A game's stat sheet (batting + pitching lines per player, linescore, totals). Cached as `data_type: "athl_boxscore"` or `"boxscore"`.

### Bracket as of Today
The tournament bracket computed from current standings — what it would look like if the season ended today. Rendered by `BracketSection` component.

### BoxscoreFetchService
Rails orchestrator for the box score fallback chain: Athletics → WMT → Cloudflare → AI. Also owns the PBP fallback within each box score fetch.

### CachedGame
Blob cache model (`app/models/cached_game.rb`). See "Blob cache" above and the `CachedGame` section in [rails/01-models.md](../rails/01-models.md).

### Cache hit path / Cache miss path
In controller waterfall: cache hit serves cached data directly; cache miss falls through to live fetch, quality gate, then cache store.

### Clinch indicator
Letter prefix in standings table: `x` = clinched #1 seed, `y` = clinched tournament berth, `e` = eliminated. Computed by `ConferenceScenarioService`.

### ConferenceSource
Config row in `conference_sources` defining one conference + season: URL, parser type, tournament shape. Seeded via `rake standings:seed_2026`.

### ConferenceStanding
One row per team per conference per season with current W/L and conf record. Written exclusively by Java `StandingsOrchestrator`.

### DH / Doubleheader
Two games on the same date between the same teams. Handled via `game_number` (1, 2). Unique constraint `(team_slug, game_date, opponent_slug, game_number)` on `team_games`. Assignment happens in Java `TeamScheduleSyncService.normalizeForDedup`.

### Discovery gate
The guard in `Api::GamesController#boxscore` that rejects a discovered box score for a `scheduled` game if it has final runs (almost certainly a prior meeting's box score). Issue #65 context. See [pipelines/02-pbp-pipeline.md](../pipelines/02-pbp-pipeline.md) and [pipelines/03-boxscore-pipeline.md](../pipelines/03-boxscore-pipeline.md).

### Dokku enter vs Dokku run
`dokku enter riseballs web '...'` runs inside the existing web container with internal-network access (can reach `riseballs-scraper.web:8080`). `dokku run riseballs '...'` creates a one-off container **without** internal-network access. Anything that calls Java must use `dokku enter`. See [operations/database-access.md](../operations/database-access.md).

### External ID (`rb_*`)
The stable public id for any game, used as the `gameID` in scoreboard JSON and in frontend URLs (`/games/rb_<id>`). Always `"rb_<games.id>"`. Decoupled from NCAA contest id as of 2026-04-19 (mondok/riseballs commit `263a684`) so URL continuity survives NCAA id changes. See [rails/01-models.md](../rails/01-models.md) `Game#url_id`. Historically a source of PBP-missing bugs when it was used as a fallback for truly orphan games (issue #66 context).

### Fallback path
The explicit ordered list of sources tried if the primary fails. See [matching-and-fallbacks.md](matching-and-fallbacks.md) for every one.

### Fingerprint (game)
Stat-based comparison for dedup/reconciliation. Two games match if they have 5+ common players with identical `player_game_stats`.

### Final (game state)
`Game.state == "final"`. The game has been played and scored. Flipping to final triggers `Game#enqueue_pbp_refresh_if_finalized` callback.

### Game
The shared record of a game, visible to both teams. Lives in `games` table. Contrast with `team_games` (per-team perspective). Linked via `game_team_links`.

### GameIdentifier
External IDs (NCAA contest ID, WMT game ID, Sidearm URL fragment) stored on `game_identifiers` for cross-source reconciliation.

### GameReview
Audit row (`game_reviews`) for every reconciliation, dedup, or validation action. Status: `pending`, `approved`, `dismissed`. See `/admin/reviews` UI.

### Game shell
A `Game` row created by `TeamGameMatcher.match_scheduled` for upcoming games — has teams + date but no scores yet. Also called "shell Game."

### Game snapshot
`game_snapshots` row — audit snapshot of full game state after a stat extraction. Used for rollback diagnostics.

### GameStatsExtractor
Rails service that converts a cached boxscore blob into normalized `player_game_stats` rows. See [rails/09-analytics-services.md](../rails/09-analytics-services.md).

### Garbage play
A PBP entry that fails the verb filter (e.g., bare name like `Smith, J.` with no play verb). Rejected by `CachedGame.pbp_quality_ok?` when >50% of plays are garbage.

### Ghost game
A `Game` that exists in our DB but doesn't exist on any source page. Detected by `GhostGameDetectionJob`. Deleted by reconciliation only if **both** teams' pages agree.

### `JavaScraperClient`
Rails service (`app/services/java_scraper_client.rb`) that wraps HTTP calls to the Java scraper. Uses internal URL `http://riseballs-scraper.web:8080`.

### Keys-to-victory
Per-team top-5 features predicted to most influence win probability. Computed by Predict service's `key_to_victory_engine.py`. See [predict/04-explain-engine.md](../predict/04-explain-engine.md).

### Legacy / deprecated
Tagged components still in codebase but no longer primary. Examples: `AiWebSearchBoxScoreService` (DEAD), `CloudflareBoxScoreService` (use Java scraper instead), Rails `RosterService` (use Java roster augmentation).

### Live (game state)
`Game.state == "live"`. Scoreboard polling has detected in-progress.

### Locked (game)
`Game.locked == true`. Set by `ScoreValidationJob` when scores are verified internally consistent. Matcher and reconciliation cannot overwrite locked games.

**Don't confuse with `CachedGame` locking.** `CachedGame` also has a `locked` column and a `try_lock!` class method — that's an unrelated advisory lock used to serialize concurrent cache writes (prevents two workers from writing the same cached boxscore simultaneously). `Game.locked` is a score-correctness signal; `CachedGame.locked` is a write-coordination primitive.

### match_scheduled / match_all
Two phases of `TeamGameMatcher`. `match_scheduled` creates shell Games for upcoming team_games; `match_all` updates shells with scores when team_games go final.

### Model version (predict)
String tag (e.g., `2026-04-01-v3`) identifying a trained XGBoost artifact bundle. Part of cache key, so retrain invalidates cleanly.

### NCAA contest ID
NCAA's unique ID for a game, stored on `games.ncaa_contest_id` when available. Authoritative for date reconciliation. Also emitted in scoreboard JSON as the separate field `ncaaContestId` (added 2026-04-19) so the live-overlay reconciler can key on it. See also "url_id" / "rb_*" for the public form of the id, which is independent.

### ncaaContestId (scoreboard JSON field)
The scoreboard API response field that carries the NCAA contest id separately from the public `gameID`. Introduced 2026-04-19. The `riseballs-live` overlay uses it as the primary match key; the frontend merge in `lib/liveOverlay.js` uses it first, with `(homeSlug, awaySlug, gameNumber)` as fallback.

### Negative cache (PBP)
`Rails.cache` key `pbp_miss:<gid>` with 5-minute TTL — set when a live PBP fetch fails. Prevents repeated slow Sidearm timeouts for the same broken game.

### Normalization (for dedup)
Java's `normalizeForDedup(name)` — strips rankings (`#5`, `No. 10`), resolves through alias table, then counts. Critical for consistent `game_number` across opposing team schedules.

### NUXT data
Sidearm Nuxt.js sites embed game data in `<script id="__NUXT_DATA__">` JSON. `BoxScoreParsers::Base` has a NUXT-specific parser for these.

### OpponentResolver
Java class (`reconciliation/schedule/OpponentResolver.java`) for team-name resolution. See [slug-and-alias-resolution.md](slug-and-alias-resolution.md).

### PBP
Play-by-play. See [pipelines/02-pbp-pipeline.md](../pipelines/02-pbp-pipeline.md).

### PlateAppearance / PitchEvent
Normalized per-plate-appearance / per-pitch rows derived from PBP blob. Used for pitch analytics and pitch count charts.

### PredictServiceClient
Rails service (`app/services/predict_service_client.rb`) that calls the Python Predict service. Uses parallel threads for bundle calls, 5s default timeout.

### Proactive vs lazy PBP
**Proactive:** `PbpOnFinalJob` fires on game state transition to `final` and fetches PBP. **Lazy:** user hits the PBP endpoint; controller fetches on-demand. See [pipelines/02-pbp-pipeline.md](../pipelines/02-pbp-pipeline.md).

### Profile URL
`player.profile_url` — URL of the player's bio page on the team athletics site. Prerequisite for Sidearm bio augmentation. Discovered via `RosterAugmentService.discoverProfileUrls`.

### Quality gate
`CachedGame.pbp_quality_ok?` — single source of truth for PBP validation. See `CachedGame` in [rails/01-models.md](../rails/01-models.md).

### Rankings (team)
Integer `teams.rank` populated by `SyncRankingsJob` from NCAA JSON. Used to strip "#5" prefixes before dedup. (Column is `rank` — don't confuse with the app model accessor.)

### Reconciliation
Comparison between our DB and source pages to correct drift. Four paths: NCAA contest-id enrichment (every 20 min + nightly), NCAA date reconciliation (2:30 AM daily), schedule reconciliation (3 AM daily), game deduplication (every 15 min). See [pipelines/06-reconciliation-pipeline.md](../pipelines/06-reconciliation-pipeline.md).

The word "reconciliation" also refers to the in-memory merge that `riseballs-live`'s `ScoreboardReconciler` does on every `/scoreboard` request — a pure function over the NCAA + ESPN feeds that produces the unified event list. See [live/02-architecture.md](../live/02-architecture.md).

### Reconciler (overlay)
Class `ScoreboardReconciler` in `riseballs-live`. Pure function: `(ncaaEvents, espnEvents, slugResolver) → List<ReconciledEvent>`. Match rules: `ncaaContestId` primary, `(homeSlug, awaySlug, startTimeEpoch within 30 min)` fallback, reversed-slug rescue with score swap, ambiguity skip. State escalation: `max(ncaa.state, espn.state)` ordered `scheduled < live < final`. Distinct from the Rails `TeamGameMatcher` (which matches opposing team_games rows) and the `ScheduleComparisonEngine` in Java (which diffs team schedule pages against the DB).

### riseballs-live
Standalone stateless Java Spring Boot service at `https://live.riseballs.com`. Shipped 2026-04-19 (mondok/riseballs-live#1). Serves a single endpoint (`GET /scoreboard?date=`) returning reconciled NCAA + ESPN live-score events. No DB, no Redis, no internal hostnames in its container env — the "prison" architecture is enforced at the Dokku config level. Consumed directly by the browser; not called by Rails. See [live/00-overview.md](../live/00-overview.md).

### Overlay (live-score)
The transient live-score data layered on top of the Rails-sourced scoreboard by `lib/liveOverlay.js`. Affects only non-final games. If the overlay service is down or slow, the scoreboard still renders from Rails data alone — degradation is silent.

### Fresh / stale / negative cache (overlay)
The three Caffeine cache tiers inside `riseballs-live`. **Fresh** (30s TTL): served immediately on hit. **Stale** (5m TTL): served with `source: "stale"` when upstreams time out and we have a recent payload. **Negative** (10s TTL): returned on hard upstream failure to keep us from hammering a broken upstream. All three TTLs are configurable via `riseballs.cache.*` properties. Separate from the PBP negative cache in Rails (`pbp_miss:<gid>`), which is unrelated.

### Scheduled (game state)
`Game.state == "scheduled"`. Not yet played.

### ScrapedPage
`scraped_pages` row — raw HTML kept for later reparse. `page_type` distinguishes `schedule`, `boxscore`, `roster`, etc.

### Shell / Shell Game
See "Game shell."

### Shell link preservation
Java `TeamScheduleSyncService` snapshots `team_games.game_id` before deleting non-final rows, then restores via natural key. Prevents the matcher from re-linking every sync cycle. Root fix for DH instability.

### Slug (team)
`teams.slug` — URL-safe identifier. Primary key for team references across the system (used in `team_games.team_slug` / `opponent_slug`, URLs like `/teams/lsu`, etc.).

### Source (PBP / boxscore)
String tag `athletics`, `nuxt_data`, `wmt_api` indicating which path produced the cached blob. Stored as `_source` field in the blob JSON.

### Store for game
`CachedGame.store_for_game(game, data_type, payload)` — store a blob keyed by game_id. Runs the quality gate.

### team_games
Per-team schedule row. Each game has TWO `team_games` rows (one per perspective). Linked to a shared `Game` via `game_team_links`.

### TeamAlias
Model for `team_aliases`. See "Alias" above.

### TeamGameMatcher
Rails service that links `team_games` rows to shared `Game` records. Two phases: `match_scheduled` and `match_all`.

### TeamScheduleSyncService
Java service that parses team schedule pages and upserts `team_games`. Owns doubleheader `game_number` assignment + shell link preservation.

### Title clinch / elimination
Conference regular-season title (#1 seed). Different from tournament clinch. See [rails/10-scenario-service.md](../rails/10-scenario-service.md).

### Tournament clinch / elimination
Qualifying for the conference tournament. Different from title clinch. See `tournament_spots` and the scenario service.

### Unclaimed / claimed (matcher)
A `team_games` row is "unclaimed" if `game_id IS NULL`. "Claimed" if it's already linked to a `Game`. Matcher priority prefers unclaimed for new pairings.

### Verb filter (PBP)
Regex filter requiring play verbs (struck, grounded, singled, …) to count a PBP entry as real. Filters out per-pitch stubs.

### Virtual threads (Java)
Java 21 `Thread.ofVirtual().start()` pattern used throughout the scraper for per-team concurrency. Cheaper than OS threads, bounded by semaphores.

### WMT / Learfield
Vendor that runs athletics sites for several hundred schools. Their API (`api.wmt.games/api/statistics/games/{id}`) is an alternate data source. Identified by `WMT_DOMAINS` constant + `wmt_school_id` column.

### WordPress roster
Alternate roster source used by some sites (e.g., LSU) via `/wp-json/v1/staff?type=roster`.

---

## See also

- [matching-and-fallbacks.md](matching-and-fallbacks.md)
- [slug-and-alias-resolution.md](slug-and-alias-resolution.md)
- [conference-tournaments.md](conference-tournaments.md)
