# Controllers — REST surface

Every `@RestController` in the service. Base paths are under `/api/*`. All methods are `POST` except health and schedule-verify. No auth layer — access control is network-level (only reachable within the Dokku internal network at `http://riseballs-scraper.web:8080`).

---

## `ScrapeController` — box score + PBP scrape

**File:** `src/main/java/com/riseballs/scraper/controller/ScrapeController.java`
**Base path:** `/api/scrape`
**Injected:** `ScrapeOrchestrator`, `PbpOrchestrator`, plus a `Semaphore(ScraperProperties.maxConcurrentGames)` for PBP batch throttling.

| Method | Path | Body (DTO) | Response | What it does |
|--------|------|-----------|----------|--------------|
| GET | `/health` | — | `{"status":"ok"}` | Liveness probe. |
| POST | `/boxscore` | `ScrapeRequest{gameId}` | `ScrapeResponse{gameId, success, boxscore?}` | Synchronously calls `orchestrator.scrapeGame(gameId)` — fetcher chain + validation + cache + stats + PBP. |
| POST | `/boxscores` | `BatchScrapeRequest{gameIds}` (max 500) | `BatchScrapeResponse{results[]}` | `orchestrator.scrapeGames(ids)` — uses virtual threads internally. Caps body at 500 ids. |
| POST | `/pbp` | `ScrapeRequest{gameId}` | `{gameId, success}` | `pbpOrchestrator.reparsePbp(id)` — tries cached PBP → WMT API → Sidearm refetch. |
| POST | `/pbp/batch` | `BatchScrapeRequest{gameIds}` (max 500) | `{total, succeeded, failed}` | Virtual-thread pool; per-task `semaphore.acquire()` + `Thread.sleep` rate limit; `future.get(5, MINUTES)` timeout per game. |

**Rails callers:** `JavaScraperClient.scrape_boxscore`, `.scrape_boxscores`, `.reparse_pbp`, `.reparse_pbp_batch`. Invoked from `BoxScoreFetchJob`, `BoxScoreBackfillJob`, `PbpReparseJob`.

---

## `ReconciliationController` — WMT cancelled-game reconciler

**File:** `src/main/java/com/riseballs/scraper/reconciliation/ReconciliationController.java`
**Base path:** `/api/reconcile`

| Method | Path | Body | Response | What it does |
|--------|------|------|----------|--------------|
| POST | `` (root) | — | `ReconciliationResult` | `reconciliationService.reconcile()` — full run: find cancelled / stale-scheduled games, check WMT API (+ schedule page fallback), move to `final` with scores, trigger box score fetch. |
| POST | `/check` | — | `ReconciliationResult` | Dry run. |

`ReconciliationResult` record has `candidatesFound, repaired, skipped, failed, dryRun, actions[]` where each action is `{gameId, homeTeamSlug, awayTeamSlug, gameDate, previousState, action, reason, homeScore, awayScore}`.

**Rails caller:** `JavaScraperClient.reconcile_games` — `GameReconciliationJob`.

---

## `ScheduleReconciliationController` — per-team schedule-first reconciler

**File:** `src/main/java/com/riseballs/scraper/reconciliation/ScheduleReconciliationController.java`
**Base path:** `/api/reconcile/schedule`

| Method | Path | Body | Response | What it does |
|--------|------|------|----------|--------------|
| POST | `` | — | `FullReconciliationResult` | `orchestrator.reconcileAll(false)` — every team with an athletics URL (~592). Virtual threads, Semaphore(5), 500ms rate limit per team. |
| POST | `/check` | — | `FullReconciliationResult` | Dry run. |
| POST | `/team` | `{"teamSlug":"virginia"}` | `FullReconciliationResult` | Single-team live run. |
| POST | `/team/check` | `{"teamSlug":"virginia"}` | `FullReconciliationResult` | Single-team dry run. |

`FullReconciliationResult` — `teamsProcessed, teamsSucceeded, teamsFailed, gamesCreated, gamesUncancelled, gamesDateCorrected, gamesScoreCorrected, gamesFinalized, gamesFlaggedForReview, gamesNoChange, dryRun, actions[], elapsedMs`.

**Rails caller:** `JavaScraperClient.reconcile_schedule` → `ScheduleReconciliationJob`. The orchestrator's downstream effect is heavy: creating/updating games triggers `scrapeOrchestrator.scrapeGame(gameId)` inside `ReconciliationExecutor`, which pulls in the fetcher chain and writes PGS + PBP.

---

## `NcaaDateReconciliationController` — NCAA GraphQL date corrector

**File:** `src/main/java/com/riseballs/scraper/reconciliation/NcaaDateReconciliationController.java`
**Base path:** `/api/reconcile/ncaa-dates`

| Method | Path | Body | Response |
|--------|------|------|----------|
| POST | `` | — | `NcaaDateReconciliationResult` |
| POST | `/check` | — | `NcaaDateReconciliationResult` (dry) |

`NcaaDateReconciliationResult` — `dateCorrected, duplicatesRemoved, ncaaWrong, flaggedForReview, skipped, noChange, errors, dryRun, elapsedMs`.

**Rails caller:** `JavaScraperClient.reconcile_ncaa_dates`. See `04-reconciliation.md` for the full decision tree (NCAA API → verify both teams' schedules → MOVE/NCAA_WRONG/REVIEW → conflict resolution).

---

## `RosterController` — player + coach augmentation

**File:** `src/main/java/com/riseballs/scraper/roster/RosterController.java`
**Base path:** `/api/roster`
**Injected:** `RosterAugmentService`, `CoachAugmentService`, `WmtRosterService`.

| Method | Path | Body | Response | What it does |
|--------|------|------|----------|--------------|
| POST | `/augment` | `{teamSlug}` | `{success, teamSlug, teamName, augmented, skipped, failed, totalPlayers}` | `rosterAugmentService.augmentTeam(slug)` — WMT-first if `isWmtTeam`, else Sidearm bio page scrape via `BioPageParser`. |
| POST | `/augment/all` | — | `{success, totalTeams, totalAugmented, teamsFailed, results[]}` | Augment every team (long-running; Rails calls from Sidekiq only). |
| POST | `/augment-coaches` | `{teamSlug}` | (same shape as `/augment`, with `totalCoaches`) | `coachAugmentService.augmentTeam(slug)` — parses coach bio with `CoachBioParser`. |
| POST | `/augment-coaches/all` | — | `{...}` | All teams. |
| POST | `/wmt-sync` | `{teamSlug}` | `{success, teamSlug, augmented, skipped, failed, totalPlayers}` | `wmtRosterService.syncTeam(slug)` — WMT website-api only (photo, position, year, height, hometown, HS, prev school, transfer flag). |
| POST | `/wmt-sync/all` | — | `{...}` | All WMT teams. |

**Contract guaranteed by all three services:** update-only. They never create, rename, or delete Player / Coach rows. `WmtRosterService` matches by jersey number (primary) or last name (fallback); `RosterAugmentService` matches by name case-insensitive on `findByTeamId(team.id)`. **A Player must already exist** (from the Ruby-side `RosterSync` job) — these services augment, they don't seed.

**Rails caller:** `JavaScraperClient.augment_roster`, `.wmt_sync_roster`, `.augment_coaches`. See `feedback_localscraper.md` — roster calls must go through localscraper, never the Playwright Cloudflare worker.

---

## `GameCreationController` — the one true game creation gate

**File:** `src/main/java/com/riseballs/scraper/controller/GameCreationController.java`
**Base path:** `/api/games`

| Method | Path | Body | Response |
|--------|------|------|----------|
| POST | `/find-or-create` | `GameCreationRequest` | `GameCreationResult{gameId, created, matchStrategy}` |
| POST | `/find-or-create-batch` | `List<GameCreationRequest>` | `GameCreationBatchResult{matched, created, failed, results[]}` |

`GameCreationRequest` fields: `gameDate, homeSlug, awaySlug, gameNumber, ncaaContestId, homeScore, awayScore, state, ncaaGameId, startTimeEpoch, neutralSite, source`.

Matching order inside `GameCreationService`:
1. Exact `ncaa_contest_id` (global, date-agnostic — this is how NCAA-seeded games de-duplicate across date moves).
2. `(game_date, sorted[homeSlug, awaySlug], game_number)`.
3. `(game_date, sorted[homeSlug, awaySlug])` any game number, prefer unmatched.

Wrapped in a `TransactionTemplate` with a single retry on `DataIntegrityViolationException` (race condition between concurrent callers — two schedule reconciliation threads finding the same game).

**Rails caller:** currently called internally by `ReconciliationExecutor` (for `CREATE` actions) and exposed for Rails jobs that need to idempotently seed games.

---

## `ScheduleVerificationController` — is this matchup real?

**File:** `src/main/java/com/riseballs/scraper/controller/ScheduleVerificationController.java`
**Base path:** `/api/schedule`

| Method | Path | Query params | Response |
|--------|------|--------------|----------|
| GET | `/verify` | `team`, `opponent` (slugs) | `{team, opponent, entries[], parser, totalScheduleEntries}` |

Fetches **every** `SchedulePageParser` that `canParse(team)` and picks the one with the most entries. Filters entries by resolved opponent slug. Each matching entry returns `{gameDate, opponentName, opponentSlug, teamScore, opponentScore, state, boxscoreUrl, gameNumber, isHome}`.

**Rails caller:** `GhostGameDetectionJob` — before deleting a suspected ghost game, it calls this endpoint for both teams. If neither team's live schedule shows the opponent on the game's date, it's safe to delete.

---

## `TeamScheduleSyncController` — schedule page → `team_games`

**File:** `src/main/java/com/riseballs/scraper/controller/TeamScheduleSyncController.java`
**Base path:** `/api/team-schedule`

| Method | Path | Body | Response |
|--------|------|------|----------|
| POST | `/sync-all` | — | `{teams, succeeded, failed, gamesCreated, elapsedMs}` |
| POST | `/sync-team` | `{teamSlug}` | `{team, created, updated, skipped}` |

`syncAll` filters `teamRepository.findAll()` for non-blank `athleticsUrl`, then runs `TeamScheduleSyncService.sync(team)` on each with virtual threads + `Semaphore(MAX_CONCURRENT=5)` + 500ms rate limit + 10-minute per-team task timeout. See `02-services.md` for the critical internals (doubleheader game_number assignment, shell link preservation, the `normalizeForDedup` opponent-resolution dedup).

---

## `StandingsController` — conference standings scrape

**File:** `src/main/java/com/riseballs/scraper/standings/StandingsController.java`
**Base path:** `/api/standings`

| Method | Path | Body | Response |
|--------|------|------|----------|
| POST | `/scrape` | `{season?}` | `{season, division, totalConferences, succeeded, failed, results[]}` |
| POST | `/scrape/division` | `{season?, division="d1"}` | (same) |
| POST | `/scrape/conference` | `{season?, division, conference}` | (same, 1-item `results`) |

Dispatches to `StandingsOrchestrator`. Defaults: `season=2026`, `division="d1"`.

---

## `MetricsController` — homepage facts computation

**File:** `src/main/java/com/riseballs/scraper/controller/MetricsController.java`
**Base path:** `/api/metrics`

| Method | Path | Body | Response |
|--------|------|------|----------|
| POST | `/compute` | — | `{status:"ok", divisions:{d1:{status,metrics_count}, d2:{...}}}` |

`D1MetricsService.computeAll()` iterates over `d1` and `d2` divisions, computes ~8+ homepage metrics in parallel via virtual threads, and upserts the JSON blob to `site_metrics` keyed `{division}_facts`.

**Rails caller:** Sidekiq cron `ComputeD1MetricsJob`. Replaces a Ruby implementation that was too slow.
