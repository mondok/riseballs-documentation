# Configuration and deployment

## Configuration surface

Three pieces:
1. **`application.yml`** at `src/main/resources/application.yml` — the base configuration, all env-var overrides.
2. **`ScraperProperties`** at `config/ScraperProperties.java` — `@ConfigurationProperties(prefix="scraper")` binding for all scraper-specific settings.
3. **`DatabaseUrlConfig`** at `config/DatabaseUrlConfig.java` — `EnvironmentPostProcessor` registered via `META-INF/spring.factories` that parses Dokku's `DATABASE_URL` into Spring's `spring.datasource.*` properties.

No `application-{profile}.yml` files exist; the service runs with the default profile only.

## `application.yml` complete annotated

```yaml
spring:
  application:
    name: riseballs-scraper
  datasource:
    url: ${SPRING_DATASOURCE_URL:jdbc:postgresql://localhost:5432/riseballs_development}
    username: ${SPRING_DATASOURCE_USERNAME:}
    password: ${SPRING_DATASOURCE_PASSWORD:}
    hikari:
      maximum-pool-size: 50    # HikariCP pool cap — watch alongside concurrency semaphores
      minimum-idle: 5
  jpa:
    hibernate:
      ddl-auto: none            # Rails owns schema
    open-in-view: false          # prevents accidental session-bound entities in controllers
    properties:
      hibernate:
        dialect: org.hibernate.dialect.PostgreSQLDialect
        default_schema: public

server:
  port: ${PORT:8080}            # Dokku convention maps http:80:8080

logging:
  file:
    name: ${LOG_FILE:riseballs-scraper.log}
  level:
    root: INFO
    com.riseballs.scraper: INFO
    com.riseballs.scraper.service.fetcher: INFO
  logback:
    rollingpolicy:
      max-file-size: 50MB       # rotate per 50 MB
      max-history: 7            # keep 7 rotated files (~7 days at 1/day)

scraper:
  cloudflare-account-id: ${CLOUDFLARE_ACCOUNT_ID:}
  cloudflare-browser-token: ${CLOUDFLARE_BROWSER_TOKEN:}
  openai-api-key: ${OPENAI_API_KEY:}
  local-scraper-url: ${LOCAL_SCRAPER_URL:http://localscraper.mondokhealth.com/scrape}
  playwright-worker-url: ${PLAYWRIGHT_WORKER_URL:https://cloudflare-game-scraper.matt-mondok.workers.dev/scrape}
  max-concurrent-games: ${MAX_CONCURRENT_GAMES:10}
  ai-extraction-enabled: ${AI_EXTRACTION_ENABLED:false}
```

## `ScraperProperties` (fields + defaults)

**File:** `config/ScraperProperties.java` (39 LOC). Bound with prefix `scraper`.

| Field | Java default | yaml default via env |
|-------|-------------|----------------------|
| `cloudflareAccountId` | `null` | empty (`${CLOUDFLARE_ACCOUNT_ID:}`) |
| `cloudflareBrowserToken` | `null` | empty |
| `openaiApiKey` | `null` | empty |
| `localScraperUrl` | `"http://localscraper.mondokhealth.com/scrape"` | `${LOCAL_SCRAPER_URL:…}` |
| `playwrightWorkerUrl` | `"https://cloudflare-game-scraper.matt-mondok.workers.dev/scrape"` | `${PLAYWRIGHT_WORKER_URL:…}` |
| `maxConcurrentGames` | `50` | `${MAX_CONCURRENT_GAMES:10}` ⚠️ mismatch |
| `aiExtractionEnabled` | `false` | `${AI_EXTRACTION_ENABLED:false}` |

**`maxConcurrentGames` default mismatch** — the Java field default is 50, the yaml default is 10. Spring's property binding picks up yaml after the field defaults, so **10 wins at runtime** unless `MAX_CONCURRENT_GAMES` env is set. Documented here so it's not mysterious: the Java default only kicks in if you remove the yaml line.

## Environment variables — canonical list

| Variable | Consumer | Default |
|----------|----------|---------|
| `PORT` | Spring `server.port` | `8080` |
| `SPRING_DATASOURCE_URL` | Hikari JDBC URL | `jdbc:postgresql://localhost:5432/riseballs_development` |
| `SPRING_DATASOURCE_USERNAME` | Hikari username | empty |
| `SPRING_DATASOURCE_PASSWORD` | Hikari password | empty |
| `DATABASE_URL` | Dokku-style postgres://user:pass@host:port/db — parsed by `DatabaseUrlConfig` and expanded into the 3 above | none |
| `LOG_FILE` | Logback file appender | `riseballs-scraper.log` |
| `CLOUDFLARE_ACCOUNT_ID` | `AiExtractionFetcher`, `PlaywrightFetcher` | empty |
| `CLOUDFLARE_BROWSER_TOKEN` | same | empty |
| `OPENAI_API_KEY` | `AiExtractionFetcher` | empty |
| `LOCAL_SCRAPER_URL` | `LocalScraperFetcher`, `StandingsOrchestrator` (HTML parsers) | `http://localscraper.mondokhealth.com/scrape` |
| `PLAYWRIGHT_WORKER_URL` | `PlaywrightFetcher` | CF Worker URL |
| `MAX_CONCURRENT_GAMES` | `ScrapeController` (batch), `ScrapeOrchestrator`, `ScrapeController` PBP batch | `10` |
| `AI_EXTRACTION_ENABLED` | `AiExtractionFetcher` gating | `false` — leave off, see `feedback_no_ai_boxscore_fallback.md` |

## `DatabaseUrlConfig` — Dokku URL parsing

**File:** `config/DatabaseUrlConfig.java` (49 LOC). Registered in `META-INF/spring.factories`:

```
org.springframework.boot.env.EnvironmentPostProcessor=com.riseballs.scraper.config.DatabaseUrlConfig
```

Rules:
1. Reads `DATABASE_URL` from the environment.
2. **Will NOT override** `SPRING_DATASOURCE_URL` if it's set explicitly.
3. Parses the URI, rewrites `postgres://` → `postgresql://`, then builds:
   - `spring.datasource.url = "jdbc:postgresql://{host}:{port}{path}"`
   - `spring.datasource.username = userInfo[0]`
   - `spring.datasource.password = userInfo[1]` (or empty)
4. Exceptions during parse are swallowed — falls through to the yaml default.

This is why Dokku "just works" — Dokku injects `DATABASE_URL` after linking the postgres service and this processor picks it up before Spring initializes the datasource.

## `HttpClientConfig` — the JDK HttpClient bean

**File:** `config/HttpClientConfig.java`. Exposes one `@Bean HttpClient` used by every fetcher and every reconciliation HTTP call:

```java
HttpClient.newBuilder()
    .version(HttpClient.Version.HTTP_1_1)    // scraper#14 — force HTTP/1.1 to avoid
    .connectTimeout(Duration.ofSeconds(10))  // HTTP/2 + istio-envoy frame corruption
    .followRedirects(HttpClient.Redirect.NORMAL)
    .build();
```

Notes:
- **Version pinned to HTTP/1.1 (scraper#14, shipped 2026-04-19).** The JDK `HttpClient` defaults to HTTP/2; against `api.wmt.games` (behind istio-envoy), large responses (≥ 1-2 MB) were arriving with stray `0x1F` bytes between JSON tokens and blowing up Jackson parsing with `Illegal character ((CTRL-CHAR, code 31))`. Curl and HTTParty (both HTTP/1.1 by default) never saw the issue against the same URLs. Forcing HTTP/1.1 at the bean level fixes every downstream consumer — every `BoxscoreFetcher`, `PbpOrchestrator`, `ReconciliationService`, `StandingsOrchestrator`, and `NcaaApiClient` injects this same bean. The only live integration test in the scraper (`WmtFetcherLiveIT`) hits `api.wmt.games` with this config and asserts the 2.5 MB response parses cleanly.
- `connectTimeout` is **connect only** — per-request read timeouts are set at the `HttpRequest` level via `.timeout(Duration.ofSeconds(N))` in each fetcher (e.g., 30s for WMT, 120s for LocalScraper/Playwright).
- No custom SSL, no proxy. Follows redirects in both http→https and https→https, but not the secure redirect policy — matches `Redirect.NORMAL`.
- `HttpClient` is thread-safe; shared across all virtual threads.

## Dockerfile

**File:** `Dockerfile` (14 lines). Two-stage.

```dockerfile
FROM eclipse-temurin:21-jdk-alpine AS build
WORKDIR /app
COPY gradle/ gradle/
COPY gradlew build.gradle settings.gradle ./
RUN chmod +x gradlew && ./gradlew dependencies --no-daemon || true
COPY src/ src/
RUN ./gradlew bootJar --no-daemon

FROM eclipse-temurin:21-jre-alpine
WORKDIR /app
COPY --from=build /app/build/libs/riseballs-scraper.jar app.jar
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "app.jar"]
```

- Build stage downloads dependencies once (line 5) before copying sources so changes to `src/` don't bust the gradle-cache layer.
- `|| true` on `./gradlew dependencies` — the command sometimes exits non-zero because we haven't copied sources yet; we don't care.
- Final image is Alpine JRE 21, ~180 MB.
- No healthcheck declared — Dokku adds its own based on port binding.

## Deployment

**Dokku app name:** `riseballs-scraper` — on `ssh.edentechapps.com` per the parent monorepo's CLAUDE.md. The Dockerfile gets detected automatically. Port mapping: `http:80:8080`.

### Creating the app (one-time)

```bash
ssh dokku@ssh.edentechapps.com apps:create riseballs-scraper
ssh dokku@ssh.edentechapps.com postgres:link riseballs-db riseballs-scraper    # injects DATABASE_URL
ssh dokku@ssh.edentechapps.com config:set --no-restart riseballs-scraper \
    CLOUDFLARE_ACCOUNT_ID=... CLOUDFLARE_BROWSER_TOKEN=... \
    LOCAL_SCRAPER_URL=... PLAYWRIGHT_WORKER_URL=... \
    MAX_CONCURRENT_GAMES=10
ssh dokku@ssh.edentechapps.com ports:set riseballs-scraper http:80:8080
git remote add dokku dokku@ssh.edentechapps.com:riseballs-scraper
```

### Deploy

```bash
git push dokku master
```

Or use the `/dokku-push` skill. The `scripts/deploy-scraper.sh` file is the historical deploy helper — it was originally pointed at `ssh.mondokhealth.com`; check before running.

### Internal network URL

From Rails containers on the same Dokku host:
```
http://riseballs-scraper.web:8080
```
This is what `JavaScraperClient` uses. It is **not resolvable** from `dokku run` one-off containers (different network namespace). To exercise the API from a Rails console for debugging:
```bash
ssh dokku@ssh.edentechapps.com ps:exec rails-app -- bundle exec rails console
# inside the console:
JavaScraperClient.new.scrape_boxscore(game_id: 12345)
```

## Local build and run

```bash
# Prerequisites: Java 21 (Temurin recommended), Postgres with riseballs_development DB

# One-time
./gradlew --version    # verifies wrapper

# Build + run tests + produce JAR
./gradlew build

# Run only unit tests
./gradlew test

# Boot the service locally (port 8080)
./gradlew bootRun

# Produce the fat JAR
./gradlew bootJar
# Output: build/libs/riseballs-scraper.jar

# Run the JAR directly
java -jar build/libs/riseballs-scraper.jar

# With env overrides
SPRING_DATASOURCE_URL=jdbc:postgresql://localhost:5432/riseballs_local \
    MAX_CONCURRENT_GAMES=2 \
    ./gradlew bootRun
```

There are two helper scripts:
- `scripts/local-test.sh` — full local integration smoke test.
- `scripts/scraper-only-local-test.sh` — narrower scraper-only smoke.

Test suite uses **H2 in-memory DB** (`build.gradle` line 28), so `./gradlew test` does not require a running Postgres.

## Logs

- Local: `./riseballs-scraper.log` in the working directory.
- Dokku: `dokku logs riseballs-scraper -t` (server uses logback rolling — 50 MB per file, 7 files retained).
- Log files in the repo root (`riseballs-scraper.log.2026-04-*.gz`) are from developer local runs; they're not gitignored but should be.

## Related docs

- [../operations/deployment.md](../operations/deployment.md) — cross-service Dokku deploy process
- [../operations/database-access.md](../operations/database-access.md) — Postgres link, DATABASE_URL, warehouse access
- [../operations/runbook.md](../operations/runbook.md) — on-call playbook for this service
- [06-scheduled-jobs.md](06-scheduled-jobs.md) — concurrency tunables that consume these env vars
- [00-overview.md](00-overview.md) — service role and high-level boundaries
- [../architecture/00-system-overview.md](../architecture/00-system-overview.md) — where this service sits in the topology
