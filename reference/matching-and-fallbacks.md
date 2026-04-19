# Matching & Fallback Reference

Every "try X, then Y, then Z" chain in the system, in one place.

---

## Box score source fallback (`BoxscoreFetchService`)

The actual order in `app/services/boxscore_fetch_service.rb:5-53`:

```
(pre) CachedGame.fetch hit + scores_match?  → serve cached, done
(pre) discover_urls if game.game_team_links has no box_score_url
0. try_wmt                 → WMT JSON API
1. try_local_scraper       → local HTTP → HTML parse
2. try_playwright_html     → Playwright worker → HTML parse
3. try_html_scraper        → plain HTTP → HTML parse
4. try_rediscovery         → re-scrape schedule pages, refresh URLs,
                             retry parsers (terminal sink: store_result_without_rediscovery)
5. try_ai_extraction       → LLM last resort (logged at WARN)
→ nil → controller returns 503
```

Each `store_result` call runs a **score-match guard**: boxscore totals must match `Game.home_score`/`away_score` or it's assumed to be a wrong-game match (common with prior meetings in a series). When steps 0–3 parse successfully but fail the score check, the service falls through to `try_rediscovery` before giving up.

See [pipelines/03-boxscore-pipeline.md](../pipelines/03-boxscore-pipeline.md).

---

## PBP source fallback (inside each box score fetch)

For a single box score fetch attempt:

```
initial PBP  (embedded in boxscore response)
    ↓ fail / quality-gate reject
WMT API PBP  (if school has WMT ID)
    ↓
Sidearm scrape of PBP-only page
    ↓
nil
```

**Where:** `parse_play_by_play` in `BoxscoreFetchService`.

Then at the controller level, a higher-level fallback wraps box source fallback:

```
cached_games hit  (no quality re-check — may be stale)
    ↓ miss
negative cache hit  (pbp_miss:<gid>, 5-min TTL)
    ↓ miss
live athletics fetch
    ↓ fail
live WMT fetch
    ↓ fail
write pbp_miss:<gid> to Rails.cache
return 503
```

See [pipelines/02-pbp-pipeline.md](../pipelines/02-pbp-pipeline.md).

---

## Opponent/team resolution (Java `OpponentResolver`)

```
1. TeamAlias exact match (alias → slug)
2. Exact slug match
3. Parenthetical-suffix stripping  "Lee University (Tenn.)" → "Lee University"
   then name / longName lookup on stripped form
4. Team.name exact match
5. Team.longName exact match
6. Common suffix stripping  "University" / "State" / leading "The"
7. State abbreviation expansion/contraction  "St" ↔ "State" / "Tenn" ↔ "Tennessee"
8. FAIL → null (returns unresolved)
```

**Where:** `src/main/java/com/riseballs/scraper/reconciliation/schedule/OpponentResolver.java`.
See [scraper/03-parsers.md](../scraper/03-parsers.md) for the Mermaid decision tree.

---

## Team resolution (Rails `TeamMatcher`)

```
1. TeamAlias exact match
2. Exact slug match
3. Team.name / Team.longName exact (case-insensitive)
4. Parenthetical-suffix stripping
5. Common suffix stripping (University, State)
6. Trigram / prefix-guarded fuzzy match  (PlayerNameMatcher-style)
```

**Where:** `app/services/team_matcher.rb`.
Used by: `Api::TeamsController#schedule` fallback, `RosterService`, `GameStatsExtractor` for team_slug correction.

See [reference/slug-and-alias-resolution.md](slug-and-alias-resolution.md) for the side-by-side comparison.

---

## Opponent-game matching (Rails `TeamGameMatcher#find_opponent_game`)

When linking a `team_games` row to the opposing team's `team_games` row to form a shared `Game`:

```
1. Unclaimed candidate (game_id IS NULL)
   with matching game_number
       → STRONGEST: pair these
2. Any unclaimed candidate
       → prevent duplicate shell creation
3. Claimed candidate (game_id NOT NULL)
   with matching game_number
       → link into existing Game shell
4. First claimed candidate
       → fallback; may indicate DH drift
5. FAIL → no match, leave unlinked
```

**Where:** `app/services/team_game_matcher.rb`.
See [rails/08-matching-services.md](../rails/08-matching-services.md).

---

## Schedule parser dispatch (Java)

The Java scraper dispatches to the right parser based on team-level config (or URL sniffing):

| Detected site type | Parser |
|--------------------|--------|
| Sidearm athletics site | `SidearmScheduleParser` |
| PrestoSports | `PrestoSportsScheduleParser` |
| WMT / Learfield | `WmtScheduleParser` |
| WordPress (LSU-style) | `WordPressScheduleParser` |
| Unknown / falls back | Throws / skipped with log |

**Where:** `SchedulePageParser` (dispatcher) + `src/main/java/com/riseballs/scraper/reconciliation/schedule/*Parser.java`.
See [scraper/03-parsers.md](../scraper/03-parsers.md).

---

## Standings parser dispatch (Java)

Dispatched on `ConferenceSource.parser_type`:

| `parser_type` | Parser |
|---------------|--------|
| `sidearm` | `SidearmStandingsParser` |
| `sec` | `SecStandingsParser` |
| `boostsport` | `BoostsportStandingsParser` |

**Where:** `src/main/java/com/riseballs/scraper/standings/*Parser.java`.
See [pipelines/04-standings-pipeline.md](../pipelines/04-standings-pipeline.md).

---

## Roster augmentation dispatch (Java)

For a given team, pick the augment path:

```
if team.wmt_school_id set OR team domain in WMT_DOMAINS:
    → WmtRosterService (/website-api/player-rosters)
elif site is WordPress (LSU-style):
    → RosterAugmentService — WordPress branch (/wp-json/v1/staff?type=roster)
else:
    → RosterAugmentService — Sidearm bio pages (per-player HTML)
        requires: profile_url discovered first
```

**Where:** `src/main/java/com/riseballs/scraper/roster/*.java`.
See [pipelines/05-roster-pipeline.md](../pipelines/05-roster-pipeline.md).

---

## Sidearm bio parser fallback (Java `BioPageParser`)

Inside a single bio page HTML:

```
1. li/span pairs       (newer Vue templates)
2. dt/dd pairs         (older Sidearm)
3. JSON-LD             (schema.org metadata)
→ merge extracted fields
```

**Where:** `src/main/java/com/riseballs/scraper/roster/BioPageParser.java`.

---

## NCAA date action decision (Java `NcaaDateReconciliationService`)

For each game with `ncaa_contest_id` and a date mismatch vs NCAA:

```
boxScoresMatch?                            → MOVE (our game_date → NCAA's)
boxScoresDisagree?                         → NCAA_WRONG (flag NCAA)
our record is empty shell?                 → MERGE (delete our shell, keep NCAA row)
otherwise                                  → REVIEW (GameReview pending)
```

**Where:** `src/main/java/com/riseballs/scraper/reconciliation/NcaaDateReconciliationService.java`.
See [scraper/04-reconciliation.md](../scraper/04-reconciliation.md).

---

## Schedule reconciliation action priority (Java `ReconciliationExecutor`)

When multiple diffs exist for one game, actions apply in this order:

```
1. FINALIZE      — scheduled → final (triggers downstream)
2. FIX_SCORE     — only if game NOT locked
3. FIX_DATE
4. UNCANCEL
5. CREATE
6. DELETE_GHOST  — ONLY if both teams' pages agree game doesn't exist
```

**Where:** `src/main/java/com/riseballs/scraper/reconciliation/ReconciliationExecutor.java`.
See [pipelines/06-reconciliation-pipeline.md](../pipelines/06-reconciliation-pipeline.md).

---

## Game dedup fingerprint (Rails `GameDedupJob`)

For two candidate games with the same sorted team pair + game_date within 14 days:

```
1. Compare PlayerGameStat rows between the two games
2. Count common players with identical stats
3. IF count >= 5 → DUPLICATE
4. IF count < 5  → DIFFERENT (legitimate doubleheader; skip)
```

Winner selection: prefer `locked: true`, then most-complete stats.

**Where:** `app/jobs/game_dedup_job.rb`.
See [pipelines/06-reconciliation-pipeline.md](../pipelines/06-reconciliation-pipeline.md).

---

## Score validation verdict (Rails `ScoreValidationJob`)

For each recent game where `Game.home_score + away_score != sum(player_game_stats.runs_scored)`:

```
if batterTotals.runsScored == sum(player.runsScored):
    → AUTO_CORRECT (update Game, set locked=true, review approved)
else:
    → REVIEW (GameReview status=pending)

if state=cancelled AND has scores:
    → flag contradictory state
```

**Where:** `app/jobs/score_validation_job.rb`.
See [pipelines/06-reconciliation-pipeline.md](../pipelines/06-reconciliation-pipeline.md).

---

## Schedule source fallback (Rails)

Rarely used — the Java scraper is primary — but Rails has its own chain for emergency use:

```
NcaaScheduleService  (NCAA GraphQL — 6-strategy matcher + contest-ID dedup)
    ↓
NcaaScoreboardService  (with verify_contest_assignment for DH)
    ↓
EspnScoreboardService
    ↓
ScheduleService / CloudflareScheduleService  (LEGACY)
    ↓
AiScheduleService  (LLM — last resort, has a scoped-variable bug at line 104)
```

**Where:** `app/services/*_schedule_service.rb`.
See [rails/06-ingestion-services.md](../rails/06-ingestion-services.md).

---

## Predict service request chain (Rails)

For a single game detail page:

```
1. Check Game.state → if final/cancelled, return 204
2. Thread A: POST /v1/matchups/predict
   Thread B: POST /v1/matchups/keys-to-victory
3. Join both with 15s timeout
4. Any timeout or connection failure → 503
5. Combine responses → single JSON to frontend
```

**Where:** `app/services/predict_service_client.rb`, `app/controllers/api/predictions_controller.rb`.
See [pipelines/07-prediction-pipeline.md](../pipelines/07-prediction-pipeline.md).

---

## Summary table: "if this breaks, try that"

| Concern | Primary | Secondary | Tertiary | Last resort |
|---------|---------|-----------|----------|-------------|
| Box score | WMT API | local scraper HTML | Playwright HTML → plain HTTP → rediscovery | AI LLM extraction |
| PBP (live) | cached_games | Athletics | WMT | negative cache 503 |
| PBP (proactive) | `PbpOnFinalJob` w/ polynomial retry | — | — | operator rake task |
| Schedule | Java `TeamScheduleSyncService` | `ScheduleReconciliationJob` (daily) | `StuckScheduleRecoveryJob` (hourly) | NCAA/ESPN Rails services |
| Team name → slug (Java) | `TeamAlias` | exact slug | name/longName | suffix strip + state abbr |
| Team name → slug (Rails) | `TeamAlias` | exact slug | case-insensitive name | fuzzy match |
| Opponent game match | unclaimed + game_number | unclaimed any | claimed + game_number | claimed first |
| Roster augment | WMT API | WordPress | Sidearm bio pages | — |
| Standings | Java `StandingsOrchestrator` daily | — | — | manual scrape via admin UI |
| Prediction | live Predict call | — | — | 503 → hide panel |

---

## Cross-references

- [pipelines/](../pipelines/) — the horizontal view of each chain in context
- [reference/slug-and-alias-resolution.md](slug-and-alias-resolution.md) — detailed side-by-side of the two slug-resolution implementations
- [reference/glossary.md](glossary.md) — terminology (quality gate, shell, locked, etc.)
