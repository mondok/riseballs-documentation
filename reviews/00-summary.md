# Review Summary

Three independent review agents audited the documentation tree after the initial 8 authoring agents completed. This doc summarizes findings and what was fixed.

---

## Reviewers

| Review | Focus | Report |
|--------|-------|--------|
| 1 | Coverage & gap analysis | [01-coverage-gaps.md](01-coverage-gaps.md) |
| 2 | Source accuracy spot-check | [02-accuracy-spot-check.md](02-accuracy-spot-check.md) |
| 3 | Knowledge-graph navigability | [03-knowledge-graph.md](03-knowledge-graph.md) |

---

## Critical issues found + fixed

### 1. Box score fallback chain was documented wrong

**Problem (accuracy review):** Docs said `Athletics → WMT → Cloudflare → AI`. Reality per `BoxscoreFetchService.fetch` (`app/services/boxscore_fetch_service.rb:5-53`): `WMT → local scraper → Playwright HTML → plain HTTP → rediscovery → AI`.

**Fixed in:**
- `pipelines/03-boxscore-pipeline.md` — new mermaid diagram matches the actual 6-step chain.
- `reference/matching-and-fallbacks.md` — prose + summary table corrected.

### 2. Broken cross-references to non-existent pipeline/reference docs

**Problem (coverage + navigability reviews):** 11–12 backtick references in `rails/01-models.md` and `rails/03-entity-relationships.md` pointed to files like `pipelines/04-pbp-pipeline.md`, `pipelines/05-review-detection.md`, `pipelines/06-lock-lifecycle.md`, `pipelines/01-schedule-pipeline.md`, `pipelines/02-batch-pipeline.md`, `reference/routes.md`, `reference/standings_feature.md`. These were ghosts of an earlier plan.

**Fixed in:**
- Every reference re-pointed to the actual file (e.g., `pipelines/04-pbp` → `pipelines/02-pbp-pipeline.md`; `reference/routes.md` → `rails/05-routes.md`).
- Converted backtick refs to clickable `[text](path)` markdown links at the same time.

### 3. Team rankings column name contradiction

**Problem (navigability review):** `glossary.md` and `architecture/02-data-flow.md` referred to `team.ranking` but the actual schema column is `teams.rank` (`db/schema.rb:542`).

**Fixed in:** `reference/glossary.md`, `architecture/02-data-flow.md`.

### 4. Predict health endpoint path contradiction

**Problem (navigability review):** `runbook.md`, `database-access.md`, `pipelines/07-prediction-pipeline.md` all said `/health`. The actual predict service mounts the health router with a `/v1` prefix, so the correct path is `/v1/health` (`riseballs-predict/app/main.py:88`).

**Fixed in:** all three files.

### 5. "Locked" glossary entry conflated two unrelated concepts

**Problem (navigability review):** Entry mixed `Game.locked` (score correctness signal, set by `ScoreValidationJob`) with `CachedGame.locked` / `try_lock!` (advisory write coordination).

**Fixed in:** `reference/glossary.md` — explicit disambiguation paragraph added.

### 6. Schedule sync endpoint mis-documented

**Problem (accuracy review):** `architecture/00-system-overview.md` and `pipelines/01-game-pipeline.md` said Rails calls Java at `/api/scrape` for schedule sync. The actual endpoint is `POST /api/team-schedule/sync-all` (or per-team iteration for non-3AM runs). Verified in `app/jobs/game_pipeline_job.rb:50`.

**Fixed in:** both files; new mermaid diagram reflects the 3 AM full-sync vs. per-team branching.

### 7. `apps/controllers/` typo

**Problem (accuracy review):** `rails/04-api-endpoints.md:41` had `apps/controllers/` instead of `app/controllers/`.

**Fixed.**

### 8. `SidearmHelper` method name wrong in new diagram

**Problem (accuracy review):** After fixing the box score chain, I cited a `#discover_box_score_urls` method that doesn't exist. The real one is `#sidearm_find_all_box_score_urls` (`app/services/concerns/sidearm_helper.rb:19`).

**Fixed in:** `pipelines/03-boxscore-pipeline.md`.

---

## Non-doc bugs surfaced (for user / engineering)

### B1. `Admin::JobsController#JOBS` references classes that don't exist

`app/controllers/admin/jobs_controller.rb:5-30` lists:

```ruby
{ name: "Team Schedule Sync", class_name: "TeamScheduleSyncJob" }
{ name: "Live Game Sync",     class_name: "LiveGameSyncJob" }
```

Neither `TeamScheduleSyncJob` nor `LiveGameSyncJob` exists in `app/jobs/`. They were consolidated into `GamePipelineJob`. Clicking those admin buttons will raise `NameError` at runtime.

**Action:** Edit `admin/jobs_controller.rb` to remove both entries or re-point to `GamePipelineJob`. Documented as a runbook playbook at [../operations/runbook.md](../operations/runbook.md#admin-run-job-crashes-with-nameerror).

### B2. `AiScheduleService` scoped-variable bug

`app/services/ai_schedule_service.rb:104` references `response.parsed_response` outside the scope where `response` is assigned. Surfaced by the ingestion-services agent during documentation. Service is deprecated / last-resort path.

### B3. `cached_api_responses` inconsistent TTL mechanism

Models agent found: `CachedApiResponse#store` writes `expires_at`, but `fetch(ttl:)` compares against `updated_at`. Two mechanisms in play — pick one.

---

## Remaining known gaps (intentionally not fixed in this pass)

1. **BatchJob pipeline doc.** `app/models/batch_job.rb` has a full state machine but the state machine logic lives in `lib/tasks/fill_missing_boxscores.rake:301-506`. Coverage review flagged; `rails/01-models.md` now references the rake source instead of a non-existent pipeline doc.
2. **Scoreboard live-refresh pipeline.** `Api::ScoreboardController` writes back to `games` on every page load. Not promoted to its own pipeline doc — covered in `rails/04-api-endpoints.md` and `architecture/02-data-flow.md` Phase 2.
3. **Predict service internal service classes.** `prediction_service`, `explanation_service`, `scenario_service`, `model_registry_service` not given standalone sections. Endpoints and feature builders are documented; internal service decomposition is less important for a reader.
4. **`ScheduleComparisonEngine`.** `scraper/04-reconciliation.md` documents the flow but doesn't dive into the comparison rules file-by-file. The public flow is captured.
5. **Leaf-file cross-links.** `rails/*`, `scraper/*`, `predict/*` mostly use backtick references rather than clickable links. The hub layer (README / architecture / pipelines / reference / operations) is densely linked. Navigability review flagged this as a C+-grade issue. Selective fixes applied to `rails/01-models.md` and `rails/03-entity-relationships.md`; the rest remain as-is for now.
6. **TOCs outside `rails/`.** Only `rails/*` files have TOCs; other dirs don't. Cosmetic.

These are tracked for a follow-up pass if the user wants another round.

---

## Verdict

- **Coverage:** unusually thorough. 28/28 models, 26/26 controllers, 41/41 services, 27/27 jobs, ~50/50 rake tasks, 9/9 Java controllers, 14/14 Java repos, 7/7 Python routers all appear somewhere in the tree.
- **Accuracy:** ~22 of 31 spot-checked claims clean; the 9 errors fixed are all concentrated in 7 files.
- **Navigability:** hub layer is densely linked and traversable; leaf files are reference-style. Critical broken refs now resolve.

The knowledge graph is traversable end-to-end. Any concept from the README reaches a source-file-level detail within 3–4 clicks.
