# Database Access

Connect to Postgres (local or production). Run rake tasks. Understand `dokku enter` vs `dokku run`.

---

## Database names

| Environment | DB name | Host |
|-------------|---------|------|
| Local dev | `riseballs_local` | `localhost` |
| Dokku production | `riseballs_db` | `dokku-postgres-riseballs-db` (internal) |

---

## Local development

```sh
# Start Rails with the local DB
DATABASE_URL="postgres://localhost/riseballs_local" bin/dev
```

Restore a production dump into the local DB:

```sh
# Dump from Dokku
ssh dokku@ssh.mondokhealth.com postgres:export riseballs-db > dump.sql

# Or use the backup subcommand for a snapshot
ssh dokku@ssh.mondokhealth.com postgres:backup riseballs-db s3://bucket/key

# Restore locally
dropdb riseballs_local
createdb riseballs_local
psql riseballs_local < dump.sql
```

---

## Production via SSH tunnel

```sh
# Open tunnel
ssh -L 15432:dokku-postgres-riseballs-db:5432 dokku@ssh.mondokhealth.com -N

# Then from a new terminal, connect
psql -h localhost -p 15432 -U postgres -d riseballs_db

# Or as a URL
postgres://postgres@localhost:15432/riseballs_db
```

Keep the tunnel running in a separate terminal while you work.

---

## `dokku enter` vs `dokku run` — THE critical distinction

| Command | What it does | Has internal network? |
|---------|-------------|----------------------|
| `dokku enter <app> <proc> 'cmd'` | Runs `cmd` inside the existing running container (e.g., `web`) | ✅ YES |
| `dokku run <app> cmd` | Creates a new one-off container with the same env | ❌ NO |

**`dokku run` cannot reach other Dokku apps.** The internal Docker network `riseballs-scraper.web` is only attached to `web` and `worker` process types. One-off containers spawned by `dokku run` are not attached.

**Consequence:** any rake task that calls `JavaScraperClient` or `PredictServiceClient` must run via `dokku enter`. Running it via `dokku run` will fail with a connection timeout or DNS resolution error.

### Examples

Check game count (no network dep — `dokku run` OK):

```sh
ssh dokku@ssh.mondokhealth.com run riseballs bin/rails runner 'puts Game.count'
```

Sync schedules (calls Java scraper — MUST use `dokku enter`):

```sh
ssh dokku@ssh.mondokhealth.com enter riseballs web \
  'bin/rails runner "GamePipelineJob.perform_now"'
```

Fix doubleheaders (rake task that calls Java — MUST use `dokku enter`):

```sh
ssh dokku@ssh.mondokhealth.com enter riseballs web 'bin/rake fix_doubleheaders'
```

Standings seed (no network dep):

```sh
ssh dokku@ssh.mondokhealth.com run riseballs bin/rake standings:seed_2026
```

---

## Common rake / runner invocations

### Rails

```sh
# One-liner via runner
ssh dokku@ssh.mondokhealth.com enter riseballs web \
  'bin/rails runner "puts Game.where(state: :scheduled).count"'

# Rake task
ssh dokku@ssh.mondokhealth.com enter riseballs web 'bin/rake pbp:purge_bad'

# Rake with env var (DRY_RUN preview)
ssh dokku@ssh.mondokhealth.com enter riseballs web 'DRY_RUN=1 bin/rake pbp:purge_bad'

# Dedup dry run (env var respected by GameDedupJob)
ssh dokku@ssh.mondokhealth.com enter riseballs web \
  'DEDUP_DRY_RUN=1 bin/rails runner "GameDedupJob.perform_now"'
```

### Java scraper

```sh
# Hit internal endpoint from Rails container
ssh dokku@ssh.mondokhealth.com enter riseballs web \
  'curl -s -X POST http://riseballs-scraper.web:8080/api/reconcile/schedule'

# Check Java health
ssh dokku@ssh.edentechapps.com enter riseballs-scraper web \
  'curl -s http://localhost:8080/actuator/health'
```

### Predict

```sh
# Hit from Rails container (router is mounted with /v1 prefix)
ssh dokku@ssh.mondokhealth.com enter riseballs web \
  'curl -s http://riseballs-predict.web:8080/v1/health'
```

---

## Checking Sidekiq

```sh
# Sidekiq web UI (basic auth — Matt only)
https://riseballs.com/sidekiq

# List cron jobs from CLI
ssh dokku@ssh.mondokhealth.com enter riseballs web \
  'bin/rails runner "puts Sidekiq::Cron::Job.all.map { |j| %[#{j.cron.ljust(16)} #{j.name}] }"'

# Queue sizes
ssh dokku@ssh.mondokhealth.com enter riseballs web \
  'bin/rails runner "puts Sidekiq::Queue.all.map { |q| %[#{q.name}: #{q.size}] }"'
```

See [rails/14-schedule.md](../rails/14-schedule.md) for the full cron table.

---

## DB dumps

```sh
# Export full DB
ssh dokku@ssh.mondokhealth.com postgres:export riseballs-db > riseballs_prod.sql

# Import into local
createdb riseballs_local_fresh
psql riseballs_local_fresh < riseballs_prod.sql

# Switch local dev to the fresh DB
DATABASE_URL="postgres://localhost/riseballs_local_fresh" bin/dev
```

---

## Running local dev against prod-like data

The typical workflow:

1. Export prod DB.
2. Import into `riseballs_local`.
3. `bin/dev` against `DATABASE_URL="postgres://localhost/riseballs_local"`.
4. Make changes.
5. Test with `bin/rails test` (full suite — never just changed files; user memory rule).
6. `bin/rubocop && bin/brakeman --no-pager` before push.
7. `git push origin main && git push dokku main`.

---

## Related docs

- [operations/deployment.md](deployment.md)
- [operations/runbook.md](runbook.md)
- [rails/13-rake-tasks.md](../rails/13-rake-tasks.md) — every rake task
