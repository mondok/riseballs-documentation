# riseballs-live — Deployment

Single Dokku app behind a Cloudflare tunnel. No inter-service env wiring — the deployment recipe is deliberately spare.

---

## Dokku app

| Field | Value |
|-------|-------|
| App name | `riseballs-live` |
| Host | `ssh.mondokhealth.com` |
| Git remote | `dokku@ssh.mondokhealth.com:riseballs-live` |
| Build | Dockerfile (Eclipse Temurin alpine + Gradle `bootJar`) |
| Default port mapping | `http:80:8080` |

Create-from-scratch recipe (one-shot; already done 2026-04-19):

```sh
ssh dokku@ssh.mondokhealth.com apps:create riseballs-live
ssh dokku@ssh.mondokhealth.com ports:set riseballs-live http:80:8080
ssh dokku@ssh.mondokhealth.com domains:add riseballs-live live.riseballs.com
# In the Cloudflare dashboard, the tunnel's Published Application Routes
# map live.riseballs.com → http://localhost:80 (NOT a CNAME).
git remote add dokku dokku@ssh.mondokhealth.com:riseballs-live
git push dokku master
```

No `config:set` calls are needed (and intentionally none of `DATABASE_URL`, `REDIS_URL`, or internal hostnames are set — that's the prison).

---

## Env vars

| Var | Purpose | Default |
|-----|---------|---------|
| `PORT` | HTTP port | `8080` |
| (nothing else required) | | |

**Explicitly not set (by design):**

- `DATABASE_URL`
- `REDIS_URL`
- `RISEBALLS_SCRAPER_URL`
- `JAVA_SCRAPER_URL`
- `PREDICT_SERVICE_URL`
- Any internal Dokku hostname

If any of these appear in `config:show riseballs-live`, something has gone wrong. The charter (`riseballs-live/CLAUDE.md`) specifies this; infrastructure enforces it. The container should not be able to resolve `riseballs.web` or `riseballs-scraper.web` at all.

---

## Application properties

All tunables live in `src/main/resources/application.properties` and are baked into the JAR at build time. They can be overridden at runtime via `-D` args or `SPRING_APPLICATION_JSON`, but the defaults are intended for production.

```properties
server.port=${PORT:8080}

# Graceful shutdown: Spring stops accepting new requests, lets in-flight
# ones finish, then exits. Must stay under Dokku's 30s SIGTERM budget.
server.shutdown=graceful
spring.lifecycle.timeout-per-shutdown-phase=20s

# Hard per-request cap. The fetcher has its own 12s joint timeout; this
# is a servlet-level safety net that returns 504 if anything downstream
# hangs past 15s.
spring.mvc.async.request-timeout=15000

riseballs.cache.fresh-ttl-seconds=30
riseballs.cache.stale-ttl-seconds=300
riseballs.upstream.joint-timeout-ms=12000
riseballs.upstream.pool.core=4
riseballs.upstream.pool.max=8
riseballs.upstream.pool.queue=16

riseballs.ratelimit.capacity=60
riseballs.ratelimit.refill-per-second=1
```

The negative-cache TTL (10s) is currently an inline constant in `ScoreboardCache.java`, not a property. Move it to a property if you need to tune it.

---

## Cloudflare tunnel

The public URL `live.riseballs.com` is served by the existing `mondokhealth` Cloudflare tunnel (same tunnel that fronts `riseballs.com`). Config lives in the Cloudflare dashboard — the tunnel is remotely managed.

1. In the Cloudflare dashboard, go to the tunnel's **Published Application Routes** tab.
2. Add an entry: `live.riseballs.com` → `http://localhost:80`.
3. Do **not** use "Hostname routes" (private network / WARP tunnel, not what we want).
4. Do **not** create a CNAME manually. Published Application Routes creates the DNS record automatically.

Cloudflare terminates SSL. No Let's Encrypt on Dokku.

---

## Deploy flow

```sh
cd /Users/mattmondok/Code/riseballs-parent/riseballs-live
git push dokku master
```

Dokku detects the Dockerfile, runs the Gradle `bootJar` build, and starts the service. Boot is under a second (minimal Spring Boot autoconfig, no DB autoconfig).

No GitHub CI is wired for this repo yet. The default Dokku deploy is the test — if the JAR boots and `/health` returns 200, the deploy succeeded.

---

## Health checks

After any deploy:

```sh
# 1. Liveness
curl -s https://live.riseballs.com/health
# {"status":"ok"}

# 2. Smoke scoreboard
curl -s 'https://live.riseballs.com/scoreboard?date=2026-04-19' | jq '.source, (.events | length), .fetchedAt'
# First hit: "fresh" (takes a second or so)
# Second hit within 30s: "cache" (instant)

# 3. CORS preflight
curl -sI -H 'Origin: https://riseballs.com' \
     -H 'Access-Control-Request-Method: GET' \
     -X OPTIONS https://live.riseballs.com/scoreboard?date=2026-04-19 \
  | grep -i access-control
# Should show Access-Control-Allow-Origin: https://riseballs.com
# and Access-Control-Allow-Methods: GET,OPTIONS

# 4. Rate limit
for i in $(seq 1 80); do
  curl -s -o /dev/null -w "%{http_code}\n" \
    'https://live.riseballs.com/scoreboard?date=2026-04-19'
done | sort | uniq -c
# First 60 should return 200 (cached after the first), subsequent 429
# within a 1-minute window.
```

---

## Logs

```sh
ssh dokku@ssh.mondokhealth.com logs riseballs-live -t
```

Structured JSON access log per request. Fields: `event`, `date`, `source`, `events`, `upstream_ms_ncaa`, `upstream_ms_espn`, `total_ms`, `ts`. See [live/01-endpoints.md](01-endpoints.md) "Observability" for a sample.

If you're troubleshooting a user-facing overlay issue, the `source` field is the fastest diagnostic: `"fresh"` means the service is actually hitting upstreams; `"cache"` means it's serving from the 30s window; `"stale"` means upstreams are failing and we're degrading gracefully.

---

## Restart

```sh
ssh dokku@ssh.mondokhealth.com ps:restart riseballs-live
```

Caches are in-memory only — restarting clears every cache. First request after restart hits the upstreams. Under normal load this is fine (boot is sub-second, first fetch takes ~1-2s).

---

## Related docs

- [operations/deployment.md](../operations/deployment.md) — all four apps in one place
- [operations/runbook.md](../operations/runbook.md) — "Live overlay not updating" playbook
- [live/00-overview.md](00-overview.md) — prison architecture rationale
- [live/01-endpoints.md](01-endpoints.md) — endpoint contracts
- [live/02-architecture.md](02-architecture.md) — component-level internals
- `riseballs-live/CLAUDE.md` — the charter. If the deployment recipe grows, the charter is the first place to revisit — any new env var that would make this service cross-talk with the DB or Redis is forbidden.
