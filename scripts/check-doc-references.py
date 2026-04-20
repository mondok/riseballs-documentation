#!/usr/bin/env python3
"""
check-doc-references.py — audit riseballs-documentation for stale source-file references.

Walks every .md file in this repo, extracts backtick-enclosed source-file paths
(ending in .rb, .java, .py, .jsx, .tsx, .ts, .js, .gradle, .rake, .yml, .yaml),
and verifies each path resolves in the matching sibling service repo.

Exit 0 if every reference resolves; exit 1 if any are stale.

Usage:
    python3 scripts/check-doc-references.py
    python3 scripts/check-doc-references.py --parent /path/to/riseballs-parent
    python3 scripts/check-doc-references.py --verbose

Assumes the docs repo is cloned as a sibling to the service repos:
    riseballs-parent/
    ├── riseballs/
    ├── riseballs-scraper/
    ├── riseballs-predict/
    ├── riseballs-live/
    └── riseballs-documentation/       # this repo

Wire up as a manual audit before doc PRs, or as a pre-push hook in each
service repo (see the HOOK EXAMPLE section at the bottom of this file).
"""

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional, Tuple

SOURCE_EXTS_RE = r"(?:rb|java|py|jsx|tsx|ts|js|gradle|rake|yml|yaml)"

# Backtick-enclosed path: at least one slash, ends in a source ext,
# optionally followed by :line, :start-end, or #method-anchor.
REF_RE = re.compile(
    rf"`([a-zA-Z0-9_./-]+/[a-zA-Z0-9_.-]+\.{SOURCE_EXTS_RE})"
    rf"(?::\d+(?:-\d+)?|#[a-zA-Z0-9_!?=]+)?`"
)

# Doc directory → ordered list of service repos to try.
# Hub dirs cite across services, so we try all.
ALL_SERVICES = ["riseballs", "riseballs-scraper", "riseballs-predict", "riseballs-live"]
REPO_SEARCH_ORDER = {
    "rails": ["riseballs"],
    "scraper": ["riseballs-scraper"],
    "predict": ["riseballs-predict"],
    "live": ["riseballs-live"],
    "architecture": ALL_SERVICES,
    "pipelines": ALL_SERVICES,
    "reference": ALL_SERVICES,
    "operations": ALL_SERVICES,
    "reviews": ALL_SERVICES,
    "": ALL_SERVICES,  # top-level .md like README.md
}

# Each service has idiomatic path prefixes. When a ref doesn't start with
# one of these, we try them as fallbacks — handles Java package shorthand
# (`controller/ScoreboardController.java`) and Rails shorthand
# (`api/games_controller.rb` → `app/controllers/api/games_controller.rb`).
PREFIX_FALLBACKS = {
    "riseballs": [
        "app/controllers/",
        "app/models/",
        "app/services/",
        "app/jobs/",
        "app/helpers/",
        "app/javascript/",
        "lib/tasks/",
    ],
    "riseballs-scraper": [
        "src/main/java/com/riseballs/scraper/",
        "src/test/java/com/riseballs/scraper/",
    ],
    "riseballs-live": [
        "src/main/java/com/riseballs/live/",
        "src/test/java/com/riseballs/live/",
    ],
    "riseballs-predict": [
        "app/",
        "tests/",
    ],
}


def resolve(parent: Path, ref: str, doc_subdir: str) -> Optional[Path]:
    # 1. Cross-repo absolute path (ref starts with a known repo name).
    head = ref.split("/", 1)[0]
    if head in ALL_SERVICES:
        candidate = parent / ref
        if candidate.is_file():
            return candidate

    # 2. Direct resolution against each candidate service repo.
    for repo in REPO_SEARCH_ORDER.get(doc_subdir, ALL_SERVICES):
        candidate = parent / repo / ref
        if candidate.is_file():
            return candidate

    # 3. Try well-known prefixes per repo (Java package shorthand,
    #    Rails app/controllers/ shorthand, etc.).
    for repo in REPO_SEARCH_ORDER.get(doc_subdir, ALL_SERVICES):
        for prefix in PREFIX_FALLBACKS.get(repo, []):
            candidate = parent / repo / (prefix + ref)
            if candidate.is_file():
                return candidate

    return None


def load_ignore(docs: Path) -> set:
    """Load baseline of refs known to be stale (e.g., DELETED file stubs)."""
    path = docs / "scripts" / ".doc-ref-ignore"
    if not path.is_file():
        return set()
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


def write_ignore(docs: Path, refs: set) -> None:
    path = docs / "scripts" / ".doc-ref-ignore"
    header = (
        "# Baseline of intentionally stale source-file references.\n"
        "# Regenerate with: python3 scripts/check-doc-references.py --write-baseline\n"
        "# Each line is a <doc-relative-path>:<source-ref> pair. Remove entries\n"
        "# as docs are updated to point at live code.\n\n"
    )
    path.write_text(header + "\n".join(sorted(refs)) + "\n", encoding="utf-8")


def audit(parent: Path, docs: Path, verbose: bool) -> Tuple[dict, int, set]:
    """Return (stale dict, total count, set of 'doc:ref' pair keys for baseline use)."""
    stale: dict = defaultdict(list)
    stale_keys: set = set()
    total = 0
    for md in sorted(docs.rglob("*.md")):
        if any(part.startswith(".") for part in md.parts):
            continue
        rel = md.relative_to(docs)
        doc_subdir = rel.parts[0] if len(rel.parts) > 1 else ""
        text = md.read_text(encoding="utf-8")
        for m in REF_RE.finditer(text):
            ref = m.group(1)
            if ref.endswith(".md"):
                continue
            total += 1
            resolved = resolve(parent, ref, doc_subdir)
            if resolved is None:
                stale[str(rel)].append(ref)
                stale_keys.add(f"{rel}:{ref}")
            elif verbose:
                print(f"  OK  {rel} → {ref}")
    return stale, total, stale_keys


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--parent",
        type=Path,
        default=None,
        help="riseballs-parent workspace root (default: docs parent dir)",
    )
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument(
        "--write-baseline",
        action="store_true",
        help="Write the current stale set to scripts/.doc-ref-ignore as the baseline.",
    )
    args = ap.parse_args()

    docs = Path(__file__).resolve().parent.parent
    parent = args.parent or docs.parent
    if not docs.is_dir():
        print(f"ERROR: docs dir not found: {docs}", file=sys.stderr)
        return 2
    if not parent.is_dir():
        print(f"ERROR: parent dir not found: {parent}", file=sys.stderr)
        return 2

    stale, total, stale_keys = audit(parent, docs, args.verbose)

    if args.write_baseline:
        write_ignore(docs, stale_keys)
        print(f"Wrote baseline: {len(stale_keys)} refs marked intentional in scripts/.doc-ref-ignore")
        return 0

    ignored = load_ignore(docs)
    # Remove baseline-ignored pairs from the stale set.
    filtered: dict = defaultdict(list)
    for doc, refs in stale.items():
        for ref in refs:
            if f"{doc}:{ref}" not in ignored:
                filtered[doc].append(ref)

    new_stale_count = sum(len(v) for v in filtered.values())
    baseline_count = len(stale_keys) - (len(stale_keys) - len(ignored & stale_keys))
    if not filtered:
        print(
            f"OK — {total} source-file references checked, 0 new stale "
            f"(plus {len(ignored)} baselined as intentional)."
        )
        return 0

    print(
        f"STALE — {new_stale_count} NEW stale source-file references "
        f"(baseline: {len(ignored)}):\n"
    )
    for doc, refs in sorted(filtered.items()):
        print(f"  {doc}:")
        for ref in refs:
            print(f"    - {ref}")
    print(
        "\nFix the reference or update the doc to describe the new location. "
        "If the ref is intentionally illustrative (e.g., a DELETED file stub), "
        "re-run with --write-baseline to re-baseline."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())

# ---------------------------------------------------------------------------
# HOOK EXAMPLE — install in a service repo to block commits that break docs:
#
#   $ cat > .git/hooks/pre-push <<'SH'
#   #!/bin/sh
#   python3 ../riseballs-documentation/scripts/check-doc-references.py || {
#     echo "Doc-reference check failed. Update riseballs-documentation/ then re-push."
#     exit 1
#   }
#   SH
#   $ chmod +x .git/hooks/pre-push
# ---------------------------------------------------------------------------
