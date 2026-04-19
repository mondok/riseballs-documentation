# riseballs-live — Endpoints

Two HTTP endpoints. Plus a CORS preflight that matters for SPA integration.

---

## GET /scoreboard

Reconciled NCAA + ESPN scoreboard for a single date.

**URL:** `https://live.riseballs.com/scoreboard?date=YYYY-MM-DD`

**Query params:**

- `date` (required) — ISO date. The reconciled event list for that date.

**Response (200):**

```json
{
  "date": "2026-04-19",
  "events": [
    {
      "ncaaContestId": "12345",
      "homeSlug": "florida",
      "awaySlug": "lsu",
      "startTimeEpoch": 1713528000,
      "state": "live",
      "homeScore": 3,
      "awayScore": 2,
      "currentInning": "Top 5th",
      "lastPlay": null,
      "sources": { "ncaa": true, "espn": true }
    },
    ...
  ],
  "fetchedAt": "2026-04-19T18:20:15Z",
  "source": "fresh"
}
```

`source` is one of:

- `"fresh"` — cache miss, just fetched + reconciled this request.
- `"cache"` — within the 30-second fresh TTL, served from the Caffeine cache.
- `"stale"` — upstreams timed out or failed, served from the 5-minute stale cache.

`state` is one of `scheduled`, `live`, `final`. The reconciler escalates state across the two feeds: `max(ncaa.state, espn.state)` in the order `scheduled < live < final`, so if either feed says a game is live, the reconciled event is live.

**Response (200, no events):**

Returned when both upstreams return empty AND no stale payload exists AND the date is just quiet. `events: []`, `source: "fresh"` (or `"cache"` on the next few requests).

**Response (200, negative cache):**

Returned on hard upstream failure with no stale fallback. Looks the same as "no events" but is cached 10s instead of 30s. Clients can't tell the difference — by design, the endpoint never returns 5xx for upstream problems.

**Response (429):**

Rate-limited. Per-IP token bucket (60 requests/min default). Returns `Retry-After: 1`. `/health` is exempt.

**Response (504):**

Servlet-level async timeout fired (default 15s). Means something downstream hung past the 12s joint upstream timeout + overhead. Rare in practice.

**Caching strategy:**

- **Fresh cache:** 30 seconds. Single-flight on miss — concurrent requests for the same date wait on a single upstream fetch.
- **Stale cache:** 5 minutes. Only served when the upstream fetch fails and the stale entry is still present.
- **Negative cache:** 10 seconds. Used on hard failure with no stale fallback.

Tunable via `riseballs.cache.fresh-ttl-seconds`, `riseballs.cache.stale-ttl-seconds`, and the inline negative-cache constant (not currently exposed as a property; see `ScoreboardCache.java`).

**Auth:** public. CORS-restricted: only origins in the hardcoded allowlist can use the response. Allowed origins:

- `https://riseballs.com`
- `https://www.riseballs.com`
- `http://localhost:3000`
- `http://localhost:3100`

Methods: `GET`, `OPTIONS`. `Max-Age: 3600`. Defined in `config/WebConfig.java`.

---

## GET /health

Cheap liveness probe.

**URL:** `https://live.riseballs.com/health`

**Response (200):**

```json
{"status":"ok"}
```

**Auth:** public. **Not rate-limited** — `RateLimitFilter` explicitly skips `/health` so monitoring / Dokku healthchecks don't burn tokens.

---

## OPTIONS /scoreboard (CORS preflight)

Browsers fire this before the cross-origin GET. Handled by Spring's CORS support (see `WebConfig.java`). Response headers:

```
Access-Control-Allow-Origin: https://riseballs.com   # or whichever allowed origin
Access-Control-Allow-Methods: GET,OPTIONS
Access-Control-Max-Age: 3600
```

If the origin isn't in the allowlist, no `Access-Control-Allow-Origin` header is returned and the browser blocks the follow-up GET.

**Important:** the allowlist is source-code-only. Adding a new origin (e.g. a staging preview domain) requires a code change + redeploy. There is no env-var or dynamic allowlist.

---

## Observability

Every `/scoreboard` request emits a single JSON line to stdout with the shape:

```json
{
  "event": "scoreboard_request",
  "date": "2026-04-19",
  "source": "fresh",
  "events": 42,
  "upstream_ms_ncaa": 1285,
  "upstream_ms_espn": 938,
  "total_ms": 1321,
  "ts": "2026-04-19T18:20:15Z"
}
```

Useful for tailing via `ssh dokku@ssh.mondokhealth.com logs riseballs-live -t` — you see source (fresh/cache/stale), upstream latencies, and total time at a glance. See [operations/runbook.md](../operations/runbook.md) "Live overlay not updating".

---

## Related docs

- [live/00-overview.md](00-overview.md) — why this service exists
- [live/02-architecture.md](02-architecture.md) — the internals (clients, reconciler, cache)
- [live/03-deployment.md](03-deployment.md) — Dokku + Cloudflare + config
