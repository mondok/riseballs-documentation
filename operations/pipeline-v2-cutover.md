# Pipeline v2 Cutover Operator Runbook

Single-source operator doc for moving production from v1 ingestion
(Sidekiq + JavaScraperClient.scrape_*) to v2 (HourlyScheduleSweep
+ ProcessScheduleEntry DAG). Read end-to-end before flipping
anything.

## Hard prerequisites (do not skip)

1. `./gradlew test` green on `riseballs-scraper`
2. `bin/rubocop && bin/brakeman --no-pager` green on `riseballs`
3. `./gradlew test --tests "com.riseballs.scraper.pipeline.stage3_parse.ParserCorpusTest"` — all sidearm fixtures pass
4. `./gradlew test --tests "com.riseballs.scraper.pipeline.stage4_verify.Stage4VerifierFixtureTest"` — all known-good ACCEPT, all known-bad REJECT
5. **50-game wider smoke** completed (see "Wider smoke" below) with **zero unexpected halts and zero score regressions**
6. `bin/rails runner script/audit_pipeline_consistency.rb` exits with no FAIL lines (WARN on halts is acceptable; gate via `SMOKE_IN_PROGRESS=true` during smoke days)
7. `riseballs-documentation/audits/parser-move-checklist.md` reviewed — confirm only Sidearm-class teams are in `PIPELINE_V2_TEAMS` until WMT/Presto/StatCrew parsers ship
8. Backup snapshot of production Postgres taken in the last 4 hours (`pg_dump`-equivalent via Dokku)

## Cutover sequence

### Step 1 — Confirm flag-off baseline

```sh
ssh dokku@ssh.mondokhealth.com -- config:get riseballs PIPELINE_V2_ENABLED
ssh dokku@ssh.mondokhealth.com -- config:get riseballs-scraper PIPELINE_V2_ENABLED
```

Both must be empty or "false". v1 paths are authoritative.

### Step 2 — Cohort smoke (one team at a time)

Set `PIPELINE_V2_TEAMS` to one team only; restart. Manual-trigger
2-3 of that team's recent finals via the trigger endpoint and
verify scores match what they were before:

```sh
ssh dokku@ssh.mondokhealth.com -- config:set --no-restart riseballs-scraper \
  PIPELINE_V2_TEAMS=indiana PIPELINE_V2_ENABLED=true
ssh dokku@ssh.mondokhealth.com -- ps:restart riseballs-scraper
```

Then via `riseballs` Rails runner:

```ruby
require "net/http"; require "json"
[<game_id_1>, <game_id_2>, <game_id_3>].each do |gid|
  uri = URI("http://riseballs-scraper.web:8080/api/pipeline/process-game")
  req = Net::HTTP::Post.new(uri, "Content-Type" => "application/json")
  req.body = { game_id: gid, trigger_source: "manual" }.to_json
  res = Net::HTTP.start(uri.hostname, uri.port) { |h| h.request(req) }
  puts "#{gid}: #{res.body}"
end
```

Verify each result:
- `status: "COMPLETED"` -- pipeline ran end-to-end
- `Game.score_source = "bundle"` -- Stage 6 wrote
- `Game.home_score / away_score` -- match the fixture's R-row in
  the existing cached_games.payload (i.e. unchanged from prior)
- `pipeline_runs` row + 7 `pipeline_stage_audits` rows in DB

If any score CHANGES from prior, **stop and investigate** before
expanding cohort. The change might be a real correction OR a
wrong-URL inheritance from v1; ground-truth before accepting.

### Step 3 — Expand cohort gradually

Once one team passes 5+ games clean, widen:

```sh
ssh dokku@ssh.mondokhealth.com -- config:set --no-restart riseballs-scraper \
  PIPELINE_V2_TEAMS='indiana,illinois,...'
ssh dokku@ssh.mondokhealth.com -- ps:restart riseballs-scraper
```

After each restart, watch one HourlyScheduleSweep tick (top of next
hour, UTC) — the sweep walks every game in scope for those teams.
Look at `pipeline_runs.outcome` distribution:

```ruby
ActiveRecord::Base.connection.exec_query(
  "SELECT outcome, count(*) FROM pipeline_runs " \
  "WHERE started_at > now() - interval '1 hour' " \
  "GROUP BY outcome ORDER BY count(*) DESC"
).each { |r| puts r.inspect }
```

Acceptable: COMPLETED:HALTED ratio reasonable; HALTED reasons all
match expected (`no_boxscore_url_available`, `fetch_empty:` for
unsupported CMS, `totals_mismatch_*` for genuine bad parses).

NOT acceptable: any HALTED reason starting with `exception:`,
`stats_extractor_not_yet_wired` (means STAGE7_ALLOW_NOOP wasn't
set — see below), or unexplained `score_drift`.

### Step 4 — Full rollout (cohort = empty allowlist)

When confident, drop the allowlist (empty = all teams):

```sh
ssh dokku@ssh.mondokhealth.com -- config:set --no-restart riseballs-scraper \
  PIPELINE_V2_TEAMS=
ssh dokku@ssh.mondokhealth.com -- ps:restart riseballs-scraper
```

### Step 5 — Sidekiq cutover (Rails-side)

ONLY after v2 has run cleanly for 24h on full rollout:

```sh
ssh dokku@ssh.mondokhealth.com -- config:set riseballs PIPELINE_V2_ENABLED=true
```

This activates the in-`#perform` `pipeline_v2_guard` short-circuits
in the 11 DELETE-list jobs (per `cron-inventory.md`). Sidekiq still
processes the surviving job classes (RPI, WAR, standings, RPI,
sync_rankings); only the ingestion-side jobs no-op.

## Stage 7 noop policy

Stage 7 (PlayerStatsExtractor) is currently a HALT on every run
unless `STAGE7_ALLOW_NOOP=true` is set on the scraper. This is
deliberate: a half-pipeline that derives bundles but skips PGS
would silently leave PGS stale. During the cohort smoke set:

```sh
ssh dokku@ssh.mondokhealth.com -- config:set riseballs-scraper STAGE7_ALLOW_NOOP=true
```

Remove this once the real PlayerStatsExtractor ships.

## Rollback

### Score corruption rollback

If a v2 run wrote wrong scores to a Game:

```ruby
# Restore from the same cached_games row's payload R-line
gid = <game_id>
cg = CachedGame.where(game_id: gid, data_type: "athl_boxscore").order(updated_at: :desc).first
ls = (cg.payload || {})["linescores"] || []
r = ls.find { |row| row["period"] == "R" }
home, visit = r["home"].to_i, r["visit"].to_i
g = Game.find(gid)
g.update_columns(home_score: home, away_score: visit, score_source: nil)
TeamGame.where(game_id: gid).each do |tg|
  if tg.is_home
    tg.update_columns(team_score: home, opponent_score: visit)
  else
    tg.update_columns(team_score: visit, opponent_score: home)
  end
end
# Demote the v2 canonical row
CachedGame.where(game_id: gid, pipeline_version: "v2").update_all(
  is_canonical: false, verification_status: "rejected", replaced_at: Time.current
)
```

### Full pipeline rollback

```sh
# Disable v2 on both apps
ssh dokku@ssh.mondokhealth.com -- config:set riseballs PIPELINE_V2_ENABLED=false
ssh dokku@ssh.mondokhealth.com -- config:set riseballs-scraper PIPELINE_V2_ENABLED=false
ssh dokku@ssh.mondokhealth.com -- ps:restart riseballs riseballs-scraper
```

v1 paths immediately resume. The cached_games written by v2 stay
in place; their `is_canonical=true` is harmless because the new
`Api::GamesController` `fetch_canonical` falls through to legacy
fetch when no canonical exists.

## What to monitor

```sh
# 1. Audit (run hourly via cron in production)
ssh dokku@ssh.mondokhealth.com -- enter riseballs web 'bin/rails runner script/audit_pipeline_consistency.rb'

# 2. Score-source distribution
psql -c "SELECT score_source, count(*) FROM games GROUP BY score_source ORDER BY count(*) DESC"

# 3. Pipeline run outcomes (last 24h)
psql -c "SELECT outcome, count(*) FROM pipeline_runs WHERE started_at > now() - interval '24 hours' GROUP BY outcome ORDER BY count(*) DESC"

# 4. Verifier reject reasons (last 24h)
psql -c "SELECT halt_reason, count(*) FROM pipeline_runs WHERE halted_at_stage = 4 AND started_at > now() - interval '24 hours' GROUP BY halt_reason ORDER BY count(*) DESC LIMIT 10"
```

## Wider smoke (50 games)

Before full rollout, run 50 random cohort-eligible games through
the manual trigger endpoint and categorize each:

| Category | Definition | Acceptable count |
|---|---|---|
| completed-match-prior | scored same as Game.scores before | many — most should be this |
| completed-no-prior | no prior scores to compare | ok |
| completed-changed-correct | scores changed AND we ground-truthed v2 right | a few |
| completed-changed-wrong | scores changed AND v2 wrong | **zero** |
| halted-correct | reason was no_url, fetch_empty (unsupported CMS), totals_mismatch on a known-bad page | ok |
| halted-wrong | reason was exception, parse-bug, fluky | **zero** |

Run via a Rails rake (lives at
`riseballs/lib/tasks/pipeline_v2_wider_smoke.rake`).
