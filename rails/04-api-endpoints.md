# Rails API Endpoint Reference

Per-endpoint reference for every action exposed by the Rails controllers. Grouped by controller. Each entry lists the HTTP verb + path, the controller action with its file path and line numbers, the params it reads, the response shape, caching behavior, and auth requirement.

All file paths in this document are absolute.

## Table of Contents

- [Conventions](#conventions)
- [Api::BaseController](#apibasecontroller)
- [Api::GamesController](#apigamescontroller)
- [Api::PredictionsController](#apipredictionscontroller)
- [Api::TeamsController](#apiteamscontroller)
- [Api::PlayersController](#apiplayerscontroller)
- [Api::StandingsController](#apistandingscontroller)
- [Api::ScoreboardController](#apiscoreboardcontroller)
- [Api::RankingsController](#apirankingscontroller)
- [Api::RpiController](#apirpicontroller)
- [Api::StatsController](#apistatscontroller)
- [Api::AnalyticsController](#apianalyticscontroller)
- [Api::PitchAnalyticsController](#apipitchanalyticscontroller)
- [~~Api::LiveStatsController~~ (DELETED 2026-04-19)](#apilivestatscontroller--deleted)
- [Api::DashboardController](#apidashboardcontroller)
- [Api::FactsController](#apifactscontroller)
- [Api::StatusController](#apistatuscontroller)
- [Api::AdminController](#apiadmincontroller)
- [Admin::JobsController](#adminjobscontroller)
- [Admin::BoxscoresController](#adminboxscorescontroller)
- [Admin::ReviewsController](#adminreviewscontroller)
- [Admin::ToolsController](#admintoolscontroller)
- [Auth::SessionsController](#authsessionscontroller)
- [Auth::RegistrationsController](#authregistrationscontroller)
- [PagesController](#pagescontroller)
- [OgImagesController](#ogimagescontroller)

---

## Conventions

- **Auth "public"** = no login required. Opens `Api::BaseController` which has `authenticate_user!` only for explicitly listed actions (none at the base level). Individual controllers may add `before_action :authenticate_user!`.
- **"optional user"** = action calls `current_user_optional` from `Api::BaseController` (`app/controllers/api/base_controller.rb:7-15`). Returns `nil` if the Authorization header is absent or invalid, otherwise the Devise user.
- `params.permit` / `params.require` — none of the API controllers use strong-params wrappers; they all read params positionally and pass them to AR queries or service calls. Parameter contracts below are derived from the action body.
- **Game ID resolution:** `GameShowService.resolve_game_id(params[:id])` accepts an internal DB id, `rb_<id>`, or an NCAA external id and returns `[external_id, Game record-or-nil]`.
- CachedGame is the durable polymorphic cache table keyed by `(game_id, data_type)` with types like `game`, `athl_boxscore`, `athl_play_by_play`, `sb_pitchers`, `ai_boxscore`, `team_stats`.

---

## Api::BaseController

File: `/Users/mattmondok/Code/riseballs-parent/riseballs/app/controllers/api/base_controller.rb`

Base class for every `/api/*` controller (except `Api::PitchAnalyticsController`, which unconditionally extends `ApplicationController`).

- `skip_before_action :verify_authenticity_token` — disables CSRF for all JSON endpoints.
- `current_user_optional` (line 7-15) — tries Devise auth if Authorization header is present, returns `nil` on failure. Used by most read endpoints to optionally personalize.

No routable actions.

---

## Api::GamesController

File: `/Users/mattmondok/Code/riseballs-parent/riseballs/app/controllers/api/games_controller.rb` (238 LOC).

All actions are **public** (no auth required).

### GET /api/games/:id

Action: `Api::GamesController#show` (lines 2-59).

- **Params:** `:id` — internal id / `rb_<id>` / NCAA external id.
- **Flow:**
  1. Resolve to `(gid, @game_record)` via `GameShowService.resolve_game_id` (line 3).
  2. **Fast path:** if `@game_record` exists and `CachedGame.locked?(@game_record)` (all data already enriched & frozen), return cached `game` payload and exit. Never hits the network (lines 5-12).
  3. Otherwise fetch `CachedGame#fetch(..., "game")`, falling back to `GameShowService.build_game_from_scoreboard(gid)` (hits NCAA scoreboard), then `build_game_from_record(@game_record)` (DB-only synthesis). Returns 503 if all three fail (lines 14-19).
  4. `GameShowService.enrich_show_data(data)` — attach team/player metadata to the contest.
  5. `patch_from_game_record` and `patch_scores_from_boxscore_fetch` — last-resort patching when scoreboard has nulls.
  6. Writes computed scores BACK to the `Game` record when the scoreboard has new info — flips `state` to `live` or `final` accordingly. This is the write-through that keeps the scoreboard view warm.
- **Response:** raw NCAA-shaped JSON with `contests[0]`, plus added keys: `internalId`. As of 2026-04-19 (mondok/riseballs#85) the former `liveStatsUrl` / `liveStatsFeedUrls` keys are no longer emitted — the StatBroadcast / SidearmStats live-stats machinery was removed and live scores are now supplied via the `riseballs-live` overlay (`live.riseballs.com/scoreboard`) consumed directly by the browser.
- **Errors:** `503 { error: "Unable to fetch game data" }` when no data source returns anything.
- **Caching:** reads from `CachedGame`. `locked?` short-circuit prevents re-scraping. Writes are async via service calls only.
- **Auth:** public.

### GET /api/games/batch

Action: `Api::GamesController#batch` (lines 208-237).

- **Params:** `ids` (comma-separated string of up to 12 external IDs).
- **Flow:** spawns a `Thread` per ID. Each thread fetches `CachedGame#fetch(gid, "game")` (never scrapes) and the last play via `extract_last_play`. Threads with exceptions return `nil` and are filtered out.
- **Response:** `{ games: [{ gameID, contest, lastPlay }, ...] }`. Empty `ids` returns `{ games: [] }`. Since 2026-04-19 no `liveStatsUrl` / `liveStatsFeedUrls` keys are included.
- **Caching:** cache-only read. No scraping path.
- **Auth:** public.

### GET /api/games/:id/boxscore

Action: `Api::GamesController#boxscore` (lines 61-154). Critical endpoint — implements the "Box Score Discovery Gate" (references issue #65).

- **Params:** `:id`.
- **Flow:**
  1. Resolve game. `lookup = @game_record || gid`.
  2. **DB-first:** If `CachedGame.locked?(lookup) || CachedGame.final?(lookup)`, serve `BoxscoreFetchService.best_from_db(lookup)` and merge in the `sb_pitchers` cache as `sbPitchers`. No network call.
  3. Fetch game metadata (cached or scoreboard-built) to determine `game_state` and `seo_slugs`.
  4. **"Pre" guard:** If `game_state == "p"` or `"pre"` AND `start_time_epoch` is in the future AND no `CachedGame` rows exist, return `404 {"error": "Game has not started yet"}` (lines 82-87).
  5. **GameTeamLink URL path:** iterate the game's `GameTeamLink` rows. For each with a `box_score_url`, call `AthleticsBoxScoreService.fetch_from_url` and if it returns a boxscore, persist via `CachedGame.store` and enqueue `PitcherEnrichmentService.enrich_async`, then render (lines 91-104). This path is preferred because per-team URLs are mapped during schedule sync and resolve doubleheaders correctly.
  6. **Generic athletics scraper:** fallback — `AthleticsBoxScoreService.fetch(gid, seo_slugs)` (discovery-keyed by slugs, no date filter). Applies two validation gates:
     - **Discovery gate (lines 112-120)**: if the Game is still in `scheduled` state and the returned linescore has a non-zero R row, reject the scrape and log a warn — prevents accidentally serving a prior meeting's final box score as the preview for tonight's game.
     - **Score-match gate (lines 121-133)**: if the `Game` has a known home/away score, reject any box score whose R-row sums don't match (either orientation).
  7. If the athletics scrape passes, store in `CachedGame`, enqueue pitcher enrichment, render.
  8. **AI fallback (lines 143-151):** `AiWebSearchBoxScoreService.fetch(gid, seo_slugs, game_date: ...)` — last resort. Stored as `ai_boxscore`. NOTE: project memory says this service is dead (see `feedback_no_ai_boxscore_fallback.md`), but the code path remains.
  9. **On-demand Java scrape (issue #87, 2026-04-19):** if every fallback above returned empty AND `probably_finished?(@game_record)` is true, call `JavaScraperClient.scrape_game(@game_record.id)` synchronously and retry `BoxscoreFetchService.best_from_db`. Gated by a 2-minute dedup key `bs_ondemand:<id>` in `Rails.cache` to prevent hammering. `probably_finished?` private helper: true if `game.final?`, else false for a null-scored doubleheader half (`game.home_score.nil? && game.has_doubleheader_sibling?`), else true if `Time.at(start_time_epoch) < 1.hour.ago`. The DH guard prevents a stuck-scheduled DH game 1 from triggering a scrape that would return DH game 2's boxscore — see [pipelines/03-boxscore-pipeline.md](../pipelines/03-boxscore-pipeline.md) and scraper#11.
  10. Returns `503 {"error": "Unable to fetch boxscore data"}` on total failure.
- **Response:** NCAA-style boxscore JSON with `linescores`, `teams`, `players`, `source_url` injected.
- **Caching:** reads/writes `CachedGame` for `athl_boxscore`, `athl_play_by_play`, `ai_boxscore`. No Rails.cache negative key on this endpoint.
- **Auth:** public.

### GET /api/games/:id/play_by_play

Action: `Api::GamesController#play_by_play` (lines 156-193). Critical endpoint — documents the quality gate and negative cache.

- **Params:** `:id`.
- **Flow:**
  1. Resolve. `lookup = game_record || gid`.
  2. **Cache serve:** `CachedGame.fetch(lookup, "athl_play_by_play") || CachedGame.fetch(lookup, "play_by_play")`. Return immediately if present.
  3. **Negative cache short-circuit:** reads `Rails.cache` key `pbp_miss:<gid>`. If set, return `503 {"error": "No play-by-play data available"}` without re-attempting (line 166-168). Prevents the frontend from hammering a game that repeatedly fails.
  4. **Athletics attempt:** read cached athletics boxscore/boxscore to get `seo_slugs`. If present, `AthleticsBoxScoreService.fetch(gid, seo_slugs)` and take its `:play_by_play` payload.
  5. **WMT fallback:** if we have a `game_record` AND the athletics result either failed or failed the quality gate (`CachedGame.send(:pbp_quality_ok?, best_pbp)`), try `WmtBoxScoreService.fetch_for_game(game_record)`. Rescues any error to `nil` (line 182).
  6. **Quality gate + write:** `CachedGame.store(gid, "athl_play_by_play", best_pbp)` — `store` internally re-runs `pbp_quality_ok?` and only writes if it passes. If write succeeds, delete `pbp_miss` and render.
  7. **Write negative cache:** on any failure path, `Rails.cache.write("pbp_miss:#{gid}", true, expires_in: 5.minutes)` and return 503.
- **Response:** cached PBP array / object on success. `503 {"error": "No play-by-play data available"}` on miss.
- **Caching:**
  - `CachedGame` for the positive result.
  - `Rails.cache` negative key `pbp_miss:<gid>` with 5-minute TTL.
- **Quality gate:** `CachedGame.pbp_quality_ok?` (private method — accessed via `.send`). Rejects empty/degenerate PBP.
- **Auth:** public.

### GET /api/games/:id/team_stats

Action: `Api::GamesController#team_stats` (lines 195-205).

- **Params:** `:id`.
- **Flow:** read-only cache lookup against `CachedGame.fetch(gid, "team_stats")`. No scraping path.
- **Response:** cached team stats JSON, or `503 {"error": "No team stats available"}`.
- **Caching:** pure cache read.
- **Auth:** public.

---

## Api::PredictionsController

File: `/Users/mattmondok/Code/riseballs-parent/riseballs/app/controllers/api/predictions_controller.rb` (212 LOC).

All actions are **public**. Talks to an external `predict-service` via `PredictServiceClient` (env: `PREDICT_SERVICE_URL`, `PREDICT_SERVICE_TIMEOUT_SECONDS`).

### GET /api/games/:id/prediction

Action: `Api::PredictionsController#show` (lines 10-42).

- **Params:** `:id`.
- **Flow:**
  1. Resolve game via `GameShowService.resolve_game_id`. `404` if not found (line 15).
  2. **Played-game short-circuit:** `game_already_played?` is true if `game.state in {"final","cancelled"}` OR any score is present. Returns `204 No Content` — the frontend treats 204 as "hide the prediction panel" (lines 17-19, 81-83).
  3. `422` if either team slug is blank.
  4. `PredictServiceClient.bundle_for(home_team_slug:, away_team_slug:, game_date:, division:)` — internally hits `/v1/matchups/predict` AND `/v1/matchups/keys-to-victory` in parallel.
  5. `503` on `PredictServiceClient::TimeoutError` or `ServiceUnavailable`.
- **Response shape:**
  ```json
  { "game_id": 12345, "home_team_slug": "...", "away_team_slug": "...",
    "prediction": { ... }, "keys_to_victory": { ... } }
  ```
- **Status codes:**
  - `200` — bundle returned.
  - `204` — game played / cancelled.
  - `404` — game not found.
  - `422` — missing team slugs (`:unprocessable_content`).
  - `503` — predict service timeout / unavailable.
- **Caching:** none in Rails; delegated to the predict service.
- **Auth:** public.

### GET /api/scoreboard/predictions

Action: `Api::PredictionsController#scoreboard` (lines 65-77).

Fan-out prediction map for scoreboard tiles / team schedule upcoming sections.

- **Params (mutually-combinable):**
  - `date=YYYY-MM-DD` (optional `division=`) — every scheduled game on that date.
  - `game_ids=` — comma-separated list of IDs (bare or `rb_`-prefixed).
  - `pairs=` — comma-separated triples `home:away:YYYY-MM-DD` for pair-only mode (when no `Game` record exists yet).
- **Selection priority** (`resolve_batch_games`, lines 120-132): `game_ids` > `date` > (no params: `Date.current`). When ONLY `pairs=` is passed, the `games` list is deliberately empty.
- **Flow:**
  - `fetch_predictions_for(games)` — `Concurrent::FixedThreadPool` of `POOL_SIZE = 10` fans out `PredictServiceClient.predict_only` calls with a 15s joint wait.
  - `fetch_pair_predictions(pairs)` — same pool-based pattern for free pairs.
  - Per-game failures are swallowed and logged (`Rails.logger.warn`) — one slow matchup doesn't poison the whole map.
- **Response:**
  ```json
  { "date": "2026-04-19",
    "predictions": {
      "rb_220126": { "home_pct": 0.65, "away_pct": 0.35, "confidence": "high" },
      "pair_home-slug_away-slug_2026-04-19": { ... }
    } }
  ```
- **Caching:** none in Rails.
- **Auth:** public.

---

## Api::TeamsController

File: `/Users/mattmondok/Code/riseballs-parent/riseballs/app/controllers/api/teams_controller.rb` (200 LOC).

`before_action :authenticate_user!` on `:follow, :unfollow`. `set_team` on `:show, :follow, :unfollow, :schedule` (finds by `slug`, renders `404` if missing).

### GET /api/teams

Action: `Api::TeamsController#index` (lines 36-53).

- **Params:** `division`, `conference`, `q` (search), `ranked` (`"true"` to filter + order by rank), `page`, `per_page` (default 50).
- **Response:** `{ teams: [...team_json...], meta: { page, per_page, total } }`. Paginated via Kaminari.
- **Auth:** optional user (for `following` flag).

### GET /api/teams/:slug

Action: `Api::TeamsController#show` (lines 55-107).

- **Params:** `:slug`.
- **Side effect:** if `team.roster_updated_at` is nil or older than 1 day, calls `RosterService.sync_roster(@team)` and reloads. Errors are rescued and logged (lines 60-67).
- **Response:** full team JSON plus nested `players` (ordered by number), `coaches` (ordered by id), and `pitching` totals (from `team_pitching_stat`). The `players` array inflates per-player batting + pitching aggregates for each roster entry.
- **Auth:** optional user (for `favorited` flag on players and `following` flag on team).

### POST /api/teams/:slug/follow

Action: `Api::TeamsController#follow` (lines 159-166).

- **Auth:** required (Devise `authenticate_user!`).
- **Response:** `{ message, following: true }` on create, or `422 { errors: [...] }`.

### DELETE /api/teams/:slug/unfollow

Action: `Api::TeamsController#unfollow` (lines 168-176).

- **Auth:** required.
- **Response:** `{ message, following: false }` — idempotent; missing follow also returns 200.

### GET /api/teams/:slug/schedule

Action: `Api::TeamsController#schedule` (lines 109-157). **Nontrivial opponent-slug fallback logic.**

- **Params:** `:slug`.
- **Source of truth:** `TeamGame` rows where `team_slug = @team.slug` (excluding `state = "cancelled"`), ordered by `(game_date, game_number)`.
- **Opponent resolution:**
  1. Primary: `teams.slug = tg.opponent_slug` lookup (batch-indexed).
  2. **Fallback:** when `opponent_slug` is NULL but `opponent_name` is set, batch-resolve via `TeamMatcher.find_many_by_name(unresolved_names, division: @team.division)` (lines 122-125). This is the same shared resolver used by `RosterService` and rankings — case-insensitive match against `teams.name` / `teams.long_name` with parenthetical-suffix stripping baked into `TeamMatcher`.
- **Response:**
  ```json
  { "record": { "wins": N, "losses": N, "ties": N },
    "games": [
      { "game_id": "...", "date": "mm/dd/YYYY", "opponent_name": "...",
        "opponent_seo": "slug-or-null", "is_home": bool,
        "team_score": int-or-null, "opponent_score": int-or-null,
        "result": "W"|"L"|"T"|null, "state": "scheduled"|"live"|"final", ... } ] }
  ```
- **Auth:** optional (set_team handles 404).

### GET /api/conferences

Action: `Api::TeamsController#conferences` (lines 26-34).

- **Params:** none.
- **Response:** `{ conferences: [{ name, seo }, ...] }`. `name` comes from the hard-coded `CONFERENCE_NAMES` map; `seo` comes from distinct non-blank `teams.conference_seo` values.
- **Auth:** public.

---

## Api::PlayersController

File: `/Users/mattmondok/Code/riseballs-parent/riseballs/app/controllers/api/players_controller.rb` (327 LOC).

`before_action :authenticate_user!` on `:favorite, :unfavorite`. Every other action uses `current_user_optional`.

### GET /api/players

Action: `Api::PlayersController#index` (lines 4-37).

- **Params:** `q` (searches `players.name ILIKE` and `teams.name ILIKE`), `position` (ILIKE), `division`, `team_slug`, `page`, `per_page` (default 50, paginated).
- **Response:** `{ players: [...player_json...], meta: { page, per_page, total } }`.
- **Auth:** optional user (for `favorited`).

### GET /api/players/:slug

Action: `Api::PlayersController#show` (lines 39-94). Accepts either a slug or a bare numeric ID (lines 192-198, `find_player_by_slug_or_id`).

- **Flow:**
  1. Find player, join to team.
  2. Match `PlayerGameStat` rows by full name OR (first + last OR first + final token of last). Handles compound last names.
  3. Split into batting vs pitching games (`has_batting`, `has_pitching` flags).
  4. Compute totals + game log + splits via `PlayerStatsCalculator`.
  5. **WAR data gate:** only loaded if `current_user_optional&.can_view_war`. Queries `PlayerWarValue` for the current `WarCalculator::SEASON` across scope_types.
- **Response:** `{ player: {...detailed fields..., game_log, splits, war: {...}?, favorited} }`.
- **404:** `{ error: "Player not found" }` when slug/id misses.
- **Auth:** optional user; WAR data gated on `can_view_war`.

### GET /api/players/:slug/spray_chart

Action: `Api::PlayersController#spray_chart` (lines 96-144).

- **Flow:**
  1. Find player.
  2. Build a fuzzy set of `batter_name` variants for this player via `find_batter_names` (lines 164-190) — last-name-prefix ILIKE filter plus first-initial check. Handles name truncations on scoreboards.
  3. Query `PlateAppearance` where `team_slug = player.team.slug` AND `team_batting IN (true, nil)` AND `batter_name IN variants`.
  4. Batted-ball scatter: rows with `hit_location` present, ordered `game_date DESC`, limit 500.
  5. Pitch count stats: aggregates over `pitch_sequence`-populated rows (first-pitch take/swing pct, avg pitches per PA).
- **Response:**
  ```json
  { "batted_balls": [{ hit_location, hit_type, result, result_category, game_date, opponent }, ...],
    "pitch_stats": { total_pas, first_pitch_take_pct, first_pitch_swing_pct,
                     first_pitch_swing_hit_pct, avg_pitches_per_pa } | null }
  ```
- **Auth:** public (player may contain name data, but no user-scoping).

### POST /api/players/:slug/favorite

Action: `Api::PlayersController#favorite` (lines 146-152).

- **Auth:** required. Creates `PlayerFavorite` record.
- **Response:** `{ favorited: bool }`.

### DELETE /api/players/:slug/unfavorite

Action: `Api::PlayersController#unfavorite` (lines 154-160).

- **Auth:** required. Destroys favorite if present (idempotent).
- **Response:** `{ favorited: false }`.

---

## Api::StandingsController

File: `/Users/mattmondok/Code/riseballs-parent/riseballs/app/controllers/api/standings_controller.rb` (65 LOC).

### GET /api/standings

Action: `Api::StandingsController#index` (lines 3-63).

- **Params:** `season` (default `Date.current.year`), `division` (default `"d1"`), `conference` (optional).
- **Flow:**
  1. Build the conference list from `ConferenceSource.by_season.by_division.active`.
  2. If `conference` is not provided, return `{ season, division, conferences, standings: nil, last_updated: nil }` (list-only mode).
  3. If provided, load `ConferenceStanding.by_season.by_division.by_conference.ranked`.
  4. Compute `games_back` for each row relative to the leader: `((leader.conf_wins - s.conf_wins) + (s.conf_losses - leader.conf_losses)) / 2.0`. Format as `"-"` for leader, integer string for whole numbers, else `%.1f`.
  5. **Scenarios:** call `ConferenceScenarioService.call(standings:, division:, season:, conference:)` — returns bracket / seeding scenarios for the conference tournament.
- **Response:**
  ```json
  { "season": 2026, "division": "d1", "conference": "sec",
    "conferences": ["acc", "big-12", ...],
    "standings": [
      { "conf_rank": 1, "team_name": "...", "team_slug": "...",
        "logo_url": "...", "conf_record": "20-4", "conf_win_pct": "0.833",
        "overall_record": "40-10", "overall_win_pct": "0.800",
        "streak": "W5", "games_back": "-" }, ... ],
    "scenarios": { ... from ConferenceScenarioService ... },
    "last_updated": "2026-04-18T14:00:00Z" }
  ```
- **Caching:** none in the controller; `last_updated` surfaces `standings.maximum(:scraped_at)`.
- **Auth:** public.

---

## Api::ScoreboardController

File: `/Users/mattmondok/Code/riseballs-parent/riseballs/app/controllers/api/scoreboard_controller.rb` (133 LOC).

### GET /api/scoreboard

Action: `Api::ScoreboardController#index`.

- **Params:** `division` (default `"d1"`), `date` (default `Date.today`).
- **Source:** `Game` table filtered by date + division, excluding cancelled / slugless rows, scoped to rows with at least one `team_games` row (`EXISTS` subquery).
- **Live refresh (today only):** If `parsed_date == Date.today`, identifies candidates — non-final, non-locked games whose `start_time_epoch` has already passed. Inside a 5-second `Timeout`, re-fetches each via `CachedGame.fetch(game, "game") || GameShowService.build_game_from_scoreboard(gid)` and writes `home_score/away_score/current_period/state` back to the `Game` record. Timeout errors are swallowed so the response never blocks.
- **Score recovery:** If a game is `final` but scores are nil, tries `CachedGame.fetch(game, "athl_boxscore")` and sums the linescore for non-aggregate periods.
- **Response shape as of 2026-04-19 (mondok/riseballs commit `263a684`, PR #83):**
  ```json
  { "games": [
      { "game": {
          "gameID": "rb_123",                // stable public id via Game#url_id; always "rb_<id>"
          "ncaaContestId": "12345",          // NCAA contest id for live-overlay join; may be null
          "gameNumber": 1,                   // doubleheader disambiguator (PR #83)
          "gameState": "pre"|"live"|"final",
          "startDate": "mm/dd/YYYY",
          "startTime": "...",
          "startTimeEpoch": "...",
          "currentPeriod": "...",
          "finalMessage": "...",
          "url": "/game/rb_123",
          "home": {...build_team...},
          "away": {...build_team...}
      } }, ... ],
    "conferences": [...unique team conferences...],
    "_source": "games_table" }
  ```
- The `gameID` field was decoupled from NCAA contest id on 2026-04-19 so public URLs stay stable across NCAA id changes. The new `ncaaContestId` field is the **primary** key used by the live-overlay reconciler in `riseballs-live` (match ladder: `ncaaContestId` → `(homeSlug, awaySlug, gameNumber)` → reversed-slug rescue; see [reference/matching-and-fallbacks.md](../reference/matching-and-fallbacks.md)).
- `build_team` returns `{ names: { char6, short, full, seo }, conference, score, winner, seed, rank, logo_url }`.
- **Caching:** reads from `CachedGame`; writes back to `Game` in-place. No explicit Rails.cache use.
- **Auth:** public.

---

## Api::RankingsController

File: `/Users/mattmondok/Code/riseballs-parent/riseballs/app/controllers/api/rankings_controller.rb` (38 LOC).

### GET /api/rankings

Action: `Api::RankingsController#index`.

- **Params:** `division` (default `"d1"`).
- **Records pipeline:** Groups final `TeamGame` rows by `team_slug` with `SUM(CASE WHEN team_score > opponent_score THEN 1)` — so the "record" shown next to the ranking is computed from the same `TeamGame` source as the team schedule page.
- **Response:** `{ title: "D1 NFCA Coaches Poll", updated: "Updated Mmm d, YYYY", data: [{ RANK, TEAM, SLUG, RECORD, CONFERENCE }, ...] }`.
- **Auth:** public.

---

## Api::RpiController

File: `/Users/mattmondok/Code/riseballs-parent/riseballs/app/controllers/api/rpi_controller.rb` (37 LOC).

### GET /api/rpi

Action: `Api::RpiController#index`.

- **Params:** `division` (default `"d2"` — note: DIFFERENT default than most other endpoints).
- **Flow:** loads `Team.where(division:).where.not(rpi: nil).order(rpi: :desc)`. Returns `404 { error: "No RPI data available. Run rake rpi:calculate first." }` if no teams have RPI.
- **Response:** `{ division, teams: [{ rank, slug, name, long_name, logo_url, conference, conference_seo, rpi, rpi_unweighted, wins, losses }], updated_at }`.
- **Auth:** public.

---

## Api::StatsController

File: `/Users/mattmondok/Code/riseballs-parent/riseballs/app/controllers/api/stats_controller.rb` (222 LOC).

### GET /api/stats

Action: `Api::StatsController#index` (lines 59-101). Leaderboards for team or individual batting/pitching stats.

- **Params:** `division` (default `"d1"`), `type` (`"team"` or `"individual"`, default `"team"`), `category` (`"batting"` or `"pitching"`, default `"batting"`), `stat` (key, default depends on category), `conference` (optional, by `conference_seo`), `page`.
- **Stat catalog:** `TEAM_BATTING_STATS`, `TEAM_PITCHING_STATS`, `INDIVIDUAL_BATTING_STATS`, `INDIVIDUAL_PITCHING_STATS` (lines 4-32). Each key has `{ label, sql, order }`. Unknown `stat` => `400 { error: "Unknown stat: ..." }`.
- **Arel sanitization:** `STAT_SELECT_EXPR` (lines 35-57) is a frozen hash of `Arel.sql(...)` expressions. Stat keys are looked up server-side; no interpolation. (Satisfies Brakeman.)
- **Minimum games threshold (team):** half the average games played across division teams (lines 116-118).
- **Minimum qualifiers (individual, lines 170-175):**
  - Rate batting stats (`batting_avg`, `obp`, `slugging`, `babip`, `k_pct`, `bb_pct`): `COUNT(*) >= 10 AND SUM(at_bats) >= 30`.
  - Rate pitching stats (`era`, `whip`, `hits_per_7`, `so_per_7`): `COUNT(*) >= 5 AND SUM(innings_pitched) >= 10`.
- **Pagination:** `PER_PAGE = 25`.
- **Response:** `{ title, stat, category, type, division, data: [...rows...], conferences: [{name, seo}], page, total_pages }`.
- **Auth:** public.

---

## Api::AnalyticsController

File: `/Users/mattmondok/Code/riseballs-parent/riseballs/app/controllers/api/analytics_controller.rb` (387 LOC).

**All actions require login:** `before_action :authenticate_user!`. `war_leaderboard` adds `require_war_access!` — returns 403 if `!current_user.can_view_war`.

### GET /api/analytics/leaderboard

Action: `Api::AnalyticsController#leaderboard` (lines 5-18) — dispatches to `batting_leaderboard` or `pitching_leaderboard`.

- **Params:** `type` (`"batting"` / `"pitching"`, default `"batting"`), `division` (default `"d1"`), `conference`, `sort`, `page`, `per_page` (capped at 100, default 50), plus rate-stat-specific: `min_ab` (batting default 30), `min_ip` (pitching default 5).
- **Sort whitelists:** `BATTING_SORT_COLS` (15 keys) and `PITCHING_SORT_COLS` (12 keys). Unknown sort falls back to `batting_avg` / `era`.
- **SQL:** groups `PlayerGameStat` on `(player_name, team_seo_slug, team_name)`. Uses `HAVING SUM(at_bats) >= min_ab` (or `SUM(innings_pitched) >= min_ip`) for qualifier gate. Aggregates include `batting_avg`, `obp`, `slg`, `ops`, or the pitching equivalents (`era`, `whip`, `k_per_7`, `bb_per_7`).
- **Player-link enrichment:** `find_player_slugs` (lines 340-370) heuristically matches `PlayerGameStat` names to `Player` records by team + last-name, returning a `player|team => slug` map for frontend linking.
- **Response:** `{ players: [...], conferences: [...], meta: { page, per_page, total, total_pages } }`.

### GET /api/analytics/war

Action: `Api::AnalyticsController#war_leaderboard` (lines 20-84).

- **Auth:** login + `can_view_war`.
- **Params:** `division` (default `"d1"`), `scope` (`"division"` or `"conference"`, default `"division"`), `conference`, `type` (`"total"`/`"batting"`/`"pitching"`, default `"total"`), `page`, `per_page` (capped at 100), `min_pa` (default 30, batting only), `min_ip` (default 10, pitching only).
- **Source:** `PlayerWarValue` for `WarCalculator::SEASON`, scoped by `scope_type` + `scope_value`.
- **Sort columns:** `batting` → `batting_war DESC`, `pitching` → `pitching_war DESC`, else `war DESC`.
- **Response:** `{ players: [{ player_name, player_slug, team_name, team_slug, team_logo, conference, war, batting_war, pitching_war, pa, woba, wraa, ip, fip }], conferences, meta }`.

---

## Api::PitchAnalyticsController

File: `/Users/mattmondok/Code/riseballs-parent/riseballs/app/controllers/api/pitch_analytics_controller.rb` (291 LOC).

**Deviates from base class:** subclasses `ApplicationController` directly (line 2), manually skips CSRF.

### GET /api/pitch_analytics/:team_slug

Action: `Api::PitchAnalyticsController#show` (lines 5-32).

- **Params:** `:team_slug` (defaults to `"montevallo"` if missing — a debugging default; in routing this param is always present).
- **Flow:** heavy-aggregation endpoint. Pulls all `PlateAppearance` and `PitchEvent` rows for a team slug, builds:
  - `summary` — game / PA / event counts.
  - `first_pitch` — take/swing splits with after-take outcomes, plus opponent first-pitch tendencies.
  - `count_analysis` — outcomes bucketed by `(balls, strikes)`.
  - `batter_breakdown` — top 20 batters with batched per-batter aggregates (avg pitches, take/swing %, hits/walks/k/hr, result distribution).
  - `bunt_analysis` — parses `play_description` text for sac vs hit vs out classification. Per-player details + count distribution.
  - `steal_analysis` — steal/CS by player, inning, to_base.
  - `situational` — outs-based and inning-based situation stats.
  - `pitching_against` — PA-against aggregates.
  - `games` — `{ source_id => { date, opponent } }` game lookup map.
- **Response:** JSON object with all the keys above plus `team`.
- **Caching:** none (expensive — relies on DB being warm).
- **Auth:** public.

---

## Api::LiveStatsController — **DELETED 2026-04-19**

File: `app/controllers/api/live_stats_controller.rb` — **removed** in mondok/riseballs#85 part 1 (PR #90). All four actions (`batch`, `boxscore_batch`, `sidearm_batch`, `resolve`) and their routes are gone. The four supporting services (`StatBroadcastService`, `SidearmStatsService`, `GameIdentityService`, the old `EspnScoreboardService`) were deleted in the same sweep along with the `/live` SPA page (`LiveView.jsx`), the `addToLiveView` button, the `/live` route, the Live nav entry, and the 10s `fetchLiveStats` poller on `Scoreboard.jsx`.

**Replacement:** live-score overlay is now served by the standalone `riseballs-live` Java service at `https://live.riseballs.com/scoreboard?date=YYYY-MM-DD`. The browser calls it directly in parallel with `/api/scoreboard`; `app/javascript/lib/liveOverlay.js` merges the two responses client-side. See [live/01-endpoints.md](../live/01-endpoints.md) and [reference/matching-and-fallbacks.md](../reference/matching-and-fallbacks.md) (overlay match ladder).

---

## Api::DashboardController

File: `/Users/mattmondok/Code/riseballs-parent/riseballs/app/controllers/api/dashboard_controller.rb` (84 LOC).

### GET /api/dashboard

Action: `Api::DashboardController#index`.

- **Auth:** **required** (`before_action :authenticate_user!`).
- **Flow:**
  1. Load `current_user.followed_teams` ordered by name.
  2. Today's games: `Game.for_date(Date.current).where("home_team_slug IN (?) OR away_team_slug IN (?)", ...)`. Projected into NCAA-shaped game objects (subset of fields).
  3. Schedule: per-followed-team `ScheduleService.games_for_team(team)`, flattened and sorted by date.
  4. Favorite players: `current_user.favorite_players.includes(:team)`.
- **Response:** `{ teams: [...], games: [...], schedule: [...], favorite_players: [...] }`.
- **Caching:** none.

---

## Api::FactsController

File: `/Users/mattmondok/Code/riseballs-parent/riseballs/app/controllers/api/facts_controller.rb` (36 LOC).

### GET /api/facts

Action: `Api::FactsController#index`.

- **Params:** `division` (default `"d1"`).
- **Flow:** reads `SiteMetric.find_by(key: "#{division}_facts")`. Returns `404 { error: "metrics not yet computed" }` if missing. Parses `metric.data` (JSON string or hash). Enriches `recent_leadoff_hrs` by back-filling `team_name` from `teams.slug => name`.
- **Response:** `{ data: { ... }, division, computed_at }`.
- **Auth:** public.

---

## Api::StatusController

File: `/Users/mattmondok/Code/riseballs-parent/riseballs/app/controllers/api/status_controller.rb` (53 LOC).

### GET /api/status

Action: `Api::StatusController#index`.

- **Params:** none.
- **Flow:** runs diagnostic queries across `Game`, `TeamGame`, `CachedGame`, `PlayerGameStat`:
  - `wrong_score_links` — finals where `Game.home_score` + `Game.away_score` don't match either orientation of `TeamGame.team_score` / `opponent_score`.
  - `self_play_games` — `home_team_slug = away_team_slug`.
  - `unmatched_finals` — `team_games` rows in final state with no `game_id`.
  - `orphaned_game_ids` — `team_games.game_id` pointing to nonexistent `games.id`.
  - `orphaned_games` — `games` with no `team_games`.
  - counts: `total_team_games`, `total_games`, `total_cached_games`, `total_player_game_stats`, `finals_matched`, `finals_total`, `finals_missing_boxscore` (finals within 60 days missing any `cached_games` row).
  - `last_sync` — `TeamGame.maximum(:updated_at).iso8601`.
- **Derived:** `healthy` = `wrong_score_links == 0 && self_play_games == 0 && orphaned_game_ids == 0 && orphaned_games == 0`.
- **Response:** flat hash of all checks.
- **Auth:** public (exposes internal counts — fine because no PII).

---

## Api::AdminController

File: `/Users/mattmondok/Code/riseballs-parent/riseballs/app/controllers/api/admin_controller.rb` (15 LOC).

`before_action :authenticate_user!` + `before_action :require_admin!` (returns `403 { error: "Forbidden" }` if `!current_user.admin?`).

### POST /api/admin/recalculate_rpi

Action: `Api::AdminController#recalculate_rpi`.

- **Flow:** enqueues `CalculateRpiJob.perform_later`.
- **Response:** `{ status: "queued", message: "RPI recalculation queued" }`.

---

## Admin::JobsController

File: `/Users/mattmondok/Code/riseballs-parent/riseballs/app/controllers/admin/jobs_controller.rb` (187 LOC).

Extends `ActionController::Base` (NOT `ApplicationController` — no browser gate, no Devise helpers at class level). Uses HTTP Basic auth via `authenticate_owner!` (lines 180-185) — only allows `matt.mondok@gmail.com` specifically (hard-coded `ALLOWED_EMAIL`).

Renders HTML views.

### GET /admin/jobs

Action: `Admin::JobsController#index`.

- **Flow:** exposes the `JOBS` constant (17 entries grouped into 4 categories: `pipeline`, `java_scraper`, `rankings`, `data_quality`). Each entry is `{ key, name, description, category, class_name }`. Also probes `JavaScraperClient.healthy?` (rescued to `false`).
- **Categories hash:** `{ "pipeline" => "Core Pipeline", "java_scraper" => "Java Scraper", "rankings" => "Rankings & Discovery", "data_quality" => "Data Quality" }`.
- **Auth:** HTTP Basic, owner email only.

### POST /admin/jobs/enqueue

Action: `Admin::JobsController#enqueue`.

- **Params:** `job_key` (one of the `JOBS[*][:key]` values).
- **Flow:** finds job def; `404` if unknown. Constantizes the `class_name`, calls `klass.perform_later(*job_def[:args] || [])`. Redirects back to index with notice.
- **Notable job classes:** `TeamScheduleSyncJob`, `LiveGameSyncJob`, `BoxScoreBackfillJob`, `NcaaDateReconciliationJob`, `ComputeD1MetricsJob`, `RosterAugmentAllJob`, `CoachAugmentAllJob`, `WmtSyncAllJob`, `RefetchMissingPbpJob`, `ReparsePbpJob`, `StandingsRefreshJob`, `SyncRankingsJob`, `CalculateRpiJob`, `AthleticsUrlDiscoveryJob`, `StaleGameCleanupJob`, `ScoreValidationJob`, `GameDedupJob`, `ScheduleReconciliationJob`.

---

## Admin::BoxscoresController

File: `/Users/mattmondok/Code/riseballs-parent/riseballs/app/controllers/admin/boxscores_controller.rb` (64 LOC).

Extends `ActionController::Base`. HTTP Basic auth via `authenticate_admin!` (gates on `user.admin?`). HTML views, uses `session` for queued-state tracking.

### GET /admin/boxscores

Action: `Admin::BoxscoresController#index`.

- **Flow:** list finals from the last 60 days (excluding today — the scheduled pipeline needs time to run) that have no `CachedGame` row with `data_type = "athl_boxscore"`. Joins to `Team` for display names and to `GameTeamLink` for known box-score URLs. `@queued` reads `session[:queued_games]` as a set.

### PATCH /admin/boxscores/:id/update_url

Action: `Admin::BoxscoresController#update_url`.

- **Params:** `:id` (game id), `box_score_url`.
- **Flow:**
  1. `400` if URL blank.
  2. Find-or-initialize a `GameTeamLink` for the home team, set `box_score_url`, save.
  3. Delete existing `CachedGame` rows for this game's `athl_boxscore`.
  4. Enqueue `AdminReprocessJob.perform_later(game.id)`.
- **Response:** redirect to `admin_boxscores_path` with notice.

### POST /admin/boxscores/:id/reprocess

Action: `Admin::BoxscoresController#reprocess`.

- **Flow:** same as `update_url` minus the URL write. Also appends `game.id` to `session[:queued_games]`.
- **Response:** redirect with notice.

---

## Admin::ReviewsController

File: `/Users/mattmondok/Code/riseballs-parent/riseballs/app/controllers/admin/reviews_controller.rb` (69 LOC).

Extends `ActionController::Base`. HTTP Basic admin gate. Backed by the `GameReview` model (review queue for data-quality events, see `feedback_*.md` memory entries).

### GET /admin/reviews

Action: `Admin::ReviewsController#index`.

- **Params:** `type` (optional filter).
- **Flow:** `GameReview.pending.includes(:game).order(created_at: :desc)`. Filterable by `by_type` scope. Preloads any games referenced in `review.proposed_changes["conflict_game_id"]`.

### POST /admin/reviews/:id/approve

Action: `Admin::ReviewsController#approve`.

- **Flow:** `review.approve!` — applies the proposed changes to the underlying Game record. Guards against double-apply (checks `pending?`). `RecordInvalid` rescued to a flash alert.

### POST /admin/reviews/:id/dismiss

Action: `Admin::ReviewsController#dismiss`.

- **Flow:** `review.dismiss!` — marks as dismissed without applying. Guards against double-dismiss.

### POST /admin/reviews/clear

Action: `Admin::ReviewsController#clear`.

- **Flow:** `GameReview.pending.delete_all`. Nuclear reset of the queue.

### POST /admin/reviews/clear_sidekiq

Action: `Admin::ReviewsController#clear_sidekiq`.

- **Flow:** clears `Sidekiq::Queue("default")`, `Sidekiq::ScheduledSet`, `Sidekiq::RetrySet`. Reports counts in the flash.

---

## Admin::ToolsController

File: `/Users/mattmondok/Code/riseballs-parent/riseballs/app/controllers/admin/tools_controller.rb` (19 LOC).

Extends `ActionController::Base` + HTTP Basic admin gate.

### POST /admin/recalculate_rpi

Action: `Admin::ToolsController#recalculate_rpi`.

- **Flow:** `CalculateRpiJob.perform_later`.
- **Response:** JSON `{ status: "queued" }`.

---

## Auth::SessionsController

File: `/Users/mattmondok/Code/riseballs-parent/riseballs/app/controllers/auth/sessions_controller.rb` (27 LOC). Extends `Devise::SessionsController`, `respond_to :json`.

### POST /auth/sign_in

Action: `Auth::SessionsController#create` (lines 5-16).

- **Body:** Devise-standard (`user: { email:, password: }`).
- **Flow:** `warden.authenticate!(auth_options)` then `sign_in`.
- **Response:** `200 { user: { id, email, can_view_war }, message: "Logged in successfully." }`.

### DELETE /auth/sign_out

Action: Devise default (destroy) → overridden `respond_to_on_destroy`.

- **Response on success:** `200 { message: "Logged out successfully." }`.
- **Response on no session:** `401 { message: "Couldn't find an active session." }`.

---

## Auth::RegistrationsController

File: `/Users/mattmondok/Code/riseballs-parent/riseballs/app/controllers/auth/registrations_controller.rb` (24 LOC). Extends `Devise::RegistrationsController`, `respond_to :json`.

### POST /auth/sign_up

Action: Devise default (create) → overridden `respond_with`.

- **Response (persisted):** `200 { user: { id, email, can_view_war }, message: "Signed up successfully." }`.
- **Response (errors):** `422 { message: "Sign up failed.", errors: [...] }`.

### Other Devise endpoints

`GET /auth/edit`, `PATCH/PUT /auth`, `DELETE /auth`, `/auth/password/*` use stock Devise controllers — not customized here.

---

## PagesController

File: `/Users/mattmondok/Code/riseballs-parent/riseballs/app/controllers/pages_controller.rb` (57 LOC).

The SPA shell. Handles `GET /` and `GET /*path` (catch-all modulo the exclusion list in routes.rb).

### GET / and GET /*path

Action: `PagesController#index` (lines 2-7).

- **Legacy player redirect (lines 11-21):** if path matches `/players/:numeric_id`, look up the player by id and `301` redirect to `/players/<slug>`. Falls through to the SPA render if the player has no slug.
- **SEO meta (lines 23-55):** sets `@page_title`, `@page_description`, and (for teams/players) `@page_image` via the OG-image routes. Covered paths:
  - `/teams/:slug` — uses team name/logo.
  - `/players/:slug` — uses player + team name.
  - `/scoreboard`, `/teams`, `/rankings`, `/stats`, `/players` — static copy.
- Always sets `request.format = :html`.
- **Response:** renders the SPA shell HTML (generated by Vite/importmap; not a controller-specific view).
- **Auth:** public. Subject to `ApplicationController#reject_unsupported_browser` (returns `406` for legacy browsers unless the UA matches the link-preview-bot regex).

---

## OgImagesController

File: `/Users/mattmondok/Code/riseballs-parent/riseballs/app/controllers/og_images_controller.rb` (34 LOC).

Redirect-only endpoints used by Open Graph / Twitter Card metadata. Always returns `302`.

### GET /og/players/:slug

Action: `OgImagesController#player`.

- **Flow:** find player by slug; preferred URL is the player's photo (rewritten via `og_photo_url` if it's a Sidearm CDN URL — changes width/height to 600 and forces JPEG); fallback is `team.logo_url`; final fallback is `/og-image.png`.

### GET /og/teams/:slug

Action: `OgImagesController#team`.

- **Flow:** find team by slug; `302` to `team.logo_url` or `/og-image.png` fallback.

- `redirect_to_image` (lines 15-21): uses `allow_other_host: true, status: :found`. Returns 302 to the image URL.

---

## Cross-cutting behaviors

- **CSRF:** disabled in `Api::BaseController` and auth controllers (both `Auth::SessionsController` and `Auth::RegistrationsController` call `skip_before_action :verify_authenticity_token`). Admin controllers are plain `ActionController::Base` and don't have CSRF in the first place.
- **Browser filter:** `ApplicationController#reject_unsupported_browser` runs for every request that hits an `ApplicationController` subclass. Returns 406 with `public/406-unsupported-browser.html` for legacy browsers UNLESS the User-Agent matches `/bot|crawl|spider|externalhit|facebot|whatsapp|telegram|slack|discord|preview|cfnetwork|linkedin|curl|wget/i`. Admin controllers inherit from `ActionController::Base` directly and bypass this.
- **Parameter truncation:** `games#batch` caps batch size at 12 ids defensively. The former `live_stats#*` caps are gone with the controller's deletion.
- **Predict service env vars:** `PREDICT_SERVICE_URL`, `PREDICT_SERVICE_TIMEOUT_SECONDS` — consumed by `PredictServiceClient` (not the controller).
- **Negative cache key format:** `pbp_miss:<gid>` in Rails.cache, 5-minute TTL. Set and cleared by `Api::GamesController#play_by_play`.
