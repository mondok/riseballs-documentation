# riseballs-live — Overview

Standalone stateless Java Spring Boot service serving transient live-score overlay data for non-final games. Shipped 2026-04-19 (mondok/riseballs-live#1). Repo lives at `/Users/mattmondok/Code/riseballs-parent/riseballs-live/` (separate git repo, `mondok/riseballs-live` on GitHub).

- **Public URL:** `https://live.riseballs.com`
- **Dokku app:** `riseballs-live` on `ssh.mondokhealth.com`
- **Stack:** Java 21, Spring Boot, Gradle, Eclipse Temurin alpine
- **Storage:** none (no DB, no Redis). In-memory Caffeine caches only.
- **Concerns:** one — reconcile NCAA (D1+D2) + ESPN public scoreboard feeds into a single event list for the browser's scoreboard overlay.

---

## The prison architecture

This service is intentionally constrained. It has **no access** to any internal system:

- No JDBC driver, no connection pool, no DB client of any kind.
- No Redis client, no shared cache with any other service.
- No HTTP client pointed at `riseballs-scraper.*`, `riseballs.com/api/*`, or any internal hostname.
- No message queue, no job processor, no scheduled tasks.
- No writes of any kind to any external system. Read-only proxy.

The enforcement is not only code-level — it is backed by Dokku config: the container has no `DATABASE_URL`, no `REDIS_URL`, no internal hostname environment variables. Any PR that would require one of those to run is rejected at infrastructure level.

See the charter at `riseballs-live/CLAUDE.md` for the full forbidden-scope enumeration. The rule of thumb: if a feature needs more than the NCAA + ESPN public feeds, it doesn't belong here.

---

## Why a separate service

Before 2026-04-19, live-score ingestion was split between Rails (`NcaaScoreboardService`, `EspnScoreboardService`), a StatBroadcast / SidearmStats live-feed fetcher (`StatBroadcastService`, `SidearmStatsService`, `GameIdentityService`), and a SPA-side `LiveView` page that polled four endpoints at 10s intervals. Problems:

- Two ESPN/NCAA codepaths (Rails + Java scraper NcaaApiClient) with slightly different seoname maps and reconciliation logic.
- Heavy DB write-through on every scoreboard render (Rails write-back of scores, state transitions, etc.).
- StatBroadcast / Sidearm feeds are flaky; per-feed URL resolution was required per game.
- Scoreboard + Live View polling concurrently from the same browser against the same backend.

Replacing all of the above with a single purpose-built service, called directly by the browser, collapses the live-score question to one endpoint, one cache, one reconciliation pass. Rails keeps authoritative game data; the overlay is a stateless frosting on top.

---

## What it does

On every `GET /scoreboard?date=YYYY-MM-DD`:

1. Check the Caffeine fresh cache (30s TTL). Hit → return immediately with `source: "fresh"` or `source: "cache"`.
2. Miss → single-flight the upstream fetch.
3. Kick off NCAA (D1 + D2 sequential in a single task) + ESPN fetches in parallel on a bounded `ThreadPoolTaskExecutor` (core=4, max=8, queue=16). 12-second joint timeout.
4. `ScoreboardReconciler` merges the two feeds:
   - Primary match: NCAA `contestId`.
   - Fallback: `(homeSlug, awaySlug, startTimeEpoch within 30 min)` position pairing.
   - Reversed-slug rescue with score swap.
   - Ambiguity skip.
   - State escalation: `max(ncaa.state, espn.state)` ordered `scheduled < live < final`.
5. Write to fresh cache (30s) and stale cache (5m, used only as a fallback on upstream failure).
6. Return `{ date, events[...], fetchedAt, source }`.

On upstream failure:

- If the stale cache still has a recent payload → serve it with `source: "stale"`.
- If no stale payload either → write to the 10-second negative cache and return an empty event list (not 500).

A hard 15-second servlet-level async timeout backs up the 12s joint upstream timeout and returns 504 if anything downstream hangs.

---

## What it doesn't do

- It does not own game identity. `ncaaContestId` and `homeSlug` / `awaySlug` in the response come from the upstream feeds; the browser (or any other client) resolves them back to a Rails game.
- It does not persist anything. Restart the service and every cache is empty.
- It does not know about doubleheaders directly. Each NCAA/ESPN event has its own contest id; the browser's match ladder handles the doubleheader case by falling back to `gameNumber`.
- It does not serve finals preferentially. Final games appear in its output, but the browser never overrides Rails-final games with overlay data — Rails is authoritative on finals. See [reference/matching-and-fallbacks.md](../reference/matching-and-fallbacks.md) "Live-score overlay match ladder".

---

## Related docs

- [live/01-endpoints.md](01-endpoints.md) — endpoint shapes (`/scoreboard`, `/health`)
- [live/02-architecture.md](02-architecture.md) — components, caches, threading model
- [live/03-deployment.md](03-deployment.md) — Dokku app, Cloudflare tunnel, config tunables
- [architecture/00-system-overview.md](../architecture/00-system-overview.md) — system-wide service topology
- [reference/matching-and-fallbacks.md](../reference/matching-and-fallbacks.md) — full overlay match ladder (reconciler side + browser side)
- `riseballs-live/CLAUDE.md` — charter, forbidden-scope enumeration
