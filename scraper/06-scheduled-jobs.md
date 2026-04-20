# Scheduled jobs and async work

## No `@Scheduled` methods exist in this service

A grep for `@Scheduled` across `src/main/java` returns zero matches. The scraper has **no cron-like scheduled methods** and no `@EnableScheduling`. This is intentional — Rails owns all cron scheduling (Sidekiq-cron or equivalent) so there is exactly one scheduler to operate and debug.

Every long-running pipeline in this service is triggered by an HTTP call from Rails. See `01-controllers.md` for the full surface.

## No `@EventListener` hooks either

Grep for `@EventListener`, `@Async`, `@EnableAsync`: none present. Async fanout is done manually via `Executors.newVirtualThreadPerTaskExecutor()` inside the services (see the concurrency patterns below).

---

## Async concurrency patterns actually used

Every large pipeline uses the same recipe:

1. `Executors.newVirtualThreadPerTaskExecutor()` (JDK 21 virtual threads — no configured pool, tasks spawn on demand).
2. `Semaphore(N)` to cap concurrent upstream HTTP requests.
3. Optional `Thread.sleep(RATE_LIMIT_MS)` right after `semaphore.acquire()` for a per-task trickle rate.
4. `future.get(TIMEOUT, TimeUnit.MINUTES)` so one stuck task can't hold the whole batch.

### Concurrency parameters per pipeline

| Pipeline | File | Semaphore | Rate limit | Per-task timeout |
|----------|------|-----------|------------|------------------|
| `ScrapeController.scrapeBatch` (box score batch) | `controller/ScrapeController.java` | `Semaphore(ScraperProperties.maxConcurrentGames)` — default 10 in yaml, but `ScraperProperties.maxConcurrentGames` has a field default of **50** (mismatch — `application.yml` sets `10`, properties record defaults to `50`. Config file wins at runtime.) | — | — (caller-level) |
| `ScrapeController.reparsePbpBatch` | same | same | — | 5 min |
| `ScheduleReconciliationOrchestrator.reconcileAll` | `reconciliation/ScheduleReconciliationOrchestrator.java` | `Semaphore(5)` | 500 ms | 10 min |
| `ReconciliationService.doReconcile` (WMT reconciler) | `reconciliation/ReconciliationService.java` | `Semaphore(3)` | 500 ms | 5 min |
| `TeamScheduleSyncController.syncAll` | `controller/TeamScheduleSyncController.java` | `Semaphore(5)` | 500 ms | 10 min |
| `StandingsOrchestrator.processSources` | `standings/StandingsOrchestrator.java` | `Semaphore(3)` | — | 5 min |
| `RosterAugmentService.augmentTeam` (per team) | `roster/RosterAugmentService.java` | `Semaphore(5)` | 200 ms | — |
| `CoachAugmentService.augmentTeam` | `roster/CoachAugmentService.java` | `Semaphore(3)` | 300 ms | — |
| `NcaaDateReconciliationService.reconcile` | `reconciliation/NcaaDateReconciliationService.java` | sequential (no fanout) | `NcaaApiClient.RATE_LIMIT_MS = 200` | — |
| `D1MetricsService.compute` | `service/D1MetricsService.java` | unbounded (each metric on its own virtual thread) | — | — |

### PBP batch concurrency

```java
Semaphore pbpConcurrencyLimit = new Semaphore(scraperProperties.getMaxConcurrentGames());
try (var executor = Executors.newVirtualThreadPerTaskExecutor()) {
    var futures = gameIds.stream()
        .map(id -> executor.submit(() -> {
            pbpConcurrencyLimit.acquire();
            try { pbpOrchestrator.reparsePbp(id); }
            finally { pbpConcurrencyLimit.release(); }
        })).toList();
    for (var f : futures) { f.get(5, TimeUnit.MINUTES); }
}
```

Note: nothing fails fast — if one task times out, the rest keep running; the `get` on timed-out futures just gives up waiting. A later review candidate: bubble task timeouts into the response.

### Rate-limit sleep pattern

Most orchestrators do:
```java
semaphore.acquire();
try {
    Thread.sleep(RATE_LIMIT_MS);  // trickle
    // ...
} finally { semaphore.release(); }
```

This means the rate limit applies per task, not globally. With `Semaphore(5)` + `sleep(500ms)`, steady-state throughput is ~10 tasks/sec if every task takes <500ms; if tasks take longer, the semaphore caps parallelism before the sleep matters.

---

## `TransactionTemplate` vs `@Transactional`

- `GameCreationService` uses `TransactionTemplate` injected via constructor so it can wrap `doFindOrCreate` + explicitly retry on `DataIntegrityViolationException`. Chosen over `@Transactional` because the retry needs the outer method to not be inside a transaction.
- `NcaaDateReconciliationWriter` was extracted from `NcaaDateReconciliationService` specifically because Spring's proxy-based `@Transactional` doesn't work on self-invocation. The reconciler service holds HTTP calls outside any transaction, then invokes the writer bean from outside, so `@Transactional` on the writer's methods actually takes effect.
- `GameStatsWriter.write` is `@Transactional` — straightforward, no self-invocation issues.
- `StandingsOrchestrator.persistStandings` is `@Transactional`, called from `processSource`. Self-invocation risk here: if `processSource` is ever called from within the same bean through an inner method, the `@Transactional` on `persistStandings` would be bypassed. Currently safe since `processSource` is only called from `processSources` / `scrapeConference` within the same bean — but only because of the Spring proxy calling from the controller boundary. Double-check if refactoring.

---

## Virtual thread caveats

- **HikariCP pool** is `maximum-pool-size: 50`. Virtual threads don't count against OS thread limits but DO hold JDBC connections when running JPA queries. If `Semaphore(5)` + 5 teams × each doing parallel per-game JPA queries, the pool can saturate — this is the reason rate limits and semaphores are conservative.
- **Logging**: virtual threads use the same logger. The log file shows them as `VirtualThread[#N]`. Rolling policy: `50 MB` / `7-day` retention (see `application.yml`).
- **Transactions**: a transaction is pinned to its thread. For virtual threads this is fine — JPA + Hikari works. But: don't hold a transaction open across an HTTP call (blocking the connection defeats the purpose). The NcaaDateReconciliationService split is the pattern to follow: HTTP outside, narrow `@Transactional` writer inside.

---

## Spring Batch? Quartz?

Neither. The dependency tree is minimal: `spring-boot-starter-web`, `spring-boot-starter-data-jpa`, `postgresql`, `jsoup`, `jackson-databind`. If you need real scheduling or durable work queues, do it in Rails Sidekiq and call this service; don't add Spring Batch.

## Related docs

- [../rails/14-schedule.md](../rails/14-schedule.md) — Rails-side cron that triggers these pipelines
- [../rails/12-jobs.md](../rails/12-jobs.md) — Sidekiq jobs that call the scraper controllers
- [02-services.md](02-services.md) — services invoked by the concurrent orchestrators
- [01-controllers.md](01-controllers.md) — HTTP surface that Rails schedules against
- [07-config-and-deployment.md](07-config-and-deployment.md) — `maxConcurrentGames` and HikariCP tunables
- [../pipelines/01-game-pipeline.md](../pipelines/01-game-pipeline.md) — end-to-end flow these concurrent tasks feed
