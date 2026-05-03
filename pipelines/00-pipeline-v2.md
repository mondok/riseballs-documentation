# Pipeline v2 — the 7-stage DAG

The v2 pipeline replaces the legacy 3-trigger sprawl
(`GamePipelineJob`, `ReconciliationOrchestrator`,
`NcaaDateReconciliationService`) with a single Java DAG and three
sibling cron concerns. It's the canonical answer to
"how does a game get on Riseballs?" after Phase 2 cutover.

> **Status (2026-05-02):** Java DAG code shipped through PR #22.
> Phase 1 deploy ready (flag-gated, no-op until
> `PIPELINE_V2_ENABLED=true`). Phase 2 flip is operator-driven; see
> [pre-flip checklist](../audits/phase-3b-deletion-checklist.md)
> first. Parser MOVE PRs (#13-17) and the documentation rewrite
> for the legacy pages are in flight.

## The DAG at a glance

```
HourlyScheduleSweep ──┐
                       │
PipelineTriggerCtl ────┼──> ProcessScheduleEntry
                       │       │
BackReconcilerNightly ─┘       ▼
                          ┌─────────────────────────┐
                          │ Stage 1: Resolve        │
                          │   GameMatcher           │
                          │   SlotArray (advisory)  │
                          │   BackReconciler        │
                          └────────────┬────────────┘
                                        │ ResolvedTarget
                                        ▼
                          ┌─────────────────────────┐
                          │ Stage 2: Fetch          │
                          │   PageFetcher chain     │
                          │   HttpStrategy          │
                          │   (+4 strategies in     │
                          │    PR #11 follow-on)    │
                          │   HostTokenBucket       │
                          │   CircuitBreaker        │
                          └────────────┬────────────┘
                                        │ FetchedPage
                                        ▼
                          ┌─────────────────────────┐
                          │ Stage 3: Parse          │
                          │   BoxscoreParserDispatch│
                          │   (+ parsers MOVE       │
                          │    PR #13-17 follow-on) │
                          └────────────┬────────────┘
                                        │ List<BoxscoreBundle>
                                        ▼
                          ┌─────────────────────────┐
                          │ Stage 4: Verify         │
                          │   BundleConsistencyCheck│
                          │   (totals, URL-date,    │
                          │    PBP identity, thin)  │
                          └────────────┬────────────┘
                                        │ List<VerifiedBundle>
                                        ▼
                          ┌─────────────────────────┐
                          │ Stage 5: Reconcile      │
                          │   (per-Game advisory    │
                          │    lock; re-read all    │
                          │    bundles inside lock) │
                          │   CanonicalBundleSelect │
                          │   OrientationFlipper    │
                          └────────────┬────────────┘
                                        │ ReconciledGame
                                        ▼
                          ┌─────────────────────────┐
                          │ Stage 6: Persist        │
                          │   PipelinePersister     │
                          │   (only writer to       │
                          │    cached_games + score │
                          │    columns; ArchUnit    │
                          │    enforced at compile) │
                          │   TeamGameScorePropagat │
                          │   (lifted Hawaii/Maine  │
                          │    fix)                 │
                          └────────────┬────────────┘
                                        │ PersistResult
                                        ▼
                          ┌─────────────────────────┐
                          │ Stage 7: Stats          │
                          │   PlayerStatsExtractor  │
                          │   (re-derives PGS by    │
                          │    bundle_hash +        │
                          │    NormalizerVersion)   │
                          │   InningsFormatter      │
                          │   (4.2 = 14 outs)       │
                          └────────────┬────────────┘
                                        │
                                        ▼
                                  pipeline_runs +
                                  pipeline_stage_audits +
                                  pipeline_events

(Sibling cron, NOT in the numbered DAG)
NcaaEnrichment -- daily NCAA contest_id attachment
                  + provisional-only scores
```

## Triggers

Three `@Scheduled` methods + one HTTP endpoint, all flag-gated by
`PIPELINE_V2_ENABLED`:

| Trigger | Class | Cadence | Purpose |
|---|---|---|---|
| Hourly sweep | `pipeline.HourlyScheduleSweep` | `0 0 * * * *` | Catch-all per-team schedule walk |
| Scoreboard fan-out | `pipeline.PipelineTriggerController` POST `/api/pipeline/process-game` | event | Acceleration when a scoreboard poller sees a final |
| Nightly | `pipeline.BackReconcilerNightly` | `0 0 5 * * *` | Re-emit every D1/D2 played game (idempotent; same `bundle_hash` = Stage 6 noop) |
| NCAA | `pipeline.ncaa.NcaaEnrichment` | `0 30 2 * * *` | Daily contest_id attachment; provisional-only scores |

## Inviolable rules

1. **One writer.** `Stage 6.PipelinePersister` is the only class
   that may write to `cached_games`, score columns of `games`, or
   `game_team_links`. Enforced at compile by ArchUnit rules 2/3.
2. **No silent fall-through.** Matchers return RESOLVED /
   AMBIGUOUS / UNRESOLVED. "Pick first" is forbidden everywhere
   (sealed `MatchResult`).
3. **Java owns ingestion.** No Ruby code reads from external
   sites, parses HTML, matches teams/games/players, or writes to
   the gated tables. Enforced at CI by
   [`script/check_no_pipeline_v1_writes.sh`](../../riseballs/script/check_no_pipeline_v1_writes.sh).
4. **Idempotence per input, not per Game-id-over-time.** Same
   input + same DB state -> same end state. Stage 6 no-op
   detection on `bundle_hash` is the load-bearing primitive.
5. **Canonical guarantee.** At most one
   `cached_games(game_id, data_type) WHERE is_canonical=true AND
   verification_status='accepted'` row at a time. Enforced by the
   partial unique from PR #6.
6. **Demote-then-promote in one tx.** Stage 6 demotes any prior
   canonical, then promotes the new winner via UPSERT keyed by
   `(game_id, data_type, team_slug)`, then commits. The partial
   unique is satisfied at commit time.

## Canonical-bundle 4-key tiebreaker

Plan §"Canonical-bundle selection". Stage 5 ranks all accepted
bundles for a Game by:

```
ORDER BY bundle_priority DESC,        -- NCAA-final=10, hosting=5, visiting=3
         page_published_at ASC NULLS LAST,
         fetched_at ASC,
         source_url ASC
```

Hosting determined from venue evidence + NCAA contest data + the
first bundle that asserts `home` with `neutral_site=false`.

## Score visibility

`Game.score_source` ∈ `{provisional, bundle, ncaa_final, ncaa_provisional_fallback}`.

| State | Source | Allowed writers |
|---|---|---|
| `NULL` | (no scores yet) | NCAA enrichment may write `provisional` |
| `provisional` | NCAA scoreboard | NCAA enrichment OR Stage 5 (overwrites) |
| `bundle` | School-site canonical | Stage 5 ONLY; NCAA enrichment cannot overwrite |
| `ncaa_final` | NCAA priority-10 bundle | Stage 5 (with priority=10 bundle) |
| `ncaa_provisional_fallback` | Stale-team degraded mode | Stage 5 |

CHECK constraint enforces the enum (PR #6).

## Observability

- `pipeline_runs(id UUID, started_at, completed_at, outcome,
  source_team_slug, game_id, halted_at_stage, halt_reason,
  pipeline_version, trigger_source)` -- one per
  `ProcessScheduleEntry` invocation.
- `pipeline_stage_audits(run_id, stage, stage_name, started_at,
  completed_at, duration_ms, outcome, reason, inputs, outputs,
  writes, decision_trace)` -- one per stage transition.
- `pipeline_events(ts, schedule_entry_fingerprint, game_id, stage,
  outcome, reason, source_url, bundle_hash, details)` -- alert-
  shaped log.
- `ncaa_enrichment_audits(contest_id, run_at, outcome, game_id,
  prior_game_id, reason)` -- daily contest log.

Admin views over all four:
- `/admin/pipeline_runs` (filterable by game_id, team_slug,
  trigger_source, halted_at_stage)
- `/admin/pipeline_runs/:id` (full lineage of one run; 7 stage
  audit rows in stage order)
- `/admin/pipeline_events` (filterable by game_id, stage, outcome)

Prometheus surface: `/actuator/prometheus` exposes
`pipeline_entries_processed_total{outcome}`,
`pipeline_bundle_verify_failures_total{reason}`,
`pipeline_canonical_flips_total`,
`pipeline_stage_duration_seconds{stage}`,
`fetcher_calls_total{strategy,host,status}`,
`fetcher_throttle_waits_total{host}`.

## Forensics: "rb_267189 is wrong"

Before Stage G nightly audit catches it, you can trace any Game:

```sql
-- last 5 runs that touched this game
SELECT * FROM pipeline_runs WHERE game_id = 267189
 ORDER BY started_at DESC LIMIT 5;

-- full lineage of one run
SELECT stage, stage_name, outcome, reason, decision_trace
  FROM pipeline_stage_audits
 WHERE run_id = '<uuid>' ORDER BY stage;

-- stage 5 candidate ranking
SELECT decision_trace FROM pipeline_stage_audits
 WHERE run_id = '<uuid>' AND stage = 5;
-- decision_trace JSONB has candidates_with_priority + tiebreak_winner_reason
```

No log archaeology. No replaying scrapes. Every transition is
recorded.

## Component map

### `riseballs-scraper` (Java)

```
com.riseballs.scraper.pipeline/
  PipelineConfig.java                 (@EnableScheduling)
  PipelineFlag.java                   (env-driven kill switch)
  ScheduleEntry.java                  (Stage 0 input record)
  HourlyScheduleSweep.java            (Trigger 1)
  BackReconcilerNightly.java          (Trigger 3)
  PipelineTriggerController.java      (Trigger 2 endpoint)
  matchers/
    MatchResult.java                  (sealed Resolved/Ambiguous/Unresolved)
    NameUtils.java                    (MOVE)
    TeamMatcher.java                  (15-step contract)
    PlayerMatcher.java                (NEW; trigram + initials + char-intersect)
  stage1_resolve/
    ResolvedTarget.java
    GameMatcher.java                  (7-step evidence ladder)
    SlotArray.java                    (per-team advisory lock)
    BackReconciler.java               (1/24h budget gate)
  stage2_fetch/
    FetchedPage.java
    FetchStrategy.java                (chain link interface)
    PageFetcher.java                  (dispatcher)
    HttpStrategy.java                 (HTTP/1.1 forced)
    HostTokenBucket.java              (per-host lock-free)
    CircuitBreaker.java               (CLOSED/OPEN/HALF_OPEN)
  stage3_parse/
    BoxscoreBundle.java               (alphabetic JSON ordering)
    BoxscoreParser.java
    BoxscoreParserDispatcher.java
  stage4_verify/
    VerifiedBundle.java
    BundleConsistencyChecker.java     (BoxscoreDateGate + ScoreValidator)
  stage5_reconcile/
    ReconciledGame.java
    CanonicalBundleSelector.java      (4-key tiebreaker)
    OrientationFlipper.java           (slug-based)
  stage6_persist/
    PersistResult.java
    PipelinePersister.java            (ONLY writer; demote-then-promote)
    TeamGameScorePropagator.java      (Hawaii/Maine fix lifted)
  stage7_stats/
    InningsFormatter.java             (4.2 = 14 outs)
    NormalizerVersion.java            (CURRENT=1)
  ncaa/
    NcaaEnrichment.java               (sibling cron)
  observability/
    PipelineMetrics.java              (Micrometer wrapper)
  util/
    CanonicalJson.java                (deterministic SHA-256)
    JacksonHardening.java             (StreamReadConstraints)
    UrlSafetyGate.java                (SSRF defense)
```

### `riseballs` (Rails)

```
app/jobs/concerns/pipeline_v2_guard.rb
app/models/pipeline_run.rb
app/models/pipeline_stage_audit.rb
app/models/pipeline_event.rb
app/controllers/admin/pipeline_runs_controller.rb
app/controllers/admin/pipeline_events_controller.rb
app/jobs/pipeline_consistency_audit_job.rb
db/migrate/20260503000001_pipeline_v2_schema_ddl.rb
db/migrate/20260503000002_pipeline_v2_constraints.rb
db/migrate/20260503000003_create_cached_games_shadow.rb
lib/tasks/pipeline_v2_backfill.rake
lib/tasks/pipeline_v2_fixtures.rake
lib/tasks/pipeline_v2_shadow.rake
lib/tasks/pipeline_v2_stage_f_backfill.rake
lib/tasks/pipeline_v2_stage_7_dryrun.rake
script/audit_game_number.rb
script/audit_pipeline_consistency.rb
script/check_no_pipeline_v1_writes.sh
test/jobs/concerns/pipeline_v2_guard_test.rb
test/models/cached_game_canonical_test.rb
```

`CachedGame.fetch_canonical(game, type)` and
`CachedGame.fetch_canonical_with_orientation(game, type,
viewing_team_slug:)` are the read-path API for every controller
post-Phase-2.

### `riseballs-predict` (Python)

`AND superseded_at IS NULL` filter on the three PGS aggregate
queries (`_BATTING_BOX`, `_PITCHING_BOX`, `_STARTER_APPEARANCES`).

## Related

- [audits/old-pipeline-inventory.md](../audits/old-pipeline-inventory.md) — the 291-component disposition list
- [audits/cron-inventory.md](../audits/cron-inventory.md) — Sidekiq cron disposition
- [audits/game-number-audit-2026-05-02.md](../audits/game-number-audit-2026-05-02.md) — pre-migration BLOCKER audit
- [audits/phase-3b-deletion-checklist.md](../audits/phase-3b-deletion-checklist.md) — Ruby cleanup runbook
- [audits/phase-3c-deletion-checklist.md](../audits/phase-3c-deletion-checklist.md) — Java cleanup runbook
- [audits/backfill-report.md](../audits/backfill-report.md) — Stage F skeleton
- [audits/stuck-games-2026-05-02.txt](../audits/stuck-games-2026-05-02.txt) — Phase 2 first cohort
- [01-game-pipeline.md](01-game-pipeline.md) — *legacy* GamePipelineJob; deleted in Phase 3
