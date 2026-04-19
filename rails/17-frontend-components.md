# Frontend Components

Reusable React components under `app/javascript/components/`. Most pages are thin glue around these; the real logic tends to live here.

## Table of contents

- [Layout chrome](#layout-chrome)
  - [Layout](#layout)
  - [RankingsLayout](#rankingslayout)
  - [ErrorBoundary](#errorboundary)
  - [RequireAuth](#requireauth)
- [Game tiles and rows](#game-tiles-and-rows)
  - [GameCard](#gamecard)
  - [GameRow](#gamerow)
- [Prediction and bracket](#prediction-and-bracket)
  - [GamePrediction](#gameprediction)
  - [BracketSection](#bracketsection-standingsjsx)
- [Live game widgets](#live-game-widgets)
  - [DiamondView](#diamondview)
- [Player widgets](#player-widgets)
  - [FavoritePlayerButton](#favoriteplayerbutton)
  - [FavoritePlayerCard](#favoriteplayercard)
  - [SprayChart](#spraychart)
  - [PlayerPdfPage](#playerpdfpage)
- [Team roster tables](#team-roster-tables)
- [Content blocks](#content-blocks)
  - [D1Facts](#d1facts)
- [Charts](#charts)
- [Loading and error UX](#loading-and-error-ux)

---

## Layout chrome

### Layout

- **File:** `app/javascript/components/Layout.jsx` (167 LOC)
- **Role:** Top-level shell for every route. Renders the sticky header, nav, theme toggle, mobile menu, and `<Outlet />`.
- **Nav configuration:** `NAV_ITEMS` array at module scope. Each entry: `{ path, label, icon, authRequired?, adminOnly? }`.
- **Admin filter:** `adminOnly` items only render when `user?.email === ADMIN_EMAIL` (hardcoded string `"matt.mondok@gmail.com"`). Currently only the RPI link uses this — call out if adding more.
- **Theme:** `dark` is persisted to `localStorage.theme` and toggles the `dark` class on `<html>`. Tailwind 4's `darkMode` is implicitly class-based through this toggle.
- **Mobile menu:** auto-closes on route change via an effect on `location.pathname`.
- **Layout container:** main content is capped at `max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6`.

### RankingsLayout

- **File:** `app/javascript/components/RankingsLayout.jsx` (46 LOC)
- **Role:** Nested layout under `/rankings`. Renders a Poll/Standings tab bar and an `<Outlet />` for the active child route.
- **Tab activation:** Poll is matched with exact path equality; Standings matches any path starting with `/rankings/standings`.

### ErrorBoundary

- **File:** `app/javascript/components/ErrorBoundary.jsx` (47 LOC)
- **Role:** Class-component error boundary wrapped around the entire `<App />`.
- **Behaviour:** `getDerivedStateFromError` flips `hasError`; `componentDidCatch` only `console.error`s. No Sentry / external reporting. The reset button triggers a full `window.location.reload()` (not just clearing state).

### RequireAuth

- **File:** `app/javascript/components/RequireAuth.jsx` (21 LOC)
- **Role:** Route guard. Returns `null` while auth is loading, redirects to `/sign-in` with `state={{ returnTo: location.pathname }}` when there is no user, otherwise renders `children`.
- **Caveat:** the `returnTo` state is set but the Sign In page currently ignores it and always navigates to `/` on success. Deliberate gap flagged in `16-frontend-pages.md`.

## Game tiles and rows

### GameCard

- **File:** `app/javascript/components/GameCard.jsx` (275 LOC)
- **Used by:** `Scoreboard`, `Dashboard` (today's games block).
- **Props:** `game`, `fromLabel?`, `liveOverlay?`, `prediction?`.
- **Role:** Clickable tile that links to `/games/:internalId`. Renders:
  - State badge (`LIVE` pulsing with red accent, `Final`, `In Progress`, `Upcoming`).
  - `Live Stats` external link (opens in new tab) and a "Live View" button that stuffs the game into `localStorage.riseballs_live_view` and routes to `/live`.
  - Two team rows with logo, optional rank (`#N`), name, and score.
  - Optional `Gm N` doubleheader badge and `Delayed` freshness badge.
  - Prediction bar (`<PredictionBar />`) — only rendered when the game is pre-game and a `prediction` prop is supplied (keys: `home_pct`, `away_pct`).
- **Live overlay rules:** The component re-implements the same score/state logic as GameDetail's header:
  - `hasLive` — `liveOverlay.has_started` or `home_score != null`.
  - `liveCompleted` — SB says completed, or NCAA says final, or scores exist with no active inning.
  - `isLive` — `hasLive && !liveCompleted`.
  - Winner highlight falls back to `live` scores when `liveCompleted`.
- **Fallback:** `scoreFromLinescores(linescores, isHome)` sums per-inning NCAA linescores when no other score is available. Returns `null` if nothing to sum.
- **Score unavailable:** If the game is final but no score from any source, shows a tiny italic "Score unavailable" line.

### GameRow

- **File:** `app/javascript/components/team/GameRow.jsx` (138 LOC)
- **Used by:** `TeamDetail` (schedule rows), indirectly by `Dashboard` (inline variant) and `PlayerDetail` game log (no — that's its own table).
- **Props:** `game`, `teamName`, `linked?`, `prediction?`.
- **Rendering:**
  - Left column: date; if upcoming, also the formatted time. If live, the current period pulses red.
  - Middle: `vs` / `@` prefix and opponent name.
  - Right: either the final result pill (`W` green, `L` red, `T` yellow) + score; or `LIVE` badge + current score + Live Stats link; or the scheduled start time + optional prediction chip + Live Stats link.
- **Opponent link null-safety (critical):** The component renders plain text instead of a `<Link>` when `linked` is true **or** `game.opponent_seo` is null. This is the rule that prevents navigating to `/teams/null` when the scraper hasn't resolved an opponent slug yet.
  ```jsx
  {linked || !game.opponent_seo ? (
    <span className="text-sm font-medium truncate">{game.opponent_name}</span>
  ) : (
    <Link to={`/teams/${game.opponent_seo}`} ...>{game.opponent_name}</Link>
  )}
  ```
- **Prediction chip:** Only shown for non-final / non-live rows when `prediction` is provided. The prediction payload is keyed to the game's home team (`home_pct`, `away_pct`), so the component flips when `game.is_home === false`. Tooltip shows both teams' percentages.
- **Time formatting:** `formatGameTime(epoch, timeStr)` prefers epoch (seconds since 1970) converted to local time, then falls back to parsing an HH:MM string.

## Prediction and bracket

### GamePrediction

- **File:** `app/javascript/components/GamePrediction.jsx` (162 LOC)
- **Used by:** `GameDetail` only, rendered *above* the tabs on the game page.
- **Props:** `homeName`, `awayName`, `prediction`, `keysToVictory`.
- **Render tree:**
  1. Header: "Pregame Prediction" + confidence band (`high` / `medium` / `low`) coloured via `confidenceColor()`.
  2. `<ProbabilityBar />` — two-colour horizontal bar. The favoured team's half is emerald; the other is slate. Percent labels sit above the bar.
  3. Expected Runs grid — two tiles, `team_a_expected_runs` (away by convention) and `team_b_expected_runs` (home), formatted to 1 decimal.
  4. Keys to Victory — two columns (`<KeysPanel />`), one per team, pulling from `keys_to_victory.team_a.keys_to_victory[]` / `team_b.keys_to_victory[]`. Each key has `{ code, title, summary }`. If neither team has keys, the grid is omitted entirely (no empty card).
  5. Footer: `Model <model_version>` (small grey line).
- **Null guard:** `if (!prediction || !prediction.prediction) return null`. Combined with the 204-aware `games.prediction` axios wrapper, this is what produces the "silently hidden when the game has been played" behaviour on `GameDetail`.
- **Shape expected:**
  ```
  prediction = {
    model_version,
    prediction: {
      team_a_win_probability, team_b_win_probability,
      team_a_expected_runs,   team_b_expected_runs,
      confidence_band: "high" | "medium" | "low"
    }
  }
  keysToVictory = {
    team_a: { keys_to_victory: [{ code, title, summary }] },
    team_b: { keys_to_victory: [...] }
  }
  ```
  Convention: `team_a = away`, `team_b = home` (the bar explicitly maps `leftLabel=awayName`, `rightLabel=homeName`).

### BracketSection (Standings.jsx)

- **File:** `app/javascript/pages/Standings.jsx` (not extracted to its own component file).
- **Used by:** Standings page only.
- **Props (implicit):** `scenarios.bracket = { format, format_label, rounds: [{ name, matchups: [{ top, bottom, bye_note }] }] }`.
- **Sub-components:** `<TeamSlot team={team} byeNote={str} isTop>` renders a single seeded row; accent colour is driven by `seedAccent(seed)` — amber for seed 1, blue for seeds 2-4, grey otherwise. Missing slot renders "TBD" or a bye note in italics (e.g. "vs. 3/6 winner").
- **Layout constants (hardcoded at module scope):**
  ```js
  const SLOT_H = 26                 // row height px
  const MATCHUP_H = SLOT_H * 2
  const R1_GAP = 8                  // gap between first-round matchups
  const ROUND_W = 150               // round column width
  const CONN_W = 28                 // connector column width
  ```
  **Flag as load-bearing:** these pixel constants drive the SVG connector geometry. Any change to the slot height or round width without updating the others will break line alignment. Deliberate over-parameterisation here would be an improvement.
- **Vertical positioning:** `computePositions(rounds)` is a `useMemo` that walks rounds left to right:
  - First round: stack matchups vertically with `R1_GAP` spacing.
  - Subsequent rounds: if the matchup count is **equal** to the previous round's (e.g. 12-team first round -> quarterfinals), use a 1:1 mapping (horizontal connector). Otherwise use a **2:1 mapping** (each new matchup centered between its two feeders, with the classic square bracket SVG shape).
  - Both branches gracefully fall back when `prev` is missing entries (orphan seed scenarios), stacking extras at the bottom.
- **Connectors:** SVG `<line>` segments, drawn in the `CONN_W`-wide column between rounds. 1:1 maps draw a single horizontal; 2:1 draws the canonical `|--` + `--|` + vertical-join + horizontal-out.
- **Horizontal scroll:** the full bracket sits in a `<div className="overflow-x-auto pb-2">` with its inner `<div>` sized to `totalW = rounds.length * ROUND_W + (rounds.length - 1) * CONN_W`. For conferences with more than ~4 rounds this horizontally scrolls rather than wrapping.
- **Format 'none':** if `bracket.format === "none"`, renders a short explanatory card instead of the bracket ("No conference tournament — regular season champion receives automatic qualifier.").

## Live game widgets

### DiamondView

- **File:** `app/javascript/components/DiamondView.jsx` (403 LOC)
- **Used by:** `GameDetail` when the game is live and both boxscore + play-by-play are loaded.
- **Exports:**
  - Default `DiamondView` (React component): SVG diamond showing runners on base, outs, current count, the at-bat/pitcher badges, and the defensive lineup (positions 1-9 overlaid onto field positions).
  - `parseSituation(pbpData, gameInfo)`: Pure function. Walks the last period's `playbyplayStats`, identifies the batting team (`battingTeamId`), derives half-inning ("top" / "bottom"), accumulates outs and runners (first/second/third) based on play descriptions, and returns `{ outs, runners, lastBatter, battingTeamId, halfInning, teams }`.
  - `getDefensiveLineup(boxscore, fieldingTeamId)`: Reads the fielding team's position 1-9 from the boxscore.
- **Coords:** hardcoded coordinate maps (`LOCATION_COORDS`, `HR_COORDS`, `BUNT_COORDS`, `DEPTH_OFFSETS`) at module scope. Coordinates are in an SVG coordinate system with home plate at (200, 330).

## Player widgets

### FavoritePlayerButton

- **File:** `app/javascript/components/FavoritePlayerButton.jsx` (73 LOC)
- **Props:** `player`, `onToggle?`, `showLabel = false`, `size = 14`.
- **Behaviour:** Optimistically flips local `favorited` state, calls `players.favorite(slug)` / `players.unfavorite(slug)`, rolls back on error. Returns `null` when no user is logged in — parents don't need to guard.
- **Variants:**
  - `showLabel = true` — full-size button with a "Favorite" / "Unfavorite" label (used on `PlayerDetail`).
  - `showLabel = false` — icon-only heart, greyed when unfavorited, red-filled when favorited (used inline in lists).

### FavoritePlayerCard

- **File:** `app/javascript/components/FavoritePlayerCard.jsx` (58 LOC)
- **Used by:** Dashboard "Favorite Players" grid.
- **Renders:** a link to `/players/:slug` with photo/avatar, number, name, team logo + name, position badge, and either a short batting line (AVG/HR/RBI) or a pitching line (ERA/W-L/K).

### SprayChart

- **File:** `app/javascript/components/SprayChart.jsx` (210 LOC)
- **Used by:** `PlayerDetail` when the player has batting stats.
- **API:** `GET /api/players/:slug/spray_chart` (`players.sprayChart`).
- **Render:** SVG field with each hit dotted at a coordinate keyed by direction (`left field`, `center field`, etc.) and hit type (`fly_ball`, `line_drive`, `ground_ball`, `popup`, `bunt`, `home_run`). Colour-coded by result.

### PlayerPdfPage

- **File:** `app/javascript/components/PlayerPdfPage.jsx` (345 LOC)
- **Role:** Offscreen component rendered into a hidden container during PDF export. `lib/exportPdf.js` mounts it, runs `html2canvas`, feeds the canvas into jspdf, then unmounts.
- **Used by:** `PlayerDetail` (single-player PDF) and `TeamDetail` (roster PDF — loops through players, fetches each via `players.show`, renders, captures, appends a new page).

## Team roster tables

- **File:** `app/javascript/components/team/RosterTables.jsx` (184 LOC)
- **Exports:**
  - `sortPlayers(players, { key, dir })` — generic stable sort: strings go through `localeCompare`, numeric-looking strings get `parseFloat`'d, nulls always sink.
  - `SortTh` — clickable `<th>` with up/down arrows and active-column colouring.
  - `PlayerCell` — photo/avatar + name `<Link>` + favorite button, used as the first cell in both tables.
  - `RosterBattingTable(players, sort, onSort, teamName)` — columns: AVG, OBP, SLG, AB, R, H, 2B, 3B, HR, RBI, BB, K, SB, HBP. Default sort: `{ key: "batting_average", dir: "desc" }` (set by caller).
  - `RosterPitchingTable(players, sort, onSort, teamName)` — columns: ERA, W-L, SV, IP, H, ER, BB, K, WHIP, NP. Default sort: `{ key: "era", dir: "asc" }` (ERA ascending).
- **Interaction:** sort state lives in the parent (TeamDetail). Clicking a header calls `onSort(key)`; the parent toggles the `dir` if the key matches, otherwise resets to the default direction for that table.

## Content blocks

### D1Facts

- **File:** `app/javascript/components/D1Facts.jsx` (414 LOC)
- **Used by:** `HomePage` only.
- **API:** `GET /api/facts?division=d1`.
- **Render:** grid of `<StatTile>` primitives (with tooltip support) grouped by section headings (home-run leaders, hottest hitters, dominant pitchers, biggest upsets, etc.). `<Tip>` sub-component is a hover tooltip with a manual show/hide state.

## Charts

The SPA uses Recharts directly — there is no charting wrapper/abstraction layer. All chart composition lives inline in `PlayerDetail.jsx`:

- **`ResponsiveContainer`** wraps every chart to fill the parent width.
- **`LineChart`** — rolling averages (batting avg, ERA), with `<ReferenceLine>` overlays for the season average/ERA.
- **`BarChart`** — hits per game, K/BB per game.
- **`ComposedChart`** — hits per game with a cumulative-avg line overlay; pitch count per game with a cumulative-NP line on a second Y-axis (`yAxisId="left"` for bars, `yAxisId="right"` for the line).
- **Tooltip content** uses custom components `ChartTooltipContent` and `PitchTooltipContent` for the dark-mode styling.
- **Colour palette (module-scope constants):**
  ```
  CHART_AMBER = "#f59e0b"
  CHART_GRAY  = "#9ca3af"
  CHART_RED   = "#ef4444"
  CHART_GREEN = "#22c55e"
  ```

## Loading and error UX

There is no shared spinner or skeleton component. Each page ships its own inline skeleton — typically a loop of `<div className="h-X bg-gray-200 dark:bg-gray-800 rounded animate-pulse" />` scaled to the expected content shape. Examples:

- `GameDetail`: 48px header pulse + 64px body pulse.
- `Standings`: 15 × 10px rows.
- `Scoreboard`: 6 × 32px cards in a responsive grid.
- `PlayerDetail`: 48px header + 32px body.
- `Dashboard`: custom `<DashboardSkeleton />` with a logo-sized title shimmer and a 6-tile grid.

Error states are similarly hand-rolled per page (a centered card with `text-lg` title + small `text-sm` subtitle). There is no global `<ErrorCard />` wrapper. The only shared error surface is the top-level `<ErrorBoundary>`, which only catches **render-phase** errors — network failures are handled per page.
