# Matching & Fallback Reference

Every "try X, then Y, then Z" chain in the system, in one place.

## Table of Contents

- [Box score source fallback (`BoxscoreFetchService`)](#box-score-source-fallback-boxscorefetchservice)
- [PBP source fallback (inside each box score fetch)](#pbp-source-fallback-inside-each-box-score-fetch)
- [Opponent/team resolution (Java `OpponentResolver`)](#opponentteam-resolution-java-opponentresolver)
- [Team resolution (Rails `TeamMatcher`)](#team-resolution-rails-teammatcher)
- [Opponent-game matching (Rails `TeamGameMatcher#find_opponent_game`)](#opponent-game-matching-rails-teamgamematcherfind_opponent_game)
- [Schedule parser dispatch (Java)](#schedule-parser-dispatch-java)
- [Standings parser dispatch (Java)](#standings-parser-dispatch-java)
- [Roster augmentation dispatch (Java)](#roster-augmentation-dispatch-java)
- [Sidearm bio parser fallback (Java `BioPageParser`)](#sidearm-bio-parser-fallback-java-biopageparser)
- [NCAA date action decision (Java `NcaaDateReconciliationService`)](#ncaa-date-action-decision-java-ncaadatereconciliationservice)
- [Schedule reconciliation action priority (Java `ReconciliationExecutor`)](#schedule-reconciliation-action-priority-java-reconciliationexecutor)
- [Game dedup fingerprint (Rails `GameDedupJob`)](#game-dedup-fingerprint-rails-gamededupjob)
- [Score validation verdict (Rails `ScoreValidationJob`)](#score-validation-verdict-rails-scorevalidationjob)
- [Live-score overlay match ladder (browser, `lib/liveOverlay.js`)](#live-score-overlay-match-ladder-browser-libliveoverlayjs)
- [Schedule source fallback (Rails)](#schedule-source-fallback-rails)
- [Predict service request chain (Rails)](#predict-service-request-chain-rails)
- [Summary table: "if this breaks, try that"](#summary-table-if-this-breaks-try-that)
- [Cross-references](#cross-references)

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

## Live-score overlay match ladder (browser, `lib/liveOverlay.js`)

Added 2026-04-19 (mondok/riseballs#83). The browser fetches the Rails scoreboard and the `riseballs-live` overlay in parallel, then merges them client-side.

```
For each Rails scoreboard game G (with .gameID, .ncaaContestId, .gameNumber,
                                     home.names.seo, away.names.seo, .gameState):

1. Primary match: find overlay event E where E.ncaaContestId == G.ncaaContestId.
     → If found, apply overlay scores/state. Done.

2. Fallback match: find E where (E.homeSlug, E.awaySlug, E.gameNumber)
                               == (G.home.names.seo, G.away.names.seo, G.gameNumber).
     → If found, apply. Done.

3. Reversed-slug rescue: find E where (E.homeSlug, E.awaySlug) is the reversed
    pair vs G AND (E.gameNumber == G.gameNumber). Apply overlay's scores with
    home/away SWAPPED (Rails is authoritative on orientation).

4. Ambiguity guard: if steps 2 or 3 produce multiple candidate overlays for
    a single Rails game, skip the overlay (don't guess). Rails data renders.

5. Final protection: if G.gameState == "final", NEVER apply the overlay.
    Rails is authoritative on finals.
```

**Where the reconciliation happens twice:** step 1 relies on the overlay service having already run its own reconciliation between NCAA and ESPN (via `ScoreboardReconciler` inside `riseballs-live` — matches on `ncaaContestId` primary, `(homeSlug, awaySlug, startTimeEpoch within 30 min)` fallback, reversed-slug rescue with score swap, ambiguity skip, state-escalation rule `max(ncaa.state, espn.state)` over `scheduled < live < final`). The browser merge is a second reconciliation layer on top of that: overlay-vs-Rails rather than NCAA-vs-ESPN.

**Why all this machinery:** NCAA's `contestId` can lag publish (the re-enabled `NcaaGameDiscoveryJob` is closing that gap but doubleheaders in particular can have null contest ids for hours). Slug-based pairing covers the gap. Reversed-slug rescue handles home/away flips between sources. Ambiguity guard handles cases where two games of the same doubleheader can't be told apart from the overlay. Final protection handles the case where the overlay has stale data about a just-concluded game.

See `app/javascript/lib/liveOverlay.js` (Rails client) and `reconciler/ScoreboardReconciler.java` (overlay service).

---

## Schedule source fallback (Rails)

Rarely used — the Java scraper is primary — but Rails has its own chain for emergency use:

```
NcaaGameDiscoveryJob  (calls NCAA GraphQL directly; used to delegate to
                       NcaaScoreboardService, which was deleted 2026-04-19)
    ↓
ScheduleService / CloudflareScheduleService  (LEGACY)
    ↓
AiScheduleService  (LLM — last resort, has a scoped-variable bug at line 104)
```

> Both Ruby `NcaaScheduleService` and Ruby `NcaaScoreboardService` were deleted in Phase 0 of the riseballs-live rollout (commit `42b585a`, 2026-04-19). NCAA live-score data is now served by `riseballs-live`'s `NcaaScoreboardClient` (consumed by the browser). NCAA contest-id backfill on the Rails side runs through the re-enabled `NcaaGameDiscoveryJob`. Ruby `EspnScoreboardService` was deleted in Phase 8 of the same rollout (mondok/riseballs#84); ESPN data lives exclusively in `riseballs-live` now.

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
| Schedule | Java `TeamScheduleSyncService` (direct HTTP) | `SidearmScheduleParser` localscraper fallback (when direct fetch is bot-challenged) | `ScheduleReconciliationJob` (daily Java re-scrape) | — (`StuckScheduleRecoveryJob` + Ruby `NcaaScheduleService` / `NcaaScoreboardService` / `EspnScoreboardService` all deleted 2026-04-19/20) |
| NCAA contest-id backfill | Java `NcaaApiClient` during reconciliation | Rails `NcaaGameDiscoveryJob` (`*/20` + nightly sweep, re-enabled 2026-04-19) | — | — |
| Live score overlay | `riseballs-live` (NCAA + ESPN reconciled in-process, Caffeine-cached) | fresh 30s → stale 5m → negative 10s inside the overlay | browser fall-through to Rails-only data | — |
| Team name → slug (Java scraper) | `TeamAlias` | exact slug | name/longName | suffix strip + state abbr |
| Team name → slug (Rails) | `TeamAlias` | exact slug | case-insensitive name | fuzzy match |
| Team name → slug (`riseballs-live`) | `espn_slug_overrides.json` (163 entries, classpath) | `known_slugs.txt` (594 entries, classpath) | lowercase-collapse of raw ESPN slug | fail |
| Opponent game match | unclaimed + game_number | unclaimed any | claimed + game_number | claimed first |
| Live-overlay game match | `ncaaContestId` | `(homeSlug, awaySlug, gameNumber)` | reversed-slug rescue with score swap | ambiguity skip / final protection |
| Roster augment | WMT API | WordPress | Sidearm bio pages | — |
| Standings | Java `StandingsOrchestrator` daily | — | — | manual scrape via admin UI |
| Prediction | live Predict call | — | — | 503 → hide panel |

---

## Cross-references

- [pipelines/](../pipelines/) — the horizontal view of each chain in context
- [reference/slug-and-alias-resolution.md](slug-and-alias-resolution.md) — detailed side-by-side of the two slug-resolution implementations
- [reference/glossary.md](glossary.md) — terminology (quality gate, shell, locked, etc.)
