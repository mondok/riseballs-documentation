# Service Boundaries

Who owns what. This doc answers the question "if I want to change X, which service do I edit?"

---

## Write authority matrix

Which service writes to each table:

| Table | Rails | Java scraper | Predict |
|-------|:-----:|:------------:|:-------:|
| `users`, `follows`, `player_favorites` | ✅ | — | — |
| `teams`, `team_aliases` | ✅ (migrations, admin) | ✅ (name/long_name updates) | — |
| `players` | ✅ (legacy `RosterService`) | ✅ (primary — `RosterAugmentService`, `WmtRosterService`) | — |
| `coaches` | — | ✅ (primary — `CoachAugmentService`) | — |
| `games` | ✅ (`TeamGameMatcher`, `GameDedupJob`, `ScoreValidationJob`) | ✅ (`GameCreationService`, reconciliation) | — |
| `team_games` | ✅ (matcher updates) | ✅ (primary — `TeamScheduleSyncService`) | — |
| `game_team_links` | ✅ (matcher) | ✅ (reconciliation) | — |
| `player_game_stats` | ✅ (`GameStatsExtractor`) | ✅ (`GameStatsWriter`) | — |
| `plate_appearances`, `pitch_events` | ✅ (`PitchByPitchParser`) | ✅ (`PbpOrchestrator`) | — |
| `cached_games` | ✅ (primary — `CachedGame.store` with quality gate) | ✅ (bypass — **no Ruby callbacks fire**) | — |
| `cached_schedules`, `cached_api_responses` | ✅ | ✅ | — |
| `scraped_pages` | ✅ | ✅ | — |
| `conference_sources` | ✅ (rake seed) | — | — |
| `conference_standings` | — | ✅ (primary — `StandingsOrchestrator`) | — |
| `standings_scrape_logs` | — | ✅ | — |
| `game_reviews` | ✅ (`ScoreValidationJob`, admin) | ✅ (reconciliation review flags) | — |
| `game_snapshots` | ✅ | — | — |
| `player_war_values`, `team_pitching_stats`, `site_metrics` | ✅ (`CalculateRpiJob`, `ComputeD1MetricsJob`) | — | — |

Predict never writes. It reads `teams`, `games`, `player_game_stats`, `plate_appearances`, `pitch_events` for feature engineering (see [predict/02-feature-engineering.md](../predict/02-feature-engineering.md)).

---

## Read authority: who serves what

Rails is the **only** user-facing service. Every read a browser makes goes through a Rails controller. Rails sometimes fans out to Predict for live prediction, and to Java for admin-triggered scraper actions, but the browser never talks to Java or Predict directly.

| Frontend URL | Backend route | Served by |
|--------------|---------------|-----------|
| `/games/:id` | `/api/games/:id` | Rails |
| `/games/:id` (prediction panel) | `/api/games/:id/prediction` | Rails → Predict |
| `/teams/:slug` | `/api/teams/:slug` | Rails |
| `/standings` | `/api/standings` | Rails |
| `/scoreboard` | `/api/scoreboard` | Rails |
| `/admin/jobs` → "run X" | `/admin/jobs/enqueue` | Rails (enqueues Sidekiq job) |
| `/admin/reviews` | `/admin/reviews` | Rails |

---

## Cron authority

**All cron lives in Rails.** The Java scraper has zero `@Scheduled` annotations (confirmed — see [scraper/06-scheduled-jobs.md](../scraper/06-scheduled-jobs.md)). Rails triggers Java endpoints from scheduled jobs like `ScheduleReconciliationJob` and `NcaaDateReconciliationJob`.

Why: one scheduling point (Sidekiq cron) is easier to reason about and monitor than two. Java runs as a request/response worker; it just happens to do heavy long-running work inside request handlers (with virtual threads + semaphores).

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

Two services resolve team slugs from raw names:

| Service | Class | Used by |
|---------|-------|---------|
| Rails | `TeamMatcher` (`app/services/team_matcher.rb`) | controllers fallback (`Api::TeamsController#schedule`), `RosterService`, cached-game lookups |
| Java | `OpponentResolver` (`reconciliation/schedule/OpponentResolver.java`) | `TeamScheduleSyncService`, `StandingsOrchestrator`, schedule parsers |

Both consult the `team_aliases` table. Both strip suffixes ("University", "State"), handle state-abbreviation expansion, and fall back to longName matching. Java has an additional parenthetical-suffix stripping step ("Lee University (Tenn.)" → "Lee University"). See [reference/slug-and-alias-resolution.md](../reference/slug-and-alias-resolution.md) for the side-by-side decision tree.

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

When in doubt: new scraping logic goes in the Java scraper, not Rails. See user preference in project memory.
