# Cron Inventory — Stage A (PR #1)

**Source:** `riseballs/config/initializers/sidekiq.rb`
**Captured:** 2026-05-02
**Plan reference:** `PIPELINE_REBUILD_PLAN.md` v5, §"Cron source" (line 699), Stage E Phase 1/3 (lines 947–984), §North Star rule 6.

This file enumerates every `Sidekiq::Cron::Job` entry currently
loaded by the Rails app. Each row carries a disposition for the v5
rebuild. Dispositions match the cron-side application of the v5
reuse table:

- **DELETE** — job scrapes external sites, parses HTML, matches
  teams/games/players, OR writes to `cached_games`,
  `game_team_links`, or score columns (`Game.home_score`,
  `Game.away_score`) from Ruby. Per North Star rule 6, Java owns
  ingestion and Ruby owns API/UI; this job's concern moves into the
  Java DAG. Phase 1 ships a `return if ENV['PIPELINE_V2_ENABLED']==
  'true'` guard at the top of `#perform` (NOT just on enqueue, so
  in-flight queued jobs respect the flip). Phase 3 deletes the cron
  entry, the `app/jobs/*.rb` file, and any callers.
- **KEEP** — job is unrelated to ingestion (RPI, WAR, scenario
  builds, prediction warm-ups, sitemap regen, etc.). Stays past
  Phase 3.
- **KEEP_DEPRECATE_LATER** — job is still scraping but its concern
  (standings, athletics-url discovery, roster sync) is **out of
  scope for this rebuild** per plan §"Out of scope (deliberate)"
  and §"REUSE_AS_IS (out of pipeline scope)". Stays through Phase
  3, but flagged here so future PRs know it still has a Ruby write
  path that should eventually be ported to Java in a separate
  effort.

## Currently-paused jobs (Feb 31 sentinel)

Multiple ingestion-side cron entries use the never-fire schedule
`0 5 31 2 *` (Feb 31). Comments in the file mark these
`PAUSED 2026-04-29 during invariants drain (Phase 5)`. The plan
did not anticipate this pre-existing pause. Implication for Phase
2: these never need a Phase 1 in-perform guard for the **cron**
trigger because the cron will not fire — but the job classes can
still be enqueued ad-hoc (admin UI, rake tasks, Sidekiq Web). The
guard is still required on `#perform` to cover those paths. Phase
3 deletes the entry from the array and the job class entirely.

## Cron entries

| # | Name | Schedule | Job class | Disposition | Phase 1 guard? | Notes |
|---|---|---|---|---|---|---|
| 1 | `game_pipeline` | `0 5 31 2 *` (PAUSED, was `*/15 * * * *`) | `GamePipelineJob` | DELETE | yes | Old hourly orchestrator. Sync schedules → match → fetch boxscores → cleanup. Replaced wholesale by Java `HourlyScheduleSweep` + `ProcessScheduleEntry`. |
| 2 | `ncaa_date_reconciliation` | `0 5 31 2 *` (PAUSED, was `30 2 * * *`) | `NcaaDateReconciliationJob` | DELETE | yes | Calls `JavaScraperClient.reconcile_ncaa_dates`. Replaced by Java `NcaaEnrichment` (sibling cron, not Stage 8). |
| 3 | `ncaa_date_reconciliation_hourly` | `0 5 31 2 *` (PAUSED, was `15 * * * *`) | `NcaaDateReconciliationHourlyJob` | DELETE | yes | Today/tomorrow scope of #2. Same replacement. |
| 4 | `ncaa_dh_inversion_resolver` | `0 5 31 2 *` (PAUSED, was `45 * * * *`) | `NcaaDhInversionResolverJob` | DELETE | yes | Auto-resolves DH inversion `GameReview` rows by swapping `ncaa_contest_id` between two Game rows (writes only `ncaa_contest_id` + `start_time_epoch`, NOT scores). Concern folds into Java `NcaaEnrichment`'s contest-attachment logic. |
| 5 | `boxscore_score_consistency` | `*/5 * * * *` (ACTIVE) | `BoxscoreScoreConsistencyJob` | DELETE | yes | Calls `PitchingAudit::BoxscoreAlignmentRepairer`, which writes to `Game.home_score` / `Game.away_score` when slot-sum disagreement is detected. **Ruby score writer — North Star rule 6 forbids.** Concern absorbed by Java Stage 4 (`BundleConsistencyChecker` thin-page reject + slot-sum check) + Stage 6 single-writer. |
| 6 | `schedule_reconciliation` | `0 5 31 2 *` (PAUSED, was `0 3 * * *`) | `ScheduleReconciliationJob` | DELETE | yes | Calls `JavaScraperClient.reconcile`. Replaced by Stage 1 of new pipeline (`HourlyScheduleSweep` walks every team's schedule). |
| 7 | `orphaned_team_game_repair` | `0 5 31 2 *` (PAUSED, was `20 * * * *`) | `OrphanedTeamGameRepairJob` | DELETE | yes | Calls `JavaScraperClient.sync_team_schedule(slug)` for Games missing a TeamGame link. Replaced by Stage 1's deterministic Game-creation (orphans cease to exist by construction). |
| 8 | `score_validation` | `30 8 * * *` (ACTIVE) | `ScoreValidationJob` | DELETE | yes | Calls `game.update_columns(home_score:, away_score:, locked: true)` (line 82 of the job). **Ruby score writer — North Star rule 6 forbids.** Concern absorbed by Java Stage 5/6: bundle-driven score writes are the only path; no Ruby reconciliation needed. |
| 9 | `game_dedup` | `0 5 31 2 *` (PAUSED, was `*/15 * * * *`) | `GameDedupJob` | DELETE | yes | On merge, calls `keeper.update_columns(state: 'final', home_score: loser.home_score, away_score: loser.away_score)` (line 284). **Ruby score writer.** Dedup concern folds into Stage 1's `idx_games_natural_key` enforcement (deterministic; cannot create the duplicate in the first place). |
| 10 | `box_score_backfill` | `0 6 * * *` (ACTIVE) | `BoxScoreBackfillJob` | DELETE | yes | Calls `JavaScraperClient.scrape_batch` (primary) or `BoxscoreFetchService` (Ruby fallback) for the last 60 days. Writes `cached_games`. Replaced by Java `BackReconcilerNightly`. |
| 11 | `athletics_url_discovery` | `0 2 * * *` (ACTIVE) | `AthleticsUrlDiscoveryJob` | KEEP_DEPRECATE_LATER | no | Scrapes NCAA school pages to populate `Team.athletics_url`. Out of scope for THIS rebuild (Stage 1 reads pre-existing `athletics_url`); should be ported to Java in a separate follow-up PR. **Note:** `Team.athletics_url` is also subject to the SSRF gate added in Stage B (plan §"SSRF defense"). |
| 12 | `sync_rankings` | `30 3 * * *` (ACTIVE) | `SyncRankingsJob` | KEEP | n/a | Wraps `RosterService.sync_rankings`. Roster augmentation is explicitly out of scope per plan §"Out of scope (deliberate)" and §"REUSE_AS_IS — roster_parsers/". |
| 13 | `calculate_rpi` | `0 4 * * *` (ACTIVE) | `CalculateRpiJob` | KEEP | n/a | Wraps `RpiService.calculate_all`. Pure analytics; no ingestion. |
| 14 | `standings_refresh` | `0 7 * * *` (ACTIVE) | `StandingsRefreshJob` | KEEP_DEPRECATE_LATER | no | Calls `JavaScraperClient.scrape_standings`. Standings is explicitly REUSE_AS_IS in the plan; the Java standings subsystem stays untouched. Flagged for awareness only — independent deprecation possible in a separate effort. |
| 15 | `compute_d1_metrics` | `0 9 * * *` (ACTIVE) | `ComputeD1MetricsJob` | KEEP | n/a | Triggers `D1MetricsService` on the Java side. Out of pipeline scope. |
| 16 | `pitching_audit` | `30 4 * * *` (ACTIVE) | `PitchingAuditJob` | DELETE | yes | Wraps `PitchingAudit::DiffEngine`, which writes `Player.{w,l,era,...}` after diffing live source vs DB. Plan §"Ruby — DELETE" lists the entire `pitching_audit/` directory. The job class itself goes away in Phase 3 along with the directory. **Note:** Player-stat diff/repair concerns absorbed by Java Stage 7 (`PlayerStatsExtractor`), which reads the canonical bundle and re-derives PGS deterministically. |

## Summary

| Disposition | Count | Phase 1 guard required |
|---|---|---|
| DELETE | 11 | yes (all 11) |
| KEEP_DEPRECATE_LATER | 3 | no — keeps writing to its own out-of-scope tables |
| KEEP | 2 | n/a — no ingestion concern |
| **TOTAL** | **16** | **11 guards required** |

## Dokku-level cron status

`PIPELINE_REBUILD_PLAN.md` line 707 states: "Dokku-level cron
(`cron:list`) is empty for both apps; no Dokku cron edits
required." Verified per plan; not re-verified live in this PR.
Re-verify before Phase 3 deletion ships:

```sh
ssh dokku@ssh.mondokhealth.com -- cron:list riseballs
ssh dokku@ssh.mondokhealth.com -- cron:list riseballs-scraper
```

Both should be empty.

## Phase mapping

- **Phase 1 (deploy with flag OFF):** All 11 DELETE jobs gain a
  `return if ENV['PIPELINE_V2_ENABLED'] == 'true'` guard at the top
  of `#perform` (PR #25 in the v5 sequencing list, line 1843 of the
  plan). The cron entries themselves are NOT removed yet — old
  paths stay live until the flag flip succeeds.
- **Phase 2 (flag flip):** No file changes here. The guards short-
  circuit; the new Java pipeline becomes authoritative.
- **Phase 3a (PR #31 in v5 sequencing):** Delete the 11 DELETE
  entries from the `desired` array in `sidekiq.rb`. Sidekiq's
  startup hook (lines 18–20, 149–154 of the file) auto-destroys
  `Sidekiq::Cron::Job` rows whose names are no longer in the
  array, so deletion is one-shot. Final desired array contains
  the 5 KEEP / KEEP_DEPRECATE_LATER entries plus any new entries
  the rebuild introduces (none expected — Java owns scheduling
  via `@Scheduled`).
- **Phase 3b (PR #32):** Delete the 11 corresponding `app/jobs/*.rb`
  files plus their tests.

## Sidekiq queue drain (Phase 2 pre-flip)

Plan §"Pre-Phase-2 checklist" line 1869 requires drained queues
before flipping the flag. The mechanics for this Rails app:

```ruby
# Verify all queues are empty for 2 consecutive minutes:
Sidekiq::Queue.all.map { |q| [q.name, q.size] }
# All sizes should be 0.

# Also drain retry/scheduled/dead sets of the legacy job classes:
LEGACY = %w[
  GamePipelineJob NcaaDateReconciliationJob
  NcaaDateReconciliationHourlyJob NcaaDhInversionResolverJob
  BoxscoreScoreConsistencyJob ScheduleReconciliationJob
  OrphanedTeamGameRepairJob ScoreValidationJob GameDedupJob
  BoxScoreBackfillJob PitchingAuditJob
]
Sidekiq::RetrySet.new.each   { |j| j.delete if LEGACY.include?(j.klass) }
Sidekiq::ScheduledSet.new.each { |j| j.delete if LEGACY.include?(j.klass) }
Sidekiq::DeadSet.new.each    { |j| j.delete if LEGACY.include?(j.klass) }
```

(Per plan §"Sidekiq queue purge command", line 2066.)

## Open questions for sign-off

1. **`AthleticsUrlDiscoveryJob`** — confirm "deprecate later in a
   separate Java port" is the right disposition. Alternative:
   include in Phase 3 deletion if you'd rather not carry a Ruby
   scraper of any kind past the flag flip.
2. **`StandingsRefreshJob`** — confirm KEEP. The plan explicitly
   marks the Java standings subsystem REUSE_AS_IS, so this Ruby
   trigger is fine, but it's the only remaining Ruby-side path
   that asks Java to scrape something. Worth flagging.
3. **`PitchingAuditJob`** — the cron delete is straightforward
   (entry comes out in Phase 3a). Confirm we are deleting the
   entire `pitching_audit/` Ruby directory in Phase 3b — that's
   ~17 files (see `old-pipeline-inventory.md` for the list).
