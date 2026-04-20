# Rails Background Jobs

Operator reference for every ActiveJob in `app/jobs/`. All jobs run on Sidekiq (single `default` queue, concurrency 5 -- see [14-schedule.md](14-schedule.md) for cron wiring).

## Table of Contents

- [Conventions](#conventions)
  - [Base class: `ApplicationJob`](#base-class-applicationjob)
  - [`JobLock` concern](#joblock-concern)
  - [Java scraper delegation](#java-scraper-delegation)
- [Core pipeline](#core-pipeline)
  - [`GamePipelineJob`](#gamepipelinejob)
  - [`BoxScoreBackfillJob`](#boxscorebackfilljob)
  - [`PbpOnFinalJob`](#pbponfinaljob)
  - [`AdminReprocessJob`](#adminreprocessjob)
- [Data-quality jobs](#data-quality-jobs)
  - [`GameDedupJob`](#gamededuplob)
  - [`ScoreValidationJob`](#scorevalidationjob)
  - [`StaleGameCleanupJob`](#stalegamecleanupjob)
  - [`GhostGameDetectionJob`](#ghostgamedetectionjob)
  - [`TeamAssignmentAuditJob`](#teamassignmentauditjob)
  - [`StuckScheduleRecoveryJob` — **DELETED 2026-04-20**](#stuckschedulerecoveryjob--deleted)
- [Reconciliation with external sources](#reconciliation-with-external-sources)
  - [`NcaaDateReconciliationJob`](#ncaadatereconciliationjob)
  - [`ScheduleReconciliationJob`](#schedulereconciliationjob)
  - [`ScheduleDiffJob`](#schedulediffjob)
  - [`NcaaGameDiscoveryJob`](#ncaagamediscoveryjob)
- [PBP jobs](#pbp-jobs)
  - [`RefetchMissingPbpJob`](#refetchmissingpbpjob)
  - [`ReparsePbpJob`](#reparsepbpjob)
- [Rosters, coaches, WMT](#rosters-coaches-wmt)
  - [`RosterSyncAllJob`](#rostersyncalljob)
  - [`RosterAugmentAllJob`](#rosteraugmentalljob)
  - [`CoachAugmentAllJob`](#coachaugmentalljob)
  - [`WmtSyncAllJob`](#wmtsyncalljob)
  - [`AthleticsUrlDiscoveryJob`](#athleticsurldiscoveryjob)
- [Rankings, RPI, standings, metrics](#rankings-rpi-standings-metrics)
  - [`SyncRankingsJob`](#syncrankingsjob)
  - [`CalculateRpiJob`](#calculaterpijob)
  - [`StandingsRefreshJob`](#standingsrefreshjob)
  - [`ComputeD1MetricsJob`](#computed1metricsjob)

---

## Conventions

### Base class: `ApplicationJob`

File: `app/jobs/application_job.rb` (6 lines).

Every job inherits from `ApplicationJob`:

```ruby
class ApplicationJob < ActiveJob::Base
  retry_on ActiveRecord::Deadlocked, wait: :exponentially_longer, attempts: 3
end
```

So: any job's default retry behavior is exponential backoff, up to 3 attempts, for `ActiveRecord::Deadlocked` only. All other exceptions bubble to Sidekiq's default retry (25 attempts, exponential backoff) unless the job overrides it.

### `JobLock` concern

File: `app/jobs/concerns/job_lock.rb` (63 lines).

Redis-backed lock that every periodic job uses to prevent overlap. Two modes:

- `lock_singleton(ttl: seconds)` -- only one instance of the class can run at a time.
- `lock_per_args(ttl: seconds)` -- one instance per unique argument set (e.g., per `game_id`).

If the lock cannot be acquired the job logs `skipped (lock held: ...)` and exits cleanly. Locks are released in an `ensure` block. TTL is a safety net if the worker is killed mid-job.

### Java scraper delegation

Many jobs delegate to the Java scraper over HTTP (`JavaScraperClient.*`). That hostname (`http://riseballs-scraper.web:8080`) only resolves from running `web` / `worker` containers, so manual runs of these jobs require `dokku enter riseballs web`, not `dokku run`. If `JavaScraperClient.available?` returns false, the job logs a warning and returns -- no retry.

---

## Core pipeline

### `GamePipelineJob`

**File:** `app/jobs/game_pipeline_job.rb`
**Queue:** `default`
**Schedule:** `*/15 * * * *` (every 15 minutes)
**Lock:** `lock_singleton ttl: 1800`
**Trigger:** sidekiq-cron. Not enqueued from anywhere else.
**Inputs:** none

The main pipeline driver. Orchestrates sync, match, reconcile, backfill, cleanup for every 15-minute cycle:

1. **Sync team schedules via Java scraper.**
   - Between 03:00 and 03:15 local time: full sync (POST `/api/team-schedule/sync-all`, 15-minute timeout). This is the once-per-day full re-scrape of all ~592 teams.
   - Every other run: only syncs teams that have unfinished games *today* (POST `/api/team-schedule/sync-team` with `teamSlug`, 30s per team). Pulls `TeamGame` rows from `team_games` filtered by `game_date: Date.current, state != "final"`.
2. **Match team_games into Games.** Calls `TeamGameMatcher.match_scheduled` first (creates shells for scheduled games) and then `TeamGameMatcher.match_all` (updates shells with scores, pairs finals, creates Game rows for unmatched finals).
2.5. **Reconcile stuck states (issue #86, 2026-04-19).** `reconcile_stuck_states` flips scheduled/live → final for today/yesterday Games when any of: (a) cached `athl_boxscore` is good AND scores match; (b) cached `athl_play_by_play` is complete; (c) `start_time_epoch < 4.hours.ago`. Forward-only; uses `update!` so `after_update_commit` enqueues `PbpOnFinalJob`. DH guard suppresses signals (a) and (c) for doubleheader halves with null scores — see [pipelines/01-game-pipeline.md](../pipelines/01-game-pipeline.md) Step 2.5.
3. **Fetch missing box scores.** `fetch_missing_boxscores` picks up any final Game (or stuck-scheduled Game whose `start_time_epoch < 4.hours.ago`, per issue #87) from today or yesterday without a good `athl_boxscore` cached, and hands them to `JavaScraperClient.scrape_batch`. Additional `.reject { |g| g.home_score.nil? && g.has_doubleheader_sibling? }` skips null-scored DH halves (belt-and-suspenders pairing with scraper#11).
4. **Clean orphans.**
   - **Pass 0 (immediate, no 7-day delay):** deletes all `team_games` with `state IN ('cancelled', 'postponed')`, plus any Game shell that had *only* those team_games attached. Also deletes `GameTeamLink` rows for those shells.
   - Pass 1: deletes `team_games` with `state = 'scheduled'` whose `game_date < 7.days.ago` (nulls `game_id` first).
   - Pass 2: deletes any Game not referenced by a team_game, plus its `GameTeamLink` rows.

**Side effects:** writes `team_games`, `games`, `cached_games` (athl_boxscore), `game_team_links`. Deletes stale/cancelled/postponed rows. Calls the Java scraper.

**Downstream jobs enqueued:** none directly, but the Games it creates/finalizes trigger `Game#enqueue_pbp_refresh_if_finalized`, which enqueues `PbpOnFinalJob`.

**Caveat:** requires `JAVA_SCRAPER_URL` env var; returns immediately if absent.

### `BoxScoreBackfillJob`

**File:** `app/jobs/box_score_backfill_job.rb` (84 lines)
**Queue:** `default`
**Schedule:** `0 6 * * *` (6 AM daily)
**Lock:** `lock_singleton ttl: 1800`
**Trigger:** sidekiq-cron, also enqueued by `ScheduleReconciliationJob` whenever that job creates/modifies games.
**Inputs:** none

Three-phase safety net:

1. **Gap fill.** Scans Games in the last 60 days matching `state = 'final' OR (state = 'scheduled' AND start_time_epoch < 4.hours.ago)` (widened by issue #87) with both team slugs set, ordered newest-first, rejects any that already have a good `athl_boxscore`. Further rejects null-scored doubleheader halves via `.reject { |g| g.home_score.nil? && g.has_doubleheader_sibling? }` (issue #87's DH guard). Batches the rest to the Java scraper. Ruby-side fallback capped at `RUBY_SCRAPE_LIMIT = 200` (`BoxscoreFetchService.fetch`).
2. **PGS name normalization.** For every team with players, load roster data, walk `PlayerGameStat` rows, match each to a roster entry via `PlayerNameMatcher`. When a collision exists between two PGS rows (same `ncaa_game_id`/`team_seo_slug`/`player_name`), keep the one with more batting+pitching activity and destroy the other.
3. **Reaggregate Player totals.** For every team with both players and existing PGS rows, call `RosterService.aggregate_player_stats_from_game_stats(team)`.

**Side effects:** writes `cached_games`, `player_game_stats` (destroys duplicates, renames rows), aggregates into `players`.

**Caveat:** Iterates every team with players twice -- slow. The singleton lock keeps two instances from overlapping.

### `PbpOnFinalJob`

**File:** `app/jobs/pbp_on_final_job.rb` (66 lines)
**Queue:** `default`
**Schedule:** none -- event-triggered.
**Trigger:** `Game#enqueue_pbp_refresh_if_finalized`, an `after_update_commit` callback that fires when `saved_change_to_state? && state == "final"`. Enqueues `PbpOnFinalJob.perform_later(id)`.
**Inputs:** `game_id` (Integer)

```ruby
retry_on PbpNotReadyError, wait: :polynomially_longer, attempts: 5
```

Roughly an hour of backoff (~3s, ~18s, ~83s, ~258s, ~623s -- ActiveJob polynomial) while the source publishes the play-by-play feed.

Mirrors the on-demand `Api::GamesController#play_by_play` so PBP is ready in cache before any user opens the page.

1. Return early if `CachedGame.fetch(game, "athl_play_by_play")` already exists -- idempotent.
2. Resolve team slugs: prefer the `seoname` entries from a cached boxscore; otherwise fall back to `game.home_team_slug` + `away_team_slug` so even orphan `rb_*` games get attempted.
3. Return if there are no slugs (the historical fallback to `live_stats_url`/`live_stats_feed_url` was removed 2026-04-19 along with those columns).
4. Call `AthleticsBoxScoreService.fetch(game.best_external_id, seo_slugs)`. If it returns no PBP -> raise `PbpNotReadyError` (retries).
5. `CachedGame.store_for_game(game, "athl_play_by_play", pbp)`. If the quality gate rejects the payload -> raise `PbpNotReadyError` (retries).
6. `PitchByPitchParser.parse_from_cached_pbp!` to populate `plate_appearances` + `pitch_events`.

**Known caveat:** `PbpNotReadyError` is intentionally retryable; every other exception falls through to Sidekiq's default retry.

### `AdminReprocessJob`

**File:** `app/jobs/admin_reprocess_job.rb` (9 lines)
**Queue:** `default`
**Trigger:** `Admin::BoxscoresController#reprocess` (admin UI action) when the operator clicks "reprocess" on a game.
**Inputs:** `game_id`

Deletes the cached `athl_boxscore` and re-runs `BoxscoreFetchService.fetch(game)`. No retry policy beyond the base class.

---

## Data-quality jobs

### `GameDedupJob`

**File:** `app/jobs/game_dedup_job.rb` (316 lines)
**Queue:** `default`
**Schedule:** `*/15 * * * *` (every 15 minutes)
**Lock:** `lock_singleton ttl: 900`
**Trigger:** sidekiq-cron
**Env:** `DEDUP_DRY_RUN=1` to log what would be merged without mutating anything.

Detects and merges duplicate `Game` records.

**Lookback cutoff (load-bearing fact):** Uses `Date.current - LOOKBACK_DAYS.days` (Ruby, Rails time zone) rather than Postgres `CURRENT_DATE` (UTC). The DB server runs in UTC and can be up to a day ahead of the app's `Time.zone`; using the database clock silently shifts the lookback window depending on what hour the job runs. `LOOKBACK_DAYS = 14`.

Flow:

1. SQL query groups games by `(game_date, LEAST(home_team_slug, away_team_slug), GREATEST(...))` with `HAVING COUNT(*) > 1`. This catches home/away swaps.
2. For each group, `find_dupe_pairs` compares pairs via `confirmed_dupe?`:
   - Both must be `final` with scores.
   - Scores must match direct OR swapped.
   - Both must have PGS rows loaded (by `game_id` OR `ncaa_game_id`).
   - Build player fingerprints keyed by `"#{team_seo_slug}|#{lowercase_name}"`, values = every batting/pitching counter joined.
   - Require >= 5 common players. Every common player's fingerprint must be identical.
3. Pick the keeper via `score_game`: locked (+4), final (+3), has `game_team_links` (+2), has PGS (+2), has `ncaa_contest_id` (+1), has `cached_games` (+1). Never merge *away from* a locked game.
4. `merge_games` transfers, under a transaction: PGS (with pre-check for uniqueness collisions), `cached_games`, `game_team_links`, `game_identifiers`, `game_snapshots`, cleans `plate_appearances` + `pitch_events` (string-keyed, no FK). Moves game-level fields (`ncaa_game_id`, `sb_event_id`, `sidearm_game_id`, `start_time`, `start_time_epoch`, `live_stats_url`, `live_stats_feed_url`). Handles unique-constraint violations by nilling the loser's value first. Captures merged `ncaa_contest_id` in `keeper.metadata["merged_contest_ids"]` as audit trail if the keeper already had one. Creates an approved `GameReview` row with `review_type: "duplicate"` and `source: "GameDedupJob"`.
5. After each group, re-numbers `game_number` on the survivors (1, 2, ...).

**Side effects:** writes/deletes `games`, `player_game_stats`, `cached_games`, `game_team_links`, `game_identifiers`, `game_snapshots`, `plate_appearances`, `pitch_events`, `game_reviews`.

**Downstream:** none.

### `ScoreValidationJob`

**File:** `app/jobs/score_validation_job.rb` (154 lines)
**Queue:** `default`
**Schedule:** `30 8 * * *` (8:30 AM daily)
**Lock:** `lock_singleton ttl: 1800`
**Trigger:** sidekiq-cron
**Lookback:** `LOOKBACK_DAYS = 14`

Compares the `Game` scores against the cached box score's team totals:

1. For each final game in the last 14 days with a cached `athl_boxscore`:
   - `home_totals` = `boxscore.teamBoxscore[*].teamStats.batterTotals.runsScored` for the home team's seoname.
   - Skip if either side's total is missing or a zero vs non-zero mismatch.
   - If `home_totals/away_totals != game.home_score/away_score`, check whether player sums equal team totals (`batterTotals.runsScored == SUM(playerStats.batterStats.runsScored)`, excluding a "Totals" row).
   - **Consistent (sums match totals):** create `GameReview` with `status: "approved"`, `review_type: "score_mismatch"`, apply the correction (`home_score`, `away_score`, `locked: true`). Count as corrected.
   - **Inconsistent:** create `GameReview` with `status: "pending"`. Human review.
2. Cancelled games with non-null scores: create a pending `GameReview` with `review_type: "cancelled_with_scores"`, `proposed_changes: { state: "final" }`.

**Side effects:** updates `games` (scores + lock), writes `game_reviews`.

### `StaleGameCleanupJob`

**File:** `app/jobs/stale_game_cleanup_job.rb` (42 lines)
**Queue:** `default`
**Schedule:** none in sidekiq-cron -- only triggerable from the admin jobs page.
**Lock:** `lock_singleton ttl: 3600`

Finds Games in `state IN (scheduled, pre, postponed)` whose `game_date < Date.current - 3` days, not locked. For each, creates a pending `GameReview` (`review_type: "stale_scheduled"`) unless one already exists. Does **not** auto-delete -- it flags for human review via `/admin/game_reviews`.

### `GhostGameDetectionJob`

**File:** `app/jobs/ghost_game_detection_job.rb` (235 lines)
**Queue:** `default`
**Schedule:** none. Manual / not registered in sidekiq-cron / not in admin jobs UI -- enqueue via `bin/rails runner "GhostGameDetectionJob.perform_later"` only.
**Lock:** `lock_singleton ttl: 7200`

Detects and resolves duplicate "ghost" games (final games that don't correspond to real contests, e.g., date-slipped duplicates with identical scores).

1. **Find candidates.** Walk all final games in the last 90 days; pair up games that share teams + scores but differ on date. Fall back to pairing games with zero `GameTeamLink` rows against nearby (+/- 3 days) games for the same matchup.
2. For each candidate call `verify_against_schedule`, which hits the Java scraper's `/api/schedule/verify` for each team to see whether the ghost's `game_date` appears on their live schedule.
3. Based on result:
   - **`:on_schedule`** -- ensure both `GameTeamLink` rows exist, keep the game.
   - **`:not_on_schedule`** -- `try_roster_resolution`: compare the ghost's PGS player_names against nearby games (+/- 1 day) for the same team; if >= 80% roster overlap with another game, the ghost is a misassigned duplicate -- delete. Otherwise if `can_safely_delete?` (no PGS, or PGS identical to sibling's), delete. Else flag for review.
   - **`:unverifiable`** (Java scraper unreachable) -- try roster resolution first; then delete only if no links and no stats.
4. `delete_ghost` destroys PGS, `game_team_links`, `cached_games`, `game_identifiers` under a transaction, nils unique IDs (`ncaa_contest_id`, `ncaa_game_id`), destroys the Game. (The former `sb_event_id` nil-out is gone — that column was dropped 2026-04-19.)
5. `flag_for_review` creates a pending `GameReview` with `review_type: "duplicate"` and `proposed_changes: { action: "delete", sibling_game_id: ... }`.

### `TeamAssignmentAuditJob`

**File:** `app/jobs/team_assignment_audit_job.rb` (141 lines)
**Queue:** `default`
**Schedule:** none. Not scheduled / not in admin jobs UI -- run manually.
**Lock:** `lock_singleton ttl: 3600`

Detects games where the cached boxscore's team `seoname` values don't match `game.home_team_slug` / `game.away_team_slug`. For every final or scheduled game with a cached `athl_boxscore`:

- If a sibling game with the correct slugs+date+game_number already exists, try to delete the duplicate (`can_safely_delete?`: no PGS, or a PGS subset of the sibling). Otherwise flag.
- If no conflict, call `fix_team_slugs`: update `games.home_team_slug/away_team_slug` and any `player_game_stats.team_seo_slug` that matched the old slugs.
- Ambiguous flag writes `GameReview` with `review_type: "team_mismatch"`.

### `StuckScheduleRecoveryJob` — **DELETED**

**Removed 2026-04-20 (mondok/riseballs-scraper#16).** The hourly recovery
loop existed to paper over a bug in `SidearmScheduleParser` where
several URL patterns / HTML layouts silently returned 0 entries. That
bug is fixed at the source (new `parseEventRowCards` strategy, extended
`candidateScheduleUrls`, `li.sidearm-schedule-game-wrapper` selector,
localscraper fallback), so the "retry hourly hoping it works" safety
net is no longer needed.

`ScheduleRecoveryService` and `app/jobs/stuck_schedule_recovery_job.rb`
were removed together. See `rails/08-matching-services.md` for the
full explanation of why the recovery model was dropped. One-shot
cleanup uses `rake schedules:resync_recovery_teams`
(`rails/13-rake-tasks.md`).

---

## Reconciliation with external sources

### `NcaaDateReconciliationJob`

**File:** `app/jobs/ncaa_date_reconciliation_job.rb` (36 lines)
**Queue:** `default`
**Schedule:** `30 2 * * *` (2:30 AM daily)
**Lock:** `lock_singleton ttl: 3600`
**Trigger:** sidekiq-cron; also enqueue-able from `/admin/jobs`.

Pure delegation. `JavaScraperClient.reconcile_ncaa_dates` -> `POST /api/reconcile/ncaa-dates`. The Java side compares our `ncaa_contest_id`-tagged games against the NCAA GraphQL API and corrects `game_date`, dedupes, flags for review.

Logs the keys returned: `dateCorrected`, `duplicatesRemoved`, `ncaaWrong`, `flaggedForReview`, `noChange`, `skipped`, `errors`.

**Caveat:** requires `dokku enter` (talks to `http://riseballs-scraper.web:8080`).

### `ScheduleReconciliationJob`

**File:** `app/jobs/schedule_reconciliation_job.rb` (47 lines)
**Queue:** `default`
**Schedule:** `0 3 * * *` (3 AM daily)
**Lock:** `lock_singleton ttl: 2400`
**Trigger:** sidekiq-cron; also enqueue-able from `/admin/jobs`.

Pure delegation. `JavaScraperClient.reconcile` -> `POST /api/reconcile/schedule`. The Java side compares each team's published schedule page against our games table and creates, uncancels, corrects dates / scores, or finalizes as needed.

Returned counts: `gamesCreated`, `gamesUncancelled`, `gamesDateCorrected`, `gamesScoreCorrected`, `gamesFinalized`, `gamesFlaggedForReview`, `teamsSucceeded`, `teamsFailed`.

**Downstream:** if `created + uncancelled + date_corrected + score_corrected + finalized > 0`, enqueues `BoxScoreBackfillJob.perform_later` to pull box scores for the newly repaired games.

**Caveat:** requires `dokku enter`.

### `ScheduleDiffJob`

**File:** `app/jobs/schedule_diff_job.rb` (164 lines)
**Queue:** `default`
**Schedule:** none. Not scheduled, not in admin UI -- manual.

Ruby-side diff against the NCAA official API (no Java scraper). For each day from `season_start` (Feb 1 of current year) through yesterday, across D1/D2:

1. Fetch NCAA contests directly via the NCAA GraphQL API (historically delegated to `NcaaScoreboardService.contests_for_date`; that Ruby class was deleted 2026-04-19 and the job now inlines the same persisted-query call).
2. For each contest, resolve home/away seonames via `SLUG_ALIASES` (handles `uiw`/`incarnate-word`, `mcneese`/`mcneese-st`), then find matching Game by (date, slugs) in either order or by `ncaa_contest_id`.
3. **Score mismatch** (final only): compare `home_t["score"]` vs `game.home_score`. **Auto-fixes** when different.
4. **Team mismatch**: compares sorted slug arrays. **Auto-fixes** (updates `home_team_slug`, `away_team_slug`, scores) when both NCAA teams exist in our DB.
5. **Missing**: contest in NCAA but no matching Game -- logged only, not created.

Returns a hash with counts. Good for ad-hoc audits; not wired to anything.

### `NcaaGameDiscoveryJob`

**File:** `app/jobs/ncaa_game_discovery_job.rb`
**Queue:** `default`
**Schedule:** `*/20 * * * *` (every 20 minutes) + nightly season sweep — re-enabled 2026-04-19 (mondok/riseballs#82). Broken since 2026-04-12; contest-id coverage recovered from ~0% to ~92% after this re-enable.
**Lock:** `lock_singleton ttl: 3600`
**Inputs:** `options = { mode: "today" | "season" }`

- `mode: "today"` (default): hits the NCAA GraphQL API for today and yesterday, updates `games.ncaa_contest_id` + `start_time_epoch`.
- `mode: "season"`: full-season sweep; used by the nightly run.

**Note:** historically this job delegated to the Ruby `NcaaScoreboardService`, which was deleted on 2026-04-19. The job now calls the NCAA GraphQL API directly (same persisted-query hash used by the Java scraper and `riseballs-live`, keeping the three consumers aligned).

---

## PBP jobs

### `RefetchMissingPbpJob`

**File:** `app/jobs/refetch_missing_pbp_job.rb` (28 lines)
**Queue:** `default`
**Schedule:** none -- enqueue from `/admin/jobs`.
**Lock:** `lock_singleton ttl: 1800`

Finds game IDs with a cached `athl_boxscore` but no `athl_play_by_play`, then batches (50 per call) to `JavaScraperClient.scrape_batch`. Requires `dokku enter`.

### `ReparsePbpJob`

**File:** `app/jobs/reparse_pbp_job.rb` (40 lines)
**Queue:** `default`
**Schedule:** none -- enqueue from `/admin/jobs`.
**Lock:** `lock_singleton ttl: 1800`

Walks every cached `athl_play_by_play` with a linked `game_id` and re-runs `PitchByPitchParser.parse_from_cached_pbp!` to re-populate `plate_appearances` + `pitch_events` with updated parser logic. Pure Ruby, no external calls, so `dokku run` works.

---

## Rosters, coaches, WMT

### `RosterSyncAllJob`

**File:** `app/jobs/roster_sync_all_job.rb` (24 lines)
**Queue:** `default`
**Schedule:** none.
**Lock:** `lock_singleton ttl: 7200`
**Inputs:** `force: false`

Walks every team with an `athletics_url` and calls `RosterService.sync_roster(team, force: force)`. Pure Ruby (Nokogiri scraping of team athletics sites).

### `RosterAugmentAllJob`

**File:** `app/jobs/roster_augment_all_job.rb` (23 lines)
**Queue:** `default`
**Schedule:** none -- `/admin/jobs`.
**Lock:** `lock_singleton ttl: 3600`

Delegates to `JavaScraperClient.augment_all` -- Java fetches bio pages across all teams and fills `previous_school`, `transfer` status, etc. Requires `dokku enter`.

### `CoachAugmentAllJob`

**File:** `app/jobs/coach_augment_all_job.rb` (23 lines)
**Queue:** `default`
**Schedule:** none -- `/admin/jobs`.
**Lock:** `lock_singleton ttl: 3600`

Delegates to `JavaScraperClient.augment_all_coaches` -- Java fetches coach contact info and social links. Requires `dokku enter`.

### `WmtSyncAllJob`

**File:** `app/jobs/wmt_sync_all_job.rb` (23 lines)
**Queue:** `default`
**Schedule:** none -- `/admin/jobs`.
**Lock:** `lock_singleton ttl: 3600`

Delegates to `JavaScraperClient.wmt_sync_all` -- syncs roster data from the WMT API for all teams. Requires `dokku enter`.

### `AthleticsUrlDiscoveryJob`

**File:** `app/jobs/athletics_url_discovery_job.rb` (52 lines)
**Queue:** `default`
**Schedule:** `0 2 * * *` (2 AM daily)
**Trigger:** sidekiq-cron.
**Inputs:** `division: nil`, `force: false`

For each team missing an `athletics_url` (or all teams if `force: true`), calls the private `RosterService#discover_athletics_url(team)` which visits the team's NCAA school page and extracts the athletics site link. Batched 10 teams at a time with a 2s sleep between batches. Pure Ruby -- `dokku run` is fine.

No singleton lock -- relies on the cron cadence for deduplication.

---

## Rankings, RPI, standings, metrics

### `SyncRankingsJob`

**File:** `app/jobs/sync_rankings_job.rb` (7 lines)
**Queue:** `default`
**Schedule:** `30 3 * * *` (3:30 AM daily)
**Trigger:** sidekiq-cron.

Thin wrapper -- just calls `RosterService.sync_rankings`. Updates `teams.rank` from external ranking sources (NFCA, etc.). Pure Ruby.

### `CalculateRpiJob`

**File:** `app/jobs/calculate_rpi_job.rb` (7 lines)
**Queue:** `default`
**Schedule:** `0 4 * * *` (4 AM daily)
**Trigger:** sidekiq-cron. Also enqueued from `Api::AdminController#recalculate_rpi` and `Admin::ToolsController`.

Thin wrapper -- `RpiService.calculate_all`. Writes `rpi_values`. See `rake rpi:calculate` for the manual version that also re-syncs past scores first.

### `StandingsRefreshJob`

**File:** `app/jobs/standings_refresh_job.rb` (22 lines)
**Queue:** `default`
**Schedule:** `0 7 * * *` (7 AM daily)
**Lock:** `lock_singleton ttl: 3600`
**Trigger:** sidekiq-cron; also `/admin/jobs`.
**Inputs:** `season: Date.current.year`

Delegates to `JavaScraperClient.scrape_standings(season: season)` -- Java parses conference standings pages (Sidearm, Boostsport, MW, SEC, Prestosports -- per `conference_sources.parser_type`). Requires `dokku enter`.

### `ComputeD1MetricsJob`

**File:** `app/jobs/compute_d1_metrics_job.rb` (23 lines)
**Queue:** `default`
**Schedule:** `0 9 * * *` (9 AM daily)
**Lock:** `lock_singleton ttl: 600`
**Trigger:** sidekiq-cron; also `/admin/jobs`.

Delegates to `JavaScraperClient.compute_d1_metrics`. Logs `metrics_count`. Requires `dokku enter`.
