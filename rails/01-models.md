# Rails Models Reference

Dense per-model reference for `riseballs/app/models/*.rb`. All file paths are absolute from the `riseballs/` Rails root unless otherwise noted.

## Table of Contents

1. [ApplicationRecord](#applicationrecord)
2. [Game](#game) — canonical game record (shared across both teams)
3. [TeamGame](#teamgame) — per-team view of a game (doubleheader-aware)
4. [GameTeamLink](#gameteamlink) — team-specific URLs/IDs for a canonical Game
5. [GameIdentifier](#gameidentifier) — sidearm-ID join table used by `Game.find_or_create_from_schedule`
6. [GameSnapshot](#gamesnapshot) — point-in-time snapshots of live game state
7. [GameReview](#gamereview) — admin review queue for game data anomalies
8. [CachedGame](#cachedgame) — polymorphic cache for NCAA/box-score/PBP payloads
9. [CachedSchedule](#cachedschedule) — team schedule JSON cache with empty-overwrite guard
10. [CachedApiResponse](#cachedapiresponse) — generic key/value JSON cache with TTL
11. [Team](#team)
12. [TeamAlias](#teamalias)
13. [TeamPitchingStat](#teampitchingstat)
14. [Player](#player)
15. [PlayerGameStat](#playergamestat) — per-game batting/pitching line
16. [PlayerWarValue](#playerwarvalue) — pre-computed WAR/wOBA/FIP per scope/season
17. [PlayerFavorite](#playerfavorite)
18. [Coach](#coach)
19. [PlateAppearance](#plateappearance) — PBP-derived PA rows
20. [PitchEvent](#pitchevent) — PBP-derived base-running / wild-pitch events
21. [ConferenceSource](#conferencesource) — configured standings URLs per conference
22. [ConferenceStanding](#conferencestanding) — scraped conference standings rows
23. [StandingsScrapeLog](#standingsscrapelog)
24. [ScrapedPage](#scrapedpage)
25. [BatchJob](#batchjob) — OpenAI batch pipeline tracking
26. [SiteMetric](#sitemetric)
27. [User](#user)
28. [Follow](#follow)

---

## ApplicationRecord

**File:** `app/models/application_record.rb`

```ruby
class ApplicationRecord < ActiveRecord::Base
  primary_abstract_class
end
```

Standard Rails abstract base. No shared concerns — `app/models/concerns/` is empty.

---

## Game

**File:** `app/models/game.rb`

Canonical, single-row-per-game record that is shared across both competing teams. `Game` is the root of the game-data graph; `TeamGame`, `GameTeamLink`, `GameIdentifier`, `CachedGame`, `GameSnapshot`, `GameReview`, and `PlayerGameStat` all hang off it.

### Constants

- `STATES = %w[scheduled live final postponed cancelled]` — `game.rb:2`

### Key Columns

| Column | Type | Notes |
|---|---|---|
| `game_date` | date | NOT NULL; indexed |
| `home_team_slug` / `away_team_slug` | string | FK-like to `teams.slug`; indexed |
| `home_team_name` / `away_team_name` | string | denormalized display names |
| `game_number` | int, default 1 | doubleheader index |
| `division` | string | e.g. `"d1"` |
| `state` | string, default `"scheduled"` | one of `STATES` |
| `home_score` / `away_score` | int, nullable | must be nil when `state == "cancelled"` |
| `current_period` / `final_message` | string | live-display strings |
| `start_time` / `start_time_epoch` | string / bigint | |
| `ncaa_game_id` | string | legacy NCAA contest key |
| `ncaa_contest_id` | bigint | primary NCAA contest key (new); unique where present |
| `home_box_score_id` / `away_box_score_id` | string | team-scoped boxscore ids; unique per `(team_slug, box_score_id)` |
| `discovery_source` | string | how Rails learned about the game |
| `data_freshness` | string, default `"unknown"` | `"ncaa_corrected"` and `"reconciled"` freeze date updates (see `Game.update_game_from_schedule` at `game.rb:184`) |
| `locked` | bool, default false | locked finals don't accept score/state rewrites |
| `metadata` | jsonb |  |

Natural-key unique index `idx_games_natural_key` on `(game_date, home_team_slug, away_team_slug, game_number)` — this is how the model enforces "one game per team-pair per date per game-number" for doubleheaders.

### Associations

- `has_many :game_identifiers, dependent: :destroy`
- `has_many :game_team_links, dependent: :destroy`
- (Inverse) `CachedGame`, `PlayerGameStat`, `GameReview`, `GameSnapshot`, `GameTeamLink`, `GameIdentifier`, `TeamGame` all `belongs_to :game` (most with `on_delete: :cascade` at the DB level — see `schema.rb:571-585`).

No `belongs_to :team` — both teams are referenced by slug strings (`home_team_slug` / `away_team_slug`); `#home_team` / `#away_team` do an explicit `Team.find_by(slug: …)` and memoize.

### Scopes

- `for_date(date, division: nil)` — `game.rb:38`
- `today`, `live`, `final`, `scheduled`
- `not_locked` — `where(locked: false)`
- `for_team(slug)` — matches either `home_team_slug` or `away_team_slug`

### Validations

- `presence`: `game_date`
- `inclusion`: `state` in `STATES`
- `numericality`: `game_number > 0`
- `uniqueness`: `home_team_slug` scoped to `(game_date, away_team_slug, game_number)` — mirrors `idx_games_natural_key`
- `uniqueness`: `ncaa_game_id` (`allow_nil`)
- Custom `team_slugs_must_exist` — only runs for `division == "d1" && new_record?` (D2/D3 Teams rows may lag)
- Custom `teams_must_differ`
- Custom `cancelled_games_must_not_have_scores`

### Callbacks

- **`after_update_commit :enqueue_pbp_refresh_if_finalized`** — `game.rb:17, 241`. Fires `PbpOnFinalJob.perform_later(id)` whenever `state` transitions to `"final"`. This is the pipeline entry-point for post-final PBP backfill (see [../pipelines/02-pbp-pipeline.md](../pipelines/02-pbp-pipeline.md)).

### Class Methods

- **`find_by_any_id(id)`** — `game.rb:100`. Accepts:
  - `"rb_<id>"` → internal Rails id (**canonical public form since 2026-04-19**; `Game#url_id` returns this, and `Api::ScoreboardController` emits it as `gameID`)
  - `ncaa_contest_id` (preferred external key; `ncaaContestId` in scoreboard JSON)
  - `ncaa_game_id` (legacy)
  - bare numeric → `id`
  Used by every API controller that takes a `:game_id` param. Legacy `/game/<contest_id>` URLs continue to resolve here; the response normalizes the outbound form to `rb_<id>`.

- **`find_or_create_from_schedule(team, game_hash)`** — `game.rb:118`. Three-step lookup that prevents the classic "both teams scrape the same game and create two rows" bug:
  1. `GameIdentifier.find_by(team_slug, sidearm_id)` → existing game (re-crawl fast-path).
  2. Otherwise, look for a Game on the same date between the same slug pair that this team hasn't linked yet (doubleheader-aware via `GameIdentifier.exists?`).
  3. Otherwise, call `JavaScraperClient.find_or_create_game(...)` — the Java scraper is the single writer for new `games` rows. Rails then re-loads the returned id.

  Handles `ActiveRecord::RecordNotUnique` by re-fetching via `GameIdentifier`.

- **`update_game_from_schedule(...)`** — private (`game.rb:181`, `private_class_method` at `:223`). Performs the actual field-by-field update with protection against:
  - Date overwrites on `locked?` games or games whose `data_freshness` is `"ncaa_corrected"` / `"reconciled"`.
  - Score overwrites on `final? && locked?` games.
  - State regressions (e.g. `"final"` won't be pushed back to `"scheduled"` unless scores are nil; `"cancelled"` is sticky).

- **`parse_schedule_date(date_str)`** — private. Accepts `Date`, `mm/dd/yyyy`, or anything `Date.parse` handles; returns `nil` on `Date::Error`.

- **`map_schedule_state(state)`** — private (`game.rb:246`). Normalizes scraper state codes (`"F"`, `"I"`, `"P"`, `"pre"`, etc.) into `STATES` values.

### Instance Methods

- State helpers: `live?`, `final?`, `scheduled?` — `game.rb:52-54`
- `home_team` / `away_team` — memoized `Team.find_by(slug: …)`
- `best_external_id` — `ncaa_contest_id` → `ncaa_game_id` → `"rb_#{id}"`. This is the cache key used by `CachedGame.store_for_game`.
- `url_id` — **stable public id** for this game. Always returns `"rb_<id>"`. Decoupled from `ncaa_contest_id` as of mondok/riseballs commit `263a684` (2026-04-19). Use this in any outbound URL / scoreboard payload. `Api::ScoreboardController` sets `gameID: game.url_id` and `ncaaContestId: game.ncaa_contest_id` as separate fields so the live-overlay reconciler can key off the NCAA id without our URL scheme being tied to NCAA.
- `box_score_id_for(team_slug)` / `set_box_score_id(team_slug, id)` — routes to `home_box_score_id` or `away_box_score_id`.
- `preferred_box_score` — delegates to `CachedGame.fetch_team_boxscore` (home first, then away).
- `has_doubleheader_sibling?` — true when another Game exists for the same `(game_date, home_team_slug, away_team_slug)` on a different `game_number`. Added in issue #87 (2026-04-19). Used by `GamePipelineJob#fetch_missing_boxscores`, `BoxScoreBackfillJob`, and `Api::GamesController#probably_finished?` to skip null-scored halves of doubleheaders — the Java scraper's pre-scraper#11 score-match DH disambiguation could return the wrong half's boxscore when `Game.home_score` was null. With scraper#11's direct-id lookup this guard is belt-and-suspenders: blocks the risky scrape from being kicked off in the first place.

### Cross-references

- PBP on-final: [../pipelines/02-pbp-pipeline.md](../pipelines/02-pbp-pipeline.md)
- Schedule ingestion path: [../pipelines/01-game-pipeline.md](../pipelines/01-game-pipeline.md)
- Java creation gate: [../scraper/02-services.md](../scraper/02-services.md), specifically `GameCreationService` + `JavaScraperClient#find_or_create_game` in [11-external-clients.md](11-external-clients.md)

---

## TeamGame

**File:** `app/models/team_game.rb`

Per-team view of a game. One game produces two `team_games` rows (one per team), unlike `games` which is a single shared row. Used by the per-team schedule UI and by scrapers that only see games from one team's schedule page.

### Key Columns

| Column | Type | Notes |
|---|---|---|
| `team_slug` | string | NOT NULL |
| `game_date` | date | NOT NULL |
| `game_number` | int, default 1 | NOT NULL; doubleheader disambiguator |
| `opponent_name` / `opponent_slug` | string |  |
| `is_home` | bool |  |
| `team_score` / `opponent_score` | int |  |
| `state` | string, default `"scheduled"` |  |
| `boxscore_id` / `boxscore_url` | string | sidearm or other team-facing boxscore |
| `source` | string |  |
| `game_id` | bigint, FK → `games.id` | links to canonical Game |

**Critical unique index:** `idx_team_games_schedule` on `(team_slug, game_date, opponent_slug, game_number)`. This is the doubleheader-handling unique constraint — the `game_number` column is what lets us store both games of a doubleheader without the upsert collapsing them into one row.

Second unique index: `idx_team_games_boxscore` on `(team_slug, boxscore_id)` where `boxscore_id IS NOT NULL`.

### Associations

- `belongs_to :team, foreign_key: :team_slug, primary_key: :slug, optional: true`
- `belongs_to :game, optional: true`

### Scopes

- `for_team(slug)`, `final`, `scheduled`, `with_boxscore`

### Validations

- `presence`: `team_slug`, `game_date`, `game_number`
- `numericality`: `game_number > 0`
- **`uniqueness`: `team_slug` scoped to `(game_date, opponent_slug, game_number)`** — Rails-level mirror of `idx_team_games_schedule`.

### Instance Methods

- `final?`, `scheduled?`

---

## GameTeamLink

**File:** `app/models/game_team_link.rb`

Join record attaching per-team URLs and external IDs (sidearm, StatBroadcast, live-stats) to a canonical `Game`. Each team competing in a given game gets one `GameTeamLink` row.

### Key Columns

| Column | Type | Notes |
|---|---|---|
| `game_id` | bigint, NOT NULL | FK → `games.id`, cascade delete |
| `team_slug` | string, NOT NULL |  |
| `sidearm_game_id` | string | **Kept** (23,733 rows populated as of 2026-04-19). Actively used by the Java scraper for box-score URL discovery — do not drop. |
| `box_score_url` | string |  |

### Indexes

- Unique `(game_id, team_slug)` — one link per team per game.
- Unique partial `(team_slug, sidearm_game_id)` where not null (`idx_game_team_links_team_sidearm`).

### What was dropped 2026-04-19 (mondok/riseballs#85 part 2)

Migration `2026_04_19_*` dropped four columns and one index from `game_team_links`:

- `live_stats_url`
- `live_stats_feed_url`
- `sb_event_id` (StatBroadcast event id) + its partial index

These columns were populated by the StatBroadcast / SidearmStats live-stats machinery that was removed in mondok/riseballs#85 part 1 (LiveView page, `/api/live_stats/*`, `GameIdentityService`, etc.). The corresponding JPA mappings were removed from `GameTeamLink.java` in riseballs-scraper PR #12. `sidearmGameId` is the only retained external id on this table.

### Associations / Validations

- `belongs_to :game`
- `presence`: `team_slug`
- `uniqueness`: `team_slug` scoped to `game_id`

---

## GameIdentifier

**File:** `app/models/game_identifier.rb`

Maps a `(team_slug, sidearm_id)` tuple to a canonical `Game`. Used by `Game.find_or_create_from_schedule` (`game.rb:130-149`) to short-circuit re-crawls and to track which teams have already claimed a sidearm id for doubleheader disambiguation.

### Columns

| Column | Type | Notes |
|---|---|---|
| `game_id` | bigint, NOT NULL | FK → `games.id`, cascade delete |
| `team_slug` | string, NOT NULL |  |
| `sidearm_id` | string, NOT NULL |  |

Unique index on `(team_slug, sidearm_id)`.

### Associations / Validations

- `belongs_to :game`
- `presence`: `team_slug`, `sidearm_id`
- `uniqueness`: `sidearm_id` scoped to `team_slug`

---

## GameSnapshot

**File:** `app/models/game_snapshot.rb`

Append-only point-in-time snapshot of a game's live state (linescore, batting/pitching summaries). Keyed by `ncaa_game_id` with optional `game_id` FK. Used for live-game diagnostics and historical replay.

### Columns

| Column | Type | Notes |
|---|---|---|
| `ncaa_game_id` | string, NOT NULL |  |
| `game_id` | bigint | optional FK → `games.id`, cascade |
| `game_state` / `current_period` | string |  |
| `home_score` / `away_score` | int, default 0 |  |
| `linescore` / `batting_summary` / `pitching_summary` | jsonb |  |
| `data_source` | string |  |

Composite index `idx_snapshots_game_time` on `(ncaa_game_id, created_at)` for time-ordered scans.

### Scopes

- `for_game(ncaa_game_id)` — ordered by `created_at`
- `for_game_record(game)` — OR of `game_id` and `ncaa_game_id`
- `latest_for_game(ncaa_game_id)` — most recent

### Validations

- `presence`: `ncaa_game_id`

---

## GameReview

**File:** `app/models/game_review.rb`

Admin review queue for data anomalies produced by the pipeline. Each row describes a proposed fix (`proposed_changes` jsonb) that can be approved to mutate the associated `Game`.

### Constants

- `STATUSES = %w[pending approved dismissed]`
- `REVIEW_TYPES = %w[date_mismatch score_mismatch duplicate missing_from_schedule merge_conflict stale_scheduled cancelled_with_scores boxscore_misassignment team_mismatch]`

### Key Columns

| Column | Type | Notes |
|---|---|---|
| `game_id` | bigint, NOT NULL | FK, cascade delete |
| `review_type` | string, NOT NULL | one of `REVIEW_TYPES` |
| `reason` | text, NOT NULL | human-readable |
| `proposed_changes` | jsonb, default `{}` | fields to apply on approve |
| `source` | string, NOT NULL | which detector surfaced it |
| `status` | string, default `"pending"` |  |
| `resolved_at` | datetime | set by `approve!` / `dismiss!` |

### Associations / Scopes / Validations

- `belongs_to :game`
- Scopes: `pending`, `resolved`, `by_type(type)`
- Validations on `review_type` (inclusion), `reason`, `source`, `status` (inclusion)

### Instance Methods

- `pending?`
- **`approve!`** — `game_review.rb:25`. In a transaction: applies `proposed_changes` to the Game (whitelisted attrs: `game_date`, `start_time_epoch`, `home_score`, `away_score`, `state`, plus `stat_totals.{home,away}` which remaps to scores), then sets `status=approved`, `resolved_at=now`.
- **`dismiss!`** — sets `status=dismissed`, `resolved_at=now`.

### Cross-references

- [../pipelines/06-reconciliation-pipeline.md](../pipelines/06-reconciliation-pipeline.md) — audit detectors (`ScoreValidationJob`, `NcaaDateReconciliationJob`, schedule reconciliation) that enqueue `GameReview` rows.
- [04-api-endpoints.md](04-api-endpoints.md) `Admin::ReviewsController` — approve/dismiss UI.

---

## CachedGame

**File:** `app/models/cached_game.rb`

Polymorphic cache for all per-game JSON payloads fetched from external sources (NCAA game detail, box scores, PBP, team stats, StatBroadcast pitcher data, Athletic.net variants). Every payload store goes through this model; PBP writes are gated by `pbp_quality_ok?`.

### Constants

- `DATA_TYPES = %w[game boxscore play_by_play team_stats sb_pitchers athl_boxscore athl_play_by_play]` — `cached_game.rb:6`
- `REQUIRED_FOR_LOCK = %w[game boxscore]`
- `REQUIRED_PBP = %w[play_by_play athl_play_by_play]` (either satisfies the PBP requirement)
- `PLAY_VERB` regex at `cached_game.rb:161` — used to detect "garbage" PBP rows (bare names without verbs).

### Columns

| Column | Type | Notes |
|---|---|---|
| `ncaa_game_id` | string, NOT NULL | external id (falls back to `"rb_<id>"`) |
| `data_type` | string, NOT NULL | one of `DATA_TYPES` |
| `game_state` | string | most recent state at write time |
| `payload` | jsonb, NOT NULL, default `{}` | the cached blob |
| `locked` | bool, default false | once locked, writes are frozen |
| `game_id` | bigint | FK → `games.id`, cascade delete |
| `team_slug` | string | set only for team-scoped `athl_boxscore` rows |

### Indexes — the composite key logic

The cache has **three** layered unique constraints so the same logical payload can't be written twice but per-team box scores can coexist:

1. `index_cached_games_on_ncaa_game_id_and_data_type` — unique `(ncaa_game_id, data_type)`. Global dedupe by external id.
2. `index_cached_games_on_game_id_and_data_type` — unique `(game_id, data_type) WHERE game_id IS NOT NULL`. Dedupe by internal FK for non-team-scoped rows.
3. `idx_cached_games_team` — unique `(game_id, data_type, team_slug) WHERE team_slug IS NOT NULL`. Lets one game hold both `athl_boxscore` rows (home + away).

### Associations / Validations

- `belongs_to :game, optional: true`
- `presence`: `ncaa_game_id`, `data_type`
- `uniqueness`: `ncaa_game_id` scoped to `data_type`

### Class Methods (critical)

- **`fetch(game_or_id, type)`** — `cached_game.rb:18`. Accepts either a `Game` object (preferred, uses `game_id` FK) or string id (legacy, uses `ncaa_game_id`). Returns `payload` or nil.

- **`store(game_or_id, type, payload, game_state: nil)`** — `cached_game.rb:31`. Main write entry-point. If `type` is a PBP type and `pbp_quality_ok?` returns false, the write is silently rejected (returns nil). Resolves string ids to `Game` via `resolve_game` when possible.

- **`store_for_game(game, type, payload, game_state: nil)`** — `cached_game.rb:55`. Preferred write path (explicit `Game` FK). Cache key is computed as `game.ncaa_contest_id || game.ncaa_game_id || game.id`. Also PBP-gated. Idempotent via `ActiveRecord::RecordNotUnique` rescue.

- **`fetch_by_game(game, type)`** — alias of `fetch`.

- **`fetch_team_boxscore(game, team_slug)`** — `cached_game.rb:81`. Looks up `data_type="athl_boxscore"` first with matching `team_slug`, then falls back to the `team_slug IS NULL` unscoped row.

- **`store_team_boxscore(game, team_slug, payload, game_state: nil)`** — `cached_game.rb:89`. Writes `data_type="athl_boxscore"` with the `team_slug` column set so both teams' boxscores can coexist under `idx_cached_games_team`.

- **`fetch_preferred_boxscore(game)`** — `cached_game.rb:102`. Home-first fallback.

- **`final?(game_or_id)`** — any cached row with `game_state IN ('F','final')`.

- **`locked?(game_or_id)`** — any cached row with `locked=true`.

- **`lock!(game_or_id)`** — `update_all(locked: true)` for all rows of the game.

- **`try_lock!(game_or_id)`** — `cached_game.rb:120`. The full lock-gate:
  - Requires `final?` to be true.
  - If any row is already locked, propagates lock to remaining rows and returns.
  - Otherwise requires both `REQUIRED_FOR_LOCK` types present AND at least one `REQUIRED_PBP` type present. Only then calls `lock!`.

- **`pbp_quality_ok?(payload)`** — `cached_game.rb:165` (private). Single source of truth for PBP quality. Rejects payloads where:
  - `payload` isn't a Hash or has no `periods`.
  - Single-period dumps with >20 plays (parser failure mode).
  - Non-last innings with one stat group and >3 plays (teams not split per half-inning).
  - Non-last innings with multiple stat groups all sharing the same `teamId` (parser didn't distinguish teams).
  - Empty `teams` array when `periods.size >= 2` (frontend needs team names).
  - More than 50% of plays have `playText` under 25 chars and no verb match.

  Called from both `CachedGame.store` and `BoxscoreFetchService`. **Every** PBP write in the system goes through this gate.

- **`resolve_game(game_id_str)`** — private (`cached_game.rb:141`). Resolves via `ncaa_contest_id`, `ncaa_game_id`, or the `"rb_<id>"` internal prefix.

- **`records_for(game_or_id)`** — private. Returns an `ActiveRecord::Relation` scoped either to the FK or the `ncaa_game_id`.

- **`pbp_type?(type)`** — private. True for `play_by_play` or `athl_play_by_play`.

### Cross-references

- [../pipelines/02-pbp-pipeline.md](../pipelines/02-pbp-pipeline.md) — how PBP writes hit `store` / `store_for_game` and pass through `pbp_quality_ok?`.
- [../pipelines/03-boxscore-pipeline.md](../pipelines/03-boxscore-pipeline.md) — boxscore blob storage path.
- [../pipelines/06-reconciliation-pipeline.md](../pipelines/06-reconciliation-pipeline.md) — `try_lock!` is the finalization gate used by `ScoreValidationJob`.

---

## CachedSchedule

**File:** `app/models/cached_schedule.rb`

Per-team cached schedule JSON. One row per `team_slug` (unique index). Hardened against the 2026-03-27 "226 teams cached as 0 games" outage by refusing overwrites of non-empty cache with empty payloads.

### Columns

| Column | Type | Notes |
|---|---|---|
| `team_slug` | string, NOT NULL, unique |  |
| `payload` | jsonb, NOT NULL, default `{}` |  |

### Constants

- `MIN_PAYLOAD_GAMES_TO_OVERWRITE = 0`

### Class Methods

- **`fetch(team_slug)`** — returns symbolized payload or nil.
- **`store(team_slug, payload, allow_empty: false)`** — `cached_schedule.rb:28`. Refuses to overwrite a previously-non-empty cache with an empty payload unless `allow_empty: true`. Logs a warning and returns the pre-existing payload when the guard fires. Retries on `RecordNotUnique`.
- **`fresh?(team_slug, ttl: 30.minutes)`** — TTL freshness check on `updated_at`.
- **`stale_data(team_slug)`** — returns payload regardless of freshness (used by recovery paths).
- **`empty_payload?(payload)`** / **`game_count(payload)`** — the empty-payload guard inside `store`. (Previously cited as "for `ScheduleRecoveryService`"; that service was removed 2026-04-20 but the helpers still guard `store` from replacing populated payloads with empties.)

---

## CachedApiResponse

**File:** `app/models/cached_api_response.rb`

Generic key/value JSON cache with optional TTL. Used for arbitrary external API responses that don't need their own model.

### Columns

| Column | Type | Notes |
|---|---|---|
| `key` | string, NOT NULL, unique |  |
| `payload` | jsonb, NOT NULL, default `{}` |  |
| `expires_at` | datetime |  |

### Class Methods

- **`fetch(key, ttl: nil)`** — `ttl=nil` means permanent cache (no expiry check); otherwise compares `updated_at` to `ttl.ago`. Note: the `expires_at` column is also written on `store` but `fetch` uses `updated_at + ttl`, not `expires_at`.
- **`store(key, payload, ttl: nil)`** — writes `expires_at = Time.current + ttl` (or nil). Retries 3x on `RecordNotUnique`.
- **`delete_key(key)`**
- **`cleanup_expired`** — bulk deletes rows where `expires_at < now`.

---

## Team

**File:** `app/models/team.rb`

### Columns (notable)

| Column | Type | Notes |
|---|---|---|
| `slug` | string, unique | primary lookup key |
| `name` / `long_name` / `abbreviation` / `nickname` | string |  |
| `division` | string | `"d1"`, `"d2"`, `"d3"` |
| `conference` / `conference_seo` | string |  |
| `logo_url` / `athletics_url` | string |  |
| `rank` | int |  |
| `rpi` / `rpi_unweighted` | decimal(6,4) | indexed on `rpi` |
| `rpi_wins` / `rpi_losses` | int |  |
| `wmt_school_id` | int |  |
| `roster_updated_at` | datetime |  |

### Associations

- `has_many :players, dependent: :destroy`
- `has_many :coaches, dependent: :destroy`
- `has_many :follows, dependent: :destroy`
- `has_many :followers, through: :follows, source: :user`
- `has_one :team_pitching_stat, dependent: :destroy`

### Validations

- `presence` + `uniqueness`: `slug`
- `presence`: `name`

### Scopes

- `displayable` — `where(division: DISPLAYABLE_DIVISIONS)` where `DISPLAYABLE_DIVISIONS = %w[d1 d2]`. Used by every browse/list/search/sitemap surface so opponent-only rows (D3, NAIA, nil division) are hidden. **Do not** apply to slug-resolution lookups (`Team.find`, `Team.where(slug: ...)`, association reads) — opponent teams must still render on a D1/D2 team's schedule and on the scoreboard so W/L counts and score cards are correct.
- `by_division(division)`, `by_conference(conference)`, `search(query)` (ILIKE on name/long_name/slug/abbreviation/nickname), `ranked`

### Visibility rule (added 2026-05-01, mondok/riseballs#181)

Teams outside `DISPLAYABLE_DIVISIONS` exist as foreign keys for boxscores / PBP / TeamGame rows but must never surface in browse UI. Currently scoped through `displayable`:

- `Api::TeamsController#index` — `/api/teams` (every tab, including "All").
- `Api::TeamsController#conferences` — `/api/conferences` (so dropdowns don't list conferences whose only members are opponent-only schools).
- `SitemapsController#show` — `/sitemap.xml` (so opponent-only team pages aren't crawled/indexed).

Division-gated controllers (`rankings`, `rpi`, `stats`, `analytics`) already require an explicit `d1` or `d2` param from the frontend and are intentionally **not** scoped through `displayable`; if they ever start accepting a `d3` param they'd need it.

#### Actual data shape (verified 2026-05-01 against prod)

Hidden rows are stored as `division IS NULL`, **not** as the strings `'d3'` / `'naia'` / `'juco'`. Production at deploy time:

| Bucket | Count |
|---|---|
| `Team.count` | 834 |
| `Team.displayable.count` (`d1`+`d2`) | 594 |
| `Team.where(division: nil).count` | 240 |
| `Team.where.not(division: %w[d1 d2]).count` | 0 |

`where.not(division: %w[...])` excludes NULL by default, which is why that final count is 0. The `displayable` scope (`division IN ('d1','d2')`) excludes NULL correctly. If the Java scraper or a future ingest path starts populating `division` with `'d3'`, `'naia'`, etc. for opponent-only rows, those rows will continue to be hidden by the same scope — no doc/code change needed. Don't write fix-up code that assumes hidden teams have a non-null division string.

### Instance Methods

- `logo_url` — falls back to `#{NCAA_LOGO_BASE}/#{slug}.svg` (NCAA's CDN) when the column is blank (`team.rb:13`).

---

## TeamAlias

**File:** `app/models/team_alias.rb`

Maps arbitrary alias strings (e.g. older naming, typos from scraped feeds) to a canonical `team_slug`. `alias_name` is globally unique.

### Associations / Validations

- `belongs_to :team, foreign_key: :team_slug, primary_key: :slug, optional: true`
- `presence`: `team_slug`, `alias_name`
- `uniqueness`: `alias_name`

---

## TeamPitchingStat

**File:** `app/models/team_pitching_stat.rb`

Thin record with aggregated team pitching totals. `belongs_to :team`; no validations.

---

## Player

**File:** `app/models/player.rb`

### Columns (notable)

Standard roster fields plus scraped batting/pitching totals (`batting_average`, `era`, `hits`, `rbis`, etc. — mostly string-typed because they come from HTML).

- `slug` — unique, `null: true` on create, populated by `after_create :generate_slug`.
- `first_name`, `previous_school`, `is_transfer`, `twitter_url`, `instagram_url`, `high_school`, `hometown`, `height`, `photo_url`, `profile_url`.

### Associations

- `belongs_to :team`
- `has_many :player_favorites, dependent: :destroy`

### Validations

- `presence`: `name`
- `uniqueness`: `slug` (allow_nil)

### Callbacks

- `before_validation :decode_html_entities_in_name` — CGI-unescape (scraped HTML entities).
- `after_create :generate_slug` — writes `slug` via `update_column` (skips validations/callbacks).
- `before_update :regenerate_slug, if: :name_changed?` — keeps slug in sync.

### Instance Methods

- `to_param` → `slug` — enables `/players/:slug` friendly URLs (see `project_player_slugs` in memory).
- `build_slug` (private) — `"#{name.parameterize}-#{id}"`, truncated to 255 chars total.

### Cross-references

- [05-routes.md](05-routes.md) for the `/players/:slug` friendly routes.
- [../pipelines/05-roster-pipeline.md](../pipelines/05-roster-pipeline.md) — how Java scraper augments player bios (update-only).

---

## PlayerGameStat

**File:** `app/models/player_game_stat.rb`

Per-player, per-game batting + pitching line. One row per `(ncaa_game_id, team_seo_slug, player_name)`. Heavy analytical scopes live here.

### Key Columns (37 total — only highlights)

Identity: `ncaa_game_id`, `player_name`, `first_name`, `last_name`, `jersey_number`, `position`, `team_name`, `team_seo_slug`, `opponent_name`, `opponent_seo_slug`, `is_home`, `division`, `game_date`, `game_state`, `starter`, `data_source`, `game_id` (FK, cascade).

Batting: `at_bats`, `hits`, `runs_scored`, `runs_batted_in`, `walks`, `strikeouts`, `doubles`, `triples`, `home_runs`, `stolen_bases`, `hit_by_pitch`, `sacrifice_flies`, `sacrifice_bunts`, `caught_stealing`, `fielding_errors`, `has_batting`.

Pitching: `innings_pitched` (decimal 4,1), `pitch_hits_allowed`, `pitch_runs_allowed`, `pitch_earned_runs`, `pitch_walks`, `pitch_strikeouts`, `pitch_home_runs_allowed`, `pitch_hit_by_pitch`, `batters_faced`, `pitch_count`, `strikes`, `wild_pitches`, `decision`, `has_pitching`.

### Indexes

- Unique `idx_pgs_game_team_player` on `(ncaa_game_id, team_seo_slug, player_name)` — natural key.
- `idx_pgs_team_date` on `(team_seo_slug, game_date)`.
- `idx_pgs_player_team` on `(player_name, team_seo_slug)`.
- Single-column on `division`, `game_date`, `game_id`, `last_name`, `opponent_seo_slug`, `team_seo_slug`, `ncaa_game_id`.

### Associations / Validations

- `belongs_to :game, optional: true`
- `presence`: `ncaa_game_id`, `player_name`
- `uniqueness`: `ncaa_game_id` scoped to `(team_seo_slug, player_name)`

### Scopes

- `batters`, `pitchers`, `starters`
- `division(div)`, `for_team(slug)`, `against(slug)`
- `since(date)`, `before(date)`, `between(from, to)`, `last_n_days(n)`
- `final_games` — `where(game_state: %w[final F])`

### Class Methods (analytical)

All defined inside `class << self` at `player_game_stat.rb:23`:

- **`hitters_with_min_hits(min_hits)`** — GROUP BY player/team, HAVING SUM(hits) >= N, selects batting totals + avg.
- **`hitters_with_hits_against(opponent_slug)`** — same shape, filtered by `opponent_seo_slug`.
- **`hot_hitters(min_hits:, days:)`** — ranked by batting avg over the last N days.
- **`team_batting_leaders(team_slug, order_by: "total_hits")`** — includes OBP and SLG formulas. `BATTING_ORDER_COLUMNS` whitelist (`player_game_stat.rb:80`) protects against SQL-injection in the order column.
- **`team_pitching_leaders(team_slug)`** — ERA and WHIP computed, ordered by ERA ASC.

All aggregate methods use `Arel.sql(...)` for ORDER BY to satisfy Rails' unsafe-string protection.

---

## PlayerWarValue

**File:** `app/models/player_war_value.rb`

Pre-computed player WAR / wOBA / FIP rollups scoped to division or conference per season. Populated by a batch job; queried by the `/war` leaderboard (gated behind `users.can_view_war`).

### Columns

| Column | Type | Notes |
|---|---|---|
| `player_name`, `team_seo_slug`, `season` | string/int, NOT NULL |  |
| `scope_type` | string | `"division"` or `"conference"` |
| `scope_value` | string | e.g. `"d1"` or a conference seo |
| `batting_war`, `pitching_war`, `war` | decimal(6,3), default 0.0 |  |
| `pa` | int, default 0 |  |
| `woba`, `wraa` | decimal |  |
| `ip_total`, `fip` | decimal |  |

Unique `idx_war_player_scope_season` on `(player_name, team_seo_slug, scope_type, scope_value, season)`.

### Validations / Scopes

- `presence`: `player_name`, `team_seo_slug`, `scope_type`, `scope_value`, `season`
- `scope_type` in `%w[division conference]`
- Scopes: `for_season`, `division_scope(division)`, `conference_scope(conference)`, `by_team(slug)`, `by_player(name, slug)`

---

## PlayerFavorite

**File:** `app/models/player_favorite.rb`

Join table: users ↔ players they've favorited.

- `belongs_to :user`, `belongs_to :player`
- Uniqueness: `user_id` scoped to `player_id` (message: `"already favorited this player"`)

---

## Coach

**File:** `app/models/coach.rb`

Team coaching staff. `belongs_to :team`. `presence: name`. No other logic. Columns: `name`, `title`, `email`, `phone`, `photo_url`, `profile_url`, `twitter_url`, `instagram_url`.

---

## PlateAppearance

**File:** `app/models/plate_appearance.rb`

PBP-derived plate appearance. One row per PA. Keyed canonically by `game_id` (FK to `games.id`); the partial unique index `idx_pa_canonical_unique` on `(game_id, team_slug, batter_name, inning, half, pa_number_in_game)` enforces one row per physical at-bat per team. The Java scraper sets `game_id` after the canonical `Game` is reconciled.

### Columns (27)

Identity: `team_slug`, `game_id`, `game_date`, `opponent`, `is_home`, `inning`, `half`, `outs_before`, `pa_number_in_game`.

Batter/Pitcher: `batter_name`, `pitcher_name`, `team_batting`.

Pitches: `pitch_sequence`, `balls`, `strikes`, `pitches_seen`, `first_pitch`, `first_pitch_result`.

Result: `result`, `result_category`, `hit_type`, `hit_location`, `play_description`, `rbis` (default 0), `runners_scored`.

### Constants

- `SWING_CODES = %w[S F X T L M]`
- `TAKE_CODES = %w[B K H]`

### Validations

- `presence`: `team_slug`, `batter_name`, `result`, `inning`, `half`
- `numericality`: `inning > 0`

### Scopes

- `for_team`, `for_game` (matches by `game_id`), `for_batter`
- `team_batting`, `team_pitching`
- `with_pitches`, `first_pitch_take`, `first_pitch_swing`
- `hits`, `outs`, `walks`, `strikeouts` (LIKE 'strikeout%'), `home_runs`
- `in_inning(n)`, `with_outs(n)`, `since(date)`

### Instance Methods

- `first_pitch_was_strike?` — `first_pitch.present? && first_pitch != "B"`

---

## PitchEvent

**File:** `app/models/pitch_event.rb`

PBP-derived base-running and ancillary events that happen between or within PAs: steals, caught stealing, wild pitches, passed balls, pickoffs, errors, sac bunts, etc. Keyed canonically by `game_id` (FK to `games.id`); the partial unique index `idx_pe_canonical_unique` enforces one row per physical event per team.

### Columns

Identity + position: `team_slug`, `game_id`, `game_date`, `inning`, `half`, `after_pa_number`.

Event: `event_type`, `player_name`, `from_base`, `to_base`, `team_event`, `play_description`.

### Validations

- `presence`: `team_slug`, `event_type`, `inning`, `half`
- `numericality`: `inning > 0`

### Scopes

- `for_team`, `for_game`
- `steals`, `caught_stealing`, `wild_pitches`, `passed_balls`
- `team_events`, `opponent_events`

---

## ConferenceSource

**File:** `app/models/conference_source.rb`

Configured URL + parser combination per conference per season. Drives the standings scraper.

### Columns

| Column | Type | Notes |
|---|---|---|
| `season` / `division` / `conference` | NOT NULL | unique composite |
| `standings_url` | string, NOT NULL |  |
| `parser_type` | string, default `"sidearm"`, NOT NULL |  |
| `active` | bool, default true, NOT NULL |  |
| `last_scraped_at` / `last_scrape_status` |  | updated after each run |
| `tournament_spots` / `tournament_format` |  | postseason metadata |

Unique `(season, division, conference)`.

### Associations / Scopes / Validations

- `has_many :standings_scrape_logs, dependent: :destroy`
- `division` must be `%w[d1 d2]`; `conference` unique scoped to `(season, division)`
- Scopes: `active`, `by_season`, `by_division`

---

## ConferenceStanding

**File:** `app/models/conference_standing.rb`

Scraped standings row. One record per team per season per conference.

### Columns (notable)

`season`, `division`, `conference`, `team_name`, `team_slug`, `conf_wins`, `conf_losses`, `overall_wins`, `overall_losses`, `conf_win_pct`, `overall_win_pct`, `streak`, `conf_rank`, `metadata` (jsonb), `scraped_at`.

Unique `(season, conference, team_name)`.

### Associations / Validations / Scopes

- `belongs_to :team, primary_key: :slug, foreign_key: :team_slug, optional: true`
- `division` in `%w[d1 d2]`; `team_name` unique scoped to `(season, conference)`
- Scopes: `by_season`, `by_division`, `by_conference`, `ranked` (ORDER BY conf_win_pct DESC NULLS LAST, overall_win_pct DESC NULLS LAST)

### Cross-references

- [../pipelines/04-standings-pipeline.md](../pipelines/04-standings-pipeline.md)
- [10-scenario-service.md](10-scenario-service.md) — clinch/elim math + bracket builder
- [../reference/conference-tournaments.md](../reference/conference-tournaments.md)

---

## StandingsScrapeLog

**File:** `app/models/standings_scrape_log.rb`

Append-only raw HTML + diagnostics blob per standings scrape attempt. `belongs_to :conference_source`. No validations in the model (enforced at DB level).

Columns: `conference_source_id` (FK), `season`, `conference`, `raw_html`, `parsed_count`, `error_message`, `diagnostics` (jsonb), `scraped_at`.

---

## ScrapedPage

**File:** `app/models/scraped_page.rb`

Cached raw HTML for team-owned pages (rosters, etc.). Keyed on `(url, page_type)` unique.

### Associations / Validations / Scopes

- `belongs_to :team`
- `presence`: `url`, `page_type`; `uniqueness`: `url` scoped to `page_type`
- `scope :rosters, -> { where(page_type: "roster") }`

---

## BatchJob

**File:** `app/models/batch_job.rb`

State machine for the OpenAI batch pipeline (scrape → submit → process → complete). Used by the nightly box-score harvest.

### Constants

- `STATUSES = %w[pending scraping submitted processing completed failed]`

### Columns (notable)

`job_type`, `status`, `openai_batch_id`, `openai_file_id`, `output_file_id`, `total_requests`, `completed_requests`, `failed_requests`, `scrape_success`, `scrape_errors`, `current_step`, `error_message`, `metadata` (jsonb), `started_at`, `submitted_at`, `completed_at`.

### Scopes / Validations

- `active` — `status IN (pending, scraping, submitted, processing)`
- `latest` — most recent by `created_at`
- `presence`: `job_type`; `inclusion`: `status`

### Instance Methods (state transitions)

- `log(message)` — `update_column(:current_step)` + Rails logger.
- `fail!(message)` — `status="failed"`, stamps `error_message`.
- `scraping!` — `status="scraping"`, stamps `started_at`.
- `submitted!(openai_batch_id, file_id, total)` — stamps `submitted_at`.
- `processing!` — `status="processing"`.
- `completed!(processed, errors)` — stamps `completed_at`.
- `store_meta(cache_id, data)` / `save_meta!` / `meta_for(cache_id)` — batched jsonb writes (call `save_meta!` periodically to persist).

### Cross-references

- [13-rake-tasks.md](13-rake-tasks.md) `fill_missing_boxscores.rake` — the state machine that drives `BatchJob` lifecycle (scraping → submitted → processing → completed).
- The BatchJob flow is not yet promoted to its own pipeline doc; the state diagram lives in `fill_missing_boxscores.rake:301-506`.

---

## SiteMetric

**File:** `app/models/site_metric.rb`

Key/value store for cached homepage metrics. `key` unique. Data in `data` jsonb. Computed timestamp in `computed_at`. No behavior beyond validations.

---

## User

**File:** `app/models/user.rb`

Devise user with JWT auth (JTIMatcher revocation strategy).

### Columns (notable)

`email` (unique), `encrypted_password`, `reset_password_token` (unique), `reset_password_sent_at`, `remember_created_at`, `jti` (unique, NOT NULL), `admin` (bool, default false), `can_view_war` (bool, default false).

### Devise modules

`:database_authenticatable, :registerable, :recoverable, :rememberable, :validatable, :jwt_authenticatable` (revocation via `self` / JTIMatcher).

### Associations

- `has_many :follows, dependent: :destroy`
- `has_many :followed_teams, through: :follows, source: :team`
- `has_many :player_favorites, dependent: :destroy`
- `has_many :favorite_players, through: :player_favorites, source: :player`

---

## Follow

**File:** `app/models/follow.rb`

Join table: users ↔ teams they follow.

- `belongs_to :user`, `belongs_to :team`
- `uniqueness`: `user_id` scoped to `team_id` (message: `"already following this team"`)

---

## Related docs

- [02-database-schema.md](02-database-schema.md) — column-level schema for every model's table
- [03-entity-relationships.md](03-entity-relationships.md) — cardinality diagrams across these models
- [../pipelines/01-game-pipeline.md](../pipelines/01-game-pipeline.md) — how `Game` / `TeamGame` / `GameTeamLink` get written
- [../pipelines/06-reconciliation-pipeline.md](../pipelines/06-reconciliation-pipeline.md) — detectors that enqueue `GameReview` rows
- [../reference/glossary.md](../reference/glossary.md) — terms like `locked`, `doubleheader`, `data_freshness`
- [../operations/runbook.md](../operations/runbook.md) — operator procedures touching these models
