# Slug and Alias Resolution

Three independent implementations resolve "arbitrary team name string → our `teams.slug`". Side-by-side.

---

## Why three implementations

Historical: the Rails `TeamMatcher` came first. When the Java scraper was extracted, Java needed its own resolver for reconciliation and roster augmentation (it doesn't call Rails). Both share the same `team_aliases` table as the canonical alias store.

As of 2026-04-19 there is also a **third resolver** in `riseballs-live` (`client/SlugResolver.java`). Unlike the other two, this one has **no database access** — it loads two classpath resources at startup and does all resolution in memory:

- `espn_slug_overrides.json` (163 entries) — originally a one-shot snapshot of the `ESPN_SLUG_OVERRIDES` hash that lived on the Ruby `EspnScoreboardService` before that service was deleted on 2026-04-19, plus three reviewer-added entries (Florida Atlantic, Sam Houston, San Jose State accent handling). Maps ESPN team names / abbreviations to canonical slugs.
- `known_slugs.txt` (594 entries) — the universe of D1+D2 slugs, one-shot exported from `Team.pluck(:slug).sort.uniq`. If a lookup falls through the override map, `SlugResolver` checks whether the lowercase-collapsed ESPN slug appears in this list.

The live service has zero DB access so it cannot consult `team_aliases`. There is no longer a mirror of `ESPN_SLUG_OVERRIDES` in the Rails repo — the JSON file in the `riseballs-live` repo is the single canonical home. To add a new ESPN override, edit `riseballs-live/src/main/resources/espn_slug_overrides.json`, rebuild, redeploy. To refresh `known_slugs.txt`, re-export from Rails and commit the new file in `riseballs-live`.

---

## Side-by-side

| Step | Rails `TeamMatcher` (`app/services/team_matcher.rb`) | Java `OpponentResolver` (`reconciliation/schedule/OpponentResolver.java`) |
|------|-----------------------------------------------------|---------------------------------------------------------------------------|
| 0 | — | **Opponent URL host match** — only via the two-arg `resolve(name, url)` overload. Strict host-only equality against `Team.athleticsUrl`. Falls through silently on null/blank/unparseable URL or unknown host. |
| 1 | `TeamAlias.find_by(alias_name: normalized)` | `TeamAliasRepository.findByAlias(name)` |
| 2 | Exact slug match (`teams.slug = name`) | Exact slug match |
| 3 | `Team.name` / `Team.longName` case-insensitive exact | Parenthetical-suffix stripping: `"Lee University (Tenn.)"` → `"Lee University"` → name/longName lookup |
| 4 | Parenthetical-suffix stripping | `Team.name` / `Team.longName` exact |
| 5 | Common suffix stripping (`" University"`, `" State"`) | Common suffix stripping (`" University"`, `" State"`, leading `"The "`) |
| 6 | Trigram / prefix-guarded fuzzy match (`PlayerNameMatcher`-style) | State abbreviation expansion/contraction (`"St"` ↔ `"State"`, `"Tenn"` ↔ `"Tennessee"`) |
| 7 | — | (fail → null) |

**Only the Java resolver does state-abbreviation handling.** Rails doesn't — when Rails has a state-abbreviation issue (historical), it's fixed by adding a `TeamAlias` row.

**Only the Rails matcher does fuzzy/trigram matching.** Java is strictly rule-based (intentional — determinism over coverage for reconciliation).

### Step 0: URL-based disambiguation (issue #97, 2026-04-20)

Some aliases are legitimate 99.9% of the time but wrong in narrow edge cases. Bare `"UNC"` is the canonical example: North Carolina owns that alias in `team_aliases`, but Nevada's Sidearm schedule page lists Northern Colorado as `"UNC"` — producing a phantom "Nevada vs North Carolina" scheduled game on the real-life Nevada vs Northern Colorado date.

The fix is additive. `SidearmScheduleParser.parseCard` extracts the opponent-link `href` (e.g. `http://www.uncbears.com/`) alongside the display text. `OpponentResolver` builds a `hostToSlug` map from every team's `athleticsUrl` at construction and tries that map first when the caller has a URL. If the host matches a known athletics domain, the URL-resolved slug wins; otherwise the resolver falls through to the name-based ladder below, unchanged.

**Hard invariant:** the URL path can only improve outcomes, never regress them. Removing the URL path would restore the name-only behavior bit-for-bit.

**Who calls the two-arg form:** every caller that processes a `ScheduleEntry` from the scraper parsers — `TeamScheduleSyncService.buildTeamGame`, `ScheduleReconciliationOrchestrator.reconcileTeam`, `ScheduleComparisonEngine.resolveOpponent`, `ScheduleVerificationController`, `NcaaDateReconciliationService`. Non-`ScheduleEntry` callers (`NcaaContestCandidateResolver` with NCAA seoname, `StandingsOrchestrator` with standings entries) stay on the single-arg path since they have no URL context.

**Who populates `opponentUrl`:** only `SidearmScheduleParser.parseCard` today. Presto, WMT, and WordPress parsers pass `null` — they can be upgraded once their source formats are confirmed to carry opponent-link hrefs. Because the URL path is strictly additive, a `null` URL is equivalent to the pre-#97 behavior.

**Audit baseline (2026-04-20):** 594/594 teams have unique normalized hosts across the `Team.athleticsUrl` column — host equality is unambiguous by construction. Re-run the audit in `how_things_work.md` before relaxing the strict host-only rule.

---

## The alias table (`team_aliases`)

Columns:

| Column | Type | Meaning |
|--------|------|---------|
| `id` | bigint | PK |
| `team_slug` | text | FK to `teams.slug`; target |
| `alias_name` | text | the variant string to match |
| `source` | text | `manual`, `wmt`, `sec`, `ncaa` (informational) |
| `created_at` / `updated_at` | timestamp | |

Unique index on `(lower(alias_name), team_slug)` — prevents duplicate aliases for the same team. Multiple teams CAN share the same `alias_name` if the name is ambiguous (e.g., "MC" maps to multiple teams), but see the warning below.

---

## Ambiguous names — the escape hatch

Some names map to multiple teams:

| Name | Possible teams |
|------|----------------|
| `MC` | Mississippi College, McDaniel College, Mary's College |
| `Southeastern` | Southeastern Oklahoma St, Southeastern University (FL), Southeastern Louisiana |
| `Concordia` | Concordia University (NE), Concordia (IL), Concordia-Ann Arbor |
| `Saint Mary's` | Saint Mary's (CA), St. Mary's (TX), St. Mary's (MN) |

**Do NOT add a global alias for an ambiguous name.** It would map correctly for one conference and wrong for another.

**Instead, set `team_slug` directly** on the relevant `conference_standings` row. The conference context disambiguates — e.g., `MC` in the Southern States Athletic Conference is always Mississippi College for that specific row, even though it's ambiguous globally.

Similar approach for `team_games`: when `TeamScheduleSyncService` can't resolve uniquely, it leaves `opponent_slug: null` and the `Api::TeamsController#schedule` fallback uses case-insensitive name/longName matching at render time.

---

## SEC-style name handling

The SEC standings API returns mascot-format names:

| SEC API | DB slug |
|---------|---------|
| Alabama Crimson Tide | alabama |
| Florida Gators | florida |
| LSU Tigers | lsu |
| Auburn Tigers | auburn |
| ... (all 15 SEC teams) | |

Aliases were added manually for all 15 SEC teams. See the `team_aliases` rows with `source = 'sec'`.

---

## Common normalization (shared)

Before either resolver runs its match chain, both normalize the input:

- Trim whitespace
- Remove rankings: `#5 Georgia` → `Georgia`; `No. 10 LSU` → `LSU`
- (Java only) Lowercase for alias lookup

`normalizeForDedup(name)` in Java also strips rankings then resolves through aliases before counting doubleheaders — this is why both teams in a DH agree on `game_number=1` and `game_number=2`.

---

## When resolution fails

### Java (`OpponentResolver`)

Returns `null`. Upstream services log a WARN and skip the row (e.g., a schedule entry with an unresolvable opponent is not inserted into `team_games`).

### Rails (`TeamMatcher`)

Returns `nil`. Callers handle differently:

- `Api::TeamsController#schedule` fallback: returns `opponent_seo: nil`; frontend renders plain text instead of a link.
- `GameStatsExtractor#correct_team_slugs`: logs warn and uses the uncorrected slug.
- `RosterService.sync_roster`: logs warn and skips the team.

---

## Audit tooling

### `rake slugs:audit`

Reports:
- Unresolved `opponent_slug` values (NULL in `team_games`) — with source team and opponent name
- Slugs in `team_games.opponent_slug` that don't match any `teams.slug`
- Ambiguous aliases (same `alias_name` → multiple `team_slug`)
- Duplicate aliases (same `(alias_name, team_slug)` → shouldn't exist with the unique index, but defensive)

### `rake slugs:suggest`

Proposes aliases for unresolved names using fuzzy matching with division + conference context. Operator reviews and inserts manually.

See [rails/13-rake-tasks.md](../rails/13-rake-tasks.md) `slugs.rake`.

---

## Adding an alias

```sql
INSERT INTO team_aliases (team_slug, alias_name, source, created_at, updated_at)
VALUES ('lsu', 'LSU Tigers', 'sec', now(), now());
```

Or via Rails console:

```ruby
TeamAlias.create!(team_slug: "lsu", alias_name: "LSU Tigers", source: "sec")
```

Aliases are matched case-insensitively via the unique index `(lower(alias_name), team_slug)`.

---

## Related docs

- [scraper/03-parsers.md](../scraper/03-parsers.md) — Java scraper `OpponentResolver` with Mermaid decision tree
- [live/02-architecture.md](../live/02-architecture.md) — `riseballs-live`'s classpath-resource `SlugResolver`
- [rails/08-matching-services.md](../rails/08-matching-services.md) — Rails `TeamMatcher`
- [rails/01-models.md](../rails/01-models.md) — `TeamAlias` model
- [pipelines/04-standings-pipeline.md](../pipelines/04-standings-pipeline.md) — how ambiguous names resolve in standings
- [operations/runbook.md](../operations/runbook.md) — "unresolved opponent" and "live overlay not updating" playbooks
