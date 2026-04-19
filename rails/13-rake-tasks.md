# Rake Tasks

Every rake task in `lib/tasks/*.rake`, grouped by purpose. Most are operator tools (diagnostics, one-shot repairs, seed data) rather than scheduled work.

## Table of Contents

- [Running conventions](#running-conventions)
- [PBP maintenance](#pbp-maintenance)
- [Schedules and games](#schedules-and-games)
- [NCAA discovery](#ncaa-discovery)
- [Stats and pitches](#stats-and-pitches)
- [Teams and rosters](#teams-and-rosters)
- [Slugs and aliases](#slugs-and-aliases)
- [Standings](#standings)
- [RPI](#rpi)
- [Cleanup](#cleanup)
- [Export](#export)
- [Debug tasks](#debug-tasks)

## Running conventions

- Local: `bin/rails <task>` against `DATABASE_URL=postgres://localhost/riseballs_local`.
- Production **without** Java scraper calls: `ssh dokku@ssh.mondokhealth.com run riseballs bin/rails <task>`. `dokku run` spins up a one-off container on the internal network but **cannot** resolve `riseballs-scraper.web`, so any task that calls `JavaScraperClient` will silently skip the scraper path.
- Production **with** Java scraper calls: `ssh dokku@ssh.mondokhealth.com -- enter riseballs web 'bin/rails <task>'`. Use this whenever the task touches `JavaScraperClient.*`, posts to `JAVA_SCRAPER_URL`, or invokes a job that does.
- Args pass through brackets: `rake games:sync_past[d1,14]`. Under zsh you must quote: `rake 'games:sync_past[d1,14]'`.
- Env-var flags: `DRY_RUN=1 rake ...`, `DEDUP_DRY_RUN=1 rake ...`, `SINCE_DATE=2026-03-01 rake ...`, `LIMIT=500 rake ...`, `TEAM=florida-st rake ...`, `SLUGS=a,b,c rake ...`, `CONFIRM_DELETE_ALL=yes rake ...` -- each task notes its own.

---

## PBP maintenance

### `rake pbp:purge_bad`

**File:** `lib/tasks/pbp.rake`
**Env:** `DRY_RUN=1` to preview.
Walks every cached PBP (`data_type IN ('athl_play_by_play', 'play_by_play')`), invokes the private `CachedGame.pbp_quality_ok?` gate, and deletes every entry that fails -- grouping deletions by `payload._source` for reporting. Use when the quality gate is tightened and you need to purge corrupted historical PBP. Safe as `dokku run` (pure DB).

### `rake pbp:refill`

**File:** `lib/tasks/pbp.rake`
**Env:** `LIMIT=N` (default 500).
Finds final games from the last 60 days with no cached PBP. For each: (1) tries to re-parse PBP from stored `ScrapedPage` HTML (via `AthleticsBoxScoreService.send(:parse, ...)`); (2) falls back to `WmtBoxScoreService.fetch_for_game`. Stores whichever passes the quality gate. **Safe as `dokku run`** (uses already-stored HTML and the WMT API directly; doesn't need the Java scraper).

### `rake audit_pbp`

**File:** `lib/tasks/audit_pbp.rake`
Audits every cached PBP for three classes of garbage:
- **garbage**: plays with text under 25 chars AND no play verbs.
- **missing teamId** on stat groups with real plays.
- **same teamId on both halves** of non-last innings (parser confusion).
Auto-deletes the "garbage" and "same teamId" groups. Logs IDs of "missing teamId" entries for follow-up with `rake fix_missing_team_ids`.

### `rake fix_pbp_groups`

**File:** `lib/tasks/fix_pbp_groups.rake`
Finds cached PBP where non-last innings have a single stat group with > 3 plays -- indicates both halves got merged into one group. Two repair strategies:
1. Re-parse from stored `ScrapedPage` HTML (the caption headers let `AthleticsBoxScoreService` split halves correctly).
2. Split using `PbpTeamSplitter.split` against the cached boxscore roster / `Player` table.
Verifies the split improved things before committing. Pure Ruby.

### `rake fix_missing_team_ids`

**File:** `lib/tasks/fix_missing_team_ids.rake`
For PBP entries where stat groups are correctly split but lack `teamId`, stamps `payload.teams[0].teamId` on the first group (away / top of inning) and `teams[1].teamId` on the second (home / bottom) per period. Updates in place.

### `rake reparse_pbp_from_html`

**File:** `lib/tasks/reparse_pbp_from_html.rake`
Re-parses PBP from already-stored `ScrapedPage` HTML **only** -- no external fetches. Indexes `ScrapedPage.where(page_type: 'boxscore')` by `team_id`, matches by opponent slug + aliases in the URL, runs `AthleticsBoxScoreService.parse`, and stores `athl_play_by_play` when periods >= 5. Safe as `dokku run`.

### `rake backfill_missing_pbp`

**File:** `lib/tasks/backfill_missing_pbp.rake`
Games with boxscore but no PBP -> try `AthleticsBoxScoreService.fetch(best_external_id, [home_slug, away_slug])` first, fall back to `WmtBoxScoreService.fetch_for_game`. Stores whichever succeeds. Does not use the Java scraper -- `dokku run` works.

### `rake reparse_nuxt_pbp`

**File:** `lib/tasks/reparse_nuxt_pbp.rake`
Finds single-period PBP cache entries with >= 20 plays (meaning the Nuxt scraper missed the inning structure) and deletes them, so the Java scraper re-fetches with proper inning boundaries on the next pipeline cycle. Prints instructions: "Run `rails refetch_missing_pbp` from dokku enter to re-fetch via Java scraper."

### `rake refetch_missing_pbp`

**File:** `lib/tasks/reparse_nuxt_pbp.rake` (second task in the same file)
**Requires** `dokku enter` -- calls `JavaScraperClient.scrape_batch`. Finds games with boxscore but no PBP and feeds them to the Java scraper in batches of 10. Aborts with exit 1 if `JavaScraperClient.available?` is false. This is the same operation as `RefetchMissingPbpJob`.

### `rake reparse_pbp`

**File:** `lib/tasks/reparse_pbp.rake`
Same as `ReparsePbpJob`: re-runs `PitchByPitchParser.parse_from_cached_pbp!` on every cached `athl_play_by_play` linked to a `Game`. Use when `PitchByPitchParser` logic has been updated and you want to re-materialize `plate_appearances` + `pitch_events`. Safe as `dokku run`.

### `rake refetch_bad_pbp`

**File:** `lib/tasks/refetch_bad_pbp.rake`
Deletes single-stat-group PBP entries and immediately re-fetches them via `AthleticsBoxScoreService.fetch` (pure Ruby, not via Java scraper). Keeps whichever returns periods >= 5.

### `rake debug_pbp_failures`

**File:** `lib/tasks/debug_pbp_failures.rake`
Diagnostic -- walks up to 15 games with bad PBP (single stat group on non-last innings), calls `AthleticsBoxScoreService.fetch`, and logs `OK`, `FAIL reason=...`, or `ERROR`. Use to decide whether a class of failures is worth fixing.

---

## Schedules and games

### `rake schedules:warm`

**File:** `lib/tasks/schedules.rake`
Pre-warms stale `CachedSchedule` for all teams with an `athletics_url` that don't already have one cached. 8 threads at a time. `dokku run` is fine.

### `rake schedules:refresh`

**File:** `lib/tasks/schedules.rake`
**Destructive**: `CachedSchedule.delete_all` + deletes games with nil slugs or no `ncaa_game_id`, then re-crawls every team's schedule via `ScheduleService.build_schedule`. Use only when the cache shape changed.

### `rake schedules:recover_stuck`

**File:** `lib/tasks/schedules.rake`
**Env:** `SLUGS=a,b,c` to target specific teams (default: auto-detect via `ScheduleRecoveryService.stuck_team_slugs`). `SKIP_SCRAPE=1` to use games-table backfill only.
Manual version of `StuckScheduleRecoveryJob`. Logs per-team result and total rows added.

### `rake games:repair`

**File:** `lib/tasks/repair_links.rake`
Three-phase repair: (1) re-creates missing `GameTeamLink` rows for every team needing them by scraping their Cloudflare-fronted schedule page and matching games by date+team; (2) fetches missing box scores via `CloudflareBoxScoreService` + `AthleticsBoxScoreService`; (3) fetches missing PBP for games with boxscores. Retries up to 3x on timeouts. **Heavy**: can take an hour.

### `rake games:lock_stale`

**File:** `lib/tasks/games.rake`
Locks every unlocked final `cached_games` row via `CachedGame.try_lock!`. Run after a data-quality sweep to freeze known-good rows from being overwritten.

### `rake games:sync_past[division,days]`

**File:** `lib/tasks/games.rake`
Walks NCAA scoreboard from season start (D1: 2026-02-06, D2: 2026-01-30) through yesterday (or last N days), syncs games via the NCAA GraphQL API (historically `NcaaScoreboardService.sync_date`; that Ruby class was deleted 2026-04-19, and the task now calls the API directly with the same persisted-query hash). Then fetches box scores via `BoxscoreFetchService.fetch` for any final game missing one. Examples:
- `rake games:sync_past` -- D1 + D2 full season
- `rake games:sync_past[d1]` -- D1 only
- `rake games:sync_past[d1,14]` -- D1, last 14 days only
Pure Ruby -- `dokku run` works.

### `rake games:dedup`

**File:** `lib/tasks/dedup_games.rake`
Finds matchups (date + home + away) with > 2 games -- anything beyond a doubleheader is a duplicate -- and merges the extras into the two oldest. Transfers `GameTeamLink`, `GameIdentifier`, deletes orphaned `CachedGame` rows, and moves the newer `ncaa_contest_id` onto the keeper. Re-numbers `game_number` 1-2 on survivors. **Older / narrower** than `GameDedupJob`; prefer the job.

### `rake games:fill_missing_boxscores`

**File:** `lib/tasks/fill_missing_boxscores.rake` (1285 LOC -- the largest rake file, carries many sub-tasks).
**Env:** `SINCE_DATE=YYYY-MM-DD` to limit scope.
The classic end-to-end fill pipeline -- links games, scrapes boxscores via Cloudflare, batches to AI extraction. Now superseded by `GamePipelineJob` + `BoxScoreBackfillJob` in practice, but still useful as a bulk "do-it-all" repair. Requires `CLOUDFLARE_BROWSER_TOKEN` and `OPENAI_API_KEY`.

### Related sub-tasks in `fill_missing_boxscores.rake`

All namespaced under `games:`:
- `games:trigram_test` (`TEAM=...`) -- shows roster vs box score name mapping with trigram + prefix match scoring. Diagnostic.
- `games:fix_duplicate_games` -- finds/removes duplicates with same date+home+score but different away.
- `games:fix_orphan_slugs` -- fixes known orphan team slugs in games. `known_mappings` updated 2026-04-19 (mondok/riseballs#81, PR #92): the last stale `east-tex-am` reference was changed to `east-texas-am` (the canonical slug on the Rails side). Note: the Java scraper's `NcaaApiClient.SEONAME_MAP` still rewrites `tex-am-commerce` → `east-tex-am` on the Java side — that mapping is unchanged (different layer).
- `games:deduplicate` (`DRY_RUN=1`) -- another dedup pass; merges true duplicates (not doubleheaders).
- `games:relink_cached_data` -- sets `cached_games.game_id` from `ncaa_game_id` where missing.
- `games:correct_slugs` -- detects + corrects team slug mismatches between boxscores and Game rows.
- `games:fix_pbp_names` -- re-stamps all PBP team names from Game records.
- `games:rebuild_player_stats` (`CONFIRM_DELETE_ALL=yes` required) -- nukes and re-extracts all PGS from stored boxscores.
- `games:fix_unmatched_names` (`DRY_RUN=1`) -- fixes unmatched player names in boxscores + PGS via trigram + prefix.
- `games:sample_short_names` -- sample truly truncated (initial-only) unmatched names.
- `games:detect_swapped_boxscores` (`DRY_RUN=1`) -- detects swapped home/away boxscore assignments via roster matching.
- `games:fix_player_names` -- trigram + prefix matching against roster.
- `games:consolidate_player_stats` -- merges duplicate PGS rows for the same player in the same game.

### `rake fix:doubleheaders`

**File:** `lib/tasks/fix_doubleheaders.rake`
(1) Finds cached box scores whose linescore R row doesn't match the Game's score, deletes them plus any linked PBP. (2) Triggers `POST JAVA_SCRAPER_URL/api/team-schedule/sync-all` to rebuild missing doubleheader `team_games`. (3) Runs `TeamGameMatcher` to create shells. (4) Reports doubleheader coverage. **Requires `dokku enter`** for step 2.

### `rake check:dh`

**File:** `lib/tasks/check_dh.rake`
Diagnostic: counts past doubleheaders (finals since 2026-03-01), future doubleheaders, and teams with future games but missing DHs. Samples the first 10 missing teams. Read-only.

### `rake stats:check_cancelled`

**File:** `lib/tasks/check_cancelled.rake`
Walks games `state = 'cancelled'` in the last 7 days; for each, calls `WmtBoxScoreService.fetch_for_game`. If the WMT API returns data, the game was actually played. Prints `PLAYED: ...` lines for investigation. Read-only.

### `rake debug:wrong_scores`

**File:** `lib/tasks/debug_wrong_scores.rake`
Diagnostic: finds `team_games` where `Game.home_score/away_score` don't match the team_game's `team_score/opponent_score` in either direction. Dumps full context (all linked team_games, all games for the matchup).

### `rake debug:fix_lewis`

**File:** `lib/tasks/debug_wrong_scores.rake`
One-shot fix for a specific Lewis / Missouri S&T mix-up on 2026-04-12. Leave alone unless you're chasing that historical bug.

### `rake debug:unmatched`

**File:** `lib/tasks/debug_unmatched.rake`
Diagnostic: for each unmatched final `team_game` (`game_id IS NULL AND state = 'final'`), prints why it didn't match -- opponent team_games on same date, existing Game shells for the matchup.

### `rake stats:discover_urls[opts]`

**File:** `lib/tasks/discover_boxscore_urls.rake`
Finds AI-extracted games where the box score URL is bad or missing, scrapes team schedule pages via `BoxscoreUrlDiscoveryService.discover`, updates `GameTeamLink.box_score_url`. Options: `team:florida-st`, `limit:50`. Read-only on games (only `GameTeamLink.box_score_url` changes).

---

## NCAA discovery

### `rake games:discover[mode,date]`

**File:** `lib/tasks/ncaa_discovery.rake`
Syncs games from the NCAA.com GraphQL API. Historically delegated to `NcaaScheduleService`; that Ruby class was deleted 2026-04-19. The task (and `NcaaGameDiscoveryJob`, which this task is a CLI wrapper for) now calls the API inline using the same persisted-query hash as the Java scraper and `riseballs-live`.
- `rake games:discover` or `rake games:discover[today]` -- sync today + yesterday, D1 + D2.
- `rake games:discover[season]` -- full-season backfill, D1 + D2.
- `rake games:discover[date,2026-04-01]` -- specific date.
Identical to `NcaaGameDiscoveryJob` but invokable from CLI. Pure Ruby.

---

## Stats and pitches

### `rake stats:backfill[limit]`

**File:** `lib/tasks/stats.rake`
Backfills `player_game_stats` from existing cached boxscores (`boxscore`, `athl_boxscore`, `sb_boxscore`). Excludes games already extracted. Runs 8 threads in parallel. Also writes a `game_snapshots` row per game.

### `rake stats:backfill_athletics[team_slug]`

**File:** `lib/tasks/stats.rake`
Scrapes every box score URL from each team's athletics site schedule, matches to NCAA game IDs by date+opponent, extracts full batting stats (HR, 2B, 3B). Can target a single team.

### `rake stats:sample_queries`

**File:** `lib/tasks/stats.rake`
Prints batting leaders (D1, min 20 AB), hot hitters (last 7 days), total row counts. Read-only.

### `rake stats:backfill_decisions[mode]`

**File:** `lib/tasks/backfill_decisions.rake`
**Arg:** `dry_run` to preview.
Backfills pitcher W/L/S decisions from cached boxscores' `player.decision` field. Only touches PGS rows where decision is currently NULL and the boxscore has a value. Matches by `(ncaa_game_id, team_seo_slug, player_name)` with last-name fallback. `update_column` writes bypass validation. Safe as `dokku run`.

### `rake stats:backfill_pitch_counts[mode]`

**File:** `lib/tasks/backfill_pitch_counts.rake`
**Arg:** `dry_run` to preview.
Finds games where pitchers have `pitch_count = 0`, re-runs `GameStatsExtractor.extract` on the cached boxscore (which now reads `NP`/`pitchCount`). Safe as `dokku run`.

### `rake pitches:backfill[team_slug]`

**File:** `lib/tasks/pitches.rake`
For one team (default `montevallo`), walks their Sidearm schedule, scrapes every `/boxscore/` URL, calls `PitchByPitchParser.parse_and_store!`. Writes `plate_appearances` + `pitch_events`.

### `rake pitches:backfill_all`

**File:** `lib/tasks/pitches.rake`
For every team with `athletics_url`, for every final Game: skip if that team already has >= 40 `plate_appearances` on that game; else try cached PBP -> WMT API -> Sidearm scraping, keep whichever yields the most real plays. Stores the winner to `cached_games` and re-parses.

### `rake pitches:summary[team_slug]`

**File:** `lib/tasks/pitches.rake`
Analytics dump for one team: first-pitch tendencies, avg pitches/PA, per-batter take vs. swing rates, steals, wild pitches, passed balls. Read-only.

### `rake diagnose_decisions`

**File:** `lib/tasks/diagnose_decisions.rake`
Diagnostic: for every roster pitcher with IP > 0 but 0W/0L, tries to find a matching decision PGS row. Buckets results as:
- TRUE_MISMATCH (same person, aggregation failed -- bug)
- DIFF_PERSON (same last name, not a bug)
- legit zero, no PGS, no boxscore.
Useful after an aggregation change.

---

## Teams and rosters

### `rake teams:backfill_conferences`

**File:** `lib/tasks/teams.rake`
Updates `teams.conference` (display name) from `teams.conference_seo` via the `CONFERENCE_NAMES` map at the top of that file.

### `rake teams:load_aliases`

**File:** `lib/tasks/teams.rake`
Loads `db/team_aliases.rb` (`TEAM_ALIASES` hash of `slug => [abbreviation, nickname]`) and fills `teams.abbreviation` + `teams.nickname` for rows where those are blank.

### `rake teams:clean`

**File:** `lib/tasks/clean_teams.rake`
**Env:** `DRY_RUN=1` to preview (default is effectively dry unless `DRY_RUN=0`).
Scans NCAA scoreboard across the season, tags teams as D1 or D2 (D1 wins on conflict), updates `conference`/`conference_seo` from NCAA data. Deletes all non-D1/D2 teams and any D1/D2 team with zero games (tagged but no softball program). Also deletes `miami-fl` explicitly. **Destructive** -- read the `DRY_RUN` semantics first: the default `DRY_RUN != "0"` means dry-run is the default.

### `rake rosters:sync_all`

**File:** `lib/tasks/rosters.rake`
Walks every team, nukes `roster_updated_at` so the sync actually runs, calls `RosterService.sync_roster(team)`. 0.5s rate limit. Prints per-team status.

### `rake rosters:discover_urls`

**File:** `lib/tasks/rosters.rake`
For every team with missing `athletics_url`, calls `RosterService#discover_athletics_url`. 0.3s rate limit. (Same logic as `AthleticsUrlDiscoveryJob` but synchronous CLI version.)

### `rake stats:warm_scoreboards[division,days]`

**File:** `lib/tasks/rosters.rake`
**Args:** `division` = `d1` (default) or `d2`, `days` = 14 default.
Warms the NCAA scoreboard cache for the last N days by calling the NCAA GraphQL API per day (historically via `NcaaScoreboardService.contests_for_date`; the call site was inlined when that Ruby class was deleted 2026-04-19).

### `rake stats:warm_schedules`

**File:** `lib/tasks/rosters.rake`
For every team with `athletics_url`, calls `ScheduleService.games_for_team(team)`. Populates `CachedSchedule`.

### `rake sync:all`

**File:** `lib/tasks/rosters.rake`
Four-step "full sync": rankings -> discover missing athletics URLs -> sync rosters/stats/photos/coaches for every team -> warm schedule caches. Slow (hours). The nightly equivalents are `SyncRankingsJob`, `AthleticsUrlDiscoveryJob`, and the ad-hoc roster/schedule jobs.

---

## Slugs and aliases

### `rake slugs:audit`

**File:** `lib/tasks/slugs.rake`
Reports on opponent slug coverage in `team_games`:
- Unresolved (NULL / blank `opponent_slug`) with counts and sample references.
- Unknown slugs (set but no Team row) with a WARNING for anything appearing 5+ times.
- Ambiguous names (same `opponent_name` -> multiple `opponent_slug`).
- Duplicate `TeamAlias.alias_name` rows (must be zero -- aliases must be unique).
Ends with percent-resolved summary.

### `rake slugs:suggest`

**File:** `lib/tasks/slugs.rake`
For each unresolved opponent name, runs `find_candidates` -- exact name/long_name match, slug match, with/without `University`/`College`/`State`/`Univ` suffix, ILIKE broad search, division filter on context. Prints `MATCH`, `AMBIGUOUS`, or `NO MATCH`. Does **not** auto-create aliases -- prints ready-to-copy `TeamAlias.create!(...)` lines for the operator to paste into the Rails console.

---

## Standings

### `rake standings:seed_2026`

**File:** `lib/tasks/standings.rake`
Seeds `conference_sources` for the 2026 season, D1 + D2. **Sets `tournament_spots` and `tournament_format` on every conference**, derived from `tournament_style.md`. Idempotent: `find_or_initialize_by(season, division, conference)`; only updates `tournament_spots` / `tournament_format` when they differ, doesn't overwrite other fields on already-existing rows. Values fully enumerated inline (e.g., ACC = 12 spots / single_elim, SEC = 15 / single_elim, Big 12 = 11 / single_elim, Ivy = 4 / best_of_3, etc.). Run once per season to lock in bracket structure.

---

## RPI

### `rake rpi:recalculate_only[division]`

**File:** `lib/tasks/rpi.rake`
**Args:** `division` = `d1`, `d2`, or omitted (= both).
Recomputes RPI (and W-L) from scoreboard cache **without** re-syncing game data. Calls `RpiService.calculate(division: div)`. Skipped teams fall below `RpiService::MIN_GAMES`.

### `rake rpi:calculate[division]`

**File:** `lib/tasks/rpi.rake`
Full path: (1) invokes `games:sync_past` to pull every past score from NCAA so the game graph is complete; (2) runs `RpiService.calculate` per division. Much slower than `recalculate_only` -- use after a schedule correction.

---

## Cleanup

### `rake cleanup:all`

**File:** `lib/tasks/cleanup.rake`
Catch-all cleanup that belongs at the end of a repair session:
1. `TeamGameMatcher.match_scheduled` + `match_all`.
2. Orphaned `Game` delete (no `team_games` linked).
3. Delete self-play `team_games` (opponent resolves to self -- intrasquad / exhibition).
4. Re-sync scores from `team_games` onto `games` wherever `GameTeamLink` disagrees with `TeamGame.team_score`.
Reports remaining unmatched / orphans / wrong-score links.

---

## Export

### `rake stats:export_urls`

**File:** `lib/tasks/export_urls.rake`
Dumps every `GameTeamLink.box_score_url` for games whose PGS came from `batch_ai` or `cloudflare_ai` extraction as a JSON array to stdout. Capture with `> urls.json`.

---

## Debug tasks

Every `debug:*` task is read-only unless noted:

| Task | Namespace | Purpose |
| --- | --- | --- |
| `debug:unmatched` | `lib/tasks/debug_unmatched.rake` | Dump unmatched final team_games with context. |
| `debug:wrong_scores` | `lib/tasks/debug_wrong_scores.rake` | Dump score mismatches between `games` and `team_games`. |
| `debug:fix_lewis` | `lib/tasks/debug_wrong_scores.rake` | **Write**. One-shot fix for 2026-04-12 Lewis / Missouri S&T mix-up. |
| `check:dh` | `lib/tasks/check_dh.rake` | Count past/future doubleheaders; flag teams missing future DH. |
| `stats:check_cancelled` | `lib/tasks/check_cancelled.rake` | Flag cancelled games that WMT still has data for (probably actually played). |
| `debug_pbp_failures` | `lib/tasks/debug_pbp_failures.rake` | Walk up to 15 bad-PBP games, show why they can't be refetched. |
