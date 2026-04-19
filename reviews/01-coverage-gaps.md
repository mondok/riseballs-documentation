# Coverage Gaps Review

Audit date: 2026-04-18. Reviewer: coverage-audit sub-agent.

Scope: spot-check the generated tree at `/Users/mattmondok/Code/riseballs-parent/riseballs-documentation/` against the three source trees (`riseballs/`, `riseballs-scraper/`, `riseballs-predict/`) and the narrative `how_things_work.md` files. Methodology: enumerated every model, controller, service, job, rake task, Java class, Python module, cron entry, and env var via Glob/Grep; verified each was present somewhere in the docs; spot-read the load-bearing files to confirm the docs match the code.

High-level verdict: **coverage is unusually thorough**. Every ActiveRecord model, every API endpoint, every ActiveJob (27 of 27), every rake task (34 of 34), every Java `@RestController`, and every Python router is documented somewhere. The gaps are concentrated in (a) broken intra-doc cross-references to pipeline files that were planned but not created, (b) several Java helper classes that the scraper docs gloss over, (c) one uncovered end-to-end flow (the OpenAI batch pipeline), and (d) a small number of env vars and admin-only operational playbooks.

---

## Critical gaps (must fix)

### C1. Six broken cross-references to pipeline files that do not exist

The model doc and ER doc link to pipeline files that were never created. Each link is a 404.

Source of gap | File referenced (nonexistent)
--- | ---
`rails/01-models.md:116` | `pipelines/04-pbp-pipeline.md` (the real file is `pipelines/02-pbp-pipeline.md`)
`rails/01-models.md:154` | `pipelines/04-pbp-pipeline.md` (same)
`rails/01-models.md:155` | `pipelines/01-schedule-pipeline.md` (no schedule pipeline doc exists — content is split across `01-game-pipeline.md` and `06-reconciliation-pipeline.md`)
`rails/01-models.md:328` | `pipelines/05-review-detection.md` (not created; review-detection content is scattered across `06-reconciliation-pipeline.md` and `12-jobs.md`)
`rails/01-models.md:416` | `pipelines/04-pbp-pipeline.md` (same PBP rename)
`rails/01-models.md:417` | `pipelines/06-lock-lifecycle.md` (not created; lock lifecycle content is inside `02-pbp-pipeline.md` and `rails/01-models.md#cachedgame`)
`rails/01-models.md:569` | `reference/routes.md` (file does not exist — `rails/05-routes.md` is the real routes doc)
`rails/01-models.md:781` | `reference/standings_feature.md` (not created; content lives in `pipelines/04-standings-pipeline.md` + `reference/conference-tournaments.md`)
`rails/01-models.md:841` | `pipelines/02-batch-pipeline.md` (not created — **see C2**)
`rails/03-entity-relationships.md:324` | `pipelines/05-review-detection.md`
`rails/03-entity-relationships.md:345` | `pipelines/04-pbp-pipeline.md`

**Why it matters:** `rails/01-models.md` is the canonical entry point for any engineer learning the schema, and every one of its "cross-references" sections points at a dead link. Fix by either (a) creating the missing pipeline files or (b) rewriting the cross-reference block to point at the real existing files.

**Where to fix:** `rails/01-models.md` and `rails/03-entity-relationships.md`. Suggested replacements: `pipelines/04-pbp-pipeline.md` → `pipelines/02-pbp-pipeline.md`; `pipelines/05-review-detection.md` → `pipelines/06-reconciliation-pipeline.md#score-audit-scorevalidationjob`; `pipelines/01-schedule-pipeline.md` → `pipelines/01-game-pipeline.md`; `pipelines/06-lock-lifecycle.md` → `pipelines/02-pbp-pipeline.md` (and inline the `try_lock!` section in the CachedGame model entry). `reference/routes.md` → `rails/05-routes.md`. `reference/standings_feature.md` → `reference/conference-tournaments.md`.

### C2. OpenAI batch pipeline has no pipeline doc

**What's missing:** The `BatchJob` model is documented in `rails/01-models.md#batchjob` with its full state machine (`pending → scraping → submitted → processing → completed/failed`) and references `pipelines/02-batch-pipeline.md` — but that file does not exist.

The actual pipeline lives in `riseballs/lib/tasks/fill_missing_boxscores.rake` (lines 301–506) and walks:
1. Create `BatchJob` with `job_type: "box_score"`.
2. Scrape box score HTML via Cloudflare + Nokogiri.
3. Build JSONL, upload to OpenAI Files API, create Batch job.
4. Poll Batch until `completed`, download output, parse extracted JSON per game.
5. Store results via `GameStatsExtractor.extract` + `CachedGame.store`.

**Where it should go:** `pipelines/08-batch-pipeline.md` (new). Should document: the state machine, the 24-hour batch window assumption, `store_meta`/`meta_for` partial-write semantics, the `CLOUDFLARE_BROWSER_TOKEN` + `OPENAI_API_KEY` preconditions, and how this pipeline interacts with the `batch_jobs.metadata` JSONB for per-game progress tracking.

**Why it matters:** The BatchJob state machine is the only place in the codebase that drives an external (OpenAI) asynchronous job. If this pipeline breaks, there is currently no documentation to diagnose it — only the rake task body.

### C3. Scoreboard live-refresh and score-recovery flow is undocumented as a pipeline

**What's missing:** `Api::ScoreboardController#index` (documented at `rails/04-api-endpoints.md:370-393`) performs two time-sensitive operations that are documented nowhere else:

1. **5-second live-refresh window** (lines 68-104 of the controller): for every non-final game whose `start_time_epoch` has passed, re-fetches from NCAA scoreboard or cache and writes `home_score / away_score / current_period / state` back into `games`. This is a **write-through on every scoreboard request** and is a documented-nowhere concurrency surface.
2. **Score-recovery fallback** (lines 36-43): if a game is marked `final` but scores are nil, sums linescore from cached `athl_boxscore`.

**Where it should go:** Either extend `pipelines/01-game-pipeline.md` with a "read-path live refresh" section, or create `pipelines/09-scoreboard-live-refresh.md`.

**Why it matters:** This is the fastest-path write-through in the entire system (every page load can mutate `games`). A data-integrity change that breaks this will show up as users reporting "score on scoreboard doesn't match score on game detail."

### C4. PBP Final-Flip Backfill (issue #66) not reflected in pipelines/02-pbp-pipeline.md

**What's missing:** `riseballs/how_things_work.md` (lines 95-123) describes a specific recent change — the PBP final-flip backfill loop that was shipped on April 18, 2026 (issue #66). The doc's `pipelines/02-pbp-pipeline.md` has a "stale cache problem" section but does not document this final-flip mechanism (the post-final `PbpOnFinalJob` retries path).

Similarly, the "PBP Negative Cache" entry (issue #67, same date) in `how_things_work.md:124` documents the `pbp_miss:` key format + 5-minute TTL. This is called out in `rails/04-api-endpoints.md` but not in the pipeline doc.

**Where it should go:** `pipelines/02-pbp-pipeline.md` — add subsections titled "Final-flip backfill (issue #66)" and "Negative cache (issue #67)" describing the polynomial retry schedule for `PbpOnFinalJob` and the 5-minute negative cache key.

**Why it matters:** These are the two most recently-shipped PBP behaviors. New engineers debugging "why didn't PBP refresh when the game went final" will miss the retry ladder entirely.

### C5. Missing Python repositories / services in predict docs

**What's missing:** The predict service has these files not named anywhere in the docs tree:

| File | Status |
|---|---|
| `riseballs-predict/app/data/repositories/teams_repository.py` | not mentioned (only `games`, `boxscores`, `pitching`, `play_by_play` are referenced in `predict/00-overview.md`) |
| `riseballs-predict/app/services/prediction_service.py` | only mentioned as a flow step, not documented as a service |
| `riseballs-predict/app/services/explanation_service.py` | only mentioned as a flow step |
| `riseballs-predict/app/services/scenario_service.py` | mentioned in `04-explain-engine.md` but no standalone entry |
| `riseballs-predict/app/services/feature_service.py` | mentioned in `02-feature-engineering.md` |
| `riseballs-predict/app/services/model_registry_service.py` | mentioned in predictions.py but not documented as a service |

**Where it should go:** The predict tree lacks a dedicated "services" doc. Either add `predict/08-services.md` enumerating each service class, or extend the relevant endpoint/engineering docs with a "Service layer" section that lists each service's class, file, public methods, and call chain.

**Why it matters:** The Python tree has seven service classes and these files own the HTTP-to-model translation layer. Missing their docs means the `predict/01-endpoints.md` doc dead-ends at "calls `prediction_service.predict()`" with no follow-through.

### C6. Java ScheduleComparisonEngine is referenced but not documented

**What's missing:** `riseballs-scraper/src/main/java/com/riseballs/scraper/reconciliation/ScheduleComparisonEngine.java` is referenced in `scraper/04-reconciliation.md:40` with a subsection heading, but the content is sparse (just a mention). Source is 300+ lines — the engine does the actual comparison and action-generation between the `ScheduleEntry` list and the DB's `games` rows.

**Where it should go:** `scraper/04-reconciliation.md` — expand the `ScheduleComparisonEngine` subsection with: (a) the full action-generation list (`CREATE`, `UPDATE_DATE`, `UPDATE_SCORE`, `FINALIZE`, `UNCANCEL`, `DELETE_GHOST`, `REVIEW`), (b) how `matchSchedule` vs `matchDb` partitions the cartesian product, (c) the same-date-same-matchup tiebreaker.

**Why it matters:** This is the brain of the schedule reconciliation pipeline — understanding it is required before anyone changes reconciliation behavior.

---

## Medium gaps (should fix)

### M1. `OpponentResolver` is only partially documented

**Source file:** `riseballs-scraper/src/main/java/com/riseballs/scraper/reconciliation/schedule/OpponentResolver.java`

The Java docs reference `OpponentResolver` in four places (`scraper/03-parsers.md:124`, `scraper/02-services.md`, etc.) and describe it as "name → slug resolution." However, `OpponentResolver` is **also** the shared resolver used by `StandingsOrchestrator`, `TeamScheduleSyncService` (for `normalizeForDedup`), and `ReconciliationService`. The interaction matrix — who injects it, what cache it uses, how ambiguity is surfaced — is not spelled out.

**Where it should go:** Expand the `## OpponentResolver` section of `scraper/03-parsers.md` (currently line 124) to cover: (a) the ambiguous-name override pattern (the `conference_standing.team_slug` manual-override escape hatch is mentioned in `02-services.md` but not rooted in the `OpponentResolver` section), (b) alias-table read path, (c) whether results are cached.

### M2. Rails service fingerprint — three services not individually documented

Cross-referencing `/Users/mattmondok/Code/riseballs-parent/riseballs/app/services/*.rb` (43 files including concerns/shared) against the doc-tree:

- **`SeriesGuardService`** — `app/services/series_guard_service.rb`. Mentioned in `rails/08-matching-services.md` TOC but its entry is shallow relative to `TeamGameMatcher`. Given that series-guard logic protects 3-game weekend series from being misclassified as doubleheaders, this deserves more depth.
- **`PbpTeamSplitter`** — `app/services/pbp_team_splitter.rb`. Described in one paragraph in `rails/06-ingestion-services.md:800`; the roster-based splitting heuristic (how it handles un-identified team IDs, threshold for accepting a split) is not spelled out.
- **`ScheduleRecoveryService`** — `app/services/schedule_recovery_service.rb`. The `stuck_team_slugs` query and games-table backfill are referenced by `StuckScheduleRecoveryJob` in `rails/12-jobs.md` but the service itself does not have a standalone entry. It IS in the `rails/08-matching-services.md` TOC, and the section exists, so this is minor — the actual per-team backfill behavior may deserve a sentence on what it writes.

**Where it should go:** Respective subsections of `rails/06-ingestion-services.md` (for `PbpTeamSplitter`) and `rails/08-matching-services.md` (for `SeriesGuardService`).

### M3. Admin controllers routes — `/admin/jobs` page JOBS constant is behind HTTP Basic auth and hardcoded to one email

**Source:** `riseballs/app/controllers/admin/jobs_controller.rb:180-185` — `ALLOWED_EMAIL = "matt.mondok@gmail.com"`. Documented in `rails/04-api-endpoints.md:621-633`.

The docs accurately cover WHAT it does, but two facts are missing:
1. The `JOBS` constant lists `TeamScheduleSyncJob` and `LiveGameSyncJob` — **neither of these classes exist in the codebase** (verified via Grep of `app/jobs/`). The admin UI would 500 when these buttons are clicked. This is a real bug surfaced by the documentation inventory, not just a doc gap.
2. The hard-coded email is not called out as a hazard in the admin runbook.

**Where it should go:** Either fix the code (remove dead job entries from the `JOBS` constant) and update `rails/04-api-endpoints.md#adminjobscontroller` accordingly, or at minimum add a note to `operations/runbook.md` that these two buttons will crash.

### M4. Sidekiq Web UI authentication not documented in runbook

**Source:** `riseballs/config/routes.rb:5-8` — `Sidekiq::Web` is mounted with its own Basic-auth closure. Checked in `rails/05-routes.md` but not surfaced as an operator task.

**Where it should go:** `operations/runbook.md` — add a section "Accessing Sidekiq Web UI" that covers (a) the URL (`/sidekiq`), (b) credentials (admin user's email + password, not a magic token), (c) how to inspect the dead-set when a job has been retried out.

### M5. Environment variables — OpenAI / Cloudflare / Google CSE / Ollama not in deployment.md

**Source:** enumerated via Grep of `ENV.fetch`/`ENV[` in `riseballs/app`. The following 11 env vars are referenced in Ruby code but not in `operations/deployment.md#env-var-reference`:

- `OPENAI_API_KEY` — used by `AiBoxScoreService`, `AiWebSearchBoxScoreService`, `AthleticsBoxScoreService`, `CloudflareBoxScoreService`, `CloudflareScheduleService`, `AiScheduleService`, `AiClient`.
- `OPENAI_BASE_URL` — `AiClient`.
- `OPENAI_MODEL` — `AiClient`.
- `CLOUDFLARE_ACCOUNT_ID` — `CloudflareBoxScoreService`, `CloudflareScheduleService`, `AiScheduleService` (with a hardcoded default fallback).
- `CLOUDFLARE_BROWSER_TOKEN` — same three services.
- `GOOGLE_SEARCH_API_KEY`, `GOOGLE_SEARCH_CX` — `BoxscoreFetchService` Google CSE path.
- `LOCAL_SCRAPER_URL` — `BoxscoreFetchService`, `BoxscoreUrlDiscoveryService`.
- `AI_PROVIDER`, `OLLAMA_HOST`, `OLLAMA_MODEL`, `OLLAMA_API_KEY` — `AiClient`.
- `DEDUP_DRY_RUN` — `GameDedupJob`.

They are mentioned scattered throughout `rails/06-ingestion-services.md` and `rails/13-rake-tasks.md`, but the consolidated env-var table in `operations/deployment.md#env-var-reference` lists only 9 vars and none of the above. Same critique for the Java env-var list at `scraper/07-config-and-deployment.md` (doesn't mention the OpenAI vars even though it notes "deprecated, not used").

**Where it should go:** Expand the `operations/deployment.md#env-var-reference` tables. Add an explicit "Deprecated (do not use)" row for `OPENAI_API_KEY` + `CLOUDFLARE_BROWSER_TOKEN` so the AI fallback path isn't accidentally re-enabled.

### M6. `how_things_work.md` has content that didn't make it into the tree

Comparing `riseballs/how_things_work.md` against the doc tree, three narrative sections are substantive and not fully reflected:

1. **"Known Issue: Stale PBP Cache" (`riseballs/how_things_work.md:91`)** — describes the cache-invalidation race condition on re-finals. `pipelines/02-pbp-pipeline.md:144` has a "stale cache problem" section but it is shorter than the narrative version.
2. **"Coach Augmentation" (lines 318-321)** — says `CoachAugmentService` runs async-per-team and is idempotent. `pipelines/05-roster-pipeline.md:55` covers the service but not the idempotency guarantee.
3. **"Schedule API Opponent Resolution" (lines 263-269)** — describes the ILIKE fallback path used by `/api/teams/:slug/schedule`. `rails/04-api-endpoints.md:246-262` covers it, so this is redundant; the gap is the cross-link from the narrative to the endpoint doc.

**Where it should go:** Minor edits to `pipelines/02-pbp-pipeline.md` + `pipelines/05-roster-pipeline.md`.

### M7. Stupid Mistakes log has no pointer in the doc tree

**Source:** `riseballs-parent/stupid_mistakes_claude_has_made.md` (129 lines). This file is referenced in the user's project `CLAUDE.md` as a pre-deploy checklist input. The doc tree's `README.md:136-138` mentions `how_things_work.md` but not this file.

**Where it should go:** `README.md` — add a bullet under "Scope disclaimers" pointing to `stupid_mistakes_claude_has_made.md` as an append-only log of regressions to consult before deploying.

---

## Minor gaps / nice-to-have

### N1. Java scraper tests directory not indexed

`riseballs-scraper/src/test/` exists (contains `java/` + `resources/`) but is not mentioned in `scraper/00-overview.md`. A one-line note — "Tests: JUnit 5 in `src/test/java`, H2 in-memory via `application-test.yml`" — would close the loop.

### N2. Predict service scripts not referenced in config doc

`riseballs-predict/scripts/train_all.py` and `scripts/evaluate_latest.py` ARE documented in `predict/03-ml-and-artifacts.md:218-238`, but the `predict/07-config-and-deployment.md` training section (line 222) does not link to them — it describes training as a concept without linking to the concrete scripts.

### N3. Rake tasks `debug:fix_lewis` is a one-shot and should be flagged for deletion

`rails/13-rake-tasks.md:393` correctly notes this is a one-shot fix for a 2026-04-12 bug. It's a valid doc entry but the tree doesn't flag it as "remove after cleanup." No fix required in the docs; a TODO elsewhere makes sense.

### N4. Minor inconsistency on `PbpParser`

`scraper/02-services.md` and `scraper/03-parsers.md` both describe `PbpParser`, with slightly different coverage. The `03-parsers.md` version (60-80) is more detailed but is at a section heading level below the box-score parsers. A reader arriving at `02-services.md` for "how does PBP parsing work" won't know the full write-up is in `03-parsers.md`. Add a cross-link.

### N5. Deployment doc — Dokku app host inconsistency

`operations/deployment.md:27` says Rails is on `ssh.mondokhealth.com`, but `ssh.edentechapps.com` for the Java scraper + predict (line 30+33). This matches the user's private `CLAUDE.md` which says "Self-hosted Dokku server at `ssh.edentechapps.com`" but the project `CLAUDE.md` says "Dokku with `dokku@ssh.mondokhealth.com`". Not a doc bug — just flagging that the split-host setup may confuse operators. A sentence in the deployment doc explaining why two Dokku hosts exist would help.

### N6. `Admin::BoxscoresController` queue-state uses `session[:queued_games]` — ephemeral

`rails/04-api-endpoints.md:654` notes this. But the doc does not call out that the "queued" marker is per-session (i.e., a second admin on a different browser sees no queue state). Worth a sentence.

### N7. `SidearmScheduleParser` added recently

`riseballs-scraper/src/main/java/com/riseballs/scraper/reconciliation/schedule/SidearmScheduleParser.java` is in the parser list at `scraper/03-parsers.md` — verified present. No gap, noting for completeness.

### N8. Some admin runbook playbooks missing

`operations/runbook.md` covers 10 operator scenarios. Missing playbooks that would have clear matching source code:

- "How to approve / dismiss a `GameReview`" — the `/admin/reviews` UI exists but no runbook entry walks through the decision tree for each `review_type` (`score_mismatch`, `duplicate`, `stale_scheduled`, etc.).
- "How to recover from a bad cron run" — `Sidekiq::Cron::Job` repair via `bin/rails runner`.
- "How to rotate the admin-UI HTTP Basic password" — there isn't one; the hardcoded email allows only `matt.mondok@gmail.com`.
- "How to check a specific team's schedule-sync output" — there's a `/api/team-schedule/sync-team` endpoint in the Java scraper with `?check=true` for dry-run; not referenced in the runbook.

### N9. `rails/02-database-schema.md` completeness

Spot-checked: all 28 models in `app/models/` have corresponding `create_table` entries in `schema.rb`, and the doc covers them. The `pg_catalog.plpgsql` extension load at line 15 of schema.rb is not noted. Minor.

### N10. Predict feature count claim

`README.md:66` says "168+15 features." `predict/02-feature-engineering.md` uses similar numbers. Didn't verify exhaustively against code; flag for future check.

---

## Broken cross-references

All the `rails/01-models.md` + `rails/03-entity-relationships.md` broken references from **C1** apply here. No additional broken intra-tree links were found in random samples of the other 30 docs. The `[see X](foo.md)`-style links in `rails/12-jobs.md`, `rails/13-rake-tasks.md`, `rails/04-api-endpoints.md`, and all `pipelines/*.md` files resolve cleanly.

Consolidated broken-link list for quick fix:

```
rails/01-models.md:116   pipelines/04-pbp-pipeline.md
rails/01-models.md:154   pipelines/04-pbp-pipeline.md
rails/01-models.md:155   pipelines/01-schedule-pipeline.md
rails/01-models.md:328   pipelines/05-review-detection.md
rails/01-models.md:416   pipelines/04-pbp-pipeline.md
rails/01-models.md:417   pipelines/06-lock-lifecycle.md
rails/01-models.md:569   reference/routes.md
rails/01-models.md:781   reference/standings_feature.md
rails/01-models.md:841   pipelines/02-batch-pipeline.md
rails/03-entity-relationships.md:324  pipelines/05-review-detection.md
rails/03-entity-relationships.md:345  pipelines/04-pbp-pipeline.md
```

(Eleven broken references, all in two files. Single sweep to fix.)

---

## Summary of coverage

**Rails (`riseballs/app/`)**
- **Models:** 28/28 covered — `ApplicationRecord`, `BatchJob`, `CachedApiResponse`, `CachedGame`, `CachedSchedule`, `Coach`, `ConferenceSource`, `ConferenceStanding`, `Follow`, `Game`, `GameIdentifier`, `GameReview`, `GameSnapshot`, `GameTeamLink`, `PitchEvent`, `PlateAppearance`, `Player`, `PlayerFavorite`, `PlayerGameStat`, `PlayerWarValue`, `ScrapedPage`, `SiteMetric`, `StandingsScrapeLog`, `Team`, `TeamAlias`, `TeamGame`, `TeamPitchingStat`, `User`.
- **Controllers:** 26/26 covered — verified in `rails/04-api-endpoints.md`.
- **Services:** 41/41 covered (base + concerns + shared). `ai_box_score_service`, `ai_web_search_box_score_service`, `ai_schedule_service`, `ai_client`, `athletics_box_score_service`, `box_score_parsers/{base,presto_sports_parser,sidearm_parser,wmt_parser}`, `boxscore_fetch_service`, `boxscore_url_discovery_service`, `cloudflare_box_score_service`, `cloudflare_schedule_service`, `concerns/player_name_matcher`, `concerns/sidearm_helper`, `conference_scenario_service`, `espn_scoreboard_service`, `game_identity_service`, `game_show_service`, `game_stats_extractor`, `java_scraper_client`, `matching_service`, `ncaa_schedule_service`, `ncaa_scoreboard_service`, `pbp_team_splitter`, `pitch_by_pitch_parser`, `pitcher_enrichment_service`, `player_stats_calculator`, `predict_service_client`, `roster_parsers/{hometown_splitter,presto_sports_parser}`, `roster_service`, `rpi_service`, `schedule_recovery_service`, `schedule_service`, `series_guard_service`, `shared/name_normalizer`, `sidearm_stats_service`, `stat_broadcast_service`, `team_game_matcher`, `team_matcher`, `today_games_service`, `war_calculator`, `wmt_box_score_service`. Depth varies — see **M2**.
- **Jobs:** 27/27 covered in `rails/12-jobs.md`. `NOTE`: `TeamScheduleSyncJob` and `LiveGameSyncJob` are referenced in `Admin::JobsController#JOBS` but **do not exist in `app/jobs/`** — see **M3**.
- **Rake tasks:** ~50 tasks across 34 `.rake` files, all covered in `rails/13-rake-tasks.md`. One meta-file (`fill_missing_boxscores.rake`) contains 10+ sub-tasks which are enumerated. `repair_links.rake` covered.
- **Cron entries:** 12/12 covered in `rails/14-schedule.md` (matches `config/initializers/sidekiq.rb` exactly).
- **Routes:** complete in `rails/05-routes.md` including Sidekiq Web + Devise + SPA catch-all constraint.

**Java scraper (`riseballs-scraper/src/main/java/com/riseballs/scraper/`)**
- **Controllers:** 9/9 covered — `ScrapeController`, `ReconciliationController`, `ScheduleReconciliationController`, `NcaaDateReconciliationController`, `RosterController`, `GameCreationController`, `ScheduleVerificationController`, `TeamScheduleSyncController`, `StandingsController`, `MetricsController`.
- **Services:** most covered. Gaps: `ScheduleComparisonEngine` (see **C6**), `OpponentResolver` thin coverage (see **M1**), `NameUtils` touched briefly in `03-parsers.md:85`.
- **Repositories:** 14/14 enumerated in `scraper/05-repositories-and-data.md`.
- **Parsers:** box-score + schedule + standings parsers covered in `scraper/03-parsers.md`.
- **Models (JPA entities):** 15/15 enumerated in `scraper/05-repositories-and-data.md#entity-inventory`.
- **Config:** `application.yml`, `ScraperProperties`, `DatabaseUrlConfig`, `HttpClientConfig` — all covered in `scraper/07-config-and-deployment.md`.

**Predict (`riseballs-predict/app/`)**
- **Routers:** 7/7 covered — `health`, `predictions`, `explanations`, `scenarios`, `models`, `metrics`. (`app/api/routers/__init__.py` is empty.)
- **Feature builders:** 5/5 covered in `predict/02-feature-engineering.md`.
- **ML modules:** dataset builder, train/val/test split, both models, metrics, slices — covered in `predict/03-ml-and-artifacts.md`.
- **Repositories:** 4/5 named explicitly. `teams_repository.py` not mentioned (see **C5**).
- **Services:** 5 service classes (prediction, explanation, scenario, feature, model_registry) — only `feature_service` has a dedicated entry. The other four are referenced as call-chain steps inside the endpoint docs. (See **C5**.)
- **Scripts:** `train_all.py`, `evaluate_latest.py` — covered in `predict/03-ml-and-artifacts.md:218-238`.

**Operations**
- **Env vars:** gaps identified in **M5** — 11 Ruby-side env vars not in the consolidated table.
- **Playbooks:** 10 operator scenarios covered. 4 plausible additions identified in **N8**.

**Pipelines**
- 7/8 expected end-to-end pipelines covered. Missing: OpenAI batch (see **C2**). Scoreboard live-refresh is a cut-through flow that deserves either its own file or an extension (see **C3**).

**Reference**
- 4/4 reference files cover their declared scope (`matching-and-fallbacks`, `slug-and-alias-resolution`, `conference-tournaments`, `glossary`). No broken cross-references internal to these files.

---

## Recommended fix order

1. **C1 broken links** (single pass through two files — highest signal, lowest effort).
2. **C2 batch pipeline doc** (one new file).
3. **M3 dead JOBS entries** (code fix, not doc — but surfaces from this audit).
4. **C5 Python services doc** (one new file or three section expansions).
5. **C3, C4, C6** — doc extensions.
6. **M1-M7** — targeted doc expansions, each touching one existing file.
7. **N1-N10** — drive-by cleanups.
