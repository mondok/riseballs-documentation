# `game_number` Audit — 2026-05-02 (PR #2)

**Plan reference:** `PIPELINE_REBUILD_PLAN.md` v5 §"Pre-migration audit (BLOCKER)" (line 716).

This audit must clear before PR #6 (constraint tightening) ships.
The existing constraint
`idx_games_natural_key UNIQUE (game_date, home_team_slug, away_team_slug, game_number)`
is verified to have zero violations on production.

## Query

```sql
SELECT home_team_slug, away_team_slug, game_date,
       count(DISTINCT game_number) AS distinct_gn,
       count(*) AS total_rows
  FROM games
 WHERE home_team_slug IS NOT NULL
   AND away_team_slug IS NOT NULL
   AND game_date IS NOT NULL
 GROUP BY home_team_slug, away_team_slug, game_date
HAVING count(DISTINCT game_number) <> count(*)
     OR count(*) FILTER (WHERE game_number IS NULL) > 0
```

Source: `riseballs/script/audit_game_number.rb`.

## Results

| Metric | Value |
|---|---:|
| Games with full natural key | 16,551 |
| Games with NULL `game_number` | **0** |
| Violation buckets (duplicate or NULL `game_number` within `(home, away, date)`) | **0** |

## Verdict

**CLEAN.** The existing `idx_games_natural_key` constraint is
already enforced and has zero violations. PR #3 (game_number
repair) is a no-op and is skipped.

PR #6 (constraint tightening) can ship without a repair PR.
The migration body in PR #6 must include the post-tightening
sanity-check query as documented in the plan.

## Re-verification command

```sh
ssh dokku@ssh.mondokhealth.com -- enter riseballs web 'bin/rails runner script/audit_game_number.rb'
```

(Script committed to `riseballs/script/audit_game_number.rb` in
this PR; exit 0 = clean, exit 1 = violations found.)
