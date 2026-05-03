# Phase 3b Deletion Checklist (PR #32 prep)

**Plan reference:** `PIPELINE_REBUILD_PLAN.md` v5 §sequencing list line 1850.

This file is the operator runbook for PR #32 -- the large
Ruby-side deletion that runs after Phase 2 flag flip stable for
48h. It is NOT safe to execute today: the legacy jobs are still
on disk (with `PipelineV2Guard` short-circuiting them), the
admin/* paths still reference some DELETE-list services, and
deleting these files before Phase 2 succeeds breaks production.

**DO NOT DELETE BEFORE:**
1. `PIPELINE_V2_ENABLED=true` on both apps for 48h.
2. `pipeline_v2:audit_backfill` exit 0 on prod.
3. Stage 7 dry-run report (PR #29) reviewed & signed off.
4. Shadow-run zero-diff for 24h (PR #27).
5. CI's `STAGE_G_ENFORCE=true` flipped (PR #35) and green.

## Deletion order (no semantic dependency between groups; pick any)

### Group A -- DELETE-list services (25 files)

```
app/services/athletics_box_score_service.rb
app/services/boxscore_fetch_service.rb
app/services/cloudflare_box_score_service.rb
app/services/cloudflare_schedule_service.rb
app/services/wmt_box_score_service.rb
app/services/schedule_service.rb
app/services/site_record_fetcher.rb
app/services/today_games_service.rb
app/services/roster_service.rb
app/services/boxscore_url_discovery_service.rb
app/services/concerns/sidearm_helper.rb
app/services/concerns/player_name_matcher.rb
app/services/boxscore_dupe_guard.rb
app/services/team_matcher.rb
app/services/team_game_matcher.rb
app/services/matching_service.rb
app/services/opponent_roster_disambiguator.rb
app/services/pitch_by_pitch_parser.rb
app/services/pbp_team_splitter.rb
app/services/pitcher_enrichment_service.rb
app/services/game_stats_extractor.rb
app/services/player_stats_calculator.rb
app/services/game_finalization_scorer.rb
app/services/series_guard_service.rb
app/services/team_game_cross_link_auditor.rb
```

### Group B -- box_score_parsers (4 files, entire dir)

```
app/services/box_score_parsers/base.rb
app/services/box_score_parsers/presto_sports_parser.rb
app/services/box_score_parsers/sidearm_parser.rb
app/services/box_score_parsers/wmt_parser.rb
```

Plus the directory itself: `rmdir app/services/box_score_parsers/`.

### Group C -- pitching_audit (18 files, entire dir)

```
app/services/pitching_audit/boxscore_alignment_repairer.rb
app/services/pitching_audit/diff_engine.rb
app/services/pitching_audit/ip_thirds.rb
app/services/pitching_audit/misattribution_repairer.rb
app/services/pitching_audit/pitcher_stat_line.rb
app/services/pitching_audit/player_name_matcher.rb
app/services/pitching_audit/roster_cross_check.rb
app/services/pitching_audit/source_detector.rb
app/services/pitching_audit/source_fetcher.rb
app/services/pitching_audit/team_canonicalizer.rb
app/services/pitching_audit/team_merger.rb
app/services/pitching_audit/sources/base.rb
app/services/pitching_audit/sources/js_rendered_via_localscraper.rb
app/services/pitching_audit/sources/presto_sports_html.rb
app/services/pitching_audit/sources/sidearm_html.rb
app/services/pitching_audit/sources/sidearm_nuxt.rb
app/services/pitching_audit/sources/stat_crew_pdf.rb
app/services/pitching_audit/sources/wmt_season_stats.rb
```

Plus dirs: `rmdir app/services/pitching_audit/sources/ app/services/pitching_audit/`.

### Group D -- DELETE-list jobs (11 files, the cron-inventory DELETE entries)

```
app/jobs/game_pipeline_job.rb
app/jobs/ncaa_date_reconciliation_job.rb
app/jobs/ncaa_date_reconciliation_hourly_job.rb
app/jobs/ncaa_dh_inversion_resolver_job.rb
app/jobs/boxscore_score_consistency_job.rb
app/jobs/schedule_reconciliation_job.rb
app/jobs/orphaned_team_game_repair_job.rb
app/jobs/score_validation_job.rb
app/jobs/game_dedup_job.rb
app/jobs/box_score_backfill_job.rb
app/jobs/pitching_audit_job.rb
```

Plus the secondary jobs that called services in Group A (verify
no references remain after Group A deletion):

```
app/jobs/pbp_on_final_job.rb
app/jobs/reparse_pbp_job.rb
app/jobs/refetch_missing_pbp_job.rb
```

### Group E -- DELETE-list rake tasks (~34 files)

See old-pipeline-inventory.md §1.8 "lib/tasks/" for the full
list. Each is verified read-only-on-DB or external-only-write,
so they do not need re-implementation in Java; they're audit/
backfill scripts that the new pipeline structurally obviates.

### Group F -- corresponding tests

```
test/services/{athletics_box_score,boxscore_fetch,...}_test.rb
test/jobs/{game_pipeline,...}_test.rb
test/services/box_score_parsers/
test/services/pitching_audit/
```

`bin/rails test` after each group.

### Group G -- JavaScraperClient method removals

Per `old-pipeline-inventory.md` §3, remove the 12 DELETE methods:
`scrape_game`, `scrape_batch`, `sync_team_schedule`,
`reconcile_team`, `reconcile`, `retry_failed_teams`,
`reconcile_check`, `find_or_create_game`,
`find_or_create_games_batch`, `reconcile_ncaa_dates`,
`reconcile_ncaa_dates_check`, `build_reconcile_query`.
Keep: `available?`, `healthy?`, `augment_*`, `wmt_sync_*`,
`compute_d1_metrics`, `scrape_standings*`.

Add: `process_game(game_id:, ncaa_contest_id:, trigger_source:)`
calling `POST /api/pipeline/process-game` with the
`X-Pipeline-Token` header. Caller: admin manual-trigger UI.

### Group H -- partial cleanup of game_show_service.rb

Per `old-pipeline-inventory.md` §1.1 PARTIAL_DELETE, strip:
- `patch_show_scores`
- `patch_scores_from_boxscore_fetch`
- `patch_from_game_record`
- `boxscore_linescores`
- `extract_last_play`

Keep the rest (`enrich_show_data` minus score patching).

Update `Api::GamesController#show` to remove every `patch_*`
call.

### Group I -- frontend route changes

`Api::GamesController` deprecated controllers
(`/api/scrape/*`, `/api/team-schedule/*`, `/api/games/find-or-create`)
become **410 Gone** for 2 weeks before final removal (plan §982).
A 410 ApplicationController concern + a route hint registers them.

### CI flip

After Groups A-H land green:

```yaml
# .github/workflows/ci.yml
- name: Pipeline v2 single-writer lock
  run: STAGE_G_ENFORCE=true bash script/check_no_pipeline_v1_writes.sh
```

(PR #35 currently runs the script in non-enforce mode; flipping
the env makes the build fail on any new violation.)

## Verification after each Group

```sh
bin/rubocop                                            # 0 offenses required
bin/brakeman --no-pager                                # green
bin/rails test                                         # all green
DATABASE_URL=... bin/rails runner script/audit_pipeline_consistency.rb  # GREEN
```

## Rollback (Phase 3b only)

`git revert <commit>` on the deletion commits restores the
files. The schema is unaffected; the v2 pipeline keeps running
as authoritative.
