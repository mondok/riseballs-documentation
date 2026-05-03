# Parser MOVE Checklist (PRs #13-17)

**Plan reference:** `PIPELINE_REBUILD_PLAN.md` v5 §sequencing list lines 1831-1835.

The Stage 3 parser MOVEs are mechanical repackages with semantic
preservation. The dispatcher contract from PR #12 +
{@link LegacyBoxscoreDataAdapter} from PR #17a let every Stage 4-7
PR build against the new contract today; the actual MOVE PRs slot
the legacy parsers into the new package with no logic changes.

## PR #13 -- PbpParser MOVE

```
src/main/java/com/riseballs/scraper/service/parser/PbpParser.java
  -> src/main/java/com/riseballs/scraper/pipeline/stage3_parse/PbpParser.java
```

863 LOC. Pure repackage (rename `package` declaration, update
imports in callers). Three callers update:
- `service.PbpOrchestrator` (deleted in Phase 3c per inventory)
- `service.GameStatsWriter` (deleted Phase 3c)
- existing tests under `src/test/java/com/riseballs/scraper/service/parser/`

The fixture corpus (`nuxt_pbp_sdsu.json` + sibling files) MOVEs to
`src/test/resources/fixtures/parsers/pbp/`. Test class
`PbpParserTest` MOVEs to `pipeline.stage3_parse.PbpParserTest`.

Verify:
```sh
./gradlew compileJava compileTestJava
./gradlew test --tests "com.riseballs.scraper.pipeline.stage3_parse.PbpParserTest"
```

## PR #14 -- SidearmParser MOVE

```
src/main/java/com/riseballs/scraper/service/parser/SidearmBoxscoreParser.java
  -> src/main/java/com/riseballs/scraper/pipeline/stage3_parse/SidearmParser.java
```

1590 LOC. Largest MOVE. Same pattern: repackage + rename
(`SidearmBoxscoreParser` -> `SidearmParser`). Callers:
- `service.ScrapeOrchestrator` (deleted Phase 3c)
- `service.lineup.SidearmLineupParser` (KEEP_OUT_OF_SCOPE per inventory; update import only)
- `service.fetcher.UrlRediscoveryFetcher` (EXTRACT_LOGIC_TO_NEW; will become pipeline.stage2_fetch.UrlRediscovery)

Fixture corpus: `sidearm_boxscore.html` + sibling fixtures MOVE to
`src/test/resources/fixtures/parsers/sidearm/`.

After this MOVE, register the new SidearmParser as a
`@Component implements BoxscoreParser` so the
{@link BoxscoreParserDispatcher} picks it up:

```java
@Component
public class SidearmParser implements BoxscoreParser {
    @Override public String name() { return "sidearm"; }
    @Override public boolean canHandle(FetchedPage page) {
        return page.html() != null
            && page.html().contains("sidearm-stats");  // existing DOM marker
    }
    @Override public List<BoxscoreBundle> parse(FetchedPage page) {
        BoxscoreData legacy = parseLegacy(page.html(), page.sourceUrl());
        return adapter.adapt(legacy, page.sourceUrl(), page.fetchedAt());
    }
}
```

## PR #15 -- WmtParser MOVE

```
src/main/java/com/riseballs/scraper/service/parser/WmtResponseParser.java
  -> src/main/java/com/riseballs/scraper/pipeline/stage3_parse/WmtParser.java
```

669 LOC. Repackage + rename. JSON dispatch hint:

```java
@Override public boolean canHandle(FetchedPage page) {
    return page.sourceUrl() != null
        && page.sourceUrl().startsWith("wmt://");
}
```

Fixture: `wmt_boxscore.json` MOVE to
`src/test/resources/fixtures/parsers/wmt/`.

## PR #16 -- PrestoParser NEW

No existing Java class to MOVE. Port from Ruby
`app/services/box_score_parsers/presto_sports_parser.rb` (138 LOC,
DELETE list).

Stage 3 contract:
```java
@Component
public class PrestoParser implements BoxscoreParser {
    @Override public String name() { return "presto"; }
    @Override public boolean canHandle(FetchedPage page) {
        // Presto pages embed a #presto-stats anchor with a json-script tag.
        return page.html() != null
            && page.html().contains("presto-component-app-loader");
    }
    @Override public List<BoxscoreBundle> parse(FetchedPage page) { ... }
}
```

Fixture corpus: scrape one presto box-score page from each of the
known Presto schools (Aurora, Aldine, Mid-America Nazarene -- see
`presto_schedule_sample.html` for the one already checked in)
into `src/test/resources/fixtures/parsers/presto/`.

## PR #17 -- Dispatcher wiring

Already partially shipped in PR #12 (the dispatcher) + PR #17a
(LegacyBoxscoreDataAdapter). Final wiring step:

1. Once PR #14 + #15 + #16 land, the
   `BoxscoreParserDispatcher` constructor injects the three
   concrete parsers automatically (Spring's
   `List<BoxscoreParser>` injection).
2. Drop the `LegacyBoxscoreDataAdapter` once SidearmParser /
   WmtParser / PrestoParser emit `BoxscoreBundle` directly.
3. Update `BoxscoreData` to `@Deprecated` with a Javadoc pointing
   at `BoxscoreBundle`.

## Verification gate (each PR)

```sh
./gradlew compileJava compileTestJava
./gradlew test
./gradlew bootJar
```

After all four parser PRs land, ArchUnit rule 5 (`stage3_parse
classes may not inject any class with Repository in its name`)
becomes meaningfully enforced -- before then, vacuous since
stage3_parse was almost empty.
