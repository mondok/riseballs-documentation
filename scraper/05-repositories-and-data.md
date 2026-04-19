# Repositories and data layer

All Spring Data JPA repositories and the entities they manage. Plus a per-service write map so you can quickly find "which service touches table X."

---

## Entity inventory

All under `src/main/java/com/riseballs/scraper/model/` (15 entities) + `src/main/java/com/riseballs/scraper/standings/model/` (3 entities). `@Table(name=...)` annotations map camelCase Java fields to snake_case Postgres columns. Schema is owned by Rails — `spring.jpa.hibernate.ddl-auto: none`.

### Core entities

| Entity | Table | Notable fields |
|--------|-------|----------------|
| `Game` | `games` | `id, gameDate, homeTeamSlug, awayTeamSlug, homeScore, awayScore, state, gameNumber, ncaaGameId, ncaaContestId, startTimeEpoch, dataFreshness, locked, homeBoxScoreId, awayBoxScoreId, liveStatsUrl, metadataJsonb, createdAt, updatedAt` |
| `Team` | `teams` | `id, slug, name, longName, nickname, division, conference, logoUrl, athleticsUrl, rpi, wmtSchoolId` |
| `Player` | `players` | `id, teamId, name, firstName, lastName, number, position, year, photo, profileUrl, height, hometown, highSchool, previousSchool, isTransfer, twitterUrl, instagramUrl, ...` |
| `PlayerGameStat` | `player_game_stats` | `id, gameId, ncaaGameId, teamSeoSlug, playerName, atBats, hits, runsScored, runsBattedIn, walks, strikeouts, doubles, triples, homeRuns, stolenBases, hitByPitch, sacrificeFlies, sacrificeBunts, caughtStealing, fieldingErrors, inningsPitched (BigDecimal), pitchHitsAllowed, pitchRunsAllowed, pitchEarnedRuns, pitchWalks, pitchStrikeouts, pitchHomeRunsAllowed` |
| `Coach` | `coaches` | `id, teamId, name, title, email, phone, photo, twitterUrl, instagramUrl, ...` |

### Support entities

| Entity | Table | Purpose |
|--------|-------|---------|
| `CachedGame` | `cached_games` | JSONB payload cache. Key columns: `gameId`, `ncaaGameId`, `dataType` (`athl_boxscore` / `athl_play_by_play`), `sourceTeamSlug`, `payload (jsonb)`. |
| `GameTeamLink` | `game_team_links` | Per-team boxscore URL map. `gameId, teamSlug, boxScoreUrl, sidearmGameId`. The scrape pipeline reads these to know where to fetch a given team's boxscore. |
| `PlateAppearance` | `plate_appearances` | One row per batter's PA. `teamSlug, gameSourceId, inning, half, batterId, result, resultCategory, finalCount, pitchCount, ...` |
| `PitchEvent` | `pitch_events` | Per-pitch + base-running events. `teamSlug, gameSourceId, paId, pitchNumber, pitchCode, ballsBefore, strikesBefore, ...` |
| `ScrapedPage` | `scraped_pages` | HTML cache for roster/coach bios. Keyed by `(url, pageType)`. |
| `SiteMetric` | `site_metrics` | Homepage facts JSON blobs keyed `{division}_facts` (e.g., `d1_facts`, `d2_facts`). `key, valueJsonb, updatedAt`. |
| `TeamAlias` | `team_aliases` | Name → slug map consumed by `OpponentResolver`. Loaded once at startup. |
| `TeamGame` | `team_games` | Per-team schedule row. Unique `(teamSlug, gameDate, gameNumber)` and `(teamSlug, boxscoreId)`. `gameId` optionally links back to `games.id`. |
| `GameReview` | `game_reviews` | Admin review queue. `gameId, reviewType, reason, source, status, proposedChanges (json)`. |
| `GameRef` | *(none — utility, not persisted)* | Helper record for consistent log formatting: `GameRef.of(game)` → `"gameId vs teams on date"`. |

### Standings entities (`standings/model/`)

| Entity | Table | Purpose |
|--------|-------|---------|
| `ConferenceSource` | `conference_sources` | One row per conference × season × division × parser_type. Drives `StandingsOrchestrator` dispatch. Columns: `season, division, conference, standingsUrl, parserType ("sidearm"/"sec"/"boostsport"/"mw"/"prestosports"), active, lastScrapedAt, lastScrapeStatus`. |
| `ConferenceStanding` | `conference_standings` | Parsed standings row. `season, division, conference, teamName, teamSlug, confWins, confLosses, overallWins, overallLosses, confWinPct, overallWinPct, streak, confRank, scrapedAt`. |
| `StandingsScrapeLog` | `standings_scrape_logs` | Per-run log with first 500 KB of raw HTML, parsedCount, errorMessage. |

---

## Repositories

### `GameRepository` — the fattest repo

**File:** `repository/GameRepository.java` (90 LOC). Custom queries drive reconciliation:

```java
Optional<Game> findByNcaaGameId(String);
Optional<Game> findByNcaaContestId(Long);

@Query /* cancelled OR stale-pre within lookback */
List<Game> findReconciliationCandidates(staleCutoff, lookbackStart);

@Query /* final sibling games in a series, ± days */
List<Game> findFinalSeriesSiblings(homeSlug, awaySlug, dateStart, dateEnd);

@Query /* exact-dupe detector for WMT reconciliation */
List<Game> findDuplicateFinals(gameDate, homeSlug, awaySlug, homeScore, awayScore, excludeId);

@Query /* matchup lookup (direction-agnostic) */
List<Game> findByDateAndTeams(date, slug1, slug2);

@Query List<Game> findByDateRangeAndTeams(dateStart, dateEnd, slug1, slug2);
@Query List<Game> findByDateRangeAndTeamSlug(dateStart, dateEnd, slug);

List<Game> findByHomeTeamSlugOrAwayTeamSlug(homeSlug, awaySlug);
```

All JPQL; direction-agnostic queries use `(home = :a AND away = :b) OR (home = :b AND away = :a)`.

### `TeamGameRepository`

```java
List<TeamGame> findByTeamSlug(slug);
List<TeamGame> findByTeamSlugAndGameDate(slug, date);
Optional<TeamGame> findByTeamSlugAndGameDateAndGameNumber(slug, date, gn);
Optional<TeamGame> findByTeamSlugAndBoxscoreId(slug, boxscoreId);
List<TeamGame> findByTeamSlugAndState(slug, state);

@Modifying @Transactional
void deleteByTeamSlugAndStateNot(slug, state);  // deletes every row not in `state`
```

### `TeamRepository`, `TeamAliasRepository`

Simple. `findBySlug(slug)` and `findByAliasNameIgnoreCase(name)`. Both are called once at startup by `OpponentResolver` and then held in memory.

### `PlayerRepository`, `CoachRepository`

```java
// Player
@Query("SELECT p.name FROM Player p JOIN Team t ON p.teamId = t.id WHERE t.slug = :teamSlug")
List<String> findNamesByTeamSlug(String teamSlug);  // used by TeamAssignmentVerifier for roster cross-check

List<Player> findByTeamId(Long teamId);

// Coach
List<Coach> findByTeamId(Long teamId);
```

### `PlayerGameStatRepository`

```java
Optional<PlayerGameStat> findByNcaaGameIdAndTeamSeoSlugAndPlayerName(...);
List<PlayerGameStat> findByGameId(Long gameId);

@Transactional void deleteByGameId(Long gameId);
@Transactional void deleteByNcaaGameId(String ncaaGameId);
```

### `CachedGameRepository`

```java
Optional<CachedGame> findByNcaaGameIdAndDataType(ncaaGameId, dataType);
Optional<CachedGame> findByGameIdAndDataType(gameId, dataType);

@Transactional void deleteByGameIdAndDataType(gameId, dataType);
```

### `GameTeamLinkRepository`

```java
List<GameTeamLink> findByGameId(gameId);

@Query("SELECT gtl FROM GameTeamLink gtl WHERE gtl.gameId = :gameId " +
       "AND gtl.boxScoreUrl IS NOT NULL AND gtl.boxScoreUrl <> ''")
List<GameTeamLink> findByGameIdWithBoxScoreUrl(gameId);
```

### `PlateAppearanceRepository`, `PitchEventRepository`

Each one method each:
```java
void deleteByTeamSlugAndGameSourceId(teamSlug, gameSourceId);
```
PBP writes are scoped to `(teamSlug, gameSourceId)` rather than `gameId` so WMT PBP (keyed by WMT game ID) and Sidearm PBP (keyed by Sidearm game ID) for the same game can coexist without clashing.

### `ScrapedPageRepository`

```java
Optional<ScrapedPage> findByUrlAndPageType(url, pageType);
```
Used by `RosterAugmentService` / `CoachAugmentService` for HTML cache so a re-run of `/augment/all` doesn't re-fetch unchanged pages.

### `SiteMetricRepository`

```java
Optional<SiteMetric> findByKey(String key);
```
Used by `D1MetricsService` to upsert `d1_facts` and `d2_facts`.

### `GameReviewRepository`

```java
List<GameReview> findByGameIdAndStatusAndReviewType(gameId, status, reviewType);
```
Used by reconciliation writers to avoid duplicate pending reviews for the same game.

### Standings repos

- `ConferenceSourceRepository` — `findBySeasonAndActiveTrue`, `findBySeasonAndDivisionAndActiveTrue`, `findBySeasonAndDivisionAndConference`.
- `ConferenceStandingRepository` — `findBySeasonAndConferenceOrderByConfRankAsc`, `findBySeasonAndDivisionOrderByConferenceAscConfRankAsc`, `@Transactional void deleteBySeasonAndConference(season, conference)`.
- `StandingsScrapeLogRepository` — `findByConferenceSourceIdOrderByScrapedAtDesc` (admin viewer).

---

## Who writes what

| Table | Writer service | Write pattern |
|-------|----------------|---------------|
| `games` | `GameCreationService.findOrCreate` (insert path) + `ReconciliationExecutor.execute*` + `NcaaDateReconciliationWriter.correctDate`/`removeDuplicate` | Narrow per-action transactions |
| `team_games` | `TeamScheduleSyncService.sync` only | `deleteByTeamSlugAndStateNot + flush`, then insert/upsert |
| `game_team_links` | `ReconciliationExecutor.upsertGameTeamLink` (schedule reconciliation) + `UrlRediscoveryFetcher` (when it discovers a new URL) | Upsert |
| `player_game_stats` | `GameStatsWriter.write` only | `@Transactional`: delete-by-gameId + delete-by-ncaaGameId (multiple ID variants) + `flush` + bulk insert |
| `cached_games` | `ScrapeOrchestrator.storeCachedBoxscore` + `PbpOrchestrator.writeCachedPbp` | Upsert by `(gameId, dataType)` + `(ncaaGameId, dataType)` |
| `plate_appearances` | `PbpWriter` | `deleteByTeamSlugAndGameSourceId` + bulk insert |
| `pitch_events` | `PbpWriter` | same |
| `players` | `WmtRosterService.syncTeam` + `RosterAugmentService.augmentTeam` (Sidearm path) | UPDATE ONLY — never insert/delete/rename |
| `coaches` | `CoachAugmentService.augmentTeam` | UPDATE ONLY |
| `scraped_pages` | `RosterAugmentService` + `CoachAugmentService` (cache writes) | Upsert by `(url, pageType)` |
| `site_metrics` | `D1MetricsService.compute` | Upsert by key |
| `teams` | *not written from Java* — Rails-only | — |
| `team_aliases` | *not written from Java* — Rails admin only | loaded at startup |
| `conference_sources` | `StandingsOrchestrator` updates `lastScrapedAt`/`lastScrapeStatus` only | — |
| `conference_standings` | `StandingsOrchestrator.persistStandings` | `@Transactional`: `deleteBySeasonAndConference` + bulk insert |
| `standings_scrape_logs` | `StandingsOrchestrator.recordSuccess`/`recordFailure` | Insert-only |
| `game_reviews` | `ReconciliationExecutor.executeFlagForReview` + `NcaaDateReconciliationWriter.createReview` | Idempotent insert guarded by `findByGameIdAndStatusAndReviewType` |

---

## Quality-gate hazard map

(Every row here is a place where Ruby-side validations are bypassed and where recent bugs have clustered.)

| Write | Ruby gate that's bypassed | Mitigation in Java |
|-------|----------------------------|---------------------|
| `CachedGame.payload` for `athl_boxscore` | Ruby `BoxScoreQualityCheck` | `ScoreValidator.scoresMatch`, `ScoreValidator.isGoodBoxscore`, `TeamAssignmentVerifier.verifyAndFix` — all in-memory before `storeCachedBoxscore` |
| `CachedGame.payload` for `athl_play_by_play` | Ruby `pbp_quality_ok?` | `PbpOrchestrator.COMPLETE_THRESHOLD = 40` real plays required, regex-filtered. Quality check in `evaluateCandidate` chooses the best PBP source, not the first. |
| `PlayerGameStat` delete+reinsert | Ruby `PlayerGameStat#normalize_player_name`, team_seo_slug normalization | Relies on `SidearmBoxscoreParser` / `WmtResponseParser` emitting correct seoname + player_name. No safety net. |
| `Game.homeScore`/`awayScore` update | Rails `Game#ensure_distinct_teams`, `Game#before_save` callbacks | None. Reconciliation code writes directly. |
| `team_games` delete + reinsert | — (Rails has its own `TeamGameMatcher` but doesn't run on Java writes) | Shell-link snapshot/restore preserves `gameId` linkages across syncs. |
| `plate_appearances` / `pitch_events` delete + reinsert | Ruby `PitchByPitchParser` validation | `PbpParser` itself is the validator — but it's a rewrite of the Ruby parser, so parity risks are real. |
| `Player.previousSchool` / `isTransfer` write | Ruby `Player#detect_transfer` | `knownCollegeNames` set loaded at startup from `Team.name` + `Team.longName`. |

**Rule of thumb when adding a new Java write:** grep Rails for the model's `before_save`/`after_save` callbacks and validations, then either port them to Java or document why they're unnecessary.
