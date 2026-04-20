# Frontend Pages

One section per page component under `app/javascript/pages/`. Each entry lists the file, the API endpoints it hits, its local state, the URL params it reads, and any conditional UI worth flagging for review.

## Table of contents

- [HomePage](#homepage)
- [Dashboard](#dashboard)
- [Scoreboard](#scoreboard)
- [TeamsIndex](#teamsindex)
- [TeamDetail](#teamdetail)
- [GameDetail](#gamedetail)
- [Rankings](#rankings)
- [Standings](#standings)
- [RPI](#rpi)
- [Stats](#stats)
- [~~LiveView~~ (deleted 2026-04-19)](#liveview--deleted)
- [PlayerSearch](#playersearch)
- [PlayerDetail](#playerdetail)
- [Analytics](#analytics)
- [PitchAnalytics](#pitchanalytics)
- [SignIn / SignUp](#signin--signup)
- [Admin pages (not in SPA)](#admin-pages-not-in-spa)

---

## HomePage

- **File:** `app/javascript/pages/HomePage.jsx` (45 LOC)
- **Route:** `/`
- **API calls:** none directly. Delegates to `<D1Facts />`, which calls `GET /api/facts?division=d1`.
- **State:** reads `useAuth()` only to swap the CTA button (`My Dashboard` vs `Get Started`).
- **Key sub-components:** `<D1Facts />` — stat/leaders block with tooltips.
- **UI:** wordmark, tagline, two CTAs, then the facts block beneath.

## Dashboard

- **File:** `app/javascript/pages/Dashboard.jsx` (311 LOC)
- **Route:** `/dashboard` (wrapped in `<RequireAuth>`)
- **API calls:**
  - `GET /api/dashboard` (`dashboard.index()`) — returns `{ teams, favorite_players, games, schedule }`.
- **State:** `{ data, loading, fetchError, teamFilter }`.
- **Polling:** every 30s **only when** `hasLiveGames` is true (today's schedule has a non-final game). `hasLiveGames` is a `useMemo` over `data.schedule`.
- **Schedule window:** client filters `data.schedule` to the window of [today - 7 days, today + 14 days]. Team filter buttons (one per followed team) narrow further; label "All" clears.
- **Key sub-components:**
  - `<GameCard />` for today's live games.
  - `<FavoritePlayerCard />` for the favorite-players grid.
  - Inline rows for past/upcoming schedule; past and live rows wrap in a `<Link>` to `/games/:id` **only when `game.game_id` is truthy** (mirrors `TeamDetail.jsx` guard, added in issue #94 to prevent `/games/null` links). Upcoming rows and rows with no linked `Game` render as a plain `<div>`.
- **Empty state:** if `teams` is empty (no follows), renders a CTA "Find Teams" pointing to `/teams`.

## Scoreboard

- **File:** `app/javascript/pages/Scoreboard.jsx`
- **Route:** `/scoreboard`
- **URL params** (all synced via `useSearchParams`, defaults stripped from URL):
  - `div` — `"d1"` (default) or `"d2"`
  - `date` — ISO `YYYY-MM-DD` (default today)
  - `q` — free-text search (team name / short / seo)
  - `conf` — conference filter
  - `ranked` — `1` = at least one team ranked
  - `top25` — `1` = both teams ranked (D1 only, mutually exclusive with `ranked`)
  - `live` — `1` = live-only
- **API calls:**
  - `GET /api/scoreboard?division&date` (`scoreboard.index`) — the day's games. Response includes `gameID` (stable `rb_<id>`), `ncaaContestId`, `gameNumber` per game.
  - `GET /api/scoreboard/predictions?division&date` (`scoreboard.predictions`) — parallel; populates a `predictions` map keyed by `gameID`.
  - `GET https://live.riseballs.com/scoreboard?date=` — **cross-origin, not through the `api` axios client**. Called via `lib/liveOverlay.js` with a 4s `AbortController` timeout. Returns `{ date, events[], fetchedAt, source: "fresh"|"cache"|"stale" }`. Silent degradation on error.
- **Polling:**
  - Scoreboard refreshes every 30s when viewing today.
  - Live overlay refreshes on the same 30s cadence in parallel with the Rails fetch.
  - Both stop when navigating away from today.
- **Live overlay match ladder** (`lib/liveOverlay.js`, added mondok/riseballs#83):
  1. Primary: key by `ncaaContestId`.
  2. Fallback: `(homeSlug, awaySlug, gameNumber)` position pairing.
  3. Reversed-slug rescue: if the overlay event has home/away flipped vs Rails, apply the overlay's scores with the swap.
  4. Ambiguity guard: if multiple overlay events match one Rails game, skip the overlay for that game (don't guess).
  5. Final protection: never override a Rails game whose `gameState === "final"`.
  Overlay results merge into a `liveOverlay` map by Rails `gameID`.
- **Sort order:** live -> upcoming -> completed; within a bucket, by `startTimeEpoch` (ascending for live/upcoming, descending for completed). Ranked games break ties.
- **Key sub-components:** `<GameCard />` (receives `liveOverlay[game.gameID]` and `predictions[game.gameID]`).
- **Notable:** filter chip row is conditionally rendered via `showFilters` and also marks "active filters" via a small amber dot on the Filters button. `setDivision` automatically clears `conf` to avoid orphan conference filters when switching divisions.

**What changed 2026-04-19 (mondok/riseballs#83, #85, mondok/riseballs-live#1):** the StatBroadcast / SidearmStats overlay fetcher (the 10s `fetchLiveStats` poller using `liveStats.batch` and `liveStats.sidearmBatch`) was replaced with the single `riseballs-live` call. No more per-game URL probing; the overlay service does reconciliation on its side and returns a unified event list.

## TeamsIndex

- **File:** `app/javascript/pages/TeamsIndex.jsx` (282 LOC)
- **Route:** `/teams`
- **API calls:**
  - `GET /api/teams` (`teams.list({ q, division, conference, ranked, page, per_page: 48 })`)
  - `GET /api/conferences` (`teams.conferences()`) — fills the conference dropdown.
  - `POST /api/teams/:slug/follow` / `DELETE /api/teams/:slug/unfollow` for follow toggles.
- **State:** `{ teams, meta, loading, fetchError, query, division, conference, ranked, page, conferences, showFilters, searchTimeout }`
- **Behaviour:** debounced search (300ms). Filter changes reset page via `fetchTeams({ page: 1 })` but intentionally do not share state via URL params (unlike Scoreboard).
- **Follow button:** hidden for logged-out users (`if (!user) return null`).

## TeamDetail

- **File:** `app/javascript/pages/TeamDetail.jsx` (461 LOC)
- **Route:** `/teams/:slug`
- **URL params:** `:slug` plus search param `tab` (`schedule` default, or `roster`).
- **API calls:**
  - `GET /api/teams/:slug` (`teams.show`) — team + players + coaches
  - `GET /api/teams/:slug/schedule` (`teams.schedule`) — returns `{ record, games }`
  - `GET /api/scoreboard/predictions?game_ids=...&pairs=...` — only for upcoming games; see below.
  - `POST /api/teams/:slug/follow` / `DELETE /api/teams/:slug/unfollow`
  - `GET /api/players/:slug` — fetched per-player when exporting the team roster PDF.
- **Prediction fetch for schedule rows (critical):** Two paths because some schedule rows don't yet have a `game_id` (scraper hasn't linked them yet):
  - Rows with `game_id` contribute to `game_ids=rb_<id>,rb_<id>`.
  - Orphan rows (no `game_id`, but have `opponent_seo`) contribute to `pairs=<home>:<away>:<iso>` where home/away is flipped based on `game.is_home`.
  - The response map is keyed either as `rb_<id>` or `pair_<home>_<away>_<iso>`. The `predictionFor` helper checks both.
  - Failures are silently swallowed; rows just render without the win-prob chip.
- **Tabs:**
  - **Schedule & Results** — splits `allGames` into `upcomingGames` (state != final, ascending date) and `completedGames` (state == final, descending date). Each row renders `<GameRow />`. Completed rows are wrapped in `<Link to="/games/:game_id">` only when `game.game_id` is present; rows without it render plain text (to avoid broken links — see the `opponent_seo` null-safety note in GameRow).
  - **Roster** — `<RosterBattingTable />` + `<RosterPitchingTable />` with independent sort state. Pitchers filter: any of `era`, `wins > 0`, `losses > 0`, `innings_pitched > 0`, `strikeouts_pitching > 0`, `saves > 0`, `earned_runs_pitching > 0`, `runs_allowed_pitching > 0`. Export toolbar: `Batting`, `Pitching`, `All Players` CSVs plus `PDF Roster` (per-player fetch loop with progress string).
- **Back button:** reads `location.state.fromLabel` (set by whichever page linked here); falls back to "Back to Teams".

## GameDetail

- **File:** `app/javascript/pages/GameDetail.jsx` (the largest page in the app)
- **Route:** `/games/:id`
- **URL params:** `:id` (internal Riseballs game id — historical NCAA contest ids still resolve via `Game.find_by_any_id`, but the canonical outbound form is `rb_<id>`).
- **API calls:**
  - `GET /api/games/:id` (`games.show`) — NCAA contest header.
  - `GET /api/games/:id/boxscore` (`games.boxscore`) — prefetched alongside `show`.
  - `GET /api/games/:id/play_by_play` (`games.playByPlay`) — eager prefetch to decide whether to show the PBP tab. Final games get one retry after 20s on failure.
  - `GET /api/games/:id/prediction` (`games.prediction`) — returns 200 with a body for pregame, **204** for games that have been played, and errors (e.g. 503 from the predict service) map to the catch path. Panel silently hides in all non-200 cases.
- **State:** `{ gameInfo, fetchError, tabData, activeTab, loading, tabLoading, predictionData }` plus refs (`boxscorePrefetching`, `isFinalRef`). No more `liveData` / `liveIntervalRef` — the StatBroadcast + SidearmStats poller was removed.
- **Polling:**
  - `games.show` every 30s when the game isn't final.
  - Active tab refreshes silently every 30s during live games (no loading flash).
  - When `isLive`, boxscore + PBP both poll every 30s to keep the `<DiamondView />` accurate.

**What changed 2026-04-19 (mondok/riseballs#85):** the 10s StatBroadcast + SidearmStats poller is gone. The `DiamondView` still updates because live boxscore + PBP poll on 30s cadence and `parseSituation` is computed from PBP. GameDetail does NOT consume the `riseballs-live` overlay — live scores on individual game pages come from the boxscore's linescore sum and the PBP tail, not the overlay. The overlay is a scoreboard-only concern.
- **Tabs:**
  - **Box Score** (`<BoxScore />`) — always present.
  - **Play-by-Play** (`<PlayByPlay />`) — suppressed if `tabData.play_by_play._error` or has no `periods`. Also suppressed pre-fetch for final games (don't show the tab until we know there's data).
  - **Team Stats** (`<TeamStats />`) — computed client-side from the boxscore; no separate fetch.
- **Prediction panel:** Renders `<GamePrediction />` between the header/DiamondView and the tabs. Passes `homeName`, `awayName`, `prediction`, `keysToVictory`. Silently omitted when `predictionData` is null (covers the 204-on-played / 503-on-down cases).
- **Back button:** `location.state.fromLabel` (often "Back to Box Score" from team pages) -> "Back to Scoreboard" default. If `location.key === "default"` (page loaded directly) it navigates to `/scoreboard` instead of `navigate(-1)`.
- **Live diamond view:** When live, parses the PBP tail into a baserunner/outs/at-bat situation via `parseSituation(pbp, gameInfo)` (exported from `DiamondView.jsx`). Defensive lineup is derived by `getDefensiveLineup(boxscore, fieldingTeamId)`.
- **Score fallback ladder (GameHeader):** `liveData.home_score` -> `home.score` -> sum of per-inning linescores (computed client-side, excluding R/H/E rows) -> `rhe.R.home` -> `""`.

## Rankings

- **File:** `app/javascript/pages/Rankings.jsx` (113 LOC) — child of `/rankings`
- **API calls:** `GET /api/rankings?division` (`rankings.index`).
- **State:** `{ division, data, loading }`.
- **Render:** generic table built from the first row's keys (minus `SLUG`). Region/group rows (where `REGION/RANK` is set but `SCHOOL` is blank) get rendered as amber full-width header rows. Team cells become `<Link to="/teams/:slug">` when the row carries a `SLUG`.

## Standings

- **File:** `app/javascript/pages/Standings.jsx` (455 LOC) — child of `/rankings/standings`
- **API calls:** `GET /api/standings?division[&conference]` (`standings.index`).
  - First request (no conference) returns `conferences: []`. The page auto-selects the first one.
  - Second request fetches the actual standings for that conference.
- **State:** `{ division, conference, conferences, data, loading }`.
- **Data shape:**
  - `data.standings` — rows with `{ team_slug, team_name, logo_url, conf_rank, conf_record, conf_win_pct, games_back, overall_record, overall_win_pct, streak }`.
  - `data.scenarios` — `{ available, reason?, tournament_spots, teams: [{ team_slug, team_name, clinch_indicator, title_status, title_summary, tournament_status }], bracket }`.
  - `data.last_updated` — ISO timestamp.
- **Clinch indicators:** `<ClinchIndicator />` renders a small inline prefix next to the team name — `x-` (green, clinched #1 seed), `y-` (blue, clinched tournament berth), `e-` (red, eliminated). Driven by `scenarioMap[team_slug]?.clinch_indicator`.
- **Scenarios section:** `<ScenarioSection />`
  - If `scenarios.available === false` with a `reason`, renders a greyed "Scenarios unavailable: <reason>" line.
  - Otherwise shows two cards:
    - **Title Race** — clinched (green) + contenders + an "Eliminated: ..." summary line.
    - **Tournament (Top N)** — `Clinched:` and `Eliminated:` summaries.
- **Bracket section:** `<BracketSection />` — "Bracket as of Today" at the bottom of the page, driven by `scenarios.bracket`.
  - If `bracket.format === "none"`: renders "No conference tournament — regular season champion receives automatic qualifier."
  - If no bracket at all: renders nothing.
  - Otherwise renders a horizontally scrollable SVG-connector bracket. Details in `17-frontend-components.md`.
- **Sort stability:** the `standings` rows come pre-sorted from the server (`conf_rank` is authoritative).

## RPI

- **File:** `app/javascript/pages/RPI.jsx` (270 LOC)
- **Route:** `/rpi` (auth-required via `<RequireAuth>`; also hidden from nav unless email is the admin email).
- **API calls:**
  - `GET /api/rpi?division` (`rpi.index`).
  - `POST /api/admin/recalculate_rpi` (raw axios; admin only) — drops a recalc job.
- **State:** `{ division, weighted, data, loading, error, sortCol, sortDir, recalculating }`.
- **Columns:** sort on any numeric column (rpi, wp, owp, oowp, sos, etc.) or by name/conference. `weighted` toggles between `rpi` and `rpi_unweighted`.
- **Admin controls:** Recalculate button only visible if `user.email === "matt.mondok@gmail.com"`.

## Stats

- **File:** `app/javascript/pages/Stats.jsx` (393 LOC)
- **Route:** `/stats`
- **API calls:**
  - `GET /api/stats` (`stats.index`) — category leaders.
  - `GET /api/analytics/war` (`analytics.war`) — when WAR type is selected.
- **State:** `{ division, type, category, stat, conference, warScope, warType, page, data, loading }`.
- **Behaviour:** flipping `category` (batting/pitching) auto-picks the first stat in the corresponding list. WAR leaderboard is gated on `user?.can_view_war`.

## LiveView — **DELETED**

**File:** `app/javascript/pages/LiveView.jsx` — **removed** 2026-04-19 (mondok/riseballs#85 part 1). The `/live` route is gone from `App.jsx`, the "Live" nav entry is gone from `Layout.jsx`, and `localStorage.riseballs_live_view` is no longer written (old values linger in users' browsers but nothing reads them).

Rationale: the StatBroadcast + SidearmStats feeds the page consumed are flaky and require per-game feed URL resolution. The replacement is the `riseballs-live` overlay on `/scoreboard`, which pulls reconciled NCAA + ESPN data in one call with server-side caching and slug resolution. Users that want a "watch multiple live games at once" view use the scoreboard filtered by `?live=1`.

## PlayerSearch

- **File:** `app/javascript/pages/PlayerSearch.jsx` (231 LOC)
- **Route:** `/players`
- **API calls:** `GET /api/players?q&position&division&page&per_page=50` (`players.list`).
- **State:** `{ players, meta, loading, query, position, division, page, searchTimeout, hasSearched }`
- **Behaviour:** no results shown until the user actually types / filters (`hasSearched` guard). Debounce 400ms.

## PlayerDetail

- **File:** `app/javascript/pages/PlayerDetail.jsx` (729 LOC)
- **Route:** `/players/:slug`
- **API calls:**
  - `GET /api/players/:slug` (`players.show`) — returns the full player including `game_log`, `splits`, `war`, `team`, `photo_url`, `favorited`.
  - `POST /api/players/:slug/favorite` / `DELETE` via `<FavoritePlayerButton>`.
  - `GET /api/players/:slug/spray_chart` (via the embedded `<SprayChart />` component) when the player has batting stats.
- **State:** `{ player, loading, exporting }` + a ref for the PDF export target.
- **Render tree:**
  1. Header card: photo, number, name, favorite button, position, year, team link, hometown/height, transfer badge, socials, "Full Bio" link, CSV/PDF export buttons.
  2. **Season Batting** grid (conditional on `hasBatting`).
  3. `<SprayChart />` (conditional on `hasBatting`).
  4. **Season Pitching** grid (conditional on `hasPitching`; includes NP = pitch count).
  5. **WAR** block (conditional on `player.war`) — renders once per scope type (division / conference).
  6. `<PlayerCharts />` — Recharts:
     - *Rolling Batting Average (5-game)* — LineChart with season avg reference line (`<ReferenceLine />`).
     - *Hits per Game* — ComposedChart (Bar hits + cumulative avg line).
     - *Rolling ERA (3-game)* — LineChart with season ERA reference line.
     - *K & BB per Game* — BarChart (K green, BB red).
     - **Pitch Count per Game** — ComposedChart with two Y-axes: left axis = `np` Bar (per-game pitch count), right axis = `cumNp` Line (cumulative season total). Driven by `computePitchCounts(gameLog)`.
  7. `<PlayerSplits />` — Home/Away, Last 7/14/30 day rows for batting and pitching, plus a "vs Conference" breakdown when available.
  8. **Game Log** table with per-game links to `/games/:game_id` and opponent links to `/teams/:opponent_slug` (null-safe).

## Analytics

- **File:** `app/javascript/pages/Analytics.jsx` (303 LOC)
- **Route:** `/analytics` (auth-required)
- **API calls:** `GET /api/analytics/leaderboard` (`analytics.leaderboard({ type, division, sort, page, per_page, conference?, min_ab?, min_ip? })`).
- **State:** `{ division, type, conference, minAb, minIp, sort, page, data, loading, sortDir }`
- **Columns:** static definitions at module scope (`BATTING_COLS`, `PITCHING_COLS`), each marked `sortable` or not, with `hideOnMobile` flags.

## PitchAnalytics

- **File:** `app/javascript/pages/PitchAnalytics.jsx` (426 LOC)
- **Route:** `/pitch-analytics/:slug`. Not in the nav — deep-linked from other pages.
- **API calls:** `GET /api/pitch_analytics/:team_slug` (`pitchAnalytics.show(slug)`).
- **State:** `{ data, loading, error }` plus a ref for PDF export.
- **Render:** a series of `<Section>`s (team overview, pitcher-by-pitcher breakdowns) built from generic `<Stat>` tiles and `<Table>` rows. HTML-escapes values before writing to `document.write` for the print view (XSS guard).

## SignIn / SignUp

- **Files:** `app/javascript/pages/SignIn.jsx` (83 LOC), `app/javascript/pages/SignUp.jsx` (97 LOC)
- **Routes:** `/sign-in`, `/sign-up`
- **API calls:** via `useAuth().signIn / signUp`, which hit `POST /auth/sign_in` and `POST /auth/sign_up`.
- **Behaviour:** local `{ email, password, [passwordConfirmation], error, loading }`. On success, `navigate("/")`. Errors render inline from `err.response?.data?.error` / `errors`.
- **Note:** neither page respects `location.state.returnTo` set by `<RequireAuth>`. After sign-in, users land on `/`, not on the protected page they were trying to reach. (Known gap; flag for the caller.)

## Admin pages (not in SPA)

`/admin/boxscores`, `/admin/reviews`, `/admin/jobs`, `/admin/tools`, and `/sidekiq` are **Rails-rendered views**, not React. They live under `app/views/admin/` and `app/controllers/admin/`, with routes declared in the `namespace :admin do ... end` block of `config/routes.rb`. They are explicitly excluded from the React catch-all via the `constraints: ->(req) { !req.path.start_with?("/admin", ...) }` filter.

Auth pages (`/auth/sign_in`, `/auth/sign_up`, `/auth/sign_out`) are handled by Devise controllers (`auth/sessions`, `auth/registrations`) and invoked by the React client purely as JSON endpoints.

---

## Related docs

- [15-frontend-overview.md](15-frontend-overview.md) — routing, auth, and API client setup
- [17-frontend-components.md](17-frontend-components.md) — components used across these pages
- [04-api-endpoints.md](04-api-endpoints.md) — JSON endpoint contracts these pages consume
- [../pipelines/07-prediction-pipeline.md](../pipelines/07-prediction-pipeline.md) — GameDetail prediction panel source
- [../architecture/02-data-flow.md](../architecture/02-data-flow.md) — full data journey from scraper to UI
