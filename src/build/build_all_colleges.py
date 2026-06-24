# Author: Chitranjan Jegadeesan
# Purpose: Build all_colleges.json -- searchable index of every Tamil Nadu college,
#          merging the full AISHE college universe with NIRF rankings via fuzzy name matching.
# Data sources: AISHE 2012-13, NIRF 2025, TN Scorecard (NIRF 2025 cycle)
# Run: python src/build/build_all_colleges.py from project root

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

from rapidfuzz import fuzz

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "processed"
OUT = ROOT / "web" / "data" / "all_colleges.json"

AISHE_FILE = DATA / "aishe_colleges.csv"
NIRF_FILE = DATA / "nirf_rankings.csv"
SCORECARD_FILE = DATA / "tn_scorecard_metrics.csv"

FUZZY_THRESHOLD = 88  # token_sort_ratio threshold for a candidate match

# Generic words that appear in many college names and inflate token_sort scores.
# A match below 95 is only accepted when at least one non-generic word is shared
# between the AISHE name and the NIRF name (case-insensitive).
GENERIC_WORDS = {
    "college", "of", "arts", "science", "engineering", "technology",
    "and", "the", "for", "women", "institute", "management", "pharmacy",
    "education", "medical", "dental", "law", "commerce", "polytechnic",
    "university", "school", "centre", "center", "research", "studies",
    "a", "an", "in", "at", "to", "by", "dr", "prof", "sri", "sree",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def title_case(s: str) -> str:
    """Title-case a string, handling None/empty."""
    if not s:
        return ""
    return s.strip().title()


def load_aishe_tn() -> list[dict]:
    """Return AISHE rows where state is Tamil Nadu."""
    rows = []
    with open(AISHE_FILE, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if "tamil nadu" in r.get("state", "").lower():
                rows.append(r)
    return rows


def load_nirf_tn() -> list[dict]:
    """Return NIRF rows where state is Tamil Nadu."""
    rows = []
    with open(NIRF_FILE, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if "tamil nadu" in r.get("state", "").lower():
                rows.append(r)
    return rows


def load_scorecard() -> dict[str, int]:
    """Return {institute_id: nirf_rank} from tn_scorecard_metrics."""
    mapping = {}
    with open(SCORECARD_FILE, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            iid = r.get("institute_id", "").strip()
            rank_raw = r.get("nirf_rank", "")
            try:
                rank = int(float(rank_raw))
            except (ValueError, TypeError):
                rank = None
            if iid and rank is not None:
                # keep lowest (best) rank if duplicate
                if iid not in mapping or rank < mapping[iid]:
                    mapping[iid] = rank
    return mapping


def build_nirf_index(nirf_rows: list[dict], scorecard_rank: dict[str, int]) -> dict[str, dict]:
    """
    Build index keyed by institute_id.
    For institutions ranked in multiple NIRF categories, keep ALL (category, rank) pairs
    and designate the best-ranked (lowest rank number) as primary.
    Returns {institute_id: {name, city, categories: [{category, rank}], best_category, best_rank}}
    """
    by_id: dict[str, dict] = {}
    for r in nirf_rows:
        iid = r["institute_id"].strip()
        cat = r["category"].strip()
        try:
            rank = int(float(r["rank"]))
        except (ValueError, TypeError):
            rank = 9999
        if iid not in by_id:
            by_id[iid] = {
                "name": r["name"].strip(),
                "city": r["city"].strip(),
                "categories": [],
                "best_rank": rank,
                "best_category": cat,
            }
        by_id[iid]["categories"].append({"category": cat, "rank": rank})
        if rank < by_id[iid]["best_rank"]:
            by_id[iid]["best_rank"] = rank
            by_id[iid]["best_category"] = cat

    # Supplement / override nirf_rank with scorecard if available
    for iid, meta in by_id.items():
        if iid in scorecard_rank:
            meta["best_rank"] = scorecard_rank[iid]

    return by_id


def distinctive_words(name: str) -> set[str]:
    """Return non-generic words from a name (lowercase)."""
    import re
    tokens = re.split(r"[\s,.\-/&'`]+", name.lower())
    return {t for t in tokens if t and t not in GENERIC_WORDS and len(t) > 2}


def best_match(query: str, candidates: list[str]) -> tuple[str, float]:
    """Return (best_candidate, effective_score) for the highest token_sort_ratio match.

    For candidates scoring 88-94, an extra check requires that at least one
    distinctive (non-generic) word is shared between query and candidate.
    If not, the effective score is reduced to 0 to reject the match.
    """
    best_name, best_score = "", 0.0
    q = query.lower()
    q_words = distinctive_words(query)

    for c in candidates:
        raw_score = fuzz.token_sort_ratio(q, c.lower())
        if raw_score < FUZZY_THRESHOLD:
            continue
        # For borderline matches (88-94), require shared distinctive word
        if raw_score < 95:
            shared = q_words & distinctive_words(c)
            if not shared:
                continue  # reject: only generic words overlap
        if raw_score > best_score:
            best_score = raw_score
            best_name = c

    return best_name, best_score


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------
def build_all_colleges(verbose: bool = True) -> list[dict]:
    aishe_rows = load_aishe_tn()
    nirf_rows = load_nirf_tn()
    scorecard_rank = load_scorecard()

    # Build NIRF index (by institute_id)
    nirf_index = build_nirf_index(nirf_rows, scorecard_rank)

    # Build lookup: nirf_name -> institute_id (for fuzzy matching)
    nirf_names: list[str] = [meta["name"] for meta in nirf_index.values()]
    nirf_name_to_id: dict[str, str] = {meta["name"]: iid for iid, meta in nirf_index.items()}

    # ---------------------------------------------------------------------------
    # Phase 1: process every AISHE college
    # ---------------------------------------------------------------------------
    entries: list[dict] = []
    matched_nirf_ids: set[str] = set()

    # Track match diagnostics
    match_scores: list[float] = []
    example_matches: list[tuple] = []  # (aishe_name, nirf_name, score)

    for row in aishe_rows:
        aishe_name = row["college_name"].strip()
        district = title_case(row.get("district", ""))
        college_type = row.get("college_type", "").strip() or "Unknown"

        # Fuzzy match against NIRF TN institution names
        best_name, score = best_match(aishe_name, nirf_names)

        # For distribution diagnostics, record the raw best score regardless of
        # distinctive-word filter (so we see what scores are in the corpus)
        raw_best = max(
            (fuzz.token_sort_ratio(aishe_name.lower(), n.lower()) for n in nirf_names),
            default=0,
        )
        match_scores.append(raw_best)

        if score >= FUZZY_THRESHOLD and best_name:
            iid = nirf_name_to_id[best_name]
            meta = nirf_index[iid]
            matched_nirf_ids.add(iid)

            if len(example_matches) < 5:
                example_matches.append((aishe_name, best_name, score))

            entry = {
                "name": title_case(aishe_name),
                "district": district,
                "type": college_type,
                "ranked": True,
                "institute_id": iid,
                "category": meta["best_category"],
                "nirf_rank": meta["best_rank"],
                "categories": sorted(meta["categories"], key=lambda x: x["rank"]),
            }
        else:
            entry = {
                "name": title_case(aishe_name),
                "district": district,
                "type": college_type,
                "ranked": False,
                "institute_id": None,
                "category": None,
                "nirf_rank": None,
                "categories": [],
            }

        entries.append(entry)

    # ---------------------------------------------------------------------------
    # Phase 2: add ranked institutions not matched to any AISHE college
    # ---------------------------------------------------------------------------
    unmatched_nirf_count = 0
    for iid, meta in nirf_index.items():
        if iid not in matched_nirf_ids:
            unmatched_nirf_count += 1
            entry = {
                "name": title_case(meta["name"]),
                "district": title_case(meta["city"]),
                "type": "University",
                "ranked": True,
                "institute_id": iid,
                "category": meta["best_category"],
                "nirf_rank": meta["best_rank"],
                "categories": sorted(meta["categories"], key=lambda x: x["rank"]),
            }
            entries.append(entry)

    # ---------------------------------------------------------------------------
    # Dedupe on (name, district), keeping ranked over unranked
    # ---------------------------------------------------------------------------
    seen: dict[tuple, dict] = {}
    for e in entries:
        key = (e["name"].lower(), e["district"].lower())
        if key not in seen:
            seen[key] = e
        else:
            # prefer ranked entry
            if e["ranked"] and not seen[key]["ranked"]:
                seen[key] = e

    entries = sorted(seen.values(), key=lambda x: x["name"].lower())

    # ---------------------------------------------------------------------------
    # Summary / diagnostics
    # ---------------------------------------------------------------------------
    if verbose:
        total = len(entries)
        ranked = sum(1 for e in entries if e["ranked"])
        unranked = total - ranked

        above_88 = sum(1 for s in match_scores if s >= 88)
        between_70_88 = sum(1 for s in match_scores if 70 <= s < 88)
        below_70 = sum(1 for s in match_scores if s < 70)

        print("=" * 60)
        print("all_colleges.json build summary")
        print("=" * 60)
        print(f"Total entries:        {total}")
        print(f"  Ranked (NIRF):      {ranked}")
        print(f"  Unranked:           {unranked}")
        print(f"  Added from NIRF     {unmatched_nirf_count} (no AISHE match)")
        print()
        print("Fuzzy match score distribution (across all AISHE colleges):")
        print(f"  >= 88 (matched):    {above_88}")
        print(f"  70-87 (near miss):  {between_70_88}")
        print(f"  < 70 (no match):    {below_70}")
        print()
        print("5 example matched pairs (AISHE name -> NIRF name | score):")
        for aishe_n, nirf_n, sc in example_matches:
            print(f"  [{sc:.0f}] {aishe_n!r}")
            print(f"       -> {nirf_n!r}")

    return entries


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    entries = build_all_colleges(verbose=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    print()
    print(f"Written: {OUT}")
    print(f"File size: {OUT.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
