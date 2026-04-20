# Rails Routes Reference

Complete route table, as defined in `config/routes.rb`. Routes below are grouped by namespace; ordering within a group matches `routes.rb` order.

**Deleted 2026-04-19 (mondok/riseballs#85):** the four `/api/live_stats/*` routes and the `/live` SPA catch-all entry — StatBroadcast / SidearmStats live-stats machinery was removed in favor of the `riseballs-live` overlay at `live.riseballs.com`. The ex-routes were:

- `GET /api/live_stats/batch`
- `GET /api/live_stats/boxscore_batch`
- `POST /api/live_stats/sidearm_batch`
- `POST /api/live_stats/resolve`
- The `/live` nav entry (still caught by the SPA `/*path` glob since `/live` isn't in the exclusion list, but the React component behind it was deleted — navigating there now renders the default 404-ish "nothing" SPA state).

Source of truth: `/Users/mattmondok/Code/riseballs-parent/riseballs/config/routes.rb`.

## Table of Contents

- [Root / Catch-all](#root--catch-all)
- [Sidekiq Web UI](#sidekiq-web-ui)
- [Admin Namespace](#admin-namespace)
- [Devise / Auth](#devise--auth)
- [API Namespace](#api-namespace)
- [OG Image Endpoints](#og-image-endpoints)
- [Health Check](#health-check)
- [Route Guards & Constraints](#route-guards--constraints)

---

## Root / Catch-all

| Verb | Path | Controller#Action | As-name |
|------|------|-------------------|---------|
| GET  | `/` | `pages#index` | `root` |
| GET  | `/*path` | `pages#index` | (none) |

The `/*path` glob is constrained: only matches when `req.path` does NOT start with `/api`, `/auth`, `/rails`, `/sidekiq`, or `/admin`. This makes `PagesController#index` the SPA shell for every frontend route (teams, players, rankings, etc.).

---

## Sidekiq Web UI

| Verb | Path | Mounted | Auth |
|------|------|---------|------|
| ANY  | `/sidekiq` | `Sidekiq::Web` | HTTP Basic via `Rack::Auth::Basic` (admin user only) |

Authentication block (`routes.rb:5-8`):

```ruby
user = User.find_by(email: email)
user&.valid_password?(password) && user.admin?
```

---

## Admin Namespace

Prefix: `/admin/*`. All admin controllers subclass `ActionController::Base` (NOT `ApplicationController`) and enforce HTTP Basic auth. Two of them gate on `user.admin?`; `JobsController` gates on a hard-coded email (`matt.mondok@gmail.com`).

| Verb  | Path | Controller#Action | As-name |
|-------|------|-------------------|---------|
| GET   | `/admin/boxscores` | `admin/boxscores#index` | `admin_boxscores` |
| PATCH | `/admin/boxscores/:id/update_url` | `admin/boxscores#update_url` | `update_url_admin_boxscore` |
| POST  | `/admin/boxscores/:id/reprocess` | `admin/boxscores#reprocess` | `reprocess_admin_boxscore` |
| GET   | `/admin/reviews` | `admin/reviews#index` | `admin_reviews` |
| POST  | `/admin/reviews/clear` | `admin/reviews#clear` | `clear_admin_reviews` |
| POST  | `/admin/reviews/clear_sidekiq` | `admin/reviews#clear_sidekiq` | `clear_sidekiq_admin_reviews` |
| POST  | `/admin/reviews/:id/approve` | `admin/reviews#approve` | `approve_admin_review` |
| POST  | `/admin/reviews/:id/dismiss` | `admin/reviews#dismiss` | `dismiss_admin_review` |
| POST  | `/admin/recalculate_rpi` | `admin/tools#recalculate_rpi` | (none) |
| GET   | `/admin/jobs` | `admin/jobs#index` | (implicit via `resources`-free declaration) |
| POST  | `/admin/jobs/enqueue` | `admin/jobs#enqueue` | `enqueue_jobs` |

---

## Devise / Auth

Mounted via `devise_for :users` at `routes.rb:33-39` with custom path segments and custom controllers.

| Verb   | Path | Controller#Action | Purpose |
|--------|------|-------------------|---------|
| GET    | `/auth/sign_in` | `auth/sessions#new` | login form (SPA doesn't use) |
| POST   | `/auth/sign_in` | `auth/sessions#create` | JSON login |
| DELETE | `/auth/sign_out` | `auth/sessions#destroy` | JSON logout |
| GET    | `/auth/sign_up` | `auth/registrations#new` | signup form (SPA doesn't use) |
| POST   | `/auth/sign_up` | `auth/registrations#create` | JSON signup |
| GET    | `/auth/edit` | `auth/registrations#edit` | edit profile form |
| PATCH  | `/auth` | `auth/registrations#update` | update profile |
| PUT    | `/auth` | `auth/registrations#update` | update profile |
| DELETE | `/auth` | `auth/registrations#destroy` | delete account |
| GET    | `/auth/password/new` | `devise/passwords#new` | request reset |
| POST   | `/auth/password` | `devise/passwords#create` | send reset |
| GET    | `/auth/password/edit` | `devise/passwords#edit` | reset form |
| PATCH  | `/auth/password` | `devise/passwords#update` | apply reset |

The auth controllers override `respond_with` / `respond_to_on_destroy` to return JSON with a `user` payload and `can_view_war` flag.

---

## API Namespace

Prefix: `/api/*`. All API controllers subclass `Api::BaseController` (except `Api::PitchAnalyticsController`, which subclasses `ApplicationController`). CSRF is disabled via `skip_before_action :verify_authenticity_token`.

### Teams

Route block: `routes.rb:42-48`. Param key is `:slug`, not `:id`.

| Verb   | Path | Controller#Action | As-name |
|--------|------|-------------------|---------|
| GET    | `/api/teams` | `api/teams#index` | `api_teams` |
| GET    | `/api/teams/:slug` | `api/teams#show` | `api_team` |
| POST   | `/api/teams/:slug/follow` | `api/teams#follow` | `follow_api_team` |
| DELETE | `/api/teams/:slug/unfollow` | `api/teams#unfollow` | `unfollow_api_team` |
| GET    | `/api/teams/:slug/schedule` | `api/teams#schedule` | `schedule_api_team` |
| GET    | `/api/conferences` | `api/teams#conferences` | `api_conferences` |

### Games

Route block: `routes.rb:52-62`. Param key is `:id` (accepts internal id, `rb_<id>`, or raw NCAA contest id — resolved by `GameShowService.resolve_game_id`).

| Verb | Path | Controller#Action | As-name |
|------|------|-------------------|---------|
| GET  | `/api/games/:id` | `api/games#show` | `api_game` |
| GET  | `/api/games/batch` | `api/games#batch` | `batch_api_games` |
| GET  | `/api/games/:id/boxscore` | `api/games#boxscore` | `boxscore_api_game` |
| GET  | `/api/games/:id/play_by_play` | `api/games#play_by_play` | `play_by_play_api_game` |
| GET  | `/api/games/:id/team_stats` | `api/games#team_stats` | `team_stats_api_game` |
| GET  | `/api/games/:id/prediction` | `api/predictions#show` | `prediction_api_game` |

### Players

Route block: `routes.rb:64-70`. Param key is `:slug` (controller accepts bare numeric id as fallback).

| Verb   | Path | Controller#Action | As-name |
|--------|------|-------------------|---------|
| GET    | `/api/players` | `api/players#index` | `api_players` |
| GET    | `/api/players/:slug` | `api/players#show` | `api_player` |
| GET    | `/api/players/:slug/spray_chart` | `api/players#spray_chart` | `spray_chart_api_player` |
| POST   | `/api/players/:slug/favorite` | `api/players#favorite` | `favorite_api_player` |
| DELETE | `/api/players/:slug/unfavorite` | `api/players#unfavorite` | `unfavorite_api_player` |

### Top-level API GETs / POSTs

| Verb | Path | Controller#Action |
|------|------|-------------------|
| GET  | `/api/dashboard` | `api/dashboard#index` |
| GET  | `/api/scoreboard` | `api/scoreboard#index` |
| GET  | `/api/scoreboard/predictions` | `api/predictions#scoreboard` |
| GET  | `/api/rankings` | `api/rankings#index` |
| GET  | `/api/stats` | `api/stats#index` |
| GET  | `/api/rpi` | `api/rpi#index` |
| GET  | `/api/standings` | `api/standings#index` |
| POST | `/api/admin/recalculate_rpi` | `api/admin#recalculate_rpi` |
| GET  | `/api/analytics/leaderboard` | `api/analytics#leaderboard` |
| GET  | `/api/analytics/war` | `api/analytics#war_leaderboard` |
| GET  | `/api/pitch_analytics/:team_slug` | `api/pitch_analytics#show` |
| GET  | `/api/facts` | `api/facts#index` |
| GET  | `/api/status` | `api/status#index` |

---

## OG Image Endpoints

Defined at `routes.rb:90-91`. Redirect-only; returns a `302` to a CDN image URL (or `/og-image.png` fallback).

| Verb | Path | Controller#Action | As-name |
|------|------|-------------------|---------|
| GET  | `/og/players/:slug` | `og_images#player` | `og_player_image` |
| GET  | `/og/teams/:slug` | `og_images#team` | `og_team_image` |

---

## Health Check

| Verb | Path | Controller#Action | As-name |
|------|------|-------------------|---------|
| GET  | `/up` | `rails/health#show` | `rails_health_check` |

Provided by Rails 8's built-in health check controller.

---

## Route Guards & Constraints

- **SPA catch-all exclusion list:** `/api`, `/auth`, `/rails`, `/sidekiq`, `/admin` (defined via lambda constraint at `routes.rb:96`). Any request path starting with one of these five prefixes bypasses `PagesController#index` and is handed to the namespaced controller.
- **Sidekiq basic auth:** enforced at mount time via `Rack::Auth::Basic` closure, rejecting non-admins.
- **Admin basic auth:** enforced in each admin controller's own `before_action :authenticate_admin!` / `authenticate_owner!` (NOT via routes).
- **Browser gate:** `ApplicationController` calls `allow_browser versions: :modern, block: :reject_unsupported_browser`. `reject_unsupported_browser` renders `public/406-unsupported-browser.html` with status 406, UNLESS the User-Agent matches a link-preview bot regex (bot, crawl, spider, externalhit, facebot, whatsapp, telegram, slack, discord, preview, cfnetwork, linkedin, curl, wget).

---

## Related docs

- [04-api-endpoints.md](04-api-endpoints.md) — per-action contracts for every route listed here
- [12-jobs.md](12-jobs.md) — Sidekiq jobs behind the `/sidekiq` mount
- [../architecture/01-service-boundaries.md](../architecture/01-service-boundaries.md) — which routes belong to Rails vs other services
- [../operations/runbook.md](../operations/runbook.md) — operator recipes invoking `/admin/*` endpoints
- [../operations/deployment.md](../operations/deployment.md) — how routes get exposed on Dokku + Cloudflare
