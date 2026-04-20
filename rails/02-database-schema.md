# Database Schema Reference

Table-by-table reference built from `riseballs/db/schema.rb` (Rails 8.0, Postgres). Extensions: `pg_catalog.plpgsql`.

**Schema changes since 2026-04-18:** migration from mondok/riseballs#85 part 2 (2026-04-19) dropped 7 columns and 3 indexes across `games` and `game_team_links`. See the "What was dropped" callouts below and the sections linked from each table.

All paths below are relative to `riseballs/` unless absolute. Foreign keys are listed under each table; a consolidated list is in the last section.

## Table of Contents

- [Games & Scheduling](#games--scheduling)
  - [games](#games)
  - [team_games](#team_games)
  - [game_team_links](#game_team_links)
  - [game_identifiers](#game_identifiers)
  - [game_snapshots](#game_snapshots)
- [Stats](#stats)
  - [player_game_stats](#player_game_stats)
  - [player_war_values](#player_war_values)
  - [plate_appearances](#plate_appearances)
  - [pitch_events](#pitch_events)
  - [team_pitching_stats](#team_pitching_stats)
- [Roster & Teams](#roster--teams)
  - [teams](#teams)
  - [team_aliases](#team_aliases)
  - [players](#players)
  - [coaches](#coaches)
- [Caching & Scraping](#caching--scraping)
  - [cached_games](#cached_games)
  - [cached_schedules](#cached_schedules)
  - [cached_api_responses](#cached_api_responses)
  - [scraped_pages](#scraped_pages)
  - [batch_jobs](#batch_jobs)
  - [solid_cache_entries](#solid_cache_entries)
  - [site_metrics](#site_metrics)
- [Standings](#standings)
  - [conference_sources](#conference_sources)
  - [conference_standings](#conference_standings)
  - [standings_scrape_logs](#standings_scrape_logs)
- [Auth / Users](#auth--users)
  - [users](#users)
  - [follows](#follows)
  - [player_favorites](#player_favorites)
- [Audit / Review](#audit--review)
  - [game_reviews](#game_reviews)
- [Consolidated Foreign Keys](#consolidated-foreign-keys)

---

## Games & Scheduling

### `games`

Canonical record — one row per game, shared across both teams. See `app/models/game.rb`.

| Column | Type | Nullable | Default | Notes |
|---|---|---|---|---|
| `id` | bigserial PK |  |  |  |
| `game_date` | date | NOT NULL |  | indexed |
| `home_team_slug` | string |  |  | references `teams.slug` |
| `away_team_slug` | string |  |  | references `teams.slug` |
| `home_team_name` | string |  |  |  |
| `away_team_name` | string |  |  |  |
| `game_number` | int |  | 1 | doubleheader index |
| `division` | string |  |  | `d1`/`d2`/`d3` |
| `state` | string |  | `"scheduled"` | one of `scheduled/live/final/postponed/cancelled` |
| `home_score` | int |  |  |  |
| `away_score` | int |  |  |  |
| `current_period` | string |  |  |  |
| `final_message` | string |  |  |  |
| `start_time` | string |  |  |  |
| `start_time_epoch` | bigint |  |  |  |
| `ncaa_game_id` | string |  |  | legacy key |
| `discovery_source` | string |  |  |  |
| `data_freshness` | string |  | `"unknown"` | `ncaa_corrected` / `reconciled` freeze date-updates |
| `locked` | bool |  | false |  |
| `metadata` | jsonb |  | `{}` |  |
| `ncaa_contest_id` | bigint |  |  | primary NCAA key (new) |
| `home_box_score_id` | string |  |  |  |
| `away_box_score_id` | string |  |  |  |
| `created_at` / `updated_at` | datetime | NOT NULL |  |  |

Total column count: **25**.

**Indexes**

- `idx_games_natural_key` — **UNIQUE** `(game_date, home_team_slug, away_team_slug, game_number)`. The doubleheader-safe natural key.
- `idx_games_home_boxscore` — UNIQUE `(home_team_slug, home_box_score_id)` WHERE `home_box_score_id IS NOT NULL`
- `idx_games_away_boxscore` — UNIQUE `(away_team_slug, away_box_score_id)` WHERE `away_box_score_id IS NOT NULL`
- `index_games_on_ncaa_contest_id` — UNIQUE WHERE NOT NULL
- `index_games_on_ncaa_game_id` — UNIQUE WHERE NOT NULL
- `index_games_on_away_team_slug`, `index_games_on_home_team_slug`
- `index_games_on_game_date`, `index_games_on_game_date_and_division`, `index_games_on_game_date_and_state`
- `index_games_on_state`, `index_games_on_state_and_locked`

**What was dropped 2026-04-19 (mondok/riseballs#85 part 2):**

- Columns: `live_stats_url`, `live_stats_feed_url`, `sb_event_id`, `sidearm_game_id`
- Indexes: `index_games_on_sb_event_id` (UNIQUE), `index_games_on_sidearm_game_id` (UNIQUE)

These were populated by the StatBroadcast/SidearmStats live-stats machinery deleted in mondok/riseballs#85 part 1. The public game id is now `games.id` surfaced as `rb_<id>` via `Game#url_id`; `ncaa_contest_id` is the authoritative external key.

No DB-level FK to `teams` — the slug-based references are application-only, enforced by `Game#team_slugs_must_exist` (D1 only).

---

### `team_games`

Per-team view of a game. Two rows per game (one per team).

| Column | Type | Nullable | Default | Notes |
|---|---|---|---|---|
| `id` | bigserial PK |  |  |  |
| `team_slug` | string | NOT NULL |  |  |
| `game_date` | date | NOT NULL |  |  |
| `game_number` | int | NOT NULL | 1 | **critical for doubleheaders** |
| `opponent_name` | string |  |  |  |
| `opponent_slug` | string |  |  |  |
| `is_home` | bool |  |  |  |
| `team_score` | int |  |  |  |
| `opponent_score` | int |  |  |  |
| `state` | string |  | `"scheduled"` |  |
| `boxscore_id` | string |  |  |  |
| `boxscore_url` | string |  |  |  |
| `source` | string |  |  |  |
| `game_id` | bigint |  |  | FK → `games.id` |
| `created_at` / `updated_at` | datetime | NOT NULL |  |  |

**Indexes**

- `idx_team_games_schedule` — **UNIQUE** `(team_slug, game_date, opponent_slug, game_number)`. This is the doubleheader-handling unique constraint. Without the `game_number` tail, both games of a doubleheader would collapse into one row.
- `idx_team_games_boxscore` — UNIQUE `(team_slug, boxscore_id)` WHERE `boxscore_id IS NOT NULL`
- `index_team_games_on_team_slug_and_game_date`
- `index_team_games_on_opponent_slug`
- `index_team_games_on_game_id`

**Foreign keys:** `team_games.game_id → games.id` (no cascade specified; default RESTRICT).

---

### `game_team_links`

Per-team URLs / external IDs attached to a canonical `Game`.

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | bigserial PK |  |  |
| `game_id` | bigint | NOT NULL | FK → `games.id`, ON DELETE CASCADE |
| `team_slug` | string | NOT NULL |  |
| `sidearm_game_id` | string |  | actively used by the Java scraper for box-score URL discovery (~23,733 rows populated as of 2026-04-19); **retained** |
| `box_score_url` | string |  |  |
| `created_at` / `updated_at` | datetime | NOT NULL |  |

Total column count: **7**.

**Indexes**

- `index_game_team_links_on_game_id_and_team_slug` — UNIQUE. One link per team per game.
- `idx_game_team_links_team_sidearm` — UNIQUE `(team_slug, sidearm_game_id)` WHERE `sidearm_game_id IS NOT NULL`
- `index_game_team_links_on_game_id`

**What was dropped 2026-04-19 (mondok/riseballs#85 part 2):**

- Columns: `live_stats_url`, `live_stats_feed_url`, `sb_event_id`
- Index: `index_game_team_links_on_sb_event_id` (partial, WHERE NOT NULL)

Matching JPA mappings removed from the Java `GameTeamLink` entity in riseballs-scraper PR #12.

---

### `game_identifiers`

Maps `(team_slug, sidearm_id) → game_id`. Used by `Game.find_or_create_from_schedule` to prevent duplicate game creation.

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | bigserial PK |  |  |
| `game_id` | bigint | NOT NULL | FK → `games.id`, ON DELETE CASCADE |
| `team_slug` | string | NOT NULL |  |
| `sidearm_id` | string | NOT NULL |  |
| `created_at` / `updated_at` | datetime | NOT NULL |  |

**Indexes**

- `index_game_identifiers_on_team_slug_and_sidearm_id` — UNIQUE
- `index_game_identifiers_on_game_id`
- `index_game_identifiers_on_sidearm_id`

---

### `game_snapshots`

Append-only point-in-time snapshots of live game state.

| Column | Type | Nullable | Default | Notes |
|---|---|---|---|---|
| `id` | bigserial PK |  |  |  |
| `ncaa_game_id` | string | NOT NULL |  |  |
| `game_state` | string |  |  |  |
| `current_period` | string |  |  |  |
| `home_score` | int |  | 0 |  |
| `away_score` | int |  | 0 |  |
| `linescore` | jsonb |  |  |  |
| `batting_summary` | jsonb |  |  |  |
| `pitching_summary` | jsonb |  |  |  |
| `data_source` | string |  |  |  |
| `game_id` | bigint |  |  | FK → `games.id`, ON DELETE CASCADE |
| `created_at` / `updated_at` | datetime | NOT NULL |  |  |

**Indexes**

- `idx_snapshots_game_time` — `(ncaa_game_id, created_at)` — for time-ordered scans.
- `index_game_snapshots_on_ncaa_game_id`
- `index_game_snapshots_on_game_id`

---

## Stats

### `player_game_stats`

Per-player, per-game batting + pitching line. Natural key: `(ncaa_game_id, team_seo_slug, player_name)`.

Columns (49 total) grouped:

- **Identity:** `ncaa_game_id` (NOT NULL), `player_name` (NOT NULL), `first_name`, `last_name`, `jersey_number`, `position`, `team_name`, `team_seo_slug`, `opponent_name`, `opponent_seo_slug`, `is_home` (default false), `division`, `game_date`, `game_state`, `starter` (default false), `data_source`, `game_id` (FK → `games.id`, CASCADE).
- **Batting:** `at_bats`, `hits`, `runs_scored`, `runs_batted_in`, `walks`, `strikeouts`, `doubles`, `triples`, `home_runs`, `stolen_bases`, `hit_by_pitch`, `sacrifice_flies`, `sacrifice_bunts`, `caught_stealing`, `fielding_errors`, `has_batting` (default false). All ints default 0 except the last two booleans/nullables.
- **Pitching:** `innings_pitched` (decimal 4,1 default 0.0), `pitch_hits_allowed`, `pitch_runs_allowed`, `pitch_earned_runs`, `pitch_walks`, `pitch_strikeouts`, `pitch_home_runs_allowed`, `pitch_hit_by_pitch`, `batters_faced`, `pitch_count`, `strikes`, `wild_pitches`, `decision` (string), `has_pitching` (default false).

**Indexes**

- `idx_pgs_game_team_player` — **UNIQUE** `(ncaa_game_id, team_seo_slug, player_name)`
- `idx_pgs_team_date` `(team_seo_slug, game_date)`
- `idx_pgs_player_team` `(player_name, team_seo_slug)`
- Singletons: `division`, `game_date`, `game_id`, `last_name`, `opponent_seo_slug`, `team_seo_slug`, `ncaa_game_id`

**FK:** `player_game_stats.game_id → games.id`, ON DELETE CASCADE.

---

### `player_war_values`

Pre-computed player WAR/wOBA/FIP per `(player, team, scope, season)`.

| Column | Type | Nullable | Default | Notes |
|---|---|---|---|---|
| `player_name` | string | NOT NULL |  |  |
| `team_seo_slug` | string | NOT NULL |  |  |
| `scope_type` | string | NOT NULL |  | `"division"` / `"conference"` |
| `scope_value` | string | NOT NULL |  |  |
| `season` | int | NOT NULL |  |  |
| `batting_war` | decimal(6,3) |  | 0.0 |  |
| `pitching_war` | decimal(6,3) |  | 0.0 |  |
| `war` | decimal(6,3) |  | 0.0 |  |
| `pa` | int |  | 0 |  |
| `woba` | decimal(5,3) |  |  |  |
| `wraa` | decimal(6,3) |  |  |  |
| `ip_total` | decimal(5,1) |  |  |  |
| `fip` | decimal(5,2) |  |  |  |

**Indexes**

- `idx_war_player_scope_season` — UNIQUE `(player_name, team_seo_slug, scope_type, scope_value, season)`
- `idx_on_scope_type_scope_value_season_54c5aa3642` `(scope_type, scope_value, season)`
- `index_player_war_values_on_team_seo_slug`

---

### `plate_appearances`

PBP-derived plate appearance rows.

Columns (28): `team_slug` (NOT NULL), `game_source_id` (NOT NULL, string — not an FK), `game_date`, `opponent`, `is_home`, `inning` (NOT NULL), `half` (NOT NULL), `outs_before`, `batter_name` (NOT NULL), `pitcher_name`, `team_batting`, `pitch_sequence`, `balls`, `strikes`, `pitches_seen`, `first_pitch`, `first_pitch_result`, `result` (NOT NULL), `result_category`, `hit_location`, `play_description`, `rbis` (default 0), `runners_scored`, `pa_number_in_game`, `hit_type`.

**Indexes**

- `index_plate_appearances_on_team_slug_and_game_source_id`
- `index_plate_appearances_on_team_slug_and_game_date`
- `index_plate_appearances_on_team_slug_and_batter_name`
- `index_plate_appearances_on_team_slug_and_first_pitch_result`
- `index_plate_appearances_on_game_source_id`
- `index_plate_appearances_on_hit_type`

No unique index (PAs repeat; a game generates many per batter).

---

### `pitch_events`

PBP-derived base-running / wild-pitch / passed-ball / pickoff events.

Columns (13): `team_slug` (NOT NULL), `game_source_id` (NOT NULL), `game_date`, `inning` (NOT NULL), `half` (NOT NULL), `event_type` (NOT NULL), `player_name`, `from_base`, `to_base`, `team_event`, `play_description`, `after_pa_number`.

**Indexes**

- `index_pitch_events_on_team_slug_and_event_type`
- `index_pitch_events_on_team_slug_and_game_date`
- `index_pitch_events_on_team_slug_and_game_source_id`

---

### `team_pitching_stats`

Aggregated per-team pitching totals. `team_id` FK → `teams.id`.

Columns: `team_id` (NOT NULL), `innings_pitched` (string), `hits_allowed`, `runs_allowed`, `earned_runs`, `walks_allowed`, `strikeouts`, `batters_faced`.

**Indexes:** `index_team_pitching_stats_on_team_id`.

---

## Roster & Teams

### `teams`

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | bigserial PK |  |  |
| `slug` | string |  | unique |
| `name` | string |  |  |
| `long_name` | string |  |  |
| `division` | string |  |  |
| `conference` | string |  |  |
| `conference_seo` | string |  |  |
| `logo_url` | string |  |  |
| `athletics_url` | string |  |  |
| `rank` | int |  |  |
| `roster_updated_at` | datetime |  |  |
| `abbreviation` | string |  |  |
| `nickname` | string |  |  |
| `rpi` | decimal(6,4) |  | indexed |
| `rpi_unweighted` | decimal(6,4) |  |  |
| `rpi_wins` | int |  |  |
| `rpi_losses` | int |  |  |
| `wmt_school_id` | int |  |  |

**Indexes**

- `index_teams_on_slug` — UNIQUE
- `index_teams_on_rpi`

No `NOT NULL` on `slug` at the DB level — the model enforces it. `teams.slug` is referenced by string from `games`, `team_games`, `conference_standings`, `team_aliases`, etc.

---

### `team_aliases`

Maps alternate naming strings to `team_slug`.

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `team_slug` | string | NOT NULL |  |
| `alias_name` | string | NOT NULL | unique |

**Indexes**

- `index_team_aliases_on_alias_name` — UNIQUE
- `index_team_aliases_on_team_slug`

---

### `players`

Roster entry for a team.

Columns: `name`, `number`, `position`, `year`, `team_id` (NOT NULL), `photo_url`, `profile_url`, `hometown`, `height`, scraped batting/pitching totals (`batting_average`, `on_base_percentage`, `at_bats`, `runs`, `hits`, `rbis`, `walks`, `strikeouts`, `doubles`, `triples`, `home_runs`, `wins`, `losses`, `era`, `appearances`, `innings_pitched`, `strikeouts_pitching`, `saves`, `runs_allowed_pitching`, `earned_runs_pitching`), `first_name`, `previous_school`, `is_transfer` (default false), `twitter_url`, `instagram_url`, `high_school`, `slug`.

**Indexes**

- `index_players_on_slug` — UNIQUE
- `index_players_on_team_id`

**FK:** `players.team_id → teams.id`.

---

### `coaches`

Columns: `team_id` (NOT NULL), `name`, `title`, `email`, `photo_url`, `profile_url`, `phone`, `twitter_url`, `instagram_url`.

**Index:** `index_coaches_on_team_id`.

**FK:** `coaches.team_id → teams.id`.

---

## Caching & Scraping

### `cached_games`

Polymorphic cache for per-game payloads (NCAA game detail, box score, PBP, team stats, StatBroadcast pitcher data, Athletic.net variants).

| Column | Type | Nullable | Default | Notes |
|---|---|---|---|---|
| `ncaa_game_id` | string | NOT NULL |  |  |
| `data_type` | string | NOT NULL |  | one of 7 `DATA_TYPES` |
| `game_state` | string |  |  |  |
| `payload` | jsonb | NOT NULL | `{}` |  |
| `locked` | bool | NOT NULL | false |  |
| `game_id` | bigint |  |  | FK → `games.id`, ON DELETE CASCADE |
| `team_slug` | string |  |  | only set for team-scoped box scores |

**Indexes (composite key logic)**

- `index_cached_games_on_ncaa_game_id_and_data_type` — UNIQUE `(ncaa_game_id, data_type)`. Legacy dedupe by external id.
- `index_cached_games_on_game_id_and_data_type` — UNIQUE `(game_id, data_type)` WHERE `game_id IS NOT NULL`. Primary FK-based dedupe.
- `idx_cached_games_team` — UNIQUE `(game_id, data_type, team_slug)` WHERE `team_slug IS NOT NULL`. Allows both teams' `athl_boxscore` rows to coexist for the same game.
- `index_cached_games_on_game_id`, `index_cached_games_on_ncaa_game_id`, `index_cached_games_on_game_state`
- `index_cached_games_on_locked` — WHERE `locked = true` (partial)

All three unique indexes work together: one row per `(ncaa_game_id, data_type)` in the legacy keyspace, one per `(game_id, data_type)` in the new keyspace, plus team-scoped fanout for box scores.

---

### `cached_schedules`

Per-team schedule JSON blob. Unique on `team_slug`.

| Column | Type | Nullable | Default | Notes |
|---|---|---|---|---|
| `team_slug` | string | NOT NULL |  | unique |
| `payload` | jsonb | NOT NULL | `{}` |  |

**Index:** `index_cached_schedules_on_team_slug` — UNIQUE.

---

### `cached_api_responses`

Generic key/value JSON cache.

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `key` | string | NOT NULL | unique |
| `payload` | jsonb | NOT NULL, default `{}` |  |
| `expires_at` | datetime |  | cleanup target |

**Indexes**

- `index_cached_api_responses_on_key` — UNIQUE
- `index_cached_api_responses_on_expires_at`

---

### `scraped_pages`

Raw HTML cache for team-owned pages (rosters, etc).

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `team_id` | bigint | NOT NULL | FK → `teams.id` |
| `url` | string | NOT NULL |  |
| `page_type` | string | NOT NULL |  |
| `html` | text |  |  |
| `scraped_at` | datetime |  |  |

**Indexes**

- `index_scraped_pages_on_url_and_page_type` — UNIQUE
- `index_scraped_pages_on_team_id`

---

### `batch_jobs`

State machine for the OpenAI batch pipeline.

Columns: `job_type` (NOT NULL), `status` (NOT NULL default `"pending"`), `openai_batch_id`, `openai_file_id`, `output_file_id`, `total_requests` (default 0), `completed_requests` (default 0), `failed_requests` (default 0), `scrape_success` (default 0), `scrape_errors` (default 0), `current_step` (text), `error_message` (text), `metadata` (jsonb default `{}`), `started_at`, `submitted_at`, `completed_at`.

**Indexes**

- `index_batch_jobs_on_openai_batch_id`
- `index_batch_jobs_on_status`

---

### `solid_cache_entries`

Rails Solid Cache backing store — managed by the framework, not by app code.

Columns: `key` (binary, NOT NULL), `value` (binary, NOT NULL), `created_at`, `key_hash` (bigint, NOT NULL), `byte_size` (int, NOT NULL).

**Indexes**

- `index_solid_cache_entries_on_key_hash` — UNIQUE
- `index_solid_cache_entries_on_key_hash_and_byte_size`
- `index_solid_cache_entries_on_byte_size`

---

### `site_metrics`

Key/value store for homepage/aggregate metrics.

Columns: `key` (NOT NULL, unique), `data` (jsonb NOT NULL default `{}`), `computed_at`.

**Index:** `index_site_metrics_on_key` — UNIQUE.

---

## Standings

### `conference_sources`

Configured standings URL + parser per `(season, division, conference)`.

| Column | Type | Nullable | Default | Notes |
|---|---|---|---|---|
| `season` | int | NOT NULL |  |  |
| `division` | string | NOT NULL |  | `d1` / `d2` |
| `conference` | string | NOT NULL |  |  |
| `standings_url` | string | NOT NULL |  |  |
| `parser_type` | string | NOT NULL | `"sidearm"` |  |
| `active` | bool | NOT NULL | true |  |
| `last_scraped_at` | datetime |  |  |  |
| `last_scrape_status` | string |  |  |  |
| `tournament_spots` | int |  |  |  |
| `tournament_format` | string |  |  |  |

**Indexes**

- `index_conference_sources_on_season_and_division_and_conference` — UNIQUE
- `index_conference_sources_on_season_and_active`

---

### `conference_standings`

Scraped standings rows.

Columns: `season` (NOT NULL), `division` (NOT NULL), `conference` (NOT NULL), `team_name` (NOT NULL), `team_slug`, `conf_wins` (NOT NULL default 0), `conf_losses` (NOT NULL default 0), `overall_wins` (NOT NULL default 0), `overall_losses` (NOT NULL default 0), `conf_win_pct` (decimal 5,3), `overall_win_pct` (decimal 5,3), `streak`, `conf_rank`, `metadata` (jsonb NOT NULL default `{}`), `scraped_at`.

**Indexes**

- `idx_on_season_conference_team_name_d2997dc01c` — UNIQUE `(season, conference, team_name)`
- `index_conference_standings_on_season_and_division`
- `index_conference_standings_on_team_slug`

---

### `standings_scrape_logs`

Append-only diagnostic log per scrape attempt.

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `conference_source_id` | bigint | NOT NULL | FK → `conference_sources.id` |
| `season` | int | NOT NULL |  |
| `conference` | string | NOT NULL |  |
| `raw_html` | text |  |  |
| `parsed_count` | int | NOT NULL default 0 |  |
| `error_message` | text |  |  |
| `diagnostics` | jsonb |  |  |
| `scraped_at` | datetime | NOT NULL |  |
| `created_at` | datetime | NOT NULL |  |

Note: this table has only `created_at`, no `updated_at`.

**Index:** `index_standings_scrape_logs_on_conference_source_id`.

---

## Auth / Users

### `users`

Devise-JWT-authenticated user.

| Column | Type | Nullable | Default | Notes |
|---|---|---|---|---|
| `email` | string | NOT NULL | `""` | unique |
| `encrypted_password` | string | NOT NULL | `""` |  |
| `reset_password_token` | string |  |  | unique |
| `reset_password_sent_at` | datetime |  |  |  |
| `remember_created_at` | datetime |  |  |  |
| `jti` | string | NOT NULL |  | unique — JWT revocation id |
| `admin` | bool | NOT NULL | false |  |
| `can_view_war` | bool | NOT NULL | false |  |

**Indexes**

- `index_users_on_email` — UNIQUE
- `index_users_on_jti` — UNIQUE
- `index_users_on_reset_password_token` — UNIQUE

---

### `follows`

Join: users ↔ teams.

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `user_id` | bigint | NOT NULL | FK → `users.id` |
| `team_id` | bigint | NOT NULL | FK → `teams.id` |

**Indexes**

- `index_follows_on_user_id_and_team_id` — UNIQUE
- `index_follows_on_user_id`
- `index_follows_on_team_id`

---

### `player_favorites`

Join: users ↔ players.

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `user_id` | bigint | NOT NULL | FK → `users.id` |
| `player_id` | bigint | NOT NULL | FK → `players.id` |

**Indexes**

- `index_player_favorites_on_user_id_and_player_id` — UNIQUE
- `index_player_favorites_on_user_id`
- `index_player_favorites_on_player_id`

---

## Audit / Review

### `game_reviews`

Admin review queue. Proposed changes live in `proposed_changes` jsonb and are applied on `GameReview#approve!`.

| Column | Type | Nullable | Default | Notes |
|---|---|---|---|---|
| `game_id` | bigint | NOT NULL |  | FK → `games.id`, ON DELETE CASCADE |
| `review_type` | string | NOT NULL |  | one of 9 `REVIEW_TYPES` |
| `reason` | text | NOT NULL |  |  |
| `proposed_changes` | jsonb |  | `{}` |  |
| `source` | string | NOT NULL |  |  |
| `status` | string | NOT NULL | `"pending"` | `pending`/`approved`/`dismissed` |
| `resolved_at` | datetime |  |  |  |

**Indexes**

- `index_game_reviews_on_game_id`
- `index_game_reviews_on_game_id_and_status`
- `index_game_reviews_on_review_type`
- `index_game_reviews_on_status`

---

## Consolidated Foreign Keys

From `schema.rb:571-586`:

| Child Table | Column | Parent Table | On Delete |
|---|---|---|---|
| `cached_games` | `game_id` | `games` | CASCADE |
| `coaches` | `team_id` | `teams` | (default RESTRICT) |
| `follows` | `team_id` | `teams` | (default) |
| `follows` | `user_id` | `users` | (default) |
| `game_identifiers` | `game_id` | `games` | CASCADE |
| `game_reviews` | `game_id` | `games` | CASCADE |
| `game_snapshots` | `game_id` | `games` | CASCADE |
| `game_team_links` | `game_id` | `games` | CASCADE |
| `player_favorites` | `player_id` | `players` | (default) |
| `player_favorites` | `user_id` | `users` | (default) |
| `player_game_stats` | `game_id` | `games` | CASCADE |
| `players` | `team_id` | `teams` | (default) |
| `scraped_pages` | `team_id` | `teams` | (default) |
| `standings_scrape_logs` | `conference_source_id` | `conference_sources` | (default) |
| `team_games` | `game_id` | `games` | (default — note: NOT cascade) |
| `team_pitching_stats` | `team_id` | `teams` | (default) |

**Notable:** `team_games.game_id` is NOT a cascading delete — deleting a `Game` will fail if any `team_games` still reference it. Contrast with `cached_games`, `game_identifiers`, `game_reviews`, `game_snapshots`, `game_team_links`, and `player_game_stats`, which all cascade.

Slug-based "soft foreign keys" (application-level, not DB-enforced):

- `games.home_team_slug` / `games.away_team_slug` → `teams.slug`
- `team_games.team_slug`, `team_games.opponent_slug` → `teams.slug`
- `game_team_links.team_slug`, `game_identifiers.team_slug` → `teams.slug`
- `cached_games.team_slug`, `cached_schedules.team_slug` → `teams.slug`
- `team_aliases.team_slug` → `teams.slug`
- `conference_standings.team_slug` → `teams.slug`
- `player_game_stats.team_seo_slug` / `opponent_seo_slug` → `teams.slug`
- `player_war_values.team_seo_slug` → `teams.slug`
- `plate_appearances.team_slug`, `pitch_events.team_slug` → `teams.slug`

---

## Related docs

- [01-models.md](01-models.md) — ActiveRecord models that back these tables
- [03-entity-relationships.md](03-entity-relationships.md) — ER diagram + cardinality for these tables
- [../operations/database-access.md](../operations/database-access.md) — how to connect and query the Postgres DB
- [../reference/slug-and-alias-resolution.md](../reference/slug-and-alias-resolution.md) — slug-based soft foreign keys explained
- [../pipelines/01-game-pipeline.md](../pipelines/01-game-pipeline.md) — writes to `games` / `team_games` / `game_team_links`
- [../pipelines/02-pbp-pipeline.md](../pipelines/02-pbp-pipeline.md) — writes to `plate_appearances` / `pitch_events`
