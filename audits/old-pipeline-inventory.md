# Old Pipeline Inventory — Stage A (PR #1)

**Captured:** 2026-05-02
**Plan reference:** `PIPELINE_REBUILD_PLAN.md` v5, §"Stage A — Inventory FIRST" (line 568) + §"Reuse table" (line 582).
**Companion file:** [`cron-inventory.md`](cron-inventory.md).
**Cohort file:** [`stuck-games-2026-05-02.txt`](stuck-games-2026-05-02.txt).

This document is the disposition list for every Ruby and Java
component that participates in the current ingestion / matching /
write-paths plus the JavaScraperClient method surface and the
documentation tree. It is the source of truth for Stage E Phase 3
deletion lists — any file marked DELETE here is targeted by PR #32
(Ruby) or PR #33 (Java) per the v5 PR sequencing (plan lines
1849–1851).

## Disposition vocabulary

(From plan §"Disposition vocabulary", line 573.)

- **REUSE_AS_IS** — keep, untouched.
- **MOVE** — relocate to new package; rename if needed; no semantic change.
- **EXTRACT_LOGIC_TO_NEW** — port specific algorithms into new components; delete the wrapper class.
- **DELETE** — gone, no replacement needed (concern is structurally obsolete).
- **PARTIAL_DELETE** — keep file, strip specified methods (used for `game_show_service.rb`).
- **KEEP_OUT_OF_SCOPE** — outside the rebuild's blast radius (predict, war, rpi, scenarios, frontend, standings, roster).

## Top-line counts

| Side | Files walked | DELETE | MOVE | EXTRACT | REUSE_AS_IS | PARTIAL | KEEP_OOS |
|---|---:|---:|---:|---:|---:|---:|---:|
| Rails (`riseballs/`) | 152 | 145 | 0 | 0 | 4 | 1 | 2 |
| Java scraper (`riseballs-scraper/`) | 139 | 17 | 15 | 51 | 56 | 0 | 0 |
| **Combined** | **291** | **162** | **15** | **51** | **60** | **1** | **2** |

JavaScraperClient public-method surface: 23 methods → **12 DELETE,
11 KEEP** (KEEP includes 6 roster / standings / metrics methods that
remain because their concerns are explicitly out of scope per plan).

Documentation pages: 59 markdown files → **19 REWRITE, 13 TOUCH,
23 KEEP, 4 AUDIT_OUTPUT, 0 DELETE**.

---

# Part 1 — Rails (`riseballs/`)

## 1.1 `app/services/` (root level)

| Path | LOC | Purpose | Disposition | New home / port target | Notes |
|------|-----|---------|-------------|------------------------|-------|
| `app/services/athletics_box_score_service.rb` | 772 | Scrape Athletics (Sidearm) box score HTML and parse player stats | DELETE | Java pipeline Stage 2/3 | Plan §Ruby DELETE list |
| `app/services/boxscore_fetch_service.rb` | 774 | Unified box score fetch coordinator | DELETE | Java `PageFetcher` chain (Stage 2) | Plan §Ruby DELETE list |
| `app/services/cloudflare_box_score_service.rb` | 217 | Cloudflare browser rendering for JS-heavy sites | DELETE | Java `PlaywrightStrategy` | Plan §Ruby DELETE list |
| `app/services/cloudflare_schedule_service.rb` | 215 | Cloudflare schedule scrape | DELETE | Java schedule parsers | Plan §Ruby DELETE list |
| `app/services/wmt_box_score_service.rb` | 206 | WMT API box score | DELETE | Java `WmtApiStrategy` | Plan §Ruby DELETE list |
| `app/services/schedule_service.rb` | 460 | Team schedule fetch + cache | DELETE | Java `HourlyScheduleSweep` | Plan §Ruby DELETE list |
| `app/services/boxscore_url_discovery_service.rb` | 250 | Discover box score URLs from schedules | DELETE | Java `UrlRediscovery` | Plan §Ruby DELETE list |
| `app/services/today_games_service.rb` | 29 | Today's games aggregator | DELETE | API-side controller helper | Plan §Ruby DELETE list |
| `app/services/roster_service.rb` | 1152 | Sync rosters from Athletics + boxscores | DELETE | Java roster service (out-of-scope-of-this-rebuild port; see §1.6) | Plan §Ruby DELETE list — but roster scraping itself is deferred to a separate Java roster-parser PR per plan §"Out of scope" |
| `app/services/site_record_fetcher.rb` | 186 | Extract W-L from team's homepage | DELETE | Java equivalent or remove | Plan §Ruby DELETE list |
| `app/services/boxscore_dupe_guard.rb` | 72 | Detect dupe boxscores before write | DELETE | Java Stage 4 thin-page reject + Stage 5 `bundle_hash` no-op detection | Plan §Ruby DELETE list (band-aid) |
| `app/services/game_stats_extractor.rb` | 807 | Extract player stats from boxscore payloads into PGS | DELETE | Java `PlayerStatsExtractor` (Stage 7) — port `format_innings_thirds`, `parse_innings`, `upsert_player_stat` shared-last-names disambiguation, `distribute_team_batting_breakdowns` first | Plan §Port-before-delete #5, #6, #7 |
| `app/services/pitch_by_pitch_parser.rb` | 658 | Parse Sidearm PBP HTML | DELETE | Java `PbpParser` (already exists) | Plan §Ruby DELETE list |
| `app/services/pitcher_enrichment_service.rb` | 58 | Merge Athletics pitcher lines into NCAA boxscore | DELETE | Java Stage 7 | Plan §Ruby DELETE list |
| `app/services/pbp_team_splitter.rb` | 123 | Split single PBP stat group into per-team | DELETE | Java Stage 7 | Plan §Ruby DELETE list |
| `app/services/player_stats_calculator.rb` | 212 | Calculate aggregated stats (AVG, OBP, ERA, WHIP, …) | DELETE | Java `PlayerStatsExtractor` | Plan §Ruby DELETE list |
| `app/services/team_game_matcher.rb` | 512 | Match TeamGame records into shared Game shells; `determine_home_away`; `find_or_create_shell`; `scores_compatible?` | DELETE | Java `GameMatcher` (Stage 1) — port `determine_home_away`, `find_or_create_shell` (→ `BackReconciler`), `scores_compatible?` first | Plan §Port-before-delete #2, #3, #4 |
| `app/services/matching_service.rb` | 70 | Validate boxscore team assignments via roster matching; `extract_names`, `count_matches` | DELETE | Java `OrientationFlipper` — verify parity with `TeamAssignmentVerifier.verifyByRoster`; port any deltas (especially diacritics handling) | Plan §Port-before-delete #9 |
| `app/services/opponent_roster_disambiguator.rb` | 123 | Last-name-overlap tiebreak between same-named candidate teams | DELETE | Java `TeamMatcher.disambiguateByLastNameOverlap()` | Plan §Port-before-delete #1 |
| `app/services/team_matcher.rb` | 132 | Canonical name → Team resolver; `RANKING_ALIASES` constant (AUM, UTRGV, UMass, …) | DELETE | Java `TeamMatcher` (rename of `OpponentResolver`); port `RANKING_ALIASES` (Step 3 of TeamMatcher contract — plan line 511) | Plan §Ruby DELETE list |
| `app/services/game_finalization_scorer.rb` | 295 | Confidence-scored finalization gate | DELETE | Java Stage 5 `OrientationFlipper` + Stage 4 verification (deterministic, replaces confidence scoring) | Plan §Ruby DELETE list |
| `app/services/series_guard_service.rb` | 27 | Detect doubleheader siblings before cancelling | DELETE | Java `Game.has_doubleheader_sibling?` equivalent in Stage 1 | Plan §Ruby DELETE list |
| `app/services/team_game_cross_link_auditor.rb` | 421 | Detect/repair team_game cross-link bugs (issue #111) | DELETE | Java Stage 1 (`idx_games_natural_key` makes the bug structurally impossible) | Plan §Ruby DELETE list |
| `app/services/game_show_service.rb` | 293 | Game show page enrichment + score patching | PARTIAL_DELETE | Strip `patch_show_scores`, `patch_scores_from_boxscore_fetch`, `patch_from_game_record`, `boxscore_linescores`, `extract_last_play`. Keep `enrich_show_data` minus score patching (conference enrich only). | Plan §Ruby — partial DELETE |
| `app/services/conference_scenario_service.rb` | 414 | Conference clinch / magic / bracket math | KEEP_OUT_OF_SCOPE | n/a | Plan §Out of scope |
| `app/services/war_calculator.rb` | 320 | WAR | KEEP_OUT_OF_SCOPE | n/a | Plan §Out of scope |
| `app/services/rpi_service.rb` | 201 | RPI | KEEP_OUT_OF_SCOPE | n/a | Plan §Out of scope |
| `app/services/predict_service_client.rb` | 159 | Python predict service client | KEEP_OUT_OF_SCOPE | n/a | Plan §Out of scope (predict reads PGS; only superseded_at filter PR #26 touches it) |
| `app/services/java_scraper_client.rb` | 449 | Client for Java scraper | REUSE_AS_IS (per-method) | See §3 below | 23 public methods; 12 DELETE / 11 KEEP — see Part 3 |
| `app/services/model_invariants.rb` | 54 | Write-time invariant enforcement | REUSE_AS_IS | n/a | Out of scope; survives untouched |

## 1.2 `app/services/concerns/`

| Path | LOC | Purpose | Disposition | Port target | Notes |
|------|-----|---------|-------------|-------------|-------|
| `app/services/concerns/player_name_matcher.rb` | 126 | Trigram-based fuzzy name match (with `clean_play_names` regex shared across 3 sites) | DELETE | Java `PlayerMatcher` — full algorithm port required (NormalizerVersion, name-normalize regex, trigram Jaccard ≥ 0.6, swap retry, char-intersection 80%) | Plan §Port-before-delete #1 (PlayerNameMatcher); plan §PlayerMatcher contract (line 530) |
| `app/services/concerns/sidearm_helper.rb` | 80 | Fetch HTML from Sidearm sites with browser headers | DELETE | Java `HttpStrategy` | Plan §Ruby DELETE list |

## 1.3 `app/services/box_score_parsers/` (entire directory)

| Path | LOC | Purpose | Disposition | Port target | Notes |
|------|-----|---------|-------------|-------------|-------|
| `app/services/box_score_parsers/base.rb` | 747 | Base class for box score HTML parsers | DELETE | Java `BoxscoreParser` dispatcher (Stage 3) | Plan: entire dir deleted |
| `app/services/box_score_parsers/presto_sports_parser.rb` | 138 | Presto box score parser | DELETE | Java `PrestoParser` (NEW) | Plan: entire dir deleted; PR #16 |
| `app/services/box_score_parsers/sidearm_parser.rb` | 292 | Sidearm box score parser | DELETE | Java `SidearmParser` (existing, MOVE) | Plan: entire dir deleted; PR #14 |
| `app/services/box_score_parsers/wmt_parser.rb` | 276 | WMT response parser | DELETE | Java `WmtParser` (existing, MOVE) | Plan: entire dir deleted; PR #15 |

## 1.4 `app/services/pitching_audit/` (entire directory)

Plan §Ruby DELETE list explicitly enumerates `pitching_audit/`
("entire dir — Ruby HTTP fetches forbidden under §6"). Concern
absorbed by Java Stage 7 (`PlayerStatsExtractor`), which derives
PGS deterministically from the canonical bundle; no diff/repair
needed once single-writer is enforced.

| Path | LOC | Purpose | Disposition | Notes |
|------|-----|---------|-------------|-------|
| `pitching_audit/boxscore_alignment_repairer.rb` | 302 | Repair misaligned pitcher stats | DELETE | Stage 4 verification + Stage 7 re-derive eliminate the misalignment class |
| `pitching_audit/diff_engine.rb` | 394 | Plan + apply pitcher-stat diffs from source vs DB | DELETE | Stage 7 always re-derives; no diff layer |
| `pitching_audit/ip_thirds.rb` | 67 | Parse innings pitched in thirds (e.g., 6.2 → 6⅔) | DELETE | Java `InningsFormatter` (Stage 7) — port required | Plan §Port-before-delete #5 |
| `pitching_audit/misattribution_repairer.rb` | 219 | Fix misattributed pitcher stats | DELETE | Stage 7 re-derive |
| `pitching_audit/pitcher_stat_line.rb` | 43 | Pitcher stat-line value object | DELETE | Java POJO equivalent inside Stage 7 |
| `pitching_audit/player_name_matcher.rb` | 109 | Deterministic pitcher name matcher (no fuzzy) | DELETE | Java `PlayerMatcher` (deterministic path) — note this is a SECOND name matcher to merge into the Java port |
| `pitching_audit/roster_cross_check.rb` | 77 | Verify source pitcher against team roster | DELETE | Java `TeamMatcher.disambiguateByLastNameOverlap` covers the equivalent in matching context |
| `pitching_audit/source_detector.rb` | 99 | Detect which CMS scraped the boxscore | DELETE | Stage 3 dispatcher infers from URL/Team without persisting |
| `pitching_audit/source_fetcher.rb` | 205 | Fetch pitcher stats from official source | DELETE | Java Stage 2 fetchers cover all sources |
| `pitching_audit/team_canonicalizer.rb` | 251 | Canonicalize team names from sources | DELETE | Java `TeamMatcher` |
| `pitching_audit/team_merger.rb` | 194 | Merge team data across sources | DELETE | Java Stage 5 canonical bundle selector |
| `pitching_audit/sources/base.rb` | 54 | Source-adapter base class | DELETE | Java fetcher strategy chain |
| `pitching_audit/sources/js_rendered_via_localscraper.rb` | 112 | LocalScraper JS-rendered adapter | DELETE | Java `LocalScraperStrategy` |
| `pitching_audit/sources/presto_sports_html.rb` | 310 | Presto adapter | DELETE | Java Presto fetcher + parser |
| `pitching_audit/sources/sidearm_html.rb` | 324 | Sidearm static-HTML adapter | DELETE | Java `HttpStrategy` + `SidearmParser` |
| `pitching_audit/sources/sidearm_nuxt.rb` | 219 | Sidearm Nuxt JS adapter | DELETE | Java `UrlRediscovery` Nuxt-aware extraction |
| `pitching_audit/sources/stat_crew_pdf.rb` | 360 | StatCrew PDF adapter | DELETE | Java equivalent (deferred — StatCrew is a tiny tail of D2; verify in Stage F backfill before deleting hard) |
| `pitching_audit/sources/wmt_season_stats.rb` | 296 | WMT season stats adapter | DELETE | Java WMT API client |

**18 files total** (11 in `pitching_audit/` + 6 in `pitching_audit/sources/` + 1 directory init not counted).

## 1.5 `app/services/roster_parsers/`

Plan §"Ruby — REUSE_AS_IS (deferred to separate Java
roster-parser PR)" — DO NOT bundle into pipeline cutover; orphaning
Presto roster scraping with no Java equivalent yet.

| Path | LOC | Purpose | Disposition | Notes |
|------|-----|---------|-------------|-------|
| `app/services/roster_parsers/hometown_splitter.rb` | 59 | Parse hometown / HS from roster text | REUSE_AS_IS | Deferred to separate Java port PR |
| `app/services/roster_parsers/presto_sports_parser.rb` | 94 | Presto roster HTML parser | REUSE_AS_IS | Deferred to separate Java port PR |

## 1.6 `app/services/shared/`

| Path | Purpose | Disposition | Notes |
|------|---------|-------------|-------|
| `app/services/shared/name_normalizer.rb` | Name normalization helper | REUSE_AS_IS | Out of scope; utility shared across surviving services |

(Sub-agent did not deep-read; spot check before Phase 3 to confirm no ingestion-side callers remain.)

## 1.7 `app/jobs/`

| Path | LOC | Purpose | Disposition | Notes |
|------|-----|---------|-------------|-------|
| `app/jobs/application_job.rb` | 6 | Base job class | REUSE_AS_IS | Framework |
| `app/jobs/concerns/job_lock.rb` | n/a | Redis-based singleton job locking | REUSE_AS_IS | Framework utility, used by surviving jobs too |
| `app/jobs/game_pipeline_job.rb` | 408 | Old hourly orchestrator (cron #1 in cron-inventory) | DELETE | Replaced by Java `HourlyScheduleSweep` |
| `app/jobs/game_dedup_job.rb` | 329 | Detect/merge duplicate Game records — writes scores | DELETE | Stage 1's `idx_games_natural_key` makes this structurally impossible |
| `app/jobs/admin_reprocess_job.rb` | 9 | Admin-triggered reprocessing | EXTRACT_LOGIC_TO_NEW | Thin wrapper; rewrite to call new `POST /api/pipeline/process-game` (Trigger 2 manual variant). Plan §"Manual trigger" line 1146 |
| `app/jobs/box_score_backfill_job.rb` | 92 | 60-day backfill of missing boxscores | DELETE | Replaced by Java `BackReconcilerNightly` |
| `app/jobs/boxscore_score_consistency_job.rb` | 102 | Auto-repair score disagreement between cached payload + Game (writes Game.scores) | DELETE | Stage 4 + Stage 6 single-writer eliminate the failure mode |
| `app/jobs/orphaned_team_game_repair_job.rb` | 163 | Sync schedule for Games missing a TeamGame link | DELETE | Stage 1 deterministic creation eliminates orphans |
| `app/jobs/pbp_on_final_job.rb` | 96 | Fetch+cache PBP when game flips to final | DELETE | Stage 5 reconciler triggers PBP read inside the same DAG run |
| `app/jobs/pitching_audit_job.rb` | 51 | Run nightly pitching audit | DELETE | Concern absorbed by Stage 7 re-derive |
| `app/jobs/score_validation_job.rb` | 156 | Validate score integrity, auto-correct via `update_columns(home_score:, away_score:, locked: true)` | DELETE | Ruby score writer; North Star §6 forbids |
| `app/jobs/ncaa_date_reconciliation_job.rb` | 36 | Full-season NCAA date reconciliation | DELETE | Replaced by Java `NcaaEnrichment` (sibling cron) |
| `app/jobs/ncaa_date_reconciliation_hourly_job.rb` | 38 | Today/tomorrow NCAA date reconciliation | DELETE | Replaced by Java `NcaaEnrichment` |
| `app/jobs/ncaa_dh_inversion_resolver_job.rb` | 113 | Auto-swap `ncaa_contest_id` between DH siblings | DELETE | NCAA contest_id attachment moves to Java `NcaaEnrichment`; Stage 1's `game_number` slot logic plus orientation-swap lookup eliminates the inversion class |
| `app/jobs/athletics_url_discovery_job.rb` | 52 | Discover `Team.athletics_url` from NCAA school pages | KEEP_DEPRECATE_LATER | Out-of-scope-of-this-rebuild but Ruby scraper; flag for separate port PR. SSRF gate from Stage B will validate values written here |
| `app/jobs/reparse_pbp_job.rb` | 40 | Reparse cached PBP | DELETE | Stage 7 re-derive on `bundle_hash` change covers it |
| `app/jobs/refetch_missing_pbp_job.rb` | 28 | Refetch missing PBP for games | DELETE | Stage 5 reconciler re-pulls when canonical is missing PBP |
| `app/jobs/stale_game_cleanup_job.rb` | 33 | Clean stale scheduled games | KEEP_OUT_OF_SCOPE | Cleanup, not ingestion |
| `app/jobs/schedule_reconciliation_job.rb` | 80 | Delegate schedule reconciliation to Java | DELETE | Replaced by Java `HourlyScheduleSweep` |
| `app/jobs/rebuild_predict_models_job.rb` | 42 | Trigger predict model rebuild | KEEP_OUT_OF_SCOPE | Predict-side concern |
| `app/jobs/roster_augment_all_job.rb` | 23 | Trigger Java roster augmentation for all teams | KEEP_DEPRECATE_LATER | Manual-trigger only (not in cron); concern is roster augment, out of scope for this rebuild |
| `app/jobs/compute_d1_metrics_job.rb` | 23 | Trigger D1 metrics computation | KEEP_OUT_OF_SCOPE | Metrics, out of scope |
| `app/jobs/coach_augment_all_job.rb` | 23 | Augment coach data for all teams | KEEP_DEPRECATE_LATER | Manual-trigger; out of scope |
| `app/jobs/wmt_sync_all_job.rb` | 23 | Sync WMT data for all teams | KEEP_DEPRECATE_LATER | Manual-trigger; out of scope |
| `app/jobs/standings_refresh_job.rb` | 22 | Refresh standings | KEEP_OUT_OF_SCOPE | Standings, out of scope |
| `app/jobs/calculate_rpi_job.rb` | 7 | Calculate RPI | KEEP_OUT_OF_SCOPE | Analytics |
| `app/jobs/sync_rankings_job.rb` | 7 | Sync ranking data | KEEP_OUT_OF_SCOPE | Analytics |

**Override on Ruby sub-agent's classifications** (verified against
the actual job source):

- `boxscore_score_consistency_job.rb` — agent said KEEP; **overridden
  to DELETE** because it calls
  `PitchingAudit::BoxscoreAlignmentRepairer`, which writes
  `Game.home_score` / `away_score`. Verified in
  `app/jobs/boxscore_score_consistency_job.rb` lines 1–60 (file
  comment confirms it auto-repairs scores).
- `score_validation_job.rb` — agent said MOVE; **overridden to
  DELETE** because line 82 calls
  `game.update_columns(home_score: home_totals, away_score:
  away_totals, locked: true)`.
- `game_dedup_job.rb` — agent classified DELETE for a different
  reason; **confirmed DELETE** also because line 284 calls
  `keeper.update_columns(state: 'final', home_score: loser.home_score,
  away_score: loser.away_score)`.

## 1.8 `lib/tasks/` (rake tasks)

All listed below are debugging / backfill / repair tasks. Per
plan §North Star rule 6 ("No Ruby code reads from external sites,
parses HTML, matches teams/games/players, or writes to
`cached_games` / `game_team_links` / score columns"), the ones
that scrape or write tracked tables go in Phase 3 deletion. Pure
admin/diagnostic tasks that read DB state can stay if they're
useful — but the entire set below was flagged DELETE by the
sub-agent. **Recommend keeping the read-only diagnostic tasks
through Phase 3 and revisiting in Stage G** (`audit_pipeline_consistency.rb`
will replace most of them).

| Path | LOC | Disposition | Notes |
|------|-----|-------------|-------|
| `lib/tasks/fill_missing_boxscores.rake` | 1202 | DELETE | Calls `SeriesGuardService`, `TeamGameMatcher`, `BoxscoreFetchService` |
| `lib/tasks/pitches.rake` | 224 | DELETE | Pitch-level debugging |
| `lib/tasks/repair_links.rake` | 199 | DELETE | Repairs `GameTeamLink` |
| `lib/tasks/slugs.rake` | 197 | DELETE | Team slug utilities |
| `lib/tasks/orphan_slugs.rake` | 185 | DELETE | Orphaned slug references |
| `lib/tasks/rosters.rake` | 184 | DELETE | Calls `RosterService` |
| `lib/tasks/schedules.rake` | 163 | DELETE | Calls `ScheduleService` |
| `lib/tasks/heal_corrupted_epochs.rake` | 144 | DELETE | One-time legacy repair |
| `lib/tasks/stats.rake` | 125 | DELETE | Calls `PlayerStatsCalculator` |
| `lib/tasks/rewrite_wmt_urls.rake` | 109 | DELETE | One-time |
| `lib/tasks/diagnose_decisions.rake` | 107 | DELETE | Debug |
| `lib/tasks/pbp.rake` | 104 | DELETE | Backfill / debug |
| `lib/tasks/backfill_decisions.rake` | 100 | DELETE | One-time |
| `lib/tasks/backfill_pitcher_starter.rake` | 96 | DELETE | One-time |
| `lib/tasks/standings.rake` | 93 | KEEP_OUT_OF_SCOPE | Standings; verify it doesn't write through deleted Ruby paths |
| `lib/tasks/backfill_pbp.rake` | 91 | DELETE | Backfill |
| `lib/tasks/fix_pbp_groups.rake` | 85 | DELETE | Repair |
| `lib/tasks/rpi.rake` | 86 | KEEP_OUT_OF_SCOPE | Analytics |
| `lib/tasks/validate_records.rake` | 82 | DELETE | Audit |
| `lib/tasks/teams.rake` | 72 | KEEP_OUT_OF_SCOPE | Verify before deleting; some entries may be admin-utility |
| `lib/tasks/audit_pbp.rake` | 72 | DELETE | Audit |
| `lib/tasks/dedup_games.rake` | 74 | DELETE | Repair |
| `lib/tasks/fix_doubleheaders.rake` | 71 | DELETE | Repair |
| `lib/tasks/reparse_pbp_from_html.rake` | 69 | DELETE | Repair |
| `lib/tasks/discover_boxscore_urls.rake` | 63 | DELETE | URL discovery backfill |
| `lib/tasks/backfill_pitch_counts.rake` | 58 | DELETE | One-time |
| `lib/tasks/debug_wrong_scores.rake` | 57 | DELETE | Debug |
| `lib/tasks/reparse_nuxt_pbp.rake` | 51 | DELETE | Debug |
| `lib/tasks/cleanup.rake` | 49 | KEEP_OUT_OF_SCOPE | Verify before deleting |
| `lib/tasks/backfill_lineups.rake` | 49 | DELETE | Lineup backfill (lineup work is out of scope per plan §"Out of scope") |
| `lib/tasks/refetch_bad_pbp.rake` | 41 | DELETE | Repair |
| `lib/tasks/fix_missing_team_ids.rake` | 39 | DELETE | One-time |
| `lib/tasks/reparse_pbp.rake` | 38 | DELETE | Repair |
| `lib/tasks/debug_pbp_failures.rake` | 36 | DELETE | Debug |
| `lib/tasks/debug_unmatched.rake` | 35 | DELETE | Debug |
| `lib/tasks/check_dh.rake` | 35 | DELETE | Audit |
| `lib/tasks/dh_audit.rake` | 28 | DELETE | Audit |
| `lib/tasks/check_cancelled.rake` | 22 | DELETE | Audit |
| `lib/tasks/export_urls.rake` | 16 | DELETE | Utility |
| `lib/tasks/games.rake` | 15 | KEEP_OUT_OF_SCOPE | Verify; admin utility |

(40 rake tasks; 34 DELETE, 6 KEEP_OUT_OF_SCOPE pending verification.)

## 1.9 `script/` (audit + probe scripts)

All 19 files are development probes. Plan does not enumerate them
explicitly. Recommend: leave intact through Phase 3, since they're
read-only diagnostic tools that will help during the cutover. Re-evaluate
in Stage G after `audit_pipeline_consistency.rb` lands.

| Path | LOC | Disposition | Notes |
|------|-----|-------------|-------|
| `script/audit_duplicate_boxscores.rb` | 82 | KEEP through cutover | Used in this PR to verify stuck-games cohort; useful through Stage F |
| `script/restore_pgs.rb` | 25 | DELETE after Phase 3 | One-time repair script |
| 17 other `probe_*` / `debug_*` / `test_*` scripts | varies | KEEP through cutover, DELETE after Stage F | Read-only debugging |

---

# Part 2 — Java scraper (`riseballs-scraper/`)

## 2.1 Overview

139 source files in 11 top-level packages. **Zero `@Scheduled`
annotations confirmed** (verified via grep of `@Scheduled`
across `src/main/java/`). Plan claim "Java side currently has
zero @Scheduled" — **CONFIRMED**.

Configuration audit: `application.yml` has no cron expressions.
All scheduling is currently externally triggered (Rails Sidekiq
cron → HTTP → Java controllers).

## 2.2 `com.riseballs.scraper` (root)

| Path | LOC | Purpose | Disposition | New home | Notes |
|------|-----|---------|-------------|----------|-------|
| `ScraperApplication` | 12 | Spring Boot entry | REUSE_AS_IS | n/a | Add `@EnableScheduling` here in PR #22 |

**Note:** sub-agent classified this DELETE; **overridden to
REUSE_AS_IS** — the Spring Boot main entry persists. The plan's
PR #22 explicitly adds `@EnableScheduling` here (line 1840).

## 2.3 `com.riseballs.scraper.config`

| Path | LOC | Disposition | Notes |
|------|-----|-------------|-------|
| `DatabaseUrlConfig` | 49 | REUSE_AS_IS | Connection pooling |
| `HttpClientConfig` | 26 | REUSE_AS_IS | Forces HTTP/1.1 (mondok/riseballs-scraper#14 from 2026-04-19) |
| `ScraperProperties` | 30 | REUSE_AS_IS | Tunables |

## 2.4 `com.riseballs.scraper.controller`

| Path | LOC | Disposition | Notes |
|------|-----|-------------|-------|
| `ScrapeController` | 172 | DELETE | After callers gone (per plan); `/api/scrape/*` → 410 Gone for 2 weeks (plan line 982) |
| `TeamScheduleSyncController` | 107 | DELETE | After callers gone; `/api/team-schedule/*` → 410 Gone |
| `GameCreationController` | 36 | DELETE | After callers gone; `/api/games/find-or-create` → 410 Gone |
| `ScheduleVerificationController` | 137 | DELETE | Plan does not name explicitly but is part of the verification-orchestration sprawl that DAG replaces; flag for confirmation |
| `MetricsController` | 34 | REUSE_AS_IS | Plan §REUSE_AS_IS list. Extend with new Micrometer counters per plan §"Metrics contract" |

**Deviation from plan:** `ScheduleVerificationController` is not
explicitly enumerated in the plan's Java DELETE list. Recommend
DELETE because its purpose (verification reports) is supplanted by
the new admin views over `pipeline_runs` + `pipeline_stage_audits`
(plan §"Admin views", line 1298). Flag for sign-off.

## 2.5 `com.riseballs.scraper.dto`

| Path | LOC | Disposition | Notes |
|------|-----|-------------|-------|
| `ScrapeRequest` | 15 | DELETE | Replaced by internal `ScheduleEntry` |
| `ScrapeResponse` | 41 | DELETE | Replaced by internal stage outputs |
| `BatchScrapeRequest` | 17 | DELETE | Replaced by orchestration internal |
| `BatchScrapeResponse` | 32 | DELETE | Same |

## 2.6 `com.riseballs.scraper.model` (JPA entities)

All 16 entity classes: **REUSE_AS_IS**.

`Game` (308 LOC), `GameTeamLink` (110), `GameLineup` (161),
`GameRef` (19), `GameReview` (81), `CachedGame` (131), `Player`
(436), `PlayerGameStat` (570), `PlateAppearance` (327),
`PitchEvent` (184), `Team` (239), `TeamGame` (115), `TeamAlias`
(30), `Coach` (89), `SiteMetric` (87), `ScrapedPage` (106).

JPA mappings receive new columns added in PRs #4–#6 (`is_canonical`,
`bundle_hash`, `score_source`, `last_canonical_bundle_hash`
removed-per-v5, etc.) but the classes themselves stay.

## 2.7 `com.riseballs.scraper.repository`

All 15 repositories: **REUSE_AS_IS**.

`GameRepository` (109), `GameTeamLinkRepository` (18),
`GameLineupRepository` (23), `CachedGameRepository` (19),
`PlayerRepository` (17), `PlayerGameStatRepository` (24),
`PlateAppearanceRepository` (11), `PitchEventRepository` (11),
`TeamRepository` (13), `TeamGameRepository` (48),
`TeamAliasRepository` (12), `GameReviewRepository` (12),
`CoachRepository` (13), `SiteMetricRepository` (13),
`ScrapedPageRepository` (13).

ArchUnit rule 2 (plan line 1389) restricts
`CachedGameRepository` injection to Stage 6; rule 3 does the same
for `GameTeamLinkRepository`. The repository classes themselves do
not change.

## 2.8 `com.riseballs.scraper.service`

| Path | LOC | Disposition | New home | Notes |
|------|-----|-------------|----------|-------|
| `ScrapeOrchestrator` | 462 | DELETE | n/a | Replaced by `ProcessScheduleEntry` |
| `PbpOrchestrator` | 542 | EXTRACT_LOGIC_TO_NEW | `pipeline/stage5_reconcile/PbpStrategy` (or absorb into `BoxscoreParser` dispatcher per plan §Stage 3 sub-PRs) | Source-prioritization logic kept |
| `GameStatsWriter` | 371 | EXTRACT_LOGIC_TO_NEW | `pipeline/stage7_stats/PlayerStatsExtractor` | Stat decomposition kept |
| `TeamScheduleSyncService` | 569 | DELETE | n/a | Replaced by `HourlyScheduleSweep` |
| `GameCreationService` | 234 | EXTRACT_LOGIC_TO_NEW | `pipeline/stage1_resolve/GameCreator` | Game/TeamGame creation logic kept |
| `NcaaApiClient` | 196 | EXTRACT_LOGIC_TO_NEW | `pipeline/ncaa/NcaaClient` | Plan does not name; classify as EXTRACT (move into `pipeline/ncaa`) |
| `NcaaContest` | 15 | EXTRACT_LOGIC_TO_NEW | `pipeline/ncaa/NcaaContest` | Record |
| `GameCreationRequest` | 18 | EXTRACT_LOGIC_TO_NEW | `pipeline/stage1_resolve/GameCreationRequest` | DTO |
| `GameCreationResult` | 7 | EXTRACT_LOGIC_TO_NEW | `pipeline/stage1_resolve/GameCreationResult` | Record |
| `GameCreationBatchResult` | 9 | EXTRACT_LOGIC_TO_NEW | same package | Record |
| `D1MetricsService` | 1248 | REUSE_AS_IS | n/a | Out of pipeline scope |

## 2.9 `com.riseballs.scraper.service.fetcher`

| Path | LOC | Disposition | New home | What to keep |
|------|-----|-------------|----------|--------------|
| `BoxscoreFetcher` (interface) | 12 | DELETE | n/a | New `PageFetcher` interface has different signature (`FetchedPage`, not `BoxscoreData`) |
| `PlainHttpFetcher` | 137 | EXTRACT_LOGIC_TO_NEW | `pipeline/stage2_fetch/HttpStrategy` | HTTP body, User-Agent, MIN_HTML_LENGTH guard. Drop `gameTeamLinkRepo` lookup (Stage 1 owns URL resolution) |
| `WmtFetcher` | 452 | EXTRACT_LOGIC_TO_NEW | `pipeline/stage2_fetch/WmtApiStrategy` | WMT API auth + JSON shaping. Drop URL lookup |
| `LocalScraperFetcher` | 148 | EXTRACT_LOGIC_TO_NEW | `pipeline/stage2_fetch/LocalScraperStrategy` | Local scraper invocation |
| `PlaywrightFetcher` | 143 | EXTRACT_LOGIC_TO_NEW | `pipeline/stage2_fetch/PlaywrightStrategy` | Session reuse + auth |
| `UrlRediscoveryFetcher` | 528 | EXTRACT_LOGIC_TO_NEW | `pipeline/stage2_fetch/UrlRediscovery` | Sitemap walk + permutation table + Nuxt-aware extraction |

## 2.10 `com.riseballs.scraper.service.parser`

| Path | LOC | Disposition | New home | Notes |
|------|-----|-------------|----------|-------|
| `SidearmBoxscoreParser` | 1590 | MOVE | `pipeline/stage3_parse/SidearmParser` | Repackage; PR #14 |
| `WmtResponseParser` | 669 | MOVE | `pipeline/stage3_parse/WmtParser` | PR #15 |
| `PbpParser` | 863 | MOVE | `pipeline/stage3_parse/PbpParser` | PR #13 |
| `NameUtils` | 69 | MOVE | `pipeline/matchers/NameUtils` | PR #9 |
| `BoxscoreData` | 56 | EXTRACT_LOGIC_TO_NEW | `pipeline/ScheduleEntry`-adjacent (or grandfathered shim per plan line 984) | Lineup-extraction grandfathering |

## 2.11 `com.riseballs.scraper.service.validation`

| Path | LOC | Disposition | New home | What to keep |
|------|-----|-------------|----------|--------------|
| `ScoreValidator` | 100 | EXTRACT_LOGIC_TO_NEW | `pipeline/stage4_verify/BundleConsistencyChecker` | `sumBattingRuns`, `isGoodBoxscore` |
| `TeamAssignmentVerifier` | 154 | EXTRACT_LOGIC_TO_NEW | `pipeline/stage5_reconcile/OrientationFlipper` | Score-based AND roster-based swap logic |
| `BoxscoreDateGate` | 71 | EXTRACT_LOGIC_TO_NEW | `pipeline/stage4_verify/BundleConsistencyChecker` | `parseDateFromUrl` (3 regex extractors: YYYYMMDD, YYYY-MM-DD, MM-DD-YYYY) |
| `BoxscoreDupeGuard` | 113 | DELETE | n/a | Per plan §Java DELETE list (band-aid, structurally obsolete) |

## 2.12 `com.riseballs.scraper.service.lineup`

Lineup extraction is **out of scope** per plan §"Out of scope":
"Lineup extraction (B1/B2/B3). Stage 7 absorbs later via separate
PR." Plan also says (line 984): "`service/parser/BoxscoreData.java`
retained as `@Deprecated` shim until lineup PR migrates to
`BoxscoreBundle`. Removed in a follow-up after lineup work merges."

| Path | LOC | Disposition | Notes |
|------|-----|-------------|-------|
| `LineupExtractor` | 294 | KEEP_OUT_OF_SCOPE | Hard contract: never throws. `player_id` immutability rule. |
| `SidearmLineupParser` | 236 | KEEP_OUT_OF_SCOPE | Folds into Stage 7 via separate PR |
| `WmtLineupParser` | 157 | KEEP_OUT_OF_SCOPE | Same |
| `LineupSlot` | 13 | KEEP_OUT_OF_SCOPE | Record |

**Deviation:** sub-agent classified these EXTRACT_LOGIC_TO_NEW.
**Overridden to KEEP_OUT_OF_SCOPE** per plan's explicit "Out of
scope (deliberate)" statement. Lineup migration is a separate PR
after the rebuild merges.

## 2.13 `com.riseballs.scraper.reconciliation`

| Path | LOC | Disposition | New home | Notes |
|------|-----|-------------|----------|-------|
| `ReconciliationService` | 727 | DELETE | n/a | Per plan §Java DELETE list |
| `ReconciliationController` | 41 | DELETE | n/a | Plan §Java DELETE list (unnamed but implied — REST gone) |
| `ReconciliationExecutor` | 606 | EXTRACT_LOGIC_TO_NEW | `propagateScoreToTeamGames` → Stage 6; `DELETE_GHOST` → `BackReconciler` | Plan §Java EXTRACT_LOGIC_TO_NEW |
| `ReconciliationAction` | 23 | DELETE | n/a | Plan §Java DELETE list |
| `ReconciliationResult` | 28 | DELETE | n/a | Implied DELETE — DTO of deleted service |
| `FullReconciliationResult` | 20 | DELETE | n/a | Same |
| `ScheduleComparisonEngine` | 560 | DELETE | n/a | Plan §Java DELETE list |
| `ScheduleReconciliationOrchestrator` | 386 | DELETE | n/a | Plan §Java DELETE list |
| `ScheduleReconciliationController` | 76 | DELETE | n/a | Plan §Java DELETE list |
| `NcaaDateReconciliationService` | 773 | EXTRACT_LOGIC_TO_NEW | `pipeline/ncaa/NcaaEnrichment` | Keep contest fetch + `(home,away,date)` match. Drop date-move decision tree |
| `NcaaDateReconciliationController` | 42 | DELETE | n/a | Plan §Java DELETE list |
| `NcaaDateReconciliationWriter` | 218 | EXTRACT_LOGIC_TO_NEW | `pipeline/ncaa/NcaaEnrichment` | Persistence logic kept |
| `NcaaDateReconciliationResult` | 16 | EXTRACT_LOGIC_TO_NEW | `pipeline/ncaa/` | Result shape |
| `NcaaContestCandidateResolver` | 165 | MOVE | `pipeline/ncaa/NcaaContestCandidateResolver` | Plan §MOVE list |

## 2.14 `com.riseballs.scraper.reconciliation.schedule`

| Path | LOC | Disposition | New home | Notes |
|------|-----|-------------|----------|-------|
| `SchedulePageParser` (interface) | 11 | MOVE | `pipeline/schedule/SchedulePageParser` | Plan §MOVE list |
| `SidearmScheduleParser` | 1268 | MOVE | `pipeline/schedule/SidearmScheduleParser` | Plan §MOVE list |
| `WmtScheduleParser` | 334 | MOVE | `pipeline/schedule/WmtScheduleParser` | Plan §MOVE list |
| `PrestoSportsScheduleParser` | 377 | MOVE | `pipeline/schedule/PrestoScheduleParser` | Rename `PrestoSports` → `Presto` |
| `WordPressScheduleParser` | 563 | MOVE | `pipeline/schedule/WordPressScheduleParser` | Plan §MOVE list |
| `ScheduleEntry` | 19 | MOVE | `pipeline/ScheduleEntry` | Plan §MOVE list. Extended in PR #8 with `triggerSource`, `lineScore`, `boxscoreUrl`, `finalMessage` per plan §"Type schemas" line 1897 |
| `ScheduleEntryMerger` | 169 | MOVE | `pipeline/stage1_resolve/ScheduleEntryMerger` | Plan §MOVE list |
| `OpponentResolver` | 480 | MOVE + EXTEND | `pipeline/matchers/TeamMatcher` | Rename + extend per `TeamMatcher` 15-step contract (plan line 511) |

## 2.15 `com.riseballs.scraper.roster` (out of scope)

All 6 files: **REUSE_AS_IS**. Plan §"Java REUSE_AS_IS (out of pipeline scope)".

`WmtRosterService` (941), `BioPageParser` (318),
`RosterAugmentService` (603), `CoachAugmentService` (218),
`CoachBioParser` (188), `RosterController` (186).

## 2.16 `com.riseballs.scraper.standings` (out of scope)

All 16 files (10 + 3 models + 3 repos): **REUSE_AS_IS**.

`StandingsOrchestrator`, `StandingsController`, `StandingsParser`,
`SidearmStandingsParser`, `PrestoSportsStandingsParser`,
`SecStandingsParser`, `MwStandingsParser`,
`BoostsportStandingsParser`, `StandingsResult`, `StandingsEntry`,
plus `ConferenceSource` / `ConferenceStanding` /
`StandingsScrapeLog` entities and their three repositories.

---

# Part 3 — `JavaScraperClient` method dispositions

(Plan §"JavaScraperClient method dispositions", line 1716. The
plan listed only 7 methods; the actual client has **23 public
methods**. This audit completes the table.)

| Method | Endpoint | Disposition | Phase 1 guard | Notes |
|---|---|---|---|---|
| `available?` | n/a | KEEP | n/a | Health utility used by other methods + cron jobs |
| `healthy?` | `/api/scrape/health` | KEEP | n/a | Used by `Admin::JobsController` dashboard |
| `scrape_game(id)` | `/api/scrape/boxscore` | DELETE | yes | Replaced by `POST /api/pipeline/process-game` (Trigger 2 / manual). Callers: `GamePipelineJob`, `Api::GamesController#boxscore` (sync miss) |
| `scrape_batch(ids)` | `/api/scrape/boxscores` | DELETE | yes | Replaced by `BackReconciler`. Callers: `GamePipelineJob`, `BoxScoreBackfillJob`, `RefetchMissingPbpJob` |
| `sync_team_schedule(slug)` | `/api/team-schedule/sync-team` | DELETE | yes | Replaced by Stage 1 `HourlyScheduleSweep`. Callers: `GamePipelineJob`, `OrphanedTeamGameRepairJob` |
| `reconcile_team(slug)` | `/api/reconcile/schedule/team` | DELETE | yes | Internal to `reconcile()` flow |
| `reconcile` | `/api/reconciliation/run` | DELETE | yes | Replaced by Stage 1. Caller: `ScheduleReconciliationJob` |
| `retry_failed_teams(result, failed_slugs)` | n/a | DELETE | n/a | Internal helper; deleted with `reconcile` |
| `reconcile_check` | `/api/reconcile/schedule/check` | DELETE | n/a | No callers in codebase — orphaned |
| `find_or_create_game(attrs)` | `/api/games/find-or-create` | DELETE | yes | Replaced by Stage 1 `GameMatcher` `CREATE_AT_SLOT`. Caller: `Game.find_or_create_from_schedule_entry` |
| `find_or_create_games_batch(requests)` | `/api/games/find-or-create-batch` | DELETE | n/a | No callers — orphaned |
| `reconcile_ncaa_dates(date:)` | `/api/reconcile/ncaa-dates` | DELETE | yes | Replaced by Java `NcaaEnrichment`. Callers: `NcaaDateReconciliationJob`, `NcaaDateReconciliationHourlyJob` (both PAUSED) |
| `reconcile_ncaa_dates_check(date:)` | `/api/reconcile/ncaa-dates/check` | DELETE | n/a | No callers — orphaned |
| `build_reconcile_query(date)` | n/a | DELETE | n/a | Internal helper for `reconcile_ncaa_dates`; deleted together |
| `augment_team(slug)` | `/api/roster/augment` | KEEP | n/a | Out of scope (roster augment) |
| `augment_all` | `/api/roster/augment/all` | KEEP | n/a | Out of scope. Caller: `RosterAugmentAllJob` (manual-trigger) |
| `augment_coaches(slug)` | `/api/roster/augment-coaches` | KEEP | n/a | Out of scope |
| `augment_all_coaches` | `/api/roster/augment-coaches/all` | KEEP | n/a | Out of scope. Caller: `CoachAugmentAllJob` (manual) |
| `wmt_sync_team(slug)` | `/api/roster/wmt-sync` | KEEP | n/a | Out of scope (roster) |
| `wmt_sync_all` | `/api/roster/wmt-sync/all` | KEEP | n/a | Out of scope. Caller: `WmtSyncAllJob` (manual) |
| `compute_d1_metrics` | `/api/metrics/compute` | KEEP | n/a | Out of scope (metrics). Caller: `ComputeD1MetricsJob` |
| `scrape_standings(season:)` | `/api/standings/scrape` | KEEP | n/a | Standings explicitly REUSE_AS_IS. Caller: `StandingsRefreshJob` |
| `scrape_standings_division(season:, division:)` | `/api/standings/scrape/division` | KEEP | n/a | No callers — orphaned but harmless |
| `scrape_standings_conference(season:, division:, conference:)` | `/api/standings/scrape/conference` | KEEP | n/a | No callers — orphaned but harmless |

**New method to add in PR #22 / #24:**
`process_game(game_id: nil, ncaa_contest_id: nil, trigger_source: 'manual')` → `POST /api/pipeline/process-game` with `X-Pipeline-Token` header. Plan §"Trigger 2" line 1086.

**Orphans flagged for cleanup:** `reconcile_check`,
`reconcile_ncaa_dates_check`, `find_or_create_games_batch`,
`scrape_standings_division`, `scrape_standings_conference`. These
have zero callers in the codebase. Recommend deleting in Phase 3a
without a Phase 1 guard (no Ruby caller can hit them).

---

# Part 4 — Documentation tree disposition

59 markdown files in `riseballs-documentation/`.

| Disposition | Count |
|---|---:|
| REWRITE | 19 |
| TOUCH | 13 |
| KEEP | 23 |
| AUDIT_OUTPUT | 4 |
| **TOTAL** | **59** |

## 4.1 REWRITE list (Phase 3 doc work)

These describe the OLD pipeline's 3-trigger sprawl, separate
Ruby+Java write paths, or `ScrapeOrchestrator` /
`ReconciliationOrchestrator` / `GamePipelineJob` / etc. They need
near-total rewrite to reflect the 7-stage DAG.

- `architecture/00-system-overview.md`
- `architecture/01-service-boundaries.md`
- `architecture/02-data-flow.md`
- `pipelines/01-game-pipeline.md` (centerpiece — entire doc describes the deleted GamePipelineJob)
- `pipelines/06-reconciliation-pipeline.md`
- `rails/06-ingestion-services.md`
- `rails/07-parsers.md`
- `rails/12-jobs.md` (27-job table consolidates to ~5 surviving + 3 Java @Scheduled)
- `rails/14-schedule.md` (entire cron table consolidates)
- `scraper/01-controllers.md`
- `scraper/04-reconciliation.md`
- `scraper/06-scheduled-jobs.md` ("zero @Scheduled" premise becomes false)
- `README.md` (root — §scope-disclaimers)

(13 files explicitly REWRITE; sub-agent counted 19 with marginal
calls. The 6 marginal entries — `pipelines/02-pbp-pipeline.md`,
`pipelines/03-boxscore-pipeline.md`, `pipelines/05-roster-pipeline.md`,
`rails/04-api-endpoints.md`, `scraper/02-services.md`,
`scraper/05-repositories-and-data.md` — are arguably TOUCH; final
call deferred to the Phase 3 doc PR author.)

## 4.2 TOUCH list (minor edits only)

13 files; representative examples: `predict/00-overview.md` (add
superseded_at note), `live/02-architecture.md` (Trigger 2 now in
scraper not live), `reference/glossary.md` (delete entries for
removed services), `operations/runbook.md` (replace deleted-job
references), `rails/01-models.md` (callbacks no longer enqueue
deleted jobs).

## 4.3 KEEP list (23 files)

Mostly: `predict/*` ML internals, `live/*` endpoint surface, `rails/15-17-frontend-*`,
`reference/conference-tournaments.md`, `reference/slug-and-alias-resolution.md`,
`scraper/03-parsers.md` (parser internals don't change post-MOVE),
`rails/02-database-schema.md` and `rails/03-entity-relationships.md`,
plus the 8 secondary `predict/01-07` docs.

## 4.4 AUDIT_OUTPUT (preserved unchanged)

`reviews/00-summary.md`, `reviews/01-coverage-gaps.md`,
`reviews/02-accuracy-spot-check.md`, `reviews/03-knowledge-graph.md`.

## 4.5 Stale-references audit (high-impact)

Files containing references to deleted components, with edit
complexity:

| File | Stale references | Edit complexity |
|---|---|---|
| `rails/06-ingestion-services.md` | AthleticsBoxScoreService, CloudflareBoxScoreService, WmtBoxScoreService, ScheduleService, RosterService | large |
| `rails/12-jobs.md` | GamePipelineJob, BoxScoreBackfillJob, PbpOnFinalJob, GameDedupJob, ScoreValidationJob, NcaaDateReconciliationJob, ScheduleReconciliationJob | large |
| `rails/14-schedule.md` | All 11 ingestion cron entries → 3 Java @Scheduled | large |
| `rails/07-parsers.md` | BoxScoreParsers subclasses | small |
| `rails/08-matching-services.md` | TeamGameMatcher, MatchingService | small |
| `pipelines/01-game-pipeline.md` | GamePipelineJob (centerpiece) | large |
| `pipelines/06-reconciliation-pipeline.md` | ReconciliationOrchestrator, ReconciliationService, NcaaDateReconciliationService | medium |
| `scraper/01-controllers.md` | ScrapeController, TeamScheduleSyncController | medium |
| `scraper/02-services.md` | ScrapeOrchestrator, PbpOrchestrator, GameStatsWriter | medium |
| `scraper/04-reconciliation.md` | ScheduleReconciliationOrchestrator, ReconciliationService, NcaaDateReconciliationService | medium |
| `scraper/06-scheduled-jobs.md` | "No @Scheduled" premise | large |

---

# Port-before-delete (algorithms with no Java equivalent today)

Plan §"Port-before-delete", line 683. These rules exist only in
Ruby and **MUST be ported into the new Java matchers/extractors
before the Ruby is deleted**. Numbered per plan; status column
will fill in during Stage B.

| # | Ruby algorithm | Java port target | Status | Plan PR |
|---|---|---|---|---|
| 1 | `OpponentRosterDisambiguator.resolve` (last-name-overlap tiebreak) | `TeamMatcher.disambiguateByLastNameOverlap()` | TODO | PR #9 |
| 2 | `TeamGameMatcher.determine_home_away` | `GameMatcher` Stage 1 helper | TODO | PR #10 |
| 3 | `TeamGameMatcher.find_or_create_shell` | `BackReconciler` | TODO | PR #10 |
| 4 | `TeamGameMatcher.scores_compatible?` | `GameMatcher` evidence rule 3 | TODO | PR #10 |
| 5 | `GameStatsExtractor.format_innings_thirds` + `parse_innings` (4.2 = 4⅔) | `pipeline/stage7_stats/InningsFormatter` | TODO | PR #21 |
| 6 | `GameStatsExtractor.upsert_player_stat` shared-last-names disambiguation | `PlayerStatsExtractor` | TODO | PR #21 |
| 7 | `GameStatsExtractor.distribute_team_batting_breakdowns` | `PlayerStatsExtractor` | TODO | PR #21 |
| 8 | `ReconciliationExecutor.propagateScoreToTeamGames` (Java; recently shipped Hawaii/Maine TG-divergence fix) | Stage 6 transactional UPSERT (`TeamGameScorePropagator`) | TODO | PR #20 |
| 9 | `MatchingService.extract_names` + `count_matches` | Verify parity with Java's existing `TeamAssignmentVerifier.verifyByRoster`; port any deltas (especially diacritics) | TODO | PR #19 |

---

# Deviations from plan

Things found during the walk that the plan didn't explicitly cover, and the proposed disposition for each. Sign-off requested before Stage B starts.

1. **`com.riseballs.scraper.controller.ScheduleVerificationController`** (137 LOC) — Java controller serving verification reports. Not on plan's DELETE list, but its purpose (verification reports) is supplanted by the new admin views over `pipeline_runs` + `pipeline_stage_audits`. **Proposed: DELETE.**
2. **`com.riseballs.scraper.service.NcaaApiClient`** (196 LOC) and adjacent records — plan mentions `pipeline/ncaa/` but doesn't enumerate the source classes. **Proposed: EXTRACT_LOGIC_TO_NEW** into `pipeline/ncaa/NcaaClient`.
3. **`com.riseballs.scraper.service.GameCreationService`** (234 LOC) and DTOs — not enumerated. **Proposed: EXTRACT_LOGIC_TO_NEW** into `pipeline/stage1_resolve/GameCreator`.
4. **`PitchingAudit::PlayerNameMatcher`** (109 LOC, deterministic-only) — second Ruby name matcher (`concerns/player_name_matcher.rb` is the trigram one). Both fold into the Java `PlayerMatcher` port (PR #9). Plan §Port-before-delete #1 mentions only one matcher; **flagging that two implementations exist** so the Java port covers both modes.
5. **Six rake tasks** (`standings`, `rpi`, `teams`, `cleanup`, `games`, `lib/tasks/standings.rake`) — sub-agent classified DELETE but they appear to be admin / out-of-scope utilities. **Proposed: KEEP_OUT_OF_SCOPE pending sign-off**; verify per-task before Phase 3.
6. **`script/audit_duplicate_boxscores.rb` and ~17 other `script/*.rb` files** — read-only diagnostic probes. **Proposed: keep through Stage F backfill, delete in a follow-up PR after `audit_pipeline_consistency.rb` lands** (Stage G). Plan didn't enumerate the `script/` directory.
7. **JavaScraperClient orphan methods** — five methods (`reconcile_check`, `reconcile_ncaa_dates_check`, `find_or_create_games_batch`, `scrape_standings_division`, `scrape_standings_conference`) have zero callers. **Proposed: DELETE in Phase 3a alongside the rest**, no Phase 1 guard needed (no Ruby caller can hit them).
8. **`AthleticsUrlDiscoveryJob`** (Rails) — actively scrapes external NCAA pages from Ruby. Out-of-scope-of-this-rebuild but a North Star §6 violation in spirit. **Proposed: KEEP_DEPRECATE_LATER** with an explicit follow-up PR for separate Java port. SSRF gate in Stage B (PR #8) will validate `Team.athletics_url` writes regardless.
9. **`ScraperApplication.java`** (12 LOC) — sub-agent classified DELETE. **Overridden to REUSE_AS_IS**: it's the Spring Boot main entry; Plan PR #22 explicitly adds `@EnableScheduling` here.
10. **Java `LineupExtractor` / `SidearmLineupParser` / `WmtLineupParser` / `LineupSlot`** — sub-agent classified EXTRACT_LOGIC_TO_NEW. **Overridden to KEEP_OUT_OF_SCOPE**: lineup extraction is explicitly out of scope per plan. The legacy `BoxscoreData` shim stays @Deprecated until the lineup PR lands.

---

# Sign-off checklist

Before Stage B begins (per plan §"Order of operations checklist", line 1035):

- [ ] User reviews this inventory + `cron-inventory.md` end-to-end.
- [ ] Sign-off on the 10 deviations above (or amend the disposition for any disputed item).
- [ ] Confirm Phase 1 guard list for the 11 cron DELETE entries.
- [ ] Confirm KEEP_DEPRECATE_LATER strategy for `AthleticsUrlDiscoveryJob`, `RosterAugmentAllJob`, `WmtSyncAllJob`, `CoachAugmentAllJob`, `StandingsRefreshJob`.
- [ ] Confirm port-before-delete list (9 algorithms) is complete.

After sign-off, PR #2 (game_number audit script) and PR #3 (game_number repair) start. Plan §"BLOCKERS" requires a clean
audit before any constraint changes ship.
