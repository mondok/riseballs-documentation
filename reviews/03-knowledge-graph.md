# Knowledge-Graph Navigability Review

Reviewer: independent pass over `/Users/mattmondok/Code/riseballs-parent/riseballs-documentation/` as a knowledge graph.
Method: walked 5 reader personas, computed link density per file, verified every `](target.md)` target existed on disk, spot-checked terminology against the glossary, traced three concepts top-to-bottom, and scanned for contradictions.

**Headline finding:** The hub-and-spoke layer (`README`, `architecture/`, `pipelines/`, `reference/`, `operations/`) is a real knowledge graph — dense, accurate, cross-linked. The leaf layer (`rails/`, `scraper/`, `predict/` — 33 of the 48 files) is **not**: 32 of those 33 files have **zero outbound markdown links**. The graph is almost entirely unidirectional. Hubs point into leaves; leaves are dead-ends.

---

## Entry-point traversal tests

### Path 1: "I need to fix a PBP bug"

1. Open `README.md`. Layout section names `pipelines/02-pbp-pipeline.md` right in the table, plus the reading path "How does `/api/games/:id/play_by_play` actually work?" gives a three-step trail. **Excellent start.**
2. Go to `pipelines/02-pbp-pipeline.md`. Full three-path cascade, storage model, quality gate, name-cleanup duplication warning, negative cache, rake toolbox, stale-cache caveat, box-score-discovery bug (#65) — all in one file. **Best single file in the tree for this persona.**
3. "Related docs" at the bottom sends me to `rails/07-parsers.md` for parser internals, `rails/01-models.md` for `CachedGame`, and `operations/runbook.md` for the playbook.
4. Land on `rails/07-parsers.md`. It covers the parsers thoroughly — but has **zero links back**. If I want to jump from here to the quality gate or to the on-final job I have to re-navigate through README. Navigation succeeds, then stops.
5. `operations/runbook.md` → "PBP missing for a game". Concrete commands, diagnosis order, three fix options, verify step. **Strong.**

**Verdict:** Navigation is excellent for two levels, then flattens. The deep technical files read like reference docs, not graph nodes.

### Path 2: "I need to understand how doubleheaders work"

1. `README.md` has no direct DH entry in the reading paths. The closest is "Why did this game get duplicated?" which lands on `pipelines/06-reconciliation-pipeline.md`. Not quite the same thing but adjacent.
2. `reference/glossary.md` → "DH / Doubleheader" defines it crisply and points at `TeamScheduleSyncService.normalizeForDedup` — but no clickable doc link. Glossary only points *within* itself here.
3. Scan the README layout table → `rails/08-matching-services.md`. TOC has "Doubleheaders & `game_number`". Detailed treatment of the `find_opponent_game` priority ladder. **Hits the target.**
4. I also find `pipelines/01-game-pipeline.md` with the shell-link-preservation explanation and the same priority ladder again (redundant but consistent).
5. `runbook.md` "Doubleheader not splitting" gives the operator playbook.

**Verdict:** Works, but the reader has to guess the right entry point. A glossary link to `rails/08-matching-services.md#doubleheaders--game_number` would close the gap. No explicit DH reading path in README.

### Path 3: "I need to deploy a change"

1. `README.md` → `operations/deployment.md`. Covers remotes, deploy commands, rollback, domains. **Strong.**
2. Links to `runbook.md` and `database-access.md`. Good backlinks.
3. `CLAUDE.md` at the parent root documents the Dokku bits too. Deployment.md mentions CI gates but does not link to the CI workflow files. That's acceptable — they live in the repo, not in the docs tree.

**Verdict:** Clean. Shortest and best-scoped persona path in the tree.

### Path 4: "I want to change a prediction feature"

1. README has a direct reading path: pipelines/07 → predict/02 → predict/03. **Best signposting of any persona.**
2. `pipelines/07-prediction-pipeline.md` is thorough on the Rails side, shows the sequence diagram, describes caching. Good.
3. `predict/02-feature-engineering.md` describes `FeatureBuilders`, the contract, and each builder. Solid.
4. `predict/03-ml-and-artifacts.md` covers models and the artifact tree.
5. **But:** every `predict/*.md` file ends with a "Cross-references" block of **bare unclickable text** — `01-endpoints.md`, `02-feature-engineering.md`, etc. — not `[01-endpoints.md](01-endpoints.md)`. Readers cannot click through.

**Verdict:** Content-excellent, navigation-degraded. `predict/` is a small island.

### Path 5: "I'm onboarding — what should I read first?"

1. README offers an "I'm new" reading path: architecture/00 → architecture/02 → glossary. That's a good 30-minute start.
2. architecture/00 hands off to 01 and 02 plus pipelines/ and glossary. All clickable.
3. architecture/02 ("Data Flow") has the best end-to-end narrative in the tree. Walks phase by phase.
4. Natural continuation is pipelines/01-game-pipeline.md (the 15-min heartbeat). That's load-bearing for understanding live operation.
5. From pipelines/01 → rails/12-jobs.md (specifically `GamePipelineJob`). TOC helps. **But** rails/12 does not link back to the pipeline that called into it or to `operations/runbook.md`. You are stuck at the bottom of a deep file.

**Verdict:** 60% of an onboarding trail works. The final 40% is a dead-end. A new hire will finish rails/12, close the tab, and have to remember how to get back in.

---

## Cross-link audit

**Counting methodology:** all inline markdown links of form `](target.md)` or `](target.md#anchor)`. Bare-text references (e.g., `` `pipelines/04-pbp-pipeline.md` ``) are not clickable and are counted separately.

### Totals

- Total markdown cross-links: **259** (all verified to resolve to an existing file on disk)
- Broken markdown links: **0**
- Broken backtick-style references (non-clickable but still broken): **12** (all in `rails/01-models.md` and `rails/03-entity-relationships.md`, see below)

### Broken backtick references

These are the ghosts of an earlier doc plan that used different filenames. They are written as `` `pipelines/04-pbp-pipeline.md` `` etc., not as clickable links, so they render as code snippets but mislead any reader searching the tree:

| File | Bad target | Correct target |
| --- | --- | --- |
| `rails/01-models.md:116` | `pipelines/04-pbp-pipeline.md` | `pipelines/02-pbp-pipeline.md` |
| `rails/01-models.md:154` | `pipelines/04-pbp-pipeline.md` | `pipelines/02-pbp-pipeline.md` |
| `rails/01-models.md:155` | `pipelines/01-schedule-pipeline.md` | `pipelines/01-game-pipeline.md` |
| `rails/01-models.md:328` | `pipelines/05-review-detection.md` | `pipelines/06-reconciliation-pipeline.md` (closest existing) |
| `rails/01-models.md:416` | `pipelines/04-pbp-pipeline.md` | `pipelines/02-pbp-pipeline.md` |
| `rails/01-models.md:417` | `pipelines/06-lock-lifecycle.md` | **does not exist** — no lock-lifecycle doc was written |
| `rails/01-models.md:569` | `reference/routes.md` | `rails/05-routes.md` |
| `rails/01-models.md:780` | `pipelines/03-standings-pipeline.md` | `pipelines/04-standings-pipeline.md` |
| `rails/01-models.md:781` | `reference/standings_feature.md` | **does not exist** |
| `rails/01-models.md:841` | `pipelines/02-batch-pipeline.md` | **does not exist** |
| `rails/03-entity-relationships.md:324` | `pipelines/05-review-detection.md` | **does not exist** |
| `rails/03-entity-relationships.md:345` | `pipelines/04-pbp-pipeline.md` | `pipelines/02-pbp-pipeline.md` |

Three of these point to docs that were never created: `pipelines/06-lock-lifecycle.md`, `reference/standings_feature.md`, `pipelines/02-batch-pipeline.md`, plus two references to `pipelines/05-review-detection.md`. The rest point to renamed files.

### Isolated files (<5 outbound links)

Any file with zero to four clickable markdown links to other docs:

**Zero outbound markdown links (32 files):**

- `rails/01-models.md` ... `rails/17-frontend-components.md` — every file in `rails/` **except** `rails/12-jobs.md` (which has exactly one)
- `scraper/00-overview.md` ... `scraper/07-config-and-deployment.md` — all 8 files
- `predict/00-overview.md` ... `predict/07-config-and-deployment.md` — all 8 files

**Under 5 (clickable) outbound links: operations files, reference/conference-tournaments, reference/slug-and-alias, predict/0x (use bare-text refs).**

This is the central finding of the review. 32 of 48 files (67%) have zero clickable outbound links. The knowledge graph is almost entirely one-way: hub files (`README`, `architecture/*`, `pipelines/*`, `reference/*`, `operations/*`) point INTO the technical reference files, but those files never point back out or to each other. The predict and rails reference files are particularly guilty because their inline "Cross-references" sections use bare text like `` `01-endpoints.md` `` instead of markdown links, so they look linked but aren't.

### Hub files (>20 outbound links)

- **`README.md`** — 58 outbound links. True index.
- **`reference/glossary.md`** — 18 outbound links + 60+ concept definitions. Functions as hub even though it's under the outbound-20 bar — every major term cross-refs a detailed file.
- **`reference/matching-and-fallbacks.md`** — 16 outbound links.
- **`operations/runbook.md`** — 13 outbound links.
- **Pipeline files (`01`–`07`)** — 7 to 14 outbound links each. Consistently hub-like.
- **Architecture files** — 7 to 14 outbound links. Good hubs.

**There are no leaf-layer hubs.** Every hub is in architecture/pipelines/reference/operations. Leaves don't even link peer-to-peer (rails/12 to rails/08, for example).

---

## Terminology consistency issues

Spot-checked ~15 terms against the glossary and across docs.

**Consistent and well-used:**

- `quality gate` / `CachedGame.pbp_quality_ok?` — appears in architecture/00, architecture/01, architecture/02, pipelines/02, pipelines/03, rails/01, rails/06, rails/07, rails/13, operations/runbook, glossary. Same definition everywhere. Gold standard.
- `shell link preservation` — consistent across architecture/02, pipelines/01, scraper/01, scraper/02, rails/08, runbook, glossary. Every mention agrees.
- `clinch indicator` (`x`, `y`, `e`) — rails/10, rails/16, pipelines/04, glossary all agree.
- `locked` (game-level) — consistent across pipelines/03, runbook, architecture/01, glossary.
- `negative cache` — pipelines/02, matching-and-fallbacks, glossary agree.
- `doubleheader` / `DH` / `game_number` — consistent across 23 files.
- `Game shell` / `shell Game` — both forms appear (glossary lists both as aliases). OK.
- `team_games vs Game` — clearly distinguished in glossary, entity-relationships, matching-services.

**Inconsistent:**

- **`teams.rank` vs `team.ranking`** — actual DB column (per `rails/02-database-schema.md:317` and `rails/12-jobs.md:418`, `rails/14-schedule.md:36`) is **`rank`**. But `reference/glossary.md:149` says `team.ranking`, and `architecture/02-data-flow.md:112` says `team.ranking`. Two of the hub files have the column name wrong.
- **Two distinct "locks" conflated** — the glossary entry "Locked (game)" defines it as `Game.locked == true`. But `rails/01-models.md:389` documents `CachedGame.locked` as a separate per-row lock with `try_lock!`, `lock!`, `locked?` class methods. These are *different locks on different tables*. The glossary treats "Locked" as one concept. Any reader tracing "locked" from glossary into rails/01 will be confused.
- **Predict health endpoint** — `operations/runbook.md:326` and `operations/database-access.md:134` both curl `http://riseballs-predict.web:8080/health`. But `predict/00-overview.md`, `predict/01-endpoints.md`, `predict/06-schemas.md`, `predict/07-config-and-deployment.md` all agree the actual routes are `/v1/health` and `/v1/ready`. `pipelines/07-prediction-pipeline.md:113` also says `/health`. Three docs send operators to a URL that doesn't exist. Low-risk because the service will 404 loudly, but still broken.

**Terms in docs but not in glossary:**

- `normalizeForDedup` — cited repeatedly in architecture/02, pipelines/01, scraper/02, but only appears in glossary under "Normalization (for dedup)". The mental model "this is the dedup normalization" is there; the glossary head term could mirror the code symbol for searchability.
- `REAL_PLAY` / `QUALITY_PLAY_VERB` / `COMPLETE_THRESHOLD` — scraper/02, scraper/05, pipelines/02 all cite these Java constants. No glossary entry for what "real play" means beyond a passing reference.
- `ghost game` is in the glossary, but "phantom" (used in scraper/00:156) is not cross-referenced.
- `legacy/deprecated` is in the glossary, but `DEAD` and `DEPRECATED` are used as badges throughout (architecture/01, pipelines/03, scraper/02) without a glossary definition.

**Terms in glossary but underused in docs:**

- `GameStatsExtractor`, `PlateAppearance`, `PitchEvent` — defined in glossary, used in doc tree, but the glossary entries don't link anywhere. Should each link to `rails/09-analytics-services.md` and `rails/01-models.md`.
- `JavaScraperClient`, `PredictServiceClient` — glossary entries exist but don't link to `rails/11-external-clients.md`.

---

## Vertical traceability

### "Quality gate"

Trace target: architecture/01 → pipelines/02 → rails/01 → source file.

- `architecture/01-service-boundaries.md:62-76` — "Quality gate authority" section, full description, links to `rails/01-models.md` and `pipelines/02-pbp-pipeline.md`. Clickable.
- `pipelines/02-pbp-pipeline.md:54-72` — "The quality gate" section, list of rejection rules, explicit source file at the top. Links to `architecture/01`, `rails/01-models.md`. Clickable.
- `rails/01-models.md:398` — `pbp_quality_ok?` method documented, rejection criteria enumerated, filed against `cached_game.rb:165`. **But: no link back up to pipelines/02 as a live URL** — the file just references `pipelines/04-pbp-pipeline.md` (broken filename).

**Verdict: trace works until the bottom file, which points at a doc that doesn't exist. Fix: update rails/01 backtick references to real filenames.**

### "Shell link preservation"

Trace target: architecture/02 → pipelines/01 → scraper/02 → source file.

- `architecture/02-data-flow.md:33` — "Shell link preservation" in phase 1 narrative. Describes the snapshot-and-restore dance.
- `pipelines/01-game-pipeline.md:35` — "Why the snapshot dance" — identical explanation, links to `scraper/02-services.md`.
- `scraper/02-services.md:75` — step 4 of `TeamScheduleSyncService` critical-steps list. Names `TeamGame.gameId`, `date|opponentSlug|gameNumber` keying, explains why. References source file at the top.
- `glossary.md:163` — entry "Shell link preservation" defines it and attributes to `TeamScheduleSyncService`.

**Verdict: clean trace. Every level agrees. This is the best vertical in the tree.**

### "Clinch indicators"

Trace target: pipelines/04 → rails/10 → rails/16 → source file.

- `pipelines/04-standings-pipeline.md:107-114` — clinch-indicator table (`x`, `y`, `e`), defined inline. Links to `rails/10-scenario-service.md`.
- `rails/10-scenario-service.md:213-222` — `clinch_indicator(title_status, tournament_status)` method at lines 167-173 of the source file, full truth table. Good.
- `rails/16-frontend-pages.md:159` — `<ClinchIndicator />` React component, colors (green/blue/red), maps to `scenarioMap[team_slug]?.clinch_indicator`. Consistent letters.
- `glossary.md:40-41` — entry matches.

**Verdict: clean vertical trace, consistent definitions. Terminology is uniform.**

---

## Contradictions between docs

### Genuine contradictions

1. **`teams.rank` vs `team.ranking`**
   - `rails/02-database-schema.md:317`, `rails/12-jobs.md:418`, `rails/14-schedule.md:36`: column is `rank`.
   - `architecture/02-data-flow.md:112`: writes "team.ranking".
   - `reference/glossary.md:149`: says "Integer `team.ranking`".
   - **Likely bug:** either the code has a column named `rank` (correct), in which case glossary + architecture/02 are wrong; or `ranking` is an alias. Given three source-adjacent docs say `rank`, the hub docs appear wrong.

2. **Predict health endpoint path**
   - `operations/runbook.md:326` and `operations/database-access.md:134` say `http://riseballs-predict.web:8080/health`.
   - `pipelines/07-prediction-pipeline.md:113` says `GET /health`.
   - `predict/00-overview.md:43`, `predict/01-endpoints.md:26-40`, `predict/06-schemas.md:262-263`, `predict/07-config-and-deployment.md:207-208` all say the routes are `/v1/health` and `/v1/ready`.
   - **Likely bug:** the predict service itself documents `/v1/*`. The three operator-facing docs send people to the wrong URL.

3. **Locked conflation (documentation gap, not a factual contradiction)**
   - Glossary defines "Locked (game)" as `Game.locked == true`.
   - rails/01-models describes `CachedGame` as having its own per-row `locked` boolean and a `try_lock!` gate tied to PBP + boxscore presence.
   - A reader encountering "locked" has no way to tell from the glossary that there are two orthogonal locks.
   - **Fix:** add a glossary entry "Locked (cached_game)" or rename the existing entry for clarity.

### Non-contradictions I checked and cleared

- Box-score fallback chain (`athletics → WMT → Cloudflare → AI`) — consistent across pipelines/01, pipelines/03, reference/matching-and-fallbacks, glossary, architecture/01.
- Cron schedules — `rails/14-schedule.md` and `pipelines/01-game-pipeline.md` agree on times (every 15 min, 5 * * * * for recovery, 3 AM for reconciliation, etc.).
- Service ports / internal URLs — all docs agree: Rails 3000, Java 8080, Predict 8080.
- `normalizeForDedup` behavior — architecture/02, pipelines/01, scraper/02 all describe the same ranking-strip-then-alias-resolve sequence.
- Conference tournament formats — conference-tournaments and pipelines/04 agree on SEC 15, Big Ten 12, ACC 12, Big 12 11, Ivy 4, NEC 4, Patriot 4.
- Dokku enter vs run — glossary, architecture/00, database-access, runbook all agree.

---

## Structural observations

### TOC / section-heading hygiene

- **Every `rails/*.md` file has a "Table of Contents" section.** All 14 non-trivial rails files (01–14; 15–17 are shorter). Excellent.
- **No other directory uses TOCs.** 0 of 3 architecture files, 0 of 7 pipelines, 0 of 8 scraper, 0 of 8 predict, 0 of 4 reference, 0 of 3 operations, 0 of README. The rails/ convention is not the project convention.
- For long files (e.g., `predict/04-explain-engine.md` at 10.8 KB, `pipelines/02-pbp-pipeline.md` at 9.9 KB, `scraper/04-reconciliation.md` at 16.1 KB) TOCs would actually help.

### Mermaid diagrams

- 21 of 48 files have at least one mermaid diagram.
- Sampled diagrams from architecture/00, architecture/02, pipelines/01, pipelines/02, scraper/03, rails/14, pipelines/07 — all parse cleanly (valid `flowchart`, `sequenceDiagram`, `stateDiagram-v2`; balanced brackets; no obvious typos).
- No diagrams spotted with syntax breakage.

### Files that may be in the wrong directory

Checked every file's content vs its directory:

- **`rails/10-scenario-service.md`** — title "Conference Scenario Service", strictly about the Rails service. Correct location.
- **`rails/14-schedule.md`** — cron scheduling, Rails-side (sidekiq-cron). Correct.
- **`reference/conference-tournaments.md`** — format matrix + bracket structure. Correct as a reference doc.
- **`scraper/04-reconciliation.md`** — Java-side reconciliation internals. Correct, and pairs with `pipelines/06-reconciliation-pipeline.md` (which is the Rails trigger side). Good split.
- **`pipelines/07-prediction-pipeline.md`** — entry sequence diagram is Rails-centric but quickly crosses into predict internals. A reasonable horizontal doc; no better home.

**No files stood out as misplaced.**

### Other structural notes

- **`predict/` uses bare-text cross-references.** Every `predict/0x.md` file ends with a "Cross-references" or "See also" block where filenames are plain text (e.g., `` `01-endpoints.md` ``) rather than links. 8 files, ~30 unclickable references. Low effort fix: convert to `[01-endpoints.md](01-endpoints.md)`.
- **`scraper/` has a similar-but-partial issue.** Most scraper files use markdown links where they link at all, but per-file link counts are 0–3 at best. Several scraper files have no cross-refs section at all.
- **`rails/` uses backtick-style refs throughout.** Explains the zero-markdown-link count for every file except 12-jobs. Converting all backtick refs in rails/ to markdown links is the single biggest knowledge-graph win available.
- `README.md` uses inline anchor-free links. Not a problem, just a stylistic note — some target files have section anchors that could be used.

---

## Recommendations

Concrete edits, ranked by impact-to-effort ratio:

1. **Fix the 12 broken backtick references in `rails/01-models.md` and `rails/03-entity-relationships.md`.** Rename targets per the table in the cross-link audit section. Delete references to non-existent `pipelines/06-lock-lifecycle.md`, `pipelines/05-review-detection.md`, `reference/standings_feature.md`, `pipelines/02-batch-pipeline.md` (or write those docs — flag to author: at least `lock-lifecycle` sounds valuable).

2. **Convert rails/ and predict/ backtick references to clickable markdown links.** This alone transforms the graph from unidirectional to bidirectional. Effort: ~1 hour per directory with a script.

3. **Fix the three factual contradictions:**
   - Update `glossary.md:149` and `architecture/02-data-flow.md:112` to use `teams.rank` (the real column).
   - Update `operations/runbook.md:326`, `operations/database-access.md:134`, and `pipelines/07-prediction-pipeline.md:113` to use `/v1/health` instead of `/health` for the predict service.
   - Split the glossary "Locked" entry into "Locked (game)" and "Locked (cached_game)" or add a sentence that disambiguates.

4. **Add a TOC to any file longer than ~400 lines.** Priority targets: `scraper/04-reconciliation.md`, `predict/04-explain-engine.md`, `pipelines/02-pbp-pipeline.md`, all architecture files. The rails TOC convention is a good model to copy.

5. **Add glossary entries for in-doc terms that have no definition:** `REAL_PLAY`, `COMPLETE_THRESHOLD`, `phantom game` (or cross-reference to ghost game), `DEPRECATED/DEAD` badge convention.

6. **Add a doubleheader reading path to the README.** Something like: `"How do doubleheaders work?" → rails/08-matching-services.md → scraper/02-services.md → reference/glossary.md (DH entry)`. This is a top-3 persona for operators and currently has no signpost.

7. **Add footer "back to" links in every leaf file.** Each `rails/*.md`, `scraper/*.md`, `predict/*.md` should end with at least a one-line "← see also: pipelines/…, operations/runbook" block of markdown links. Makes every leaf reachable from every other leaf.

8. **Link every glossary term's first-mention phrase to the glossary.** For example, `rails/08-matching-services.md` mentions "shell model" — could link the phrase to `../reference/glossary.md#game-shell`. Low-effort, high navigability gain.

---

## Overall knowledge-graph score: C+

The hub layer (`README`, `architecture/`, `pipelines/`, `reference/`, `operations/`) is genuinely good — dense, accurate, interlinked, consistent, and traces vertically. A reader who stays within these five directories can navigate the whole system. Zero broken markdown links across 259 checked is a real achievement, and the terminology hygiene for major terms like `quality gate`, `shell link preservation`, and `clinch indicator` is exemplary.

But 67% of the files (32 of 48) — every single rails/, scraper/, and predict/ file — have zero clickable outbound links. These files are reference material, not graph nodes. The user asked for "a full-fledged knowledge graph"; what exists is a well-designed hub-and-spoke index where the spokes are dead ends. The 12 broken backtick references in `rails/01-models.md` and `rails/03-entity-relationships.md` also point to an earlier doc plan with different filenames, suggesting the tree was generated in multiple passes without a final link-reconciliation sweep. Three minor factual contradictions (`teams.rank` vs `team.ranking`, predict `/health` vs `/v1/health`, and the unmarked dual use of "locked") persist in hub files where they will be most confusing.

This is a solid B-grade technical reference that becomes a genuine A-grade knowledge graph if the ~40 backtick references in rails/ and predict/ are converted to markdown links and the 12 broken targets are fixed. The content is there; the graph wiring is half-built.
