# Conference Tournament Reference

Format and seeding per conference. Sourced from `tournament_style.md` at the repo root and seeded via `rake standings:seed_2026`.

---

## Configuration model

`conference_sources` table (seeded):

- `tournament_spots` — how many teams qualify (`0` if no tournament)
- `tournament_format` — one of `double_elim`, `single_elim`, `best_of_3`, `none`

See [rails/01-models.md](../rails/01-models.md) `ConferenceSource`.

---

## Format matrix

### Double elimination (~35 conferences)

Most common. Typical size 6 or 8 teams.

| Conference | Size | Division |
|-----------|------|----------|
| Sun Belt | 8 | D1 |
| AAC | 8 | D1 |
| Conference USA | 8 | D1 |
| MAC | 6 | D1 |
| Missouri Valley | 6 | D1 |
| ... (many more) | 6-8 | D1/D2/D3 |

### Single elimination

| Conference | Size |
|-----------|------|
| **SEC** | 15 |
| **Big Ten** | 12 |
| **Big 12** | 11 |
| **ACC** | 12 |

### Best-of-3 series

| Conference | Size |
|-----------|------|
| Ivy League | 4 |
| Northeast (NEC) | 4 |
| Patriot League | 4 |

### No tournament (regular-season champ → AQ)

| Conference |
|-----------|
| Big West |
| Mountain West |
| West Coast (WCC) |

---

## Bracket structure by size

`ConferenceScenarioService#build_bracket` uses hardcoded templates:

### 4-team (best-of-3 series)

```
1 vs 4
2 vs 3
→ Winners meet in championship series
```

### 6-team (byes for 1, 2)

```
Round 1:    Round 2:
3 vs 6      1 vs winner(4v5)
4 vs 5      2 vs winner(3v6)
```

### 8-team (standard double-elim)

```
1 vs 8
4 vs 5
3 vs 6
2 vs 7
```

### 11-team (Big 12 byes)

Top 5 get byes. Round 1: `6v11`, `7v10`, `8v9`.

### 12-team (ACC / Big Ten byes)

Top 4 get byes. Round 1: `5v12`, `6v11`, `7v10`, `8v9`.

### 15-team (SEC)

Five-round single-elimination. Top 4 seeds bye to the Quarterfinals; seeds 5-7 bye to the Second Round.

- **First Round (3 games):** `14v11`, `15v10`, `13v12`
- **Second Round (4 games):** `6 vs 11/14 winner`, `7 vs 10/15 winner`, `5 vs 12/13 winner`, `8v9`
- **Quarterfinals (4 games):** `3`, `2`, `4`, `1` each vs a Second Round winner (seed 1 specifically faces the `8/9` winner)
- **Semifinals → Championship**

Vanderbilt does not sponsor softball, so SEC tournament fields all 15 conference programs.

### Other sizes (fallback)

Power-of-2 seeding (e.g., 16-team bracket).

---

## Frontend display

Standings page renders the "Bracket as of Today" at the bottom:

- `BracketSection` React component (`app/javascript/components/`).
- Renders rounds as columns, matchups stacked vertically.
- Each matchup: seed number + team name. Byes show descriptive text like `"vs. 3/6 winner"`.
- Horizontal scroll for large brackets (SEC 15-team).
- Format label ("Double Elimination", "Single Elimination", "Best-of-3 Series") shown above bracket.
- Conferences with `tournament_format: "none"` show a text notice instead.

Hardcoded sizing constants in the component (`SLOT_H`, `MATCHUP_H`, `R1_GAP`, `ROUND_W`, `CONN_W`) are load-bearing for layout.

See [rails/17-frontend-components.md](../rails/17-frontend-components.md) `BracketSection`.

---

## Bracket updates

Bracket is computed per-request in `ConferenceScenarioService` — no caching. It reflects current standings instantly.

As teams lock in seeds, the bracket auto-populates. Only first-round matchups are shown with concrete teams; later rounds show TBD until first-round games are played (which won't happen until after the regular season).

---

## Adding a new conference

1. Insert a row into `conference_sources` (via migration or seed task):
   ```ruby
   ConferenceSource.create!(
     season: 2026,
     division: "d2",
     conference: "New Conference",
     standings_url: "https://example.com/standings",
     parser_type: "sidearm",     # or "sec", "boostsport"
     tournament_spots: 6,        # 0 for no tournament
     tournament_format: "double_elim"
   )
   ```
2. Ensure team slugs in that conference resolve via `OpponentResolver` — add `team_aliases` entries if needed.
3. Re-run `rake standings:seed_2026` or insert directly.
4. Next `StandingsRefreshJob` run will scrape and populate.

---

## Related docs

- [pipelines/04-standings-pipeline.md](../pipelines/04-standings-pipeline.md)
- [rails/10-scenario-service.md](../rails/10-scenario-service.md) — clinch/elim math + full bracket builder
- [rails/17-frontend-components.md](../rails/17-frontend-components.md) — `BracketSection` component
- `tournament_style.md` (repo root) — authoritative source of format and size per conference
