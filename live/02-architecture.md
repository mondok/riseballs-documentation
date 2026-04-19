# riseballs-live — Architecture

The code lives in `/Users/mattmondok/Code/riseballs-parent/riseballs-live/src/main/java/com/riseballs/live/`. Organized into seven packages:

```
controller/     HTTP handlers (/scoreboard, /health)
fetcher/        orchestration of parallel upstream calls + reconciliation
client/         NCAA + ESPN HTTP clients, SlugResolver
reconciler/     pure merge function (NCAA + ESPN → unified event list)
cache/          Caffeine fresh / stale / negative tiers
ratelimit/      per-IP token bucket over Caffeine
config/         Spring @Configuration (CORS, async timeout, upstream pool)
model/          DTOs
```

---

## Request flow

```
Browser
  │  GET /scoreboard?date=YYYY-MM-DD
  ▼
ScoreboardController
  │  (check RateLimitFilter first — /scoreboard counts against bucket; /health doesn't)
  ▼
ScoreboardCache.getFresh(date)
  │  Caffeine 30s TTL
  ├─ hit ──────────────────────────────────► return {source: "cache"}
  │
  ▼ miss
ScoreboardFetcher.fetch(date)     (single-flight per date)
  │
  ▼
ThreadPoolTaskExecutor         (core=4, max=8, queue=16)
  │
  ├─ NcaaScoreboardClient.fetch(date)   [D1 + D2 sequential inside the task, 15s timeout]
  │      https://sdataprod.ncaa.com  (persisted query)
  │
  ├─ EspnScoreboardClient.fetch(date)   [10s timeout]
  │      https://site.api.espn.com/apis/site/v2/sports/baseball/college-softball/scoreboard
  │
  ▼ join(12s joint timeout)
ScoreboardReconciler.reconcile(ncaa, espn, slugResolver)
  │  pure function
  ▼
ScoreboardCache.putFresh(date, result) + putStale(date, result)
  │
  ▼
return {source: "fresh", ...}
```

On failure (either upstream throws or 12s joint timeout fires):

```
upstream failure
  │
  ▼
ScoreboardCache.getStale(date)
  │  Caffeine 5m TTL
  ├─ hit ──────────────────► return {source: "stale"}
  │
  ▼ miss
ScoreboardCache.putNegative(date, emptyResult)
  │  Caffeine 10s TTL
  ▼
return empty result (not 5xx — degradation is silent to the client)
```

On servlet-level async timeout (15s hard cap):

```
AsyncTimeoutConfig returns 504 Gateway Timeout
```

---

## Components

### ScoreboardController

`controller/ScoreboardController.java`. One handler method. Wraps the fetch call in a `Callable<ResponseEntity>` so Spring MVC can apply the async request timeout configured in `AsyncTimeoutConfig`. Also enforces the date-param presence + ISO format.

### HealthController

`controller/HealthController.java`. Returns `{"status":"ok"}`. Skipped by the rate limiter.

### ScoreboardFetcher

`fetcher/ScoreboardFetcher.java`. Orchestrates the parallel NCAA + ESPN fetch and calls `ScoreboardReconciler`. Single-flight behavior comes from the cache layer (`CompletableFuture.computeIfAbsent`-style pattern on the fresh map). Uses the `ThreadPoolTaskExecutor` configured by `UpstreamExecutorConfig` — both clients share this pool so total concurrency is bounded.

### NcaaScoreboardClient

`client/NcaaScoreboardClient.java`. Calls NCAA's persisted-query GraphQL:

- URL: `https://sdataprod.ncaa.com`
- Persisted query hash: `6b26e5cda954c1302873c52835bfd223e169e2068b12511e92b3ef29fac779c2` (the same hash the Java scraper's `NcaaApiClient` uses — keeping the two aligned means NCAA breaking either one breaks both, which is the desired coupling)
- Timeout: 15s
- Fetches D1 then D2 sequentially within the same task (so the single future returned covers both divisions)

Returns a list of `NcaaEvent` DTOs with `contestId`, `gameDate`, `homeSlug`, `awaySlug`, `homeScore`, `awayScore`, `state`, `startTimeEpoch`.

### EspnScoreboardClient

`client/EspnScoreboardClient.java`. Calls ESPN's public scoreboard endpoint:

- URL: `https://site.api.espn.com/apis/site/v2/sports/baseball/college-softball/scoreboard?dates=YYYYMMDD&limit=200`
- Timeout: 10s

Returns a list of `EspnEvent` DTOs. Each event goes through `SlugResolver` to map ESPN team names / abbreviations to our canonical slugs before it hits the reconciler.

### SlugResolver

`client/SlugResolver.java`. The only piece of this service that needs team-knowledge. Unlike the Rails `TeamMatcher` or the Java scraper's `OpponentResolver`, it has no database. At startup it loads two classpath resources:

- `src/main/resources/espn_slug_overrides.json` — 163 entries. Originally a one-shot snapshot of the Ruby `ESPN_SLUG_OVERRIDES` hash that lived on `EspnScoreboardService` before that service was deleted on 2026-04-19 (mondok/riseballs#84). Plus three reviewer-added entries from the initial riseballs-live rollout: Florida Atlantic, Sam Houston, San Jose State with accent. Hand-maintained; entries survive between releases. This JSON file is now the single canonical home for ESPN-location-to-slug overrides — there is no equivalent in the Rails repo anymore.
- `src/main/resources/known_slugs.txt` — 594 entries. One-shot export from `Team.pluck(:slug)` in Rails.

Resolution algorithm:

1. If the raw ESPN team name is a key in `espn_slug_overrides.json`, return the override.
2. Otherwise lowercase-collapse the ESPN slug form (often already the desired slug) and check if it's in `known_slugs.txt`. Return it if so.
3. Otherwise return a special `UNKNOWN` marker — the reconciler drops events whose either side is UNKNOWN so we don't publish garbage.

**Update workflow:** new ESPN team? Add the override to `espn_slug_overrides.json` here, rebuild, redeploy. The Rails repo no longer holds a mirror of this map, so there's only one place to change. When a team's canonical Rails slug changes, re-export `known_slugs.txt` from `Team.pluck(:slug).sort.uniq` and commit the new file.

### ScoreboardReconciler

`reconciler/ScoreboardReconciler.java`. **Pure function.** No external calls, no mutation of inputs, no state. Signature:

```
List<ReconciledEvent> reconcile(
    List<NcaaEvent> ncaa,
    List<EspnEvent> espn,
    SlugResolver slugResolver)
```

Algorithm:

1. Index NCAA events by `contestId` and by `(homeSlug, awaySlug, startTimeEpochBucket)` (where the bucket is "within 30 minutes").
2. For each ESPN event:
   - Match on `ncaaContestId` if ESPN provides one (rare but it happens).
   - Else match by `(homeSlug, awaySlug, startTimeEpoch within 30 min)`.
   - Reversed-slug rescue: if no match but the swap matches, accept with score swap.
   - Ambiguity skip: if multiple NCAA events match one ESPN event (or vice versa), skip the overlay for that row — don't guess.
3. For each unmatched NCAA event, emit as NCAA-only.
4. For each matched pair, emit as a merged event with state `max(ncaa.state, espn.state)` in `scheduled < live < final` order, scores from the preferred source (NCAA for contest-id-matched events; ESPN's otherwise — see code for tiebreakers).

Output is a flat list of `ReconciledEvent` DTOs ready for JSON serialization.

### ScoreboardCache

`cache/ScoreboardCache.java`. Three Caffeine caches:

- **fresh:** `Caffeine.newBuilder().expireAfterWrite(30, TimeUnit.SECONDS)`. Served as `source: "fresh"` on the request that filled it; subsequent hits show `source: "cache"`.
- **stale:** `Caffeine.newBuilder().expireAfterWrite(5, TimeUnit.MINUTES)`. Only read when the fresh miss AND the upstream fetch fails.
- **negative:** `Caffeine.newBuilder().expireAfterWrite(10, TimeUnit.SECONDS)`. Written when hard upstream failure has no stale fallback. Returns empty events but keeps us from hammering broken upstreams.

Single-flight is implemented via an internal per-date lock so concurrent misses don't multiplex upstream calls.

### Rate limiter

`ratelimit/RateLimitFilter.java` + `ratelimit/TokenBucket.java`. Servlet filter that runs on every request except `/health`. Per-IP token bucket stored in a Caffeine cache keyed by remote IP. Default: capacity 60, refill 1/sec. On empty bucket, returns `429 Too Many Requests` with `Retry-After: 1`. Configurable via `riseballs.ratelimit.capacity` and `riseballs.ratelimit.refill-per-second`.

### Async timeout

`config/AsyncTimeoutConfig.java`. Sets `spring.mvc.async.request-timeout=15000` (15 seconds) — if a `Callable<ResponseEntity>` doesn't complete in time, Spring returns a 504. This is the servlet-level safety net, one step outside the 12s joint upstream timeout.

### Upstream executor

`config/UpstreamExecutorConfig.java`. Defines the `ThreadPoolTaskExecutor` used by the clients:

- `corePoolSize = 4`
- `maxPoolSize = 8`
- `queueCapacity = 16`

These are configurable via `riseballs.upstream.pool.core`, `.max`, `.queue`. The pool is shared between NCAA and ESPN clients, so total outbound concurrency is bounded at 8.

---

## Runtime characteristics

- Boot time: under 1s (minimal Spring Boot autoconfig, no DB autoconfig, no Redis).
- Idle memory: ~150 MiB.
- Under load: ~170 MiB.
- JDK HTTP client (`JdkClientHttpRequestFactory`): HTTP/2, connection pooling.
- Graceful shutdown: `server.shutdown=graceful` + `spring.lifecycle.timeout-per-shutdown-phase=20s`. Spring stops accepting new requests, lets in-flight ones finish, then exits. Under Dokku's 30s SIGTERM budget.

---

## Related docs

- [live/00-overview.md](00-overview.md) — why the service exists
- [live/01-endpoints.md](01-endpoints.md) — endpoint contracts
- [live/03-deployment.md](03-deployment.md) — Dokku / Cloudflare / config
- [reference/matching-and-fallbacks.md](../reference/matching-and-fallbacks.md) — overlay match ladder (reconciler side + browser side)
- [reference/slug-and-alias-resolution.md](../reference/slug-and-alias-resolution.md) — `SlugResolver` in the context of all three slug resolvers
