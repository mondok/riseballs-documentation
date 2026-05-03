# Stage F Season Backfill Report

**Plan reference:** `PIPELINE_REBUILD_PLAN.md` v5 §"Stage F --
Backfill" line 990.

This is the report skeleton operators fill in after running the
Stage F backfill via `bin/rails pipeline_v2:stage_f_backfill[...]`
post-cutover. Populate the sections below as each
division/conference batch completes.

## Pre-conditions

- [ ] Phase 2 flag flip stable for 48h (per
      §"Pre-Phase-2 checklist", line 1866).
- [ ] `pipeline_v2:audit_backfill` exit 0 on prod.
- [ ] Shadow run zero-diff for 24h (PR #27).
- [ ] PR #29 Stage 7 dry-run reviewed and approved.

## Run log

### D1 -- SEC

- Run started: _YYYY-MM-DD HH:MM_
- Teams dispatched: _N_
- Games dispatched: _N_
- Errors: _N_
- Stage 4 verification rejects: _N_ (paste sample IDs)
- Canonical flips: _N_ (from
  `pipeline_canonical_flips_total` Prometheus counter)
- Notable: _commentary_

### D1 -- ACC

(repeat per conference)

### D1 -- BIG TEN
### D1 -- PAC-12 / BIG WEST
### D1 -- (other)
### D2 -- (per conference)

## Aggregate metrics

| Metric | Value |
|---|---:|
| Total teams swept | _N_ |
| Total games dispatched | _N_ |
| Corrected `Game.scores` rows | _N_ |
| Corrected orientation rows (FLIPPED) | _N_ |
| Corrected dates | _N_ |
| Corrected cached boxscore (canonical promote) | _N_ |
| Stage 4 rejects (URL date / totals / thin page) | _N_ |
| Stage 5 PBP-divergence events | _N_ |
| Errors (HTTP 5xx, fetcher circuit open) | _N_ |

## Open issues surfaced by backfill

- _GitHub issue link_ -- description

## Sign-off

Backfill completed: _date_
Reviewed by: _name_
Diff against pre-cutover snapshot: _link or paste counts_
