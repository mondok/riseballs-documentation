# Phase 3c Deletion Checklist (PR #33 prep)

**Plan reference:** `PIPELINE_REBUILD_PLAN.md` v5 §sequencing list line 1851.

This file is the operator runbook for PR #33 -- the Java-side
deletion + flag removal that runs after Phase 3b is green. It
also removes the `PIPELINE_V2_ENABLED` flag itself.

**DO NOT EXECUTE BEFORE:**
1. PR #32 (Phase 3b) merged + green.
2. CI's `STAGE_G_ENFORCE=true` flipped + green.
3. 48h post-Phase-3b stability monitoring.

## Java DELETE list (17 classes + 4 DTOs)

### Group A -- service/ orchestrators

```
src/main/java/com/riseballs/scraper/service/ScrapeOrchestrator.java
src/main/java/com/riseballs/scraper/service/PbpOrchestrator.java
src/main/java/com/riseballs/scraper/service/PbpWriter.java
src/main/java/com/riseballs/scraper/service/GameStatsWriter.java
src/main/java/com/riseballs/scraper/service/TeamScheduleSyncService.java
```

### Group B -- service/validation/BoxscoreDupeGuard

```
src/main/java/com/riseballs/scraper/service/validation/BoxscoreDupeGuard.java
```

### Group C -- service/fetcher/BoxscoreFetcher interface

```
src/main/java/com/riseballs/scraper/service/fetcher/BoxscoreFetcher.java
```

(The 5 EXTRACT_LOGIC_TO_NEW fetcher implementations stay until
each strategy under `pipeline/stage2_fetch/` ports its logic in
PR #11 follow-on commits.)

### Group D -- reconciliation/* legacy

```
src/main/java/com/riseballs/scraper/reconciliation/ReconciliationService.java
src/main/java/com/riseballs/scraper/reconciliation/ReconciliationAction.java
src/main/java/com/riseballs/scraper/reconciliation/ScheduleReconciliationOrchestrator.java
src/main/java/com/riseballs/scraper/reconciliation/ScheduleReconciliationController.java
src/main/java/com/riseballs/scraper/reconciliation/ScheduleComparisonEngine.java
src/main/java/com/riseballs/scraper/reconciliation/NcaaDateReconciliationController.java
src/main/java/com/riseballs/scraper/reconciliation/NcaaDateReconciliationWriter.java
```

### Group E -- legacy controllers

```
src/main/java/com/riseballs/scraper/controller/ScrapeController.java
src/main/java/com/riseballs/scraper/controller/TeamScheduleSyncController.java
src/main/java/com/riseballs/scraper/controller/GameCreationController.java
src/main/java/com/riseballs/scraper/controller/ScheduleVerificationController.java
```

### Group F -- DTOs

```
src/main/java/com/riseballs/scraper/dto/ScrapeRequest.java
src/main/java/com/riseballs/scraper/dto/ScrapeResponse.java
src/main/java/com/riseballs/scraper/dto/BatchScrapeRequest.java
src/main/java/com/riseballs/scraper/dto/BatchScrapeResponse.java
```

## Phase 3c also does

### Flag removal

- `app/jobs/concerns/pipeline_v2_guard.rb` -> delete
- Every `include PipelineV2Guard` and `return if pipeline_v2_enabled?`
  -> remove (in the surviving job classes -- already PR #32 deleted
  most of them; only PR #25's includes in jobs not on the DELETE
  list remain).
- `PipelineFlag.java` -> delete
- Every `if (!flag.isEnabled()) return;` -> remove from
  `HourlyScheduleSweep`, `NcaaEnrichment`, `BackReconcilerNightly`.

### 410 Gone for deprecated controllers

For 2 weeks before final removal (plan §line 982): the routes
`/api/scrape/*`, `/api/team-schedule/*`,
`/api/games/find-or-create` respond 410 with a JSON pointer at
`/api/pipeline/process-game`. After 2 weeks the routes themselves
are removed.

### `BoxscoreData` lineup-grandfathering shim

`service/parser/BoxscoreData.java` retained as `@Deprecated` shim
until the lineup PR migrates LineupExtractor to consume
`BoxscoreBundle` directly. Removed in a follow-up after lineup
work merges.

## Verification

```sh
./gradlew compileJava                  # green required
./gradlew test                         # green required
./gradlew bootJar                      # green required
```

ArchUnit rules (PR #8) become more meaningful at this point:
every stage rule that was passing vacuously (no classes in
`..pipeline.stageN..`) starts checking real code as the parser
MOVE PRs (#13-17) populate stage3_parse.

## Rollback

`git revert <commit>` restores. The pipeline package and the
schema are unaffected; the rebuild remains operational.
