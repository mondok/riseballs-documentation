# Frontend Overview

The Riseballs frontend is a React 19 single-page application that lives inside the Rails app at `app/javascript/` and is mounted under a catch-all Rails route. There is no separate frontend server, no separate deploy, and no separate base URL for API calls — everything is same-origin.

## Table of contents

- [Tech stack](#tech-stack)
- [Directory layout](#directory-layout)
- [How the SPA is served](#how-the-spa-is-served)
- [Entry point and provider tree](#entry-point-and-provider-tree)
- [Routing](#routing)
- [API consumption pattern](#api-consumption-pattern)
- [Auth flow](#auth-flow)
- [Build and dev commands](#build-and-dev-commands)
- [Major UI routes](#major-ui-routes)

## Tech stack

From `riseballs/package.json`:

| Concern             | Choice                                                      |
| ------------------- | ----------------------------------------------------------- |
| UI library          | `react` 19.x + `react-dom` 19.x                             |
| Router              | `react-router-dom` 7.x (BrowserRouter)                      |
| Bundler             | `esbuild` 0.27 (no Vite, no Webpack)                        |
| Styling             | Tailwind CSS 4 via `@tailwindcss/cli` (no PostCSS config)   |
| HTTP client         | `axios` 1.13 (two instances: `api` and `authApi`)           |
| Charts              | `recharts` 3.x (LineChart, BarChart, ComposedChart)         |
| Icons               | `lucide-react`                                              |
| PDF / image export  | `jspdf` 4.x + `html2canvas` 1.4                             |
| Runtime prop checks | `prop-types` (no TypeScript — plain `.jsx`)                 |
| Hotwire leftovers   | `@hotwired/turbo-rails`, `@hotwired/stimulus` installed but unused by the SPA |

There is no TypeScript, no ESLint config, no Jest. `.jsx` files are bundled directly by esbuild with `--jsx=automatic`.

## Directory layout

```
riseballs/app/javascript/
  application.jsx          entry point: mounts <App /> into #root
  components/
    App.jsx                route table (react-router)
    Layout.jsx             shell: sticky nav, dark-mode toggle, <Outlet />
    RankingsLayout.jsx     nested layout for /rankings + /rankings/standings
    ErrorBoundary.jsx      class component, catches render errors
    RequireAuth.jsx        redirects to /sign-in when unauthenticated
    GamePrediction.jsx     pregame win-prob / keys-to-victory panel
    GameCard.jsx           scoreboard tile (links to /games/:id)
    D1Facts.jsx            homepage facts block
    DiamondView.jsx        live baserunners / outs / defensive lineup widget
    SprayChart.jsx         batter spray chart (SVG)
    FavoritePlayerButton.jsx / FavoritePlayerCard.jsx
    PlayerPdfPage.jsx      off-screen render target for PDF export
    team/
      GameRow.jsx          single schedule row (used by TeamDetail, Dashboard)
      RosterTables.jsx     batting + pitching roster tables with sort
  contexts/
    AuthContext.jsx        user state + signIn/signUp/signOut
  lib/
    api.js                 axios wrappers (single source of truth for endpoints)
    statbroadcast.js       URL parsing for StatBroadcast / SidearmStats feeds
    usePageTitle.js        tiny hook: document.title = "<title> - Riseballs.com"
    exportCsv.js           CSV download helpers
    exportPdf.js           PDF export (jspdf + html2canvas)
  pages/
    HomePage.jsx Dashboard.jsx Scoreboard.jsx TeamsIndex.jsx TeamDetail.jsx
    GameDetail.jsx Rankings.jsx Standings.jsx RPI.jsx Stats.jsx LiveView.jsx
    PlayerSearch.jsx PlayerDetail.jsx Analytics.jsx PitchAnalytics.jsx
    SignIn.jsx SignUp.jsx
  controllers/             Stimulus controllers (not used by the SPA)
```

There is **no dedicated `admin/` pages folder in the SPA**. Admin screens (`/admin/boxscores`, `/admin/reviews`, `/admin/jobs`, `/sidekiq`) are plain Rails views under `app/views/admin/` and are routed outside the React catch-all; see `config/routes.rb`.

## How the SPA is served

`riseballs/config/routes.rb`:

```ruby
root "pages#index"
get "*path", to: "pages#index",
    constraints: ->(req) { !req.path.start_with?("/api", "/auth", "/rails", "/sidekiq", "/admin") }
```

Every non-API, non-admin path renders `app/views/pages/index.html.erb`, which is literally:

```erb
<div id="root"></div>
```

The Rails layout (`application.html.erb`) handles the server-rendered shell: `<title>`, meta description, Open Graph tags, CSP / CSRF tokens, and the `<script>` / `<link>` tags that pull in the esbuild bundle (`application.js` and `application.css` from `app/assets/builds/`).

`PagesController#index` also:

1. 301-redirects legacy numeric `/players/:id` URLs to the slug form `/players/:slug` (via `friendly_id`).
2. Pattern-matches the request path to populate `@page_title`, `@page_description`, and `@page_image` for SSR of OG / Twitter meta tags — important for link previews since the SPA can't set those before first paint. Paths handled: `/teams/:slug`, `/players/:slug`, `/scoreboard`, `/teams`, `/rankings`, `/stats`, `/players`.

Once the HTML ships, React takes over via `BrowserRouter` and handles all subsequent navigation client-side.

## Entry point and provider tree

`app/javascript/application.jsx`:

```jsx
createRoot(root).render(
  <BrowserRouter>
    <ErrorBoundary>
      <AuthProvider>
        <App />
      </AuthProvider>
    </ErrorBoundary>
  </BrowserRouter>
)
```

`ErrorBoundary` is a class component that catches render-phase errors and shows a "Something went wrong" card with a refresh button. It does **not** report to an external error tracker — it only `console.error`s.

`AuthProvider` hydrates `user` from `localStorage` keys `user` (JSON) and `jwt_token` (string) on mount. All components read `useAuth()` to get `{ user, loading, signIn, signUp, signOut }`.

## Routing

`components/App.jsx` declares all routes inside a single `<Routes>` nested under `<Layout />`:

| Path                      | Element                            | Auth              |
| ------------------------- | ---------------------------------- | ----------------- |
| `/`                       | `HomePage`                         | public            |
| `/dashboard`              | `Dashboard`                        | `RequireAuth`     |
| `/scoreboard`             | `Scoreboard`                       | public            |
| `/teams`                  | `TeamsIndex`                       | public            |
| `/teams/:slug`            | `TeamDetail`                       | public            |
| `/games/:id`              | `GameDetail`                       | public            |
| `/rankings`               | `RankingsLayout` -> `Rankings`     | public            |
| `/rankings/standings`     | `RankingsLayout` -> `Standings`    | public            |
| `/rpi`                    | `RPI`                              | `RequireAuth`     |
| `/stats`                  | `Stats`                            | public            |
| `/live`                   | `LiveView`                         | `RequireAuth`     |
| `/players`                | `PlayerSearch`                     | public            |
| `/players/:slug`          | `PlayerDetail`                     | public            |
| `/analytics`              | `Analytics`                        | `RequireAuth`     |
| `/pitch-analytics/:slug`  | `PitchAnalytics`                   | public (hardcoded not in nav) |
| `/sign-in`, `/sign-up`    | `SignIn`, `SignUp`                 | public            |

`RequireAuth` returns `null` while auth is loading, redirects to `/sign-in` with `state={{ returnTo: location.pathname }}` when there is no user, and renders `children` otherwise.

`Layout.jsx` provides the global chrome:

- Sticky header with the Riseballs wordmark and `NAV_ITEMS` (Dashboard, Scoreboard, Teams, Players, Rankings, RPI, Stats, Live, Analytics).
- Each nav item can be flagged `authRequired: true` (hidden for logged-out users) or `adminOnly: true` (hidden for everyone except the hard-coded `ADMIN_EMAIL = "matt.mondok@gmail.com"` — only RPI uses this).
- Dark-mode toggle persists to `localStorage.theme` and toggles `documentElement.classList("dark")`.
- Mobile burger menu collapses on route change.
- The main `<Outlet />` is wrapped in `max-w-7xl mx-auto`.

`RankingsLayout` is a nested route that renders a small tab bar (Poll / Standings) and defers to its child `<Outlet />`.

## API consumption pattern

All network calls funnel through `app/javascript/lib/api.js`, which exports two axios instances and a set of per-resource wrapper objects.

```js
const api = axios.create({ baseURL: "/api", headers: { "Content-Type": "application/json" } })
const authApi = axios.create({ baseURL: "/auth", ... })
```

Same-origin: no CORS, no absolute base URL. Both clients inject the CSRF token from the Rails-rendered `<meta name="csrf-token">` on every request.

The `api` instance additionally:

- **Request:** reads `localStorage.jwt_token`; if present, sets `Authorization: Bearer <token>`.
- **Response:** on a 401, clears `jwt_token` and `user` from localStorage. Does **not** auto-redirect — individual pages typically silently fail.

### Resource wrappers

Each group exposes named methods so call sites don't build URLs by hand:

| Wrapper          | Methods                                                                                      |
| ---------------- | -------------------------------------------------------------------------------------------- |
| `auth`           | `signIn`, `signUp`, `signOut` (hits `/auth/...`)                                             |
| `teams`          | `list`, `show`, `follow`, `unfollow`, `conferences`, `schedule`                              |
| `players`        | `list`, `show`, `sprayChart`, `favorite`, `unfavorite`                                       |
| `dashboard`      | `index`                                                                                      |
| `scoreboard`    | `index`, `predictions`                                                                        |
| `games`          | `show`, `boxscore`, `playByPlay`, `teamStats`, `batch`, `prediction`                         |
| `liveStats`      | `batch`, `boxscoreBatch`, `sidearmBatch`, `resolve`                                          |
| `rankings`       | `index`                                                                                      |
| `stats`          | `index`                                                                                      |
| `rpi`            | `index`                                                                                      |
| `standings`      | `index`                                                                                      |
| `analytics`      | `leaderboard`, `war`                                                                         |
| `pitchAnalytics` | `show(teamSlug)`                                                                             |
| `facts`          | `index(division)`                                                                            |

### Special status handling

`games.prediction(id)` passes a custom `validateStatus` that treats `200` and `204` both as success:

```js
prediction: (id) => api.get(`/games/${id}/prediction`, {
  validateStatus: (s) => s === 200 || s === 204
})
```

This is how the `GameDetail` page implements **silent hiding** of the prediction panel when the server returns 204 (game already played) or when the request errors for any other reason (including a 503 from a downed predict microservice). The calling code in `GameDetail.jsx` simply reads `res.status === 200 && res.data` and gives up otherwise:

```js
gamesApi.prediction(id)
  .then((res) => { if (res.status === 200 && res.data) setPredictionData(res.data) })
  .catch(() => {})
```

### Error handling conventions

There is no global toast / snackbar / error modal. Patterns observed across pages:

- `.catch(() => setFetchError(true))` flips a local state and the page renders an inline error card.
- `.catch(() => {})` silently swallows errors for non-critical auxiliary data (predictions, live overlay, favorite toggles).
- Forms (SignIn, SignUp) display `err.response?.data?.error` inline.

## Auth flow

`contexts/AuthContext.jsx`:

1. On mount, rehydrate `user` from `localStorage.user` (JSON) and `localStorage.jwt_token`.
2. `signIn(email, password)` posts to `/auth/sign_in`, pulls the JWT out of the `Authorization` response header (`Bearer <token>`), stores it, stores the user body, and sets React state.
3. `signUp` mirrors `signIn` against `/auth/sign_up`.
4. `signOut` attempts to DELETE `/auth/sign_out` (ignores failures) and clears both localStorage keys.

`RequireAuth` is a simple guard. There is no per-role gating beyond the hardcoded admin email comparison in `Layout.jsx` and `RPI.jsx`.

## Build and dev commands

From `package.json`:

```json
"scripts": {
  "build":    "esbuild app/javascript/application.jsx --bundle --sourcemap --format=esm --outdir=app/assets/builds --public-path=/assets --loader:.jsx=jsx --loader:.js=jsx --jsx=automatic",
  "build:css": "npx @tailwindcss/cli -i ./app/assets/stylesheets/application.tailwind.css -o ./app/assets/builds/application.css --minify"
}
```

`Procfile.dev`:

```
web:  env RUBY_DEBUG_OPEN=true bin/rails server
js:   yarn build --watch
css:  yarn build:css --watch
jobs: bundle exec sidekiq -C config/sidekiq.yml
```

Local development: `bin/dev` (via foreman / overmind) starts all four processes. The JS and CSS watchers rebuild into `app/assets/builds/`; Sprockets/Propshaft serves those as fingerprinted assets.

For production, `bin/rails assets:precompile` invokes both build scripts (wired through the Rails asset pipeline).

## Major UI routes

See the routing table above for the exhaustive list. Summary:

- **Public content:** `/`, `/scoreboard`, `/teams`, `/teams/:slug`, `/games/:id`, `/rankings`, `/rankings/standings`, `/stats`, `/players`, `/players/:slug`, `/pitch-analytics/:slug`.
- **Auth-required:** `/dashboard`, `/live`, `/analytics`, `/rpi` (admin-only in the nav but the route guard is just `RequireAuth`).
- **Auth pages:** `/sign-in`, `/sign-up`.

All URLs are user-visible and bookmarkable. Filter and pagination state on `Scoreboard` (and increasingly elsewhere) is synced to `useSearchParams`, so page reload preserves view — see `Scoreboard.jsx`'s `updateParams` helper for the pattern (strips defaults to keep URLs clean).
