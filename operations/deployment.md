# Deployment

All three services run on Dokku (self-hosted at `ssh.edentechapps.com` / `ssh.mondokhealth.com`). One Dokku app per service.

---

## Apps

| Dokku app | Service | Internal URL | Public URL |
|-----------|---------|-------------|-----------|
| `riseballs` | Rails (web + worker) | `riseballs.web:3000` | `riseballs.com` |
| `riseballs-scraper` | Java Spring Boot | `riseballs-scraper.web:8080` | internal only |
| `riseballs-predict` | Python FastAPI | `riseballs-predict.web:8080` | internal only |

Only the Rails app is publicly exposed. The scraper and predict services are reachable only from other Dokku apps on the internal network.

---

## Git remotes

From inside each service's repo:

```sh
# riseballs (Rails)
git remote -v
# origin   https://github.com/... (GitHub — runs CI)
# dokku    dokku@ssh.mondokhealth.com:riseballs (deploy)

# riseballs-scraper (Java)
# dokku    dokku@ssh.edentechapps.com:riseballs-scraper

# riseballs-predict (Python)
# dokku    dokku@ssh.edentechapps.com:riseballs-predict
```

---

## Deploy commands

### Rails

**Always push both remotes:**

```sh
git push origin main && git push dokku main
```

- `origin` triggers GitHub CI (RuboCop + Brakeman + importmap audit). Must pass before push.
- `dokku` builds and deploys immediately.

Before every push:

```sh
bin/rubocop && bin/brakeman --no-pager
```

CI fails → do not push. (See `CLAUDE.md` in `riseballs/` for full CI guide.)

### Java scraper

```sh
git push dokku master
```

Dockerfile-based. Dokku detects and builds via `./gradlew bootJar`. No external CI.

### Python predict

```sh
git push dokku master
```

Dockerfile-based. `pip install` from `pyproject.toml` at build time.

---

## Creating a new app (Dokku reference)

From the parent `CLAUDE.md`:

```sh
# 1. Create the app
ssh dokku@ssh.edentechapps.com apps:create <app-name>

# 2. Set env vars (no-restart to batch)
ssh dokku@ssh.edentechapps.com config:set --no-restart <app-name> KEY=value

# 3. Set port mapping
ssh dokku@ssh.edentechapps.com ports:set <app-name> http:80:5000

# 4. Add git remote
git remote add dokku dokku@ssh.edentechapps.com:<app-name>

# 5. Deploy
git push dokku master
```

Dockerfile-based deploys — Dokku auto-detects. If a `Procfile` is also present, it overrides Dockerfile CMD. Default port mapping `http:80:5000`.

---

## Custom domains

The server uses a Cloudflare Tunnel (tunnel name: `edentechapps` or `mondokhealth`, remotely managed). To add a custom domain:

1. Add domain to Dokku:
   ```sh
   ssh dokku@ssh.edentechapps.com domains:add <app-name> example.com
   ```
2. In Cloudflare dashboard → tunnel's **Published application routes** → add `example.com` → `http://localhost:80`.
   - Do NOT use "Hostname routes" (that's for private network / WARP).
   - Do NOT manually create CNAME records pointing to the tunnel ID — Published application routes creates DNS records automatically.
3. If the domain was previously hosted elsewhere, delete old DNS records first.
4. Cloudflare handles SSL termination — no Let's Encrypt needed on Dokku.

---

## Inter-service URLs

Services reach each other by internal Dokku hostname:

| From | To | URL |
|------|-----|-----|
| Rails web/worker | Java scraper | `http://riseballs-scraper.web:8080` |
| Rails web/worker | Python predict | `http://riseballs-predict.web:8080` |
| Java scraper | Rails | (no — Java never calls Rails) |
| Python predict | DB only | `postgres://...` |

**Critical:** `dokku run` one-off containers do NOT have access to the internal network. They cannot resolve `riseballs-scraper.web` or `riseballs-predict.web`. Any rake task that calls `JavaScraperClient` or `PredictServiceClient` must run via `dokku enter`, not `dokku run`.

See [operations/database-access.md](database-access.md).

---

## Env var reference

### Rails (`riseballs`)

| Var | Purpose |
|-----|---------|
| `DATABASE_URL` | Postgres connection (provided by `dokku-postgres`) |
| `REDIS_URL` | Redis for Sidekiq (provided by `dokku-redis`) |
| `PREDICT_SERVICE_URL` | Predict service base URL (default `http://localhost:8080`; prod: `http://riseballs-predict.web:8080`) |
| `PREDICT_SERVICE_TIMEOUT_SECONDS` | Predict request timeout (default `5`) |
| `JAVA_SCRAPER_URL` | Java scraper base URL (default `http://localhost:8081`; prod: `http://riseballs-scraper.web:8080`) |
| `RAILS_MASTER_KEY` | Rails credentials decryption key |
| `SECRET_KEY_BASE` | Rails session signing |
| `MAILER_FROM_ADDRESS` | Outbound email sender |
| `SMTP_*` | Outbound SMTP (if configured) |

### Java scraper (`riseballs-scraper`)

| Var | Purpose |
|-----|---------|
| `DATABASE_URL` | Postgres connection (same DB as Rails; parsed by `DatabaseUrlConfig`) |
| `SERVER_PORT` | HTTP port (default 8080) |
| `SCRAPER_MAX_CONCURRENT_GAMES` | Virtual-thread concurrency cap (default 10 in yaml, 50 in Java class — yaml wins) |
| (OpenAI keys if `AiExtractionFetcher` enabled — deprecated, not used) | |

### Python predict (`riseballs-predict`)

| Var | Purpose |
|-----|---------|
| `DATABASE_URL` | Postgres connection (read-only use) |
| `PORT` | HTTP port (default 8080) |
| `LOG_LEVEL` | `INFO` / `DEBUG` |
| `ACTIVE_WIN_MODEL_VERSION` | Present but unused in V1 (loader uses `models/current/`) |
| `WAREHOUSE_URL` | Present but unused in V1 |

See [predict/07-config-and-deployment.md](../predict/07-config-and-deployment.md).

---

## Postgres

**Service:** `dokku-postgres` named `riseballs-db`.
**Database:** `riseballs_db`.
**Hostname inside Dokku:** `dokku-postgres-riseballs-db`.

All three services share this DB. See [operations/database-access.md](database-access.md) for tunneling and local development.

---

## Redis

**Service:** `dokku-redis` (attached to `riseballs` only).
Used by: Sidekiq (queues + cron + web UI) and `Rails.cache` (including `pbp_miss:<gid>` negative cache).

---

## Logs

```sh
# Rails
ssh dokku@ssh.mondokhealth.com logs riseballs -t

# Java scraper
ssh dokku@ssh.edentechapps.com logs riseballs-scraper -t

# Predict
ssh dokku@ssh.edentechapps.com logs riseballs-predict -t
```

Or per-process (web / worker):

```sh
ssh dokku@ssh.mondokhealth.com logs riseballs -p web -t
ssh dokku@ssh.mondokhealth.com logs riseballs -p worker -t
```

---

## Restart

```sh
# Rails
ssh dokku@ssh.mondokhealth.com ps:restart riseballs

# Java scraper
ssh dokku@ssh.edentechapps.com ps:restart riseballs-scraper
```

Soft-restart via env change (usually preferred, applies without full rebuild):

```sh
ssh dokku@ssh.edentechapps.com config:set <app> REBUILD=$(date +%s)
```

---

## Post-deploy checklist

After Rails deploy:

1. Watch logs for ~60s (Sidekiq cron should reload from `config/initializers/sidekiq.rb`).
2. Hit `/api/status` or `/health` to confirm web responds.
3. If migrations, confirm `dokku run riseballs bin/rails db:migrate:status` shows all `up`.
4. Check admin `/admin/jobs` — cron entries should match the `desired` array in `sidekiq.rb`.

After Java scraper deploy:

1. Hit `/actuator/health` from inside another Dokku app:
   ```sh
   ssh dokku@ssh.edentechapps.com enter riseballs web 'curl -s http://riseballs-scraper.web:8080/actuator/health'
   ```
2. Trigger a small scrape via `/api/scrape` to confirm DB writes work.

---

## Related docs

- [operations/database-access.md](database-access.md)
- [operations/runbook.md](runbook.md)
- [scraper/07-config-and-deployment.md](../scraper/07-config-and-deployment.md)
- [predict/07-config-and-deployment.md](../predict/07-config-and-deployment.md)
