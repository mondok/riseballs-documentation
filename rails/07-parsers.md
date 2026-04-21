# Parser Internals Reference

Detailed reference for the HTML/JSON parsers used by the ingestion services.
Paired with `06-ingestion-services.md` — that file covers the "what runs
when", this file covers the "what the parser actually does with the bytes".

## Table of Contents

- [BoxScoreParsers::Base](#boxscoreparsersbase)
  - [Table Classification](#table-classification)
  - [Batting Table Selection](#batting-table-selection)
  - [Team Name Extraction](#team-name-extraction)
  - [Linescore Parsing](#linescore-parsing)
  - [Play-by-Play Parsing](#play-by-play-parsing)
  - [Scoring Summary Fallback](#scoring-summary-fallback)
  - [NUXT Data Fallback](#nuxt-data-fallback)
  - [clean_play_names — name cleanup rule](#clean_play_names--name-cleanup-rule)
- [BoxScoreParsers::SidearmParser](#boxscoreparserssidearmparser)
- [BoxScoreParsers::PrestoSportsParser](#boxscoreparsersprestosportsparser)
- [BoxScoreParsers::WmtParser](#boxscoreparserswmtparser)
- [Decision Extraction](#decision-extraction)
- [Pitch Count (`np`) Column](#pitch-count-np-column)
- [PBP Shape on CachedGame](#pbp-shape-on-cachedgame)
- [Verb Filtering and Garbage Rejection](#verb-filtering-and-garbage-rejection)
- [Name Cleanup Rules](#name-cleanup-rules)

---

## BoxScoreParsers::Base

**File:** `app/services/box_score_parsers/base.rb`

Abstract base for all HTML box score parsers. Subclasses must implement:

- `can_parse?(doc)` — return true if this parser should handle this HTML.
- `parse_batting_table(table)` — returns array of player hashes with
  `firstName`, `lastName`, `position`, `starter`, `batterStats`.
- `parse_pitching_table(table)` — returns array with `firstName`, `lastName`,
  `position: "P"`, `starter: true`, `decision`, `pitcherStats`.

Base provides: table classification, team name extraction, linescore parsing,
PBP parsing (both full tables and scoring summary fallback), NUXT data fallback,
breakdown merging stubs, shared helpers.

### Table Classification

`classify_tables(tables)` iterates every `<table>` on the page, reads headers
(prefers `thead th`, falls back to first row's `th, td`), normalizes each
header to its last word (`"1st innning 1"` → `"1"`, `"Runs R"` → `"r"`), and
buckets the table:

| Table type  | Header signature                                             |
| ----------- | ------------------------------------------------------------ |
| `linescore` | Contains `r` and `h` and at least one inning digit column    |
| `pitching`  | Contains `ip` AND (`er` OR `bb`)                             |
| `batting`   | Contains `ab` AND `rbi`, OR `ab` AND `h`                     |
| `pbp`       | Header contains `"play description"` or `"score summary"` AND more than 2 rows |

PBP tables are deduplicated via `dedup_pbp_tables` using the first 60 chars of
the first cell with length >10 as a fingerprint. Sidearm often renders the
same PBP table twice.

### Batting Table Selection

Handles multi-game pages that emit 4+ batting tables (one compact + one full
per team). `pick_best_batting_tables`:

1. Score each table by count of `EXTENDED_STAT_HEADERS`
   (`2b 3b hr sb cs hbp sh sf`) in its headers, plus row count.
2. "Full" = tables with 3+ extended stat columns.
3. If `@expected_score` is set (`[home_score, away_score]` passed into
   `parse`), try every pair and return the pair whose batter-runs totals
   match.
4. Prefer 2 full tables. Else fall back to compact tables sorted by
   extended-stat count desc, row count desc.

`find_score_matching_pair(tables)` — iterates consecutive pairs, sums each
table's `runsScored`, accepts the pair matching either orientation.

### Team Name Extraction

`extract_team_names(doc, linescore_table)`:

1. Prefer linescore `<tbody>` rows — first data row's first cell is away,
   second is home. Passed through `clean_cell_name`.
2. Fallback: `<title>` split on `" vs "` / `" at "` (case-insensitive),
   stripping anything past a `|`.
3. Defaults: `"Visitor"` / `"Home"`.

`clean_cell_name(cell)` — splits the cell's text on `\r\n\t`, keeps non-blank
segments, and prefers the last segment that contains a lowercase letter
(the Sidearm short display name, not the all-caps abbreviation).

### Linescore Parsing

`parse_linescore(table)`:

- Normalizes headers so `"1st innning 1"` → `"1"`, `"Runs R"` → `"R"`,
  `"Hits H"` → `"H"`, `"Errors E"` → `"E"`.
- Data rows = all `<tr>` with at least one `<td>`, skipping the header row.
- Requires at least 2 data rows (away + home).
- Output array: one entry per inning column, then `R`, `H`, `E` rows:

```json
[
  {"period": "1", "visit": "0", "home": "2"},
  {"period": "2", "visit": "1", "home": "0"},
  ...
  {"period": "R", "visit": "3", "home": "5"},
  {"period": "H", "visit": "6", "home": "8"},
  {"period": "E", "visit": "1", "home": "0"}
]
```

### Play-by-Play Parsing

`parse_play_by_play(pbp_tables, teams)`:

- Splits tables into "scoring summary" (header contains `inning` or
  `score summary` or `logo`) vs "full PBP half-inning tables".
- Prefers full PBP. Falls back to scoring summary only when no full tables
  are present.
- For each full-PBP table:
  - Data rows only (has at least one `<td>`).
  - Column 0 = `playText`, column 1 = `visitorScore`, column 2 = `homeScore`.
  - `playText` is run through `clean_play_names` for `Last,First` normalization.
  - Reads `<caption>` for the half ("Top" / "Bottom"). Half = `top` unless
    caption contains `"bottom"`. Team ID = `away_id` for top, `home_id`
    for bottom.
- Half-innings are grouped by pairs into periods (`inning_idx + 1`).

Output shape:

```json
{
  "teams": [ {"teamId": "athl_foo_away", ...}, {"teamId": "athl_foo_home", ...} ],
  "periods": [
    {
      "periodNumber": 1,
      "periodDisplay": "Inning 1",
      "playbyplayStats": [
        { "teamId": "athl_foo_away", "plays": [ { "playText": "...", "visitorScore": "0", "homeScore": "0" } ] },
        { "teamId": "athl_foo_home", "plays": [ ... ] }
      ]
    }
  ],
  "_source": "athletics"
}
```

### Scoring Summary Fallback

`parse_scoring_summary(table, teams)` — used when only a single all-in-one
"Score summary" table is present. Detects columns:

- Header row's cells. If 4+ columns, away = size-2, home = size-1.
- Finds the inning cell per row via `\A\d+(?:st|nd|rd|th)\z` regex.
- `play_text` = the longest cell in the row.
- Groups plays by inning number, emits one `playbyplayStats` entry per period
  with no `teamId` (frontend will fall back to generic labels).

### NUXT Data Fallback

`extract_nuxt_play_by_play(html, teams, team_boxscores = nil)` — used when the
HTML tables don't yield >=40 real plays.

- Extracts `<script id="__NUXT_DATA__">` as a big flat array.
- Filters strings matching `PLAY_PATTERN`
  (`singled|doubled|...|wild pitch|passed ball`, 20+ verbs).
- Requires >=10 matching strings.
- `nuxt_build_name_to_team(team_boxscores, away_id, home_id)` — builds a
  `lastName.downcase -> teamId` lookup.
- `nuxt_split_into_half_innings(play_texts, name_to_team)`:
  - **Primary:** roster-based (`nuxt_split_by_roster`). Starts new half when
    the batter's team changes; also starts new half when outs reach 3+ for
    same-team inning boundaries (away team bats bottom of 6th AND top of 7th).
  - **Fallback:** `nuxt_split_by_outs` — count to 3 outs per half using
    `nuxt_count_outs` (strikeout, grounded/flied/fouled/lined/popped out,
    caught stealing, picked off, infield fly, double/triple play bonus,
    sacrifice-as-out).
- `nuxt_detect_first_team(first_half, name_to_team)` votes across the plays
  in the first half-inning to decide whether to tag it with `away_id`.

Output tagged `"_source" => "nuxt_data"`.

### `pbp_complete?`

Requires 40+ real plays matching
`singled|doubled|tripled|homered|grounded|flied|struck out|walked|lined|popped|fouled|reached|hit by pitch`.

### `clean_play_names` — name cleanup rule

```ruby
def clean_play_names(text)
  # "Torres,Isa" -> "Isa Torres"
  text = text.gsub(/\b([A-Z][a-zA-Z'-]+),([A-Z][a-zA-Z'-]+)\b/) { "#{$2} #{$1}" }
  # "Ganje, G." -> "G. Ganje"
  text.gsub(/\b([A-Z][a-zA-Z'-]+), ([A-Z]\.)\s/) { "#{$2} #{$1} " }
end
```

Exact same rule is duplicated in:

- `AthleticsBoxScoreService#clean_play_names` (`athletics_box_score_service.rb:157`)
- `BoxScoreParsers::WmtParser#wmt_clean_names` (`wmt_parser.rb:271`)

These three implementations must stay in sync. Safe to refactor into a single
shared helper if touched.

---

## BoxScoreParsers::SidearmParser

**File:** `app/services/box_score_parsers/sidearm_parser.rb`

Default parser for Sidearm-powered athletics sites.

### `can_parse?(doc)`

Returns true when any `<table>` has a header matching `\A(player|name)\z`
AND contains `ab` or `ip` as one of its headers.

### Header maps

```ruby
BATTING_HEADERS = {
  position: /\Apos(ition)?\z/,
  name:     /\A(player|name)\z/,
  ab:       /\Aab\z/,
  r:        /\Ar\z/,
  h:        /\Ah\z/,
  rbi:      /\Arbi\z/,
  bb:       /\Abb\z/,
  so:       /\A(so|k)\z/,
  doubles:  /\A2b\z/,
  triples:  /\A3b\z/,
  hr:       /\Ahr\z/,
  sb:       /\Asb\z/,
  cs:       /\Acs\z/,
  hbp:      /\Ahbp\z/,
  sh:       /\Ash\z/,
  sf:       /\Asf\z/
}

PITCHING_HEADERS = {
  name: /\A(player|name|pitcher)\z/,
  ip:   /\Aip\z/,
  h:    /\Ah\z/,
  r:    /\Ar\z/,
  er:   /\Aer\z/,
  bb:   /\Abb\z/,
  so:   /\A(so|k)\z/,
  wp:   /\Awp\z/,
  hp:   /\Ahp?\z/,
  bf:   /\Abf\z/,
  np:   /\Anp\z/   # pitch count
}
```

### Batting rows

- Reads `position` column separately.
- Name cell handling:
  - Detects **subs** by presence of any `<span>` that isn't
    `hide-on-medium` / `mobile-jersey-number` — Sidearm wraps substitutes
    in a `<span>` for indentation.
  - Strips hidden helper spans (`span.hide-on-medium`,
    `span.mobile-jersey-number`).
  - Replaces `\u00a0` with space, collapses whitespace.
  - Strips a leading position abbreviation from the name if it matches the
    position cell.
- `PH` / `PR` position forces `is_sub = true`.
- `split_name(raw)` from `Shared::NameNormalizer`.
- `compact` on the stats hash drops nil entries so only columns present in the
  table appear in `batterStats`.

### Pitching rows

- Strips a leading `"p "` if the position abbreviation leaked into the name.
- Extracts decision with `\(([WLS])[,)]/i` — single capital letter followed by
  comma or closing paren (see [Decision Extraction](#decision-extraction)).
- Strips any parenthetical content from the name after extracting the
  decision.

### Breakdowns

Two layouts supported:

1. **Sidearm Nuxt `<div>` breakdowns.** Divs whose text starts with `"Batting"`
   (len <600) and contains at least one `(2B|3B|HR|SB|HBP|SF|SH):` label.
   Each inner `div.flex` has a `span.font-bold` label like `"HR:"` and a
   trailing span / text node with entries
   `"Last, First (count); Last2, First2 (count)"`.
2. **PrestoSports `<dl><dt><dd>` breakdowns.** Same content, different markup.

`extract_breakdown_names` and `merge_stat_breakdowns` both replace
`\u00A0` → space before splitting on `;`. Team assignment: score each team's
batter list by how many breakdown last names it contains and pick the team
with the most matches.

Merge rule: when a stat is already non-zero on the player (came from a table
column), keep it. When zero, set to the breakdown count.

### `BREAKDOWN_STAT_MAP`

```ruby
{
  "HR"  => "homeRuns",
  "2B"  => "doubles",
  "3B"  => "triples",
  "SB"  => "stolenBases",
  "HBP" => "hitByPitch",
  "SF"  => "sacrificeFlies",
  "SH"  => "sacrificeBunts",
  "SAC" => "sacrificeBunts",
  "CS"  => "caughtStealing"
}
```

---

## BoxScoreParsers::PrestoSportsParser

**File:** `app/services/box_score_parsers/presto_sports_parser.rb`

Used by schools on the PrestoSports platform. Tried **first** by
`AthleticsBoxScoreService#parse` because it's more specific than Sidearm.

### `can_parse?(doc)`

Returns true if any table has a header matching `\A(hitters?|batters?)\z`.
PrestoSports uses "Hitters" / "Batters" rather than "Player" / "Name".

### Headers

- Batting:
  `name: /\A(hitters?|batters?|player|name)\z/`, plus `ab`, `r`, `h`, `rbi`,
  `bb`, `so` (or `k`), `lob`, `2b`, `3b`, `hr`, `sb`, `cs`, `hbp`, `sh`, `sf`.
- Pitching:
  `name: /\A(pitchers?|player|name)\z/`, plus `ip`, `h`, `r`, `er`, `bb`,
  `so`, `wp`, `bf`, `hr`, `np`.

### Position embedded in name cell

PrestoSports puts position inline in the name column: `"ss Izzy Wilson"`.

```ruby
POSITIONS = %w[c 1b 2b 3b ss lf cf rf dh dp p pr ph of ut flex]
POSITION_PATTERN = /\A(#{POSITIONS.join("|")}|[a-z]{1,2}\/[a-z]{1,2})\s+(.+)\z/i
```

If the name matches, capture group 1 is the position, group 2 is the actual
name. `PH`/`PR` flag `is_sub = true`. For pitchers, the position is simply
stripped.

### Decision extraction

Same regex as Sidearm: `\(([WLS])[,)]/i`.

---

## BoxScoreParsers::WmtParser

**File:** `app/services/box_score_parsers/wmt_parser.rb`

Parses JSON from `https://api.wmt.games/api/statistics/games/{id}?with=...`.
Not HTML-based.

### Input shape (partial)

```json
{
  "competitors": [
    { "homeContest": false, "teamId": ..., "schoolId": ..., "score": 5, "nameTabular": "...", "teamStats": [...] },
    { "homeContest": true,  "teamId": ..., "schoolId": ..., "score": 3, "nameTabular": "...", "teamStats": [...] }
  ],
  "players": { "data": [
    {
      "team_id": ..., "xml_name": "Last,First", "xml_uni": "22", "xml_position": "ss",
      "games_started": 1,
      "statistic": [ { "period": 0, "statistic": { "sAtBats": 3, ...} }, ... ]
    }
  ]},
  "actions": { "data": [ { "action": {...} } ] },
  "plays":   { "data": [ { "play":   {...} } ] },
  "periods_played": 7
}
```

### Stat field mapping (batting)

| Output key         | WMT key              |
| ------------------ | -------------------- |
| `atBats`           | `sAtBats`            |
| `hits`             | `sHits`              |
| `runsScored`       | `sRuns`              |
| `runsBattedIn`     | `sRunsBattedIn`      |
| `walks`            | `sWalks`             |
| `strikeouts`       | `sStrikeoutsHitting` |
| `doubles`          | `sDoubles`           |
| `triples`          | `sTriples`           |
| `homeRuns`         | `sHomeRuns`          |
| `stolenBases`      | `sStolenBases`       |
| `caughtStealing`   | `sCaughtStealing`    |
| `hitByPitch`       | `sHitByPitch`        |
| `sacrificeFlies`   | `sSacrificeFlies`    |
| `sacrificeBunts`   | `sSacrificeBunts`    |
| `fieldingErrors`   | `sErrors`            |

Gated by `has_activity = sAtBats || sWalks || sHitByPitch || sRuns` OR the
player isn't a `PR`/`PH` sub.

### Stat field mapping (pitching)

| Output key         | WMT key                    |
| ------------------ | -------------------------- |
| `inningsPitched`   | `sInningsPitched` (string) |
| `hitsAllowed`      | `sHitsAllowed`             |
| `runsAllowed`      | `sRunsAllowed`             |
| `earnedRuns`       | `sEarnedRuns`              |
| `walksAllowed`     | `sBasesOnBallsAllowed`     |
| `strikeouts`       | `sStrikeouts`              |
| `homeRunsAllowed`  | `sHomeRunsAllowed`         |
| `hitBatsmen`       | `sHitBattersPitching`      |
| `battersFaced`     | `sBattersFaced`            |
| `wildPitches`      | `sWildPitches`             |
| `pitchCount`       | `sNumberOfPitches`         |

Gated by `sInningsPitched > 0 OR sPitchingAppearances > 0`.

Decision: `W` if `sIndWon > 0`, `L` if `sIndLost > 0`, `S` if `sSaves > 0`.

### Team seonames

`wmt_build_teams` looks up seonames via
`Team.find_by(wmt_school_id: ...)&.slug`. Empty string if not backfilled — will
be stamped by `CloudflareBoxScoreService.assign_seonames` via
`BoxscoreFetchService.store_result`.

### PBP from actions (preferred)

Action payload:

```json
{ "action": {
    "game_period_id": 1,
    "member_org_id": 123,
    "play_by_play_text": "...",
    "narrative": "...",
    "home_score": 2,
    "visitor_score": 1
} }
```

Plays are grouped by `game_period_id`. A strict verb filter
(`WMT_PLAY_VERB`) discards garbage (player substitutions emit bare names
which fail the regex). `wmt_split_by_team` groups consecutive plays by
`member_org_id` (team ID) so the frontend renders correct half-inning
headers.

### PBP from plays (fallback)

Same shape, different key (`play` instead of `action`). Used when `actions`
array is empty.

### Linescores

`build_linescores` emits one row per inning played (`sRuns` from each team's
`teamStats[period=N]`), then `R`, `H`, `E` from `teamStats[period=0]`.

---

## Decision Extraction

Every HTML parser uses the same regex to extract decisions from pitcher names:

```ruby
dec = name_raw.match(/\(([WLS])[,)]/i)&.[](1)&.upcase
```

Matches: `(W, 5-3)`, `(W,5-3)`, `(W)`, `(L, 2-1)`, `(S)`.
Rejects: `(3-1)` (season record), `(W3-1)` (ambiguous).

After extraction, the parenthetical is stripped:
`name_clean = name_raw.gsub(/\s*\([^)]*\)/, "").strip`.

WMT derives decision from its own `sIndWon` / `sIndLost` / `sSaves` flags
rather than parsing from the name string.

---

## Pitch Count (`np`) Column

Both `SidearmParser::PITCHING_HEADERS` and
`PrestoSportsParser::PITCHING_HEADERS` map `np: /\Anp\z/` to
`pitcher_stats["pitchCount"]`. This is the Sidearm "number of pitches"
column when present. Missing when the site doesn't render it — `.compact`
drops the key from `pitcherStats`.

WMT uses `sNumberOfPitches` → `pitchCount`.

Athletics sites that split "balls / strikes / total" — not currently parsed.

---

## PBP Shape on CachedGame

Stored under `CachedGame.data_type = "athl_play_by_play"` with the following
structure (covers Sidearm athletics, PrestoSports, WMT actions, WMT plays,
and NUXT-data fallback):

```json
{
  "teams": [
    { "teamId": "...", "nameShort": "...", "seoname": "away-slug", "isHome": false },
    { "teamId": "...", "nameShort": "...", "seoname": "home-slug", "isHome": true }
  ],
  "periods": [
    {
      "periodNumber": 1,
      "periodDisplay": "Inning 1",
      "playbyplayStats": [
        {
          "teamId": "...",
          "plays": [
            { "playText": "...", "visitorScore": "0", "homeScore": "0" }
          ]
        },
        { "teamId": "...", "plays": [ ... ] }
      ]
    },
    ...
  ],
  "_source": "athletics" | "wmt_api" | "nuxt_data" | "cloudflare_ai"
}
```

Inside each `playbyplayStats[]` entry, a `teamId` identifies who is batting
so the frontend and `PbpTeamSplitter` can render the correct half-inning
header. When `teamId` is missing (Sidearm scoring-summary fallback), all
plays are in a single stat group and `PbpTeamSplitter` can repair it later
using roster data from the boxscore.

The boxscore payload is a sibling under `CachedGame.data_type = "athl_boxscore"`:

```json
{
  "teams": [ {...away...}, {...home...} ],
  "teamBoxscore": [
    { "teamId": "...", "teamName": "...", "seoname": "...", "isHome": false,
      "playerStats": [ { "firstName":..., "lastName":..., "position":..., "starter":..., "batterStats": {...}, "pitcherStats": {...}, "decision": "W" } ],
      "teamStats": { "batterTotals": {...}, "pitcherTotals": {...} },
      "_source": "..." }
  ],
  "linescores": [ { "period": "1", "visit": "0", "home": "2" }, ..., {"period":"R",...}, {"period":"H",...}, {"period":"E",...} ],
  "_source": "athletics" | "wmt_api" | "cloudflare_ai",
  "source_url": "...optional original HTML URL..."
}
```

Raw HTML for reparse lives in `ScrapedPage` (`page_type: "boxscore"`), set by
`BoxscoreFetchService.cache_raw_html` so re-parsing can happen without
re-scraping.

---

## Verb Filtering and Garbage Rejection

Three layers of verb filtering guard against bare-name / lineup entries being
stored as plays:

### Layer 1 — `WmtParser::WMT_PLAY_VERB`

```ruby
/singled|doubled|tripled|homered|grounded|flied|struck|walked|fouled|
 lined|popped|reached|sacrifice|stole|advanced|caught|picked|wild|
 passed|error|hit by|out at|flew out|pinch|to [a-z]+ for/i
```

Used at WMT ingest: any action/play whose text fails this regex is dropped.

### Layer 2 — `PitchByPitchParser.parse_from_cached_pbp!` (lines 237-238)

```ruby
next unless play_text.match?(/singled|doubled|...|hit by|sacrifice|bunted|error|out /i)
next if play_text.match?(/\A\d+\s+[A-Z]{1,3}\s+/i)   # "0 LF Sturgis, Makenna"
```

### Layer 3 — `CachedGame.pbp_quality_ok?` (model layer)

```ruby
PLAY_VERB = /struck|grounded|flied|singled|doubled|tripled|homered|walked|
             fouled|lined|popped|reached|sacrifice|stole|advanced|caught|
             picked|wild|passed|error|hit by/i
```

Rejects a payload when >50% of plays are "garbage" (playText <25 chars AND
does not match `PLAY_VERB`). Also rejects:

- Single-period dumps with >20 plays (no inning split → bad data).
- Non-last innings where all stat groups share the same `teamId`.
- Non-last innings with a single stat group containing >3 plays (teams unsplit).
- Empty `teams` array on multi-period games.

This is the **single source of truth** for PBP quality — `CachedGame.store`,
`CachedGame.fetch`, `BoxscoreFetchService.pbp_quality_ok?`, and the games
controller (`app/controllers/api/games_controller.rb:181`) all funnel through it.

---

## Name Cleanup Rules

### Last-First → First-Last (applied to play text)

Identical implementation in three places — keep in sync:

- `BoxScoreParsers::Base#clean_play_names`
  (`app/services/box_score_parsers/base.rb:428`)
- `AthleticsBoxScoreService#clean_play_names`
  (`app/services/athletics_box_score_service.rb:157`)
- `BoxScoreParsers::WmtParser#wmt_clean_names`
  (`app/services/box_score_parsers/wmt_parser.rb:271`)

```ruby
# "Torres,Isa" -> "Isa Torres"
text = text.gsub(/\b([A-Z][a-zA-Z'-]+),([A-Z][a-zA-Z'-]+)\b/) { "#{$2} #{$1}" }
# "Ganje, G." -> "G. Ganje"
text.gsub(/\b([A-Z][a-zA-Z'-]+), ([A-Z]\.)\s/) { "#{$2} #{$1} " }
```

### Split name (applied to player rows)

From `Shared::NameNormalizer#split_name`:

- `"Last, First"` → `["First", "Last"]`
- `"First Last"` → `["First", "Last"]`
- `"Last"` → `[nil, "Last"]`

### WMT xml_name

`player["xml_name"]` is **always** `"Last,First"` (no space). `WmtParser`
splits on `,` manually:

```ruby
name_parts = (p["xml_name"] || "").split(",").map(&:strip)
last_name = name_parts[0] || ""
first_name = name_parts[1] || ""
```

### PrestoSports duplicated names

`RosterParsers::PrestoSportsParser#dedupe_name` handles
`"Daci Sarver Daci Sarver"` by detecting when the first half equals the
second half:

```ruby
half = name.length / 2
if name.length > 4 && name[0...half].strip == name[half..].strip
  name[0...half].strip
else
  name
end
```

### Hidden Sidearm spans

Both `SidearmParser` and the legacy `AthleticsBoxScoreService.parse_batting_table`
remove hidden helper spans before reading name text:

```ruby
name_cell.css("span.hide-on-medium, span.mobile-jersey-number").each(&:remove)
```

The presence of non-hidden `<span>` wrappers inside the name cell is the
signal that a player is a **substitute** (Sidearm renders subs indented).

### Position leak-in

Some sites render the position inline in the name column:
`"ss Izzy Wilson"`. PrestoSports always does this; Sidearm does occasionally.
`PrestoSportsParser` defines `POSITION_PATTERN` with the full set of softball
positions including split-position slashes (`"c/1b"`) and strips the match
from the name.

---

## Related docs

- [06-ingestion-services.md](06-ingestion-services.md) — services that invoke these parsers on raw HTML/JSON
- [../pipelines/03-boxscore-pipeline.md](../pipelines/03-boxscore-pipeline.md) — end-to-end boxscore ingest that consumes parser output
- [../pipelines/02-pbp-pipeline.md](../pipelines/02-pbp-pipeline.md) — play-by-play pipeline and quality gate
- [../reference/glossary.md](../reference/glossary.md) — quality gate, PBP, boxscore terms used throughout
- [08-matching-services.md](08-matching-services.md) — `MatchingService` validates parsed rosters against Games
