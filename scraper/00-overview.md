# Riseballs Scraper — Overview

Java Spring Boot service that scrapes college softball box scores, play-by-play, rosters, schedules, and standings from ~8 different upstream platforms (WMT/Learfield, Sidearm, PrestoSports, WordPress/LSU-style, Boostsport, SEC, Mountain West, NCAA GraphQL). Writes directly to the Rails Postgres (`riseballs_db`) via Spring Data JPA — bypassing every Ruby quality gate.

**Repo root:** `/Users/mattmondok/Code/riseballs-parent/riseballs-scraper/`
**Main entry:** `src/main/java/com/riseballs/scraper/ScraperApplication.java` — standard `@SpringBootApplication`.

---

## Stack

| Component | Version / Library | Reference |
|-----------|-------------------|-----------|
| Language | Java 21 (virtual threads, records) | `build.gradle` line 12 |
| Framework | Spring Boot 3.4.4 | `build.gradle` line 3 |
| Persistence | Spring Data JPA / Hibernate (PostgreSQLDialect) | `application.yml` |
| Database driver | `org.postgresql:postgresql` | `build.gradle` line 23 |
| HTTP client | `java.net.http.HttpClient` (built-in, JDK 21) — single bean in `config/HttpClientConfig.java` | `config/HttpClientConfig.java` |
| HTML parsing | Jsoup 1.18.3 | `build.gradle` line 24 |
| JSON | Jackson databind (via Spring auto-config) | `build.gradle` line 25 |
| Build | Gradle wrapper (`./gradlew`); produces `build/libs/riseballs-scraper.jar` | `build.gradle` line 35-37 |
| Runtime | Eclipse Temurin Alpine; JRE 21 | `Dockerfile` |
| Tests | JUnit 5 + H2 in-memory DB | `build.gradle` line 28 |

No OkHttp, no WebClient, no Reactor — everything uses the JDK built-in `HttpClient` (sync `.send()` calls with `HttpResponse.BodyHandlers.ofString()` / `ofByteArray()`). Concurrency is done with **virtual threads + Semaphore** (classic pattern), not reactive streams.

---

## Package layout

Package root: `com.riseballs.scraper` under `src/main/java/com/riseballs/scraper/` (142 source files).

```
com.riseballs.scraper
├── ScraperApplication.java           # Spring Boot main
├── config/                           # @Configuration + env post-processors
│   ├── DatabaseUrlConfig.java        # DATABASE_URL -> spring.datasource.* (EnvironmentPostProcessor)
│   ├── HttpClientConfig.java         # java.net.http.HttpClient @Bean (10s connect, follow redirects)
│   └── ScraperProperties.java        # @ConfigurationProperties(prefix="scraper")
├── controller/                       # Scrape/game/metrics/schedule-verification controllers
│   ├── GameCreationController.java
│   ├── MetricsController.java
│   ├── ScheduleVerificationController.java
│   ├── ScrapeController.java
│   └── TeamScheduleSyncController.java
├── dto/                              # Request/response payloads for /api/scrape/*
├── model/                            # JPA @Entity classes (Game, Team, Player, Coach,
│                                     #  CachedGame, GameTeamLink, PlateAppearance,
│                                     #  PitchEvent, PlayerGameStat, ScrapedPage,
│                                     #  SiteMetric, TeamAlias, TeamGame, GameReview, GameRef)
├── reconciliation/                   # WMT + schedule + NCAA date reconciliation subsystems
│   ├── schedule/                     # Schedule-page parsers + OpponentResolver
│   ├── NcaaDateReconciliation*.java  # NCAA GraphQL date sync
│   ├── Schedule*.java                # Per-team schedule reconciliation
│   └── Reconciliation*.java          # WMT-based cancelled-game reconciliation
├── repository/                       # Spring Data JPA repositories (14 repos)
├── roster/                           # Player/coach roster augmentation
│   ├── BioPageParser.java            # Sidearm player-bio HTML
│   ├── CoachAugmentService.java      # + CoachBioParser
│   ├── RosterAugmentService.java     # dispatches WMT-first, Sidearm bio fallback
│   └── WmtRosterService.java         # WMT website-api JSON sync
├── service/                          # Scrape pipeline (orchestrator + fetchers + parsers + validation)
│   ├── fetcher/                      # Per-source fetchers implementing BoxscoreFetcher
│   ├── parser/                       # Box score + PBP parsers (Sidearm, WMT)
│   ├── validation/                   # ScoreValidator, TeamAssignmentVerifier
│   ├── ScrapeOrchestrator.java       # Pipeline entry point
│   ├── PbpOrchestrator.java + PbpWriter.java
│   ├── GameStatsWriter.java          # player_game_stats writes
│   ├── GameCreationService.java      # Single gate for all game creation
│   ├── TeamScheduleSyncService.java  # Syncs schedule page -> team_games
│   ├── NcaaApiClient.java + NcaaContest.java
│   └── D1MetricsService.java         # Homepage metrics computation
└── standings/                        # Conference standings scraping
    ├── model/                        # ConferenceSource, ConferenceStanding, StandingsScrapeLog
    ├── repository/
    ├── StandingsController.java
    ├── StandingsOrchestrator.java
    ├── StandingsParser.java (interface)
    └── *StandingsParser.java         # Sidearm, SEC, Boostsport, MW, PrestoSports
```

---

## Deployment

**Dokku app name:** `riseballs-scraper` (deployed on `ssh.edentechapps.com`, but see `scripts/deploy-scraper.sh` for the historical Mondok deploy path).

**Internal URL from Rails containers:** `http://riseballs-scraper.web:8080` — only resolvable from inside the Dokku internal network. A `dokku run rails-app bundle exec rake ...` one-off **cannot** reach it (different network namespace); you have to `ps:exec` into a running web container to curl it.

**Dockerfile** (`/Users/mattmondok/Code/riseballs-parent/riseballs-scraper/Dockerfile`): two-stage build.
1. `eclipse-temurin:21-jdk-alpine AS build` — runs `./gradlew bootJar --no-daemon`.
2. `eclipse-temurin:21-jre-alpine` — copies `app.jar` and `ENTRYPOINT ["java", "-jar", "app.jar"]`.
Exposes 8080. No healthcheck declared (Dokku uses its own).

Dokku port mapping convention: `http:80:8080` (the scraper listens on 8080, Dokku proxies 80 → container:8080). Rails convention in this monorepo is `http:80:5000`, but the scraper overrides with 8080 per `server.port` in `application.yml`.

---

## Database connection

**`application.yml`** sets `spring.datasource.url = ${SPRING_DATASOURCE_URL:jdbc:postgresql://localhost:5432/riseballs_development}`. Hibernate uses `PostgreSQLDialect`, `ddl-auto: none` (schema is owned by Rails migrations — **the scraper never creates tables**).

**HikariCP pool:** `maximum-pool-size: 50`, `minimum-idle: 5`. This is high relative to the DB's limits — multi-team roster augment + schedule sync can saturate the pool if not carefully throttled.

**`config/DatabaseUrlConfig.java`** is a Spring `EnvironmentPostProcessor` (registered via `META-INF/spring.factories`, not shown here but present). It auto-translates Dokku's `DATABASE_URL=postgres://user:pass@host:port/db` into the three `spring.datasource.*` properties. It **will not override** an explicitly-set `SPRING_DATASOURCE_URL`. Pseudocode:

```
if DATABASE_URL present and SPRING_DATASOURCE_URL not set:
    parse URI, rewrite postgres:// → jdbc:postgresql://
    addFirst() a MapPropertySource with url/username/password
```

---

## Critical hazard — "Java writes bypass Ruby quality gates"

This is the single most important operational fact about this service. Every JPA `save()` from this codebase goes straight to Postgres without triggering:

- Rails model validations (e.g., `Game#ensure_distinct_teams`, `PlayerGameStat#normalize_player_name`)
- Rails callbacks (e.g., `after_save` hooks that recompute derived columns)
- `pbp_quality_ok?`-style guards that Ruby pipelines apply before persisting PBP
- ActiveRecord paranoia (e.g., `acts_as_paranoid` soft-delete)

**Places this matters most:**
- `CachedGameRepository` — `ScrapeOrchestrator.storeCachedBoxscore` writes JSONB payloads with no "is this box score actually good" gate other than the code-level `ScoreValidator` + `TeamAssignmentVerifier` checks *inside* this service. If those checks are wrong, Java cements bad data that Ruby would have rejected.
- `PlayerGameStatRepository` — `GameStatsWriter.write` does a wholesale delete+insert of every PGS row for the game. If the boxscore payload is partial, PGS gets partial data with no sanity check that row count ≥ previous.
- `GameRepository` — reconciliation writes (`setState("final")`, `setHomeScore(...)`) do not go through `Game#before_save` hooks.
- `PlateAppearance`/`PitchEvent` — `PbpWriter` inserts rows that Ruby-side `PitchByPitchParser` would have validated against its `COMPLETE_THRESHOLD` before persisting.

Mitigations present in this codebase (look for these patterns to understand intent):
- `ScoreValidator.scoresMatch()` — compares summed batting runs to `Game.homeScore`/`awayScore`. If mismatch, `ScrapeOrchestrator` kicks off `UrlRediscoveryFetcher`.
- `TeamAssignmentVerifier.verifyAndFix()` — roster cross-check before stats are persisted.
- `NcaaDateReconciliationService.boxScoresMatch()` — player-stat fingerprint before a duplicate is merged.
- `ScheduleReconciliationOrchestrator.deduplicateActions()` — DELETE_GHOST requires BOTH teams' schedules to agree.

**Anything new written to Postgres from Java must document why a Ruby quality gate is unnecessary, or replicate the gate in Java.** See CLAUDE.md feedback `feedback_check_java_writes.md` and `feedback_java_scraper_logic.md`.

---

## How Rails talks to it

Rails triggers the scraper via `JavaScraperClient` (Ruby) at these endpoints (full controller-by-controller breakdown in `01-controllers.md`):

| Endpoint | Rails trigger |
|----------|---------------|
| `POST /api/scrape/boxscore`, `/boxscores`, `/pbp`, `/pbp/batch` | `BoxScoreFetchJob`, `BoxScoreBackfillJob`, `PbpReparseJob` |
| `POST /api/roster/augment`, `/augment/all`, `/augment-coaches`, `/augment-coaches/all` | Rails roster admin actions / nightly cron |
| `POST /api/roster/wmt-sync`, `/wmt-sync/all` | Rails WMT roster sync cron (always use localscraper, not CF worker — see `feedback_localscraper.md`) |
| `POST /api/reconcile` (`/check` for dry run) | Rails `GameReconciliationJob` (the WMT/cancelled-game reconciler) |
| `POST /api/reconcile/schedule` (+ `/check`, `/team`, `/team/check`) | Rails `ScheduleReconciliationJob` — the "592-team schedule pipeline" |
| `POST /api/reconcile/ncaa-dates` (+ `/check`) | Rails `NcaaDateReconciliationJob` |
| `POST /api/team-schedule/sync-all`, `/sync-team` | Rails `TeamScheduleSyncJob` |
| `POST /api/standings/scrape` (+ `/division`, `/conference`) | Rails standings cron |
| `POST /api/games/find-or-create`, `/find-or-create-batch` | Game creation gate called by the above jobs |
| `POST /api/metrics/compute` | Rails `ComputeD1MetricsJob` (Sidekiq cron) |
| `GET /api/schedule/verify?team=…&opponent=…` | `GhostGameDetectionJob` — is this matchup on the live schedule or is it a phantom? |

All calls are synchronous POSTs with JSON bodies. Rails waits for the HTTP response. Long operations (e.g., `augment/all`) block the Rails worker thread until Java finishes — use the `/all` variants only from Sidekiq.

---

## Scheduled work

There are **no `@Scheduled` methods** in this codebase (verified via grep). The Java service is purely reactive — every pipeline runs on HTTP request from Rails. Rails owns all cron scheduling (Sidekiq-cron or equivalent), which is intentional so there's one scheduler to operate.

---

## Related docs

- [01-controllers.md](01-controllers.md) — full REST surface exposed by this service
- [02-services.md](02-services.md) — orchestrators, fetchers, validators, roster services
- [../architecture/01-service-boundaries.md](../architecture/01-service-boundaries.md) — what Rails owns vs what Java owns
- [../pipelines/01-game-pipeline.md](../pipelines/01-game-pipeline.md) — how Rails orchestrates scraper calls end-to-end
- [../rails/11-external-clients.md](../rails/11-external-clients.md) — `JavaScraperClient`, the Rails side of every call
- [../operations/runbook.md](../operations/runbook.md) — deploy, restart, debug the scraper in prod
