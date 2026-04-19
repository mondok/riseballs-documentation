# Operator Runbook

Common tasks, in priority order. Each one says **symptom → diagnosis → fix → verify**.

---

## Quick reference

| Symptom | Playbook |
|---------|----------|
| PBP missing for a game | [#pbp-missing-for-a-game](#pbp-missing-for-a-game) |
| Wrong box score shown | [#wrong-box-score-shown](#wrong-box-score-shown) |
| Score wrong on a game | [#score-wrong-on-a-game](#score-wrong-on-a-game) |
| Game appears duplicated | [#game-appears-duplicated](#game-appears-duplicated) |
| Doubleheader not splitting | [#doubleheader-not-splitting](#doubleheader-not-splitting) |
| Team opponent shows as unlinked (`nil` link) | [#opponent-shows-as-unlinked](#opponent-shows-as-unlinked) |
| Standings wrong for a team | [#standings-wrong-for-a-team](#standings-wrong-for-a-team) |
| Prediction panel never shows | [#prediction-panel-never-shows](#prediction-panel-never-shows) |
| Roster photo URL malformed | [#roster-photo-url-malformed](#roster-photo-url-malformed) |
| Schedule for a team is empty | [#schedule-for-a-team-is-empty](#schedule-for-a-team-is-empty) |
| Admin "Run Job" button 500s | [#admin-run-job-crashes-with-nameerror](#admin-run-job-crashes-with-nameerror) |
| CI red — need to ship | [#ci-red](#ci-red) |

---

## PBP missing for a game

**Symptom:** User reports PBP tab empty for a game that's been final for hours.

**Diagnose:**

```sh
ssh dokku@ssh.mondokhealth.com enter riseballs web 'bin/rails runner "
game = Game.find(<id>)
pp cached: CachedGame.fetch(game, \"athl_play_by_play\").present?
pp state: game.state, locked: game.locked
pp neg_cache: Rails.cache.read(\"pbp_miss:#{game.id}\")
"'
```

Possible causes:

1. **Neg cache set** → live fetch failed within last 5 min. Usually means Sidearm is rate-limiting. Wait 5 min, try again.
2. **Proactive job failed 5 retries** → check Sidekiq dead set for `PbpOnFinalJob`.
3. **External source still partial** → quality gate rejected. Wait, or re-trigger.
4. **`rb_*` orphan game with no source URL** → needs external ID resolution first.

**Fix:**

```sh
# Option A: Re-trigger the proactive job
ssh dokku@ssh.mondokhealth.com enter riseballs web \
  'bin/rails runner "PbpOnFinalJob.perform_now(<id>)"'

# Option B: Reparse from stored HTML (if ScrapedPage exists)
ssh dokku@ssh.mondokhealth.com enter riseballs web \
  'GAME_ID=<id> bin/rake reparse_pbp_from_html'

# Option C: Refetch via Java scraper (requires dokku enter)
ssh dokku@ssh.mondokhealth.com enter riseballs web \
  'GAME_IDS=<id> bin/rake refetch_missing_pbp'
```

**Verify:** hit the PBP endpoint directly and check response:

```sh
curl https://riseballs.com/api/games/<id>/play_by_play | jq '.periods | length'
```

**See:** [pipelines/02-pbp-pipeline.md](../pipelines/02-pbp-pipeline.md).

---

## Wrong box score shown

**Symptom:** Box score shown is from a prior meeting in the series (date / scores don't match).

**Diagnose:** compare `cached_games.source_url` + `cached_games.fetched_at` against `Game.game_date`.

**Root cause:** Sidearm URL discovery returned the most recent prior meeting when the current game hadn't posted yet. Discovery gate in `Api::GamesController#boxscore` is supposed to catch this for `state=scheduled` games with final runs, but if the game is already `final` the gate is looser (score-match guard only).

**Fix:**

```sh
# Invalidate the cached boxscore; next fetch will re-discover
ssh dokku@ssh.mondokhealth.com enter riseballs web 'bin/rails runner "
game = Game.find(<id>)
CachedGame.for_game(game).where(data_type: [\"athl_boxscore\", \"boxscore\"]).destroy_all
"'

# User's next page load re-fetches
```

If the pattern recurs for same game → needs source URL lock:

```sh
# Admin UI: /admin/boxscores → find game → Update URL
```

**Verify:** reload the game page; confirm scores match.

**See:** [pipelines/03-boxscore-pipeline.md](../pipelines/03-boxscore-pipeline.md) "box score discovery gate".

---

## Score wrong on a game

**Symptom:** `Game.home_score` / `away_score` doesn't match what actually happened.

**Diagnose:**

```sh
ssh dokku@ssh.mondokhealth.com enter riseballs web 'bin/rails runner "
game = Game.find(<id>)
pp game.home_score, game.away_score, game.locked
pp PlayerGameStat.where(game_id: game.id)
     .group(:team_slug).sum(:runs_scored)
"'
```

Compare: if player stats sum correctly but `Game` differs → matcher wrote wrong scores. If player stats are also wrong → boxscore parse is wrong.

**Fix:**

```sh
# If player stats are right, let ScoreValidationJob correct + lock
ssh dokku@ssh.mondokhealth.com enter riseballs web \
  'bin/rails runner "ScoreValidationJob.perform_now"'

# If player stats are wrong, nuke cached boxscore + re-extract
ssh dokku@ssh.mondokhealth.com enter riseballs web 'bin/rails runner "
game = Game.find(<id>)
CachedGame.for_game(game).destroy_all
PlayerGameStat.where(game_id: game.id).destroy_all
BoxScoreBackfillJob.perform_now(<id>)
"'
```

If clearly wrong and no data source agrees:

```sh
# Manual correction via admin UI creates a GameReview
https://riseballs.com/admin/reviews
```

**Verify:** refresh game page; confirm `game.locked == true` after validation.

**See:** [pipelines/06-reconciliation-pipeline.md](../pipelines/06-reconciliation-pipeline.md) "Score audit".

---

## Game appears duplicated

**Symptom:** Two `Game` rows for what looks like the same matchup.

**Diagnose:**

```sh
ssh dokku@ssh.mondokhealth.com enter riseballs web 'bin/rails runner "
# Look for candidates
Game.where(game_date: \"<date>\")
    .joins(:team_games)
    .where(team_games: { team_slug: [\"<slug1>\", \"<slug2>\"] })
    .distinct
    .each { |g| puts %[#{g.id} #{g.home_team_slug} vs #{g.away_team_slug} g##{g.game_number} scores=#{g.home_score}-#{g.away_score}] }
"'
```

Two cases:

1. **Real duplicate** — same `game_number`, same or similar scores. `GameDedupJob` should merge on next run (every 15 min).
2. **Legitimate doubleheader** — different `game_number` (1, 2). Correct behavior.

**Fix (if real duplicate):**

```sh
# Dry run first
ssh dokku@ssh.mondokhealth.com enter riseballs web \
  'DEDUP_DRY_RUN=1 bin/rails runner "GameDedupJob.perform_now"'

# Then actual
ssh dokku@ssh.mondokhealth.com enter riseballs web \
  'bin/rails runner "GameDedupJob.perform_now"'
```

If dedup doesn't catch it (<5 common players overlap):

```sh
# Manual merge via rake
ssh dokku@ssh.mondokhealth.com enter riseballs web \
  'KEEPER=<id> LOSER=<id> bin/rake dedup_games:manual_merge'
```

**Verify:** only one `Game` row for the pair; all child records (PlayerGameStat, CachedGame, etc.) transferred to keeper.

**See:** [pipelines/06-reconciliation-pipeline.md](../pipelines/06-reconciliation-pipeline.md) "Game deduplication".

---

## Doubleheader not splitting

**Symptom:** DH shows as a single game or only one of the two games.

**Diagnose:**

```sh
ssh dokku@ssh.mondokhealth.com enter riseballs web 'bin/rails runner "
TeamGame.where(team_slug: \"<slug>\", game_date: \"<date>\")
        .order(:game_number)
        .each { |tg| puts tg.attributes.slice(\"id\", \"game_number\", \"opponent_slug\", \"game_id\") }
"'
```

Possible causes:

1. **Java `normalizeForDedup` missed a ranking prefix** — "#5 Georgia" and "Georgia" got different `game_number`. Fix: add `team_alias` for the ranked variant if not already present.
2. **Opposing team's `game_number` disagrees** — one team has 1/2, other has 1. Matcher can't pair. Force re-sync of both teams.
3. **Shell link preservation broke** — Game shells lost their `game_id` links. Run `GamePipelineJob` + check `repair_links` rake.

**Fix:**

```sh
# Force re-sync + match (calls Java, needs enter)
ssh dokku@ssh.mondokhealth.com enter riseballs web \
  'bin/rails runner "GamePipelineJob.perform_now"'

# Specific rake for DH repair
ssh dokku@ssh.mondokhealth.com enter riseballs web 'bin/rake fix_doubleheaders'

# Check unresolved slugs
ssh dokku@ssh.mondokhealth.com enter riseballs web 'bin/rake slugs:audit'
```

**Verify:** both team_games have matching `game_number`, both point at same `Game` via `game_id`.

**See:** [pipelines/01-game-pipeline.md](../pipelines/01-game-pipeline.md), [rails/08-matching-services.md](../rails/08-matching-services.md).

---

## Opponent shows as unlinked

**Symptom:** On a team's schedule page, some opponent names are plain text instead of links.

**Diagnose:** frontend `GameRow` renders plain text when `opponent_seo` is `nil` (never `/teams/null`). Means `team_games.opponent_slug` is NULL AND the controller's fallback (name/longName case-insensitive match) couldn't resolve it either.

```sh
ssh dokku@ssh.mondokhealth.com enter riseballs web 'bin/rails runner "
TeamGame.where(team_slug: \"<team>\")
        .where(opponent_slug: nil)
        .each { |tg| puts %[#{tg.game_date} #{tg.opponent_name}] }
"'
```

**Fix:**

Resolve the name. If unambiguous, add a `TeamAlias`:

```sh
ssh dokku@ssh.mondokhealth.com enter riseballs web 'bin/rails runner "
TeamAlias.create!(team_slug: \"<target_slug>\", alias_name: \"<raw_name>\", source: \"manual\")
"'
```

Then the next sync will resolve:

```sh
ssh dokku@ssh.mondokhealth.com enter riseballs web \
  'bin/rails runner "GamePipelineJob.perform_now"'
```

Or use `rake slugs:suggest` for fuzzy-match proposals.

**Verify:** `opponent_slug` populated on future syncs; schedule page shows link.

**See:** [reference/slug-and-alias-resolution.md](../reference/slug-and-alias-resolution.md).

---

## Standings wrong for a team

**Symptom:** A team's conf record in `/standings` doesn't match what you expect.

**Diagnose:**

```sh
ssh dokku@ssh.mondokhealth.com enter riseballs web 'bin/rails runner "
cs = ConferenceStanding.find_by(team_slug: \"<slug>\", season: 2026)
pp cs&.attributes
pp StandingsScrapeLog.where(conference: cs.conference).order(created_at: :desc).first
"'
```

Possible causes:

1. **Stale** — last scrape was hours ago; conference page hasn't updated. Trigger refresh.
2. **Parser drift** — site changed HTML; parser now extracts wrong columns.
3. **Name resolution** — a team in the conference maps to wrong slug.

**Fix:**

```sh
# Force standings refresh (calls Java)
ssh dokku@ssh.mondokhealth.com enter riseballs web \
  'bin/rails runner "StandingsRefreshJob.perform_now"'

# If parser is wrong — check logs
ssh dokku@ssh.edentechapps.com logs riseballs-scraper -t | grep <Conference>
```

For parser bugs → fix Java, redeploy. Not an operator-fix.

**Verify:** standings match the conference's official page.

**See:** [pipelines/04-standings-pipeline.md](../pipelines/04-standings-pipeline.md).

---

## Prediction panel never shows

**Symptom:** User says prediction never appears on any game page.

**Diagnose:**

```sh
# Check predict service health (router is mounted with /v1 prefix)
ssh dokku@ssh.mondokhealth.com enter riseballs web \
  'curl -s http://riseballs-predict.web:8080/v1/health'

# Test a prediction call
ssh dokku@ssh.mondokhealth.com enter riseballs web \
  'curl -s https://riseballs.com/api/games/<id>/prediction'
```

If 503 → predict service is down or timing out.
If 204 → game is final/cancelled (expected; frontend hides panel).

**Fix:**

```sh
# Restart predict
ssh dokku@ssh.edentechapps.com ps:restart riseballs-predict

# Check logs
ssh dokku@ssh.edentechapps.com logs riseballs-predict -t
```

If the issue is model-loading or feature-DB-connectivity → inspect predict logs.

**See:** [pipelines/07-prediction-pipeline.md](../pipelines/07-prediction-pipeline.md).

---

## Roster photo URL malformed

**Symptom:** Player photos broken, URL has base prepended twice (e.g., `https://site.com/https://cloudfront.net/...`).

**Cause:** historical bug in Rails `RosterService` — prepended base URL to already-absolute CloudFront URLs. Fixed in Java path, but 507 rows across App State / Arizona / others still have bad data.

**Fix:**

```sh
# Clean up with targeted SQL (operator — not rake yet)
ssh dokku@ssh.mondokhealth.com enter riseballs web 'bin/rails runner "
Player.where(\"photo_url LIKE ?\", \"%/https://%\")
      .find_each { |p|
        new_url = p.photo_url.sub(/^.*?\\/(https:\\/\\/)/, \"\\\\1\")
        p.update(photo_url: new_url)
      }
"'

# Then re-augment via Java for fresh data
ssh dokku@ssh.mondokhealth.com enter riseballs web \
  'bin/rails runner "RosterAugmentAllJob.perform_now"'
```

**Verify:** photos load on team roster page.

**See:** `stupid_mistakes_claude_has_made.md` item #11.

---

## Schedule for a team is empty

**Symptom:** A team's schedule page is empty or missing recent games.

**Cause:** usually "empty-payload scrape failure" — Sidearm rate-limited or returned 0 bytes; the sync wiped the team's schedule.

**Diagnose:**

```sh
ssh dokku@ssh.mondokhealth.com enter riseballs web 'bin/rails runner "
puts TeamGame.where(team_slug: \"<slug>\").count
puts TeamGame.where(team_slug: \"<slug>\").order(:game_date).last&.game_date
"'
```

If `count == 0` → wiped. Otherwise last-date shows stale.

**Fix:**

```sh
# StuckScheduleRecoveryJob runs hourly at :05 but you can force it
ssh dokku@ssh.mondokhealth.com enter riseballs web \
  'bin/rails runner "StuckScheduleRecoveryJob.new.perform(team_slug: \"<slug>\")"'

# Or full sync via pipeline
ssh dokku@ssh.mondokhealth.com enter riseballs web \
  'bin/rails runner "GamePipelineJob.perform_now"'
```

**Verify:** team's `team_games` populated; `/teams/<slug>/schedule` shows games.

**See:** [pipelines/01-game-pipeline.md](../pipelines/01-game-pipeline.md).

---

## Admin "Run Job" crashes with NameError

**Symptom:** Click "Team Schedule Sync" or "Live Game Sync" in `/admin/jobs` → 500 error, logs show `NameError: uninitialized constant TeamScheduleSyncJob` or `LiveGameSyncJob`.

**Cause:** `app/controllers/admin/jobs_controller.rb:5-30` defines a `JOBS = [...]` array that still references `class_name: "TeamScheduleSyncJob"` and `class_name: "LiveGameSyncJob"`. Neither of those Job classes exists in `app/jobs/` anymore — they were consolidated into `GamePipelineJob`. The admin UI still offers the buttons but they'll always fail.

**Fix (code change, not operator):** edit `app/controllers/admin/jobs_controller.rb` and either:
- Remove the two stale `JOBS` entries, OR
- Re-point them to `GamePipelineJob`.

Until then: avoid those two buttons. To trigger the equivalent, use the "Game Pipeline" button or:

```sh
ssh dokku@ssh.mondokhealth.com enter riseballs web \
  'bin/rails runner "GamePipelineJob.perform_now"'
```

---

## CI red

**Symptom:** GitHub CI failing on push.

**The rule:** CI red **is** the current task. Do not proceed with other work while it's red (per `CLAUDE.md` §9).

**Diagnose:** check the failing stage:

- RuboCop → run `bin/rubocop` locally; fix offenses.
- Brakeman → run `bin/brakeman --no-pager`; address security warnings (usually SQL injection or unsafe params).
- importmap audit → dep check failed; usually a missing pin.

**Never** push with `--no-verify`. If hooks fail, investigate — don't bypass.

**See:** `CLAUDE.md` at repo root and `riseballs/CLAUDE.md`.

---

## General debugging cheat sheet

```sh
# Rails log tail
ssh dokku@ssh.mondokhealth.com logs riseballs -t

# Specific process
ssh dokku@ssh.mondokhealth.com logs riseballs -p worker -t

# Java scraper logs
ssh dokku@ssh.edentechapps.com logs riseballs-scraper -t

# Sidekiq queue sizes
ssh dokku@ssh.mondokhealth.com enter riseballs web \
  'bin/rails runner "Sidekiq::Queue.all.each { |q| puts %[#{q.name}: #{q.size}] }"'

# Sidekiq dead set (failed jobs)
ssh dokku@ssh.mondokhealth.com enter riseballs web \
  'bin/rails runner "puts Sidekiq::DeadSet.new.size"'

# Force cron reload
ssh dokku@ssh.mondokhealth.com ps:restart riseballs

# DB row count sanity
ssh dokku@ssh.mondokhealth.com enter riseballs web \
  'bin/rails runner "puts Game.count, TeamGame.count, PlayerGameStat.count"'
```

---

## Related docs

- [operations/deployment.md](deployment.md)
- [operations/database-access.md](database-access.md)
- [pipelines/](../pipelines/) — flow-specific context
- [rails/12-jobs.md](../rails/12-jobs.md) — every job with side effects
- [rails/13-rake-tasks.md](../rails/13-rake-tasks.md) — every rake task
- `/Users/mattmondok/Code/riseballs-parent/stupid_mistakes_claude_has_made.md` — historical pitfalls
