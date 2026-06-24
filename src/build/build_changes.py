# Author: Chitranjan Jegadeesan
# Purpose: Compute NIRF ranking changes for Tamil Nadu institutions between 2024 and 2025.
#          Downloads 2024 NIRF category pages, parses them, compares with the existing
#          2025 nirf_rankings.csv, and writes web/data/changes.json.
#
# Run from project root:
#   python src/build/build_changes.py
#
# Re-running is safe: 2024 HTML files are written to data/raw/nirf_2024/ (separate from
# the 2025 files in data/raw/nirf/) and will be re-used if already present and valid.

import json
import re
import sys
import time
import unicodedata
import urllib.request
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[2]
RAW_NIRF_2024 = ROOT / "data" / "raw" / "nirf_2024"
NIRF_2025_CSV = ROOT / "data" / "processed" / "nirf_rankings.csv"
WEB_DATA      = ROOT / "web" / "data"
CHANGES_JSON  = WEB_DATA / "changes.json"

RAW_NIRF_2024.mkdir(parents=True, exist_ok=True)
WEB_DATA.mkdir(parents=True, exist_ok=True)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

YEAR_2024 = "2024"

CATEGORIES = [
    "Overall",
    "University",
    "College",
    "Engineering",
    "Management",
    "Pharmacy",
    "Medical",
    "Dental",
    "Law",
    "Architecture",
    "Research",
    "Agriculture",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fetch_url(url: str, dest: Path, min_bytes: int = 40_000) -> bool:
    """Download url to dest. Returns True if file size >= min_bytes after write."""
    if dest.exists() and dest.stat().st_size >= min_bytes:
        print(f"    CACHED {dest.name} ({dest.stat().st_size:,} bytes)")
        return True
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
        if len(data) < min_bytes:
            print(f"    SKIP  {url}: only {len(data)} bytes (< {min_bytes})")
            return False
        dest.write_bytes(data)
        print(f"    OK    {url}: {len(data):,} bytes -> {dest.name}")
        return True
    except Exception as exc:
        print(f"    FAIL  {url}: {exc}")
        return False


def clean_name(raw: str) -> str:
    """Strip 'More Details' suffix and extra whitespace from institute names."""
    text = re.sub(r"More\s+Details.*$", "", str(raw), flags=re.I)
    return re.sub(r"\s+", " ", text).strip(" |").strip()


def normalize_name(name: str) -> str:
    """
    Lowercase, remove punctuation/diacritics, collapse spaces.
    Used for fuzzy matching across years when institute_id differs.
    """
    # Unicode normalise -> drop diacritics
    text = unicodedata.normalize("NFKD", str(name))
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.lower()
    text = re.sub(r"[^a-z0-9 ]", " ", text)  # strip punctuation
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ---------------------------------------------------------------------------
# Step 1 – Download 2024 category HTML pages
# ---------------------------------------------------------------------------

def download_2024_pages() -> list[str]:
    """Fetch 2024 NIRF ranking pages; return list of category names that succeeded."""
    print("\n=== Step 1: Download 2024 NIRF category pages ===")
    found = []
    failed = []
    for cat in CATEGORIES:
        url  = f"https://www.nirfindia.org/Rankings/{YEAR_2024}/{cat}Ranking.html"
        dest = RAW_NIRF_2024 / f"{cat}.html"
        ok   = fetch_url(url, dest, min_bytes=40_000)
        if not ok:
            failed.append(cat)
            continue
        # Verify a parseable Rank/Name table exists
        try:
            tables = pd.read_html(dest)
            cand   = [t for t in tables if "Rank" in t.columns and "Name" in t.columns and len(t) > 5]
            if cand:
                found.append(cat)
                print(f"    -> table found ({len(cand[0])} rows)")
            else:
                print(f"    -> no Rank/Name table found; discarding")
                dest.unlink(missing_ok=True)
                failed.append(cat)
        except Exception as exc:
            print(f"    -> table parse error: {exc}; discarding")
            dest.unlink(missing_ok=True)
            failed.append(cat)
        time.sleep(0.5)

    print(f"\n  Categories downloaded successfully: {found}")
    print(f"  Categories failed/skipped:          {failed}")
    return found


# ---------------------------------------------------------------------------
# Step 2 – Parse 2024 HTML into a DataFrame
# ---------------------------------------------------------------------------

def parse_2024_rankings(found_cats: list[str]) -> pd.DataFrame:
    """Parse all downloaded 2024 HTML files; return a DataFrame matching nirf_rankings.csv schema."""
    print("\n=== Step 2: Parse 2024 rankings ===")
    frames = []
    for cat in found_cats:
        p = RAW_NIRF_2024 / f"{cat}.html"
        if not p.exists():
            continue
        try:
            tables = pd.read_html(p)
        except Exception as exc:
            print(f"  skip {cat}: read_html error: {exc}")
            continue
        cand = [t for t in tables if "Rank" in t.columns and "Name" in t.columns and len(t) > 5]
        if not cand:
            print(f"  skip {cat}: no scored ranking table")
            continue
        t = max(cand, key=len).copy()
        keep = ["Institute ID", "Name", "City", "State", "Score", "Rank"]
        t = t[[c for c in keep if c in t.columns]].copy()
        t["Name"] = t["Name"].map(clean_name)
        t.insert(0, "category", cat)
        t.columns = [c.lower().replace(" ", "_") for c in t.columns]
        frames.append(t)
        print(f"  {cat:22s}  {len(t):>4} total institutions")

    if not frames:
        print("  ERROR: No 2024 frames parsed.")
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True)
    print(f"\n  2024 total rows: {len(df)} across {df['category'].nunique()} categories")
    tn = df[df["state"].str.contains("Tamil Nadu", case=False, na=False)]
    print(f"  2024 Tamil Nadu rows: {len(tn)} entries, {tn['name'].nunique()} unique institutions")
    return df


# ---------------------------------------------------------------------------
# Step 3 – Match 2024 and 2025 TN institutions, classify changes
# ---------------------------------------------------------------------------

def build_changes(df_2024: pd.DataFrame, df_2025: pd.DataFrame) -> dict:
    """
    Match TN institutions across years; classify climbed/fell/entered/dropped.
    Matching priority:
      1. Exact institute_id match within same category.
      2. Normalized name + category match (fallback).
    Returns the changes.json payload and a diagnostics dict.
    """
    print("\n=== Step 3: Match and classify changes ===")

    TN_FILTER = "Tamil Nadu"
    tn_24 = df_2024[df_2024["state"].str.contains(TN_FILTER, case=False, na=False)].copy()
    tn_25 = df_2025[df_2025["state"].str.contains(TN_FILTER, case=False, na=False)].copy()

    print(f"  TN 2024 rows: {len(tn_24)}")
    print(f"  TN 2025 rows: {len(tn_25)}")

    # Add normalized-name column for fallback matching
    tn_24["norm_name"] = tn_24["name"].map(normalize_name)
    tn_25["norm_name"] = tn_25["name"].map(normalize_name)

    # Ensure rank and score are numeric
    for col in ["rank", "score"]:
        tn_24[col] = pd.to_numeric(tn_24[col], errors="coerce")
        tn_25[col] = pd.to_numeric(tn_25[col], errors="coerce")

    climbed  = []
    fell     = []
    same     = []
    entered  = []
    dropped  = []

    # Track per-match diagnostics
    id_matches   = 0
    name_matches = 0
    unmatched_25 = 0
    unmatched_24 = 0

    # Keep track of which 2024 rows were matched (to identify "dropped")
    matched_24_indices = set()

    categories_seen = set(tn_24["category"].unique()) | set(tn_25["category"].unique())

    for cat in sorted(categories_seen):
        rows_24 = tn_24[tn_24["category"] == cat].copy()
        rows_25 = tn_25[tn_25["category"] == cat].copy()

        # Build lookup dicts for fast matching
        # Primary: institute_id -> row
        id_map_24   = {str(r["institute_id"]).strip(): r for _, r in rows_24.iterrows()
                       if pd.notna(r.get("institute_id"))}
        name_map_24 = {r["norm_name"]: r for _, r in rows_24.iterrows()}

        matched_25_ids_24 = set()  # institute_id or norm_name keys in rows_24 that matched

        for _, row25 in rows_25.iterrows():
            iid25  = str(row25.get("institute_id", "")).strip()
            norm25 = row25["norm_name"]

            matched_row24 = None
            match_method  = None

            # Try institute_id first
            if iid25 and iid25 in id_map_24:
                matched_row24 = id_map_24[iid25]
                match_method  = "id"
                matched_25_ids_24.add(iid25)
            # Fallback: normalized name
            elif norm25 in name_map_24:
                matched_row24 = name_map_24[norm25]
                match_method  = "name"
                matched_25_ids_24.add(matched_row24["norm_name"])

            if matched_row24 is not None:
                # Track matched 24 rows (by original index)
                matched_24_indices.add(matched_row24.name)

                r24 = int(matched_row24["rank"]) if pd.notna(matched_row24["rank"]) else None
                r25 = int(row25["rank"])          if pd.notna(row25["rank"])          else None

                if r24 is None or r25 is None:
                    continue  # skip if rank missing

                s24 = matched_row24.get("score")
                s25 = row25.get("score")
                s24 = float(s24) if pd.notna(s24) else None
                s25 = float(s25) if pd.notna(s25) else None

                entry = {
                    "name":      row25["name"],
                    "category":  cat,
                    "rank_2024": r24,
                    "rank_2025": r25,
                    "delta":     r24 - r25,   # positive = improved (lower rank number)
                    "score_2024": round(s24, 2) if s24 is not None else None,
                    "score_2025": round(s25, 2) if s25 is not None else None,
                }

                if match_method == "id":
                    id_matches += 1
                else:
                    name_matches += 1

                if r25 < r24:
                    climbed.append(entry)
                elif r25 > r24:
                    fell.append(entry)
                else:
                    same.append(entry)
            else:
                # In 2025 TN but not matched in 2024 -> "entered"
                unmatched_25 += 1
                entered.append({
                    "name":      row25["name"],
                    "category":  cat,
                    "rank_2025": int(row25["rank"]) if pd.notna(row25["rank"]) else None,
                })

        # 2024 TN rows not matched by any 2025 row -> "dropped"
        for _, row24 in rows_24.iterrows():
            iid24  = str(row24.get("institute_id", "")).strip()
            norm24 = row24["norm_name"]
            # Was this row matched?
            if iid24 in matched_25_ids_24 or norm24 in matched_25_ids_24:
                continue
            # Also skip if the original index was already counted via id match
            if row24.name in matched_24_indices:
                continue
            unmatched_24 += 1
            dropped.append({
                "name":      row24["name"],
                "category":  cat,
                "rank_2024": int(row24["rank"]) if pd.notna(row24["rank"]) else None,
            })

    total_matched = id_matches + name_matches

    print(f"\n  Matched institutions:   {total_matched}")
    print(f"    - by institute_id:    {id_matches}")
    print(f"    - by name+category:   {name_matches}")
    print(f"  Climbed (rank improved): {len(climbed)}")
    print(f"  Fell    (rank worsened): {len(fell)}")
    print(f"  Same rank:               {len(same)}")
    print(f"  Entered (new in 2025):   {len(entered)}")
    print(f"  Dropped (absent 2025):   {len(dropped)}")

    # Top movers: sort by |delta| desc, take up to 20
    all_movers = climbed + fell
    all_movers.sort(key=lambda x: abs(x["delta"]), reverse=True)
    movers_top20 = []
    for m in all_movers[:20]:
        movers_top20.append({
            "name":      m["name"],
            "category":  m["category"],
            "rank_2024": m["rank_2024"],
            "rank_2025": m["rank_2025"],
            "delta":     m["delta"],
            "direction": "up" if m["delta"] > 0 else "down",
        })

    # Summary
    n_cats = len(
        set(r["category"] for r in climbed)
        | set(r["category"] for r in fell)
        | set(r["category"] for r in entered)
        | set(r["category"] for r in dropped)
    )

    payload = {
        "summary": {
            "climbed":    len(climbed),
            "fell":       len(fell),
            "entered":    len(entered),
            "dropped":    len(dropped),
            "categories": n_cats,
        },
        "movers":  movers_top20,
        "entered": entered,
        "dropped": dropped,
    }

    diagnostics = {
        "total_matched":  total_matched,
        "id_matches":     id_matches,
        "name_matches":   name_matches,
        "climbed":        len(climbed),
        "fell":           len(fell),
        "same":           len(same),
        "entered":        len(entered),
        "dropped":        len(dropped),
        "top5_movers":    movers_top20[:5],
    }

    return payload, diagnostics


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("build_changes.py -- NIRF 2024->2025 Tamil Nadu rank changes")
    print("=" * 60)

    # Step 1: Download 2024 pages
    found_cats = download_2024_pages()
    if not found_cats:
        print("\nERROR: No 2024 categories downloaded. Aborting.")
        sys.exit(1)

    # Step 2: Parse 2024 HTML
    df_2024 = parse_2024_rankings(found_cats)
    if df_2024.empty:
        print("\nERROR: 2024 parse produced empty DataFrame. Aborting.")
        sys.exit(1)

    # Step 3: Load 2025 CSV
    print(f"\n=== Loading 2025 data from {NIRF_2025_CSV.name} ===")
    if not NIRF_2025_CSV.exists():
        print(f"ERROR: {NIRF_2025_CSV} not found. Run refresh_2025.py first.")
        sys.exit(1)
    df_2025 = pd.read_csv(NIRF_2025_CSV)
    print(f"  2025 rows: {len(df_2025)} across {df_2025['category'].nunique()} categories")

    # Step 4: Build changes and diagnostics
    payload, diag = build_changes(df_2024, df_2025)

    # Step 5: Write changes.json
    print(f"\n=== Writing {CHANGES_JSON.name} ===")
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    CHANGES_JSON.write_text(text, encoding="utf-8")
    # Validate
    _ = json.loads(CHANGES_JSON.read_text(encoding="utf-8"))
    print(f"  OK — {CHANGES_JSON}")

    # Step 6: Print verification report
    print("\n" + "=" * 60)
    print("VERIFICATION REPORT")
    print("=" * 60)
    print(f"  Matched TN institutions (both years): {diag['total_matched']}")
    print(f"    matched by institute_id:            {diag['id_matches']}")
    print(f"    matched by name+category:           {diag['name_matches']}")
    print(f"  Climbed (rank improved):              {diag['climbed']}")
    print(f"  Fell    (rank worsened):              {diag['fell']}")
    print(f"  Same rank:                            {diag['same']}")
    print(f"  Entered (new in 2025):                {diag['entered']}")
    print(f"  Dropped (absent in 2025):             {diag['dropped']}")
    print()
    print("  Top 5 movers (by |delta|):")
    for i, m in enumerate(diag["top5_movers"], 1):
        direction = "UP" if m["delta"] > 0 else "DOWN"
        print(f"    {i}. {m['name'][:55]:<55} "
              f"[{m['category']}]  {m['rank_2024']} -> {m['rank_2025']}  "
              f"({direction} {abs(m['delta'])})")
    print()
    print(f"  Output: {CHANGES_JSON}")
    print("Done.")


if __name__ == "__main__":
    main()
