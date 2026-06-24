# Author: Chitranjan Jegadeesan
# Purpose: Tag each row in tn_scorecard_metrics.csv with the NIRF rankings year
#          found inside the institution's scorecard text (or PDF fallback).
#          Year is extracted via: India Rankings\s*'?(20\d\d)
# Run: python src/clean/tag_scorecard_year.py from project root

import re
import sys
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR   = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent

TEXT_DIR  = PROJECT_ROOT / "data" / "raw" / "scorecards_text"
PDF_DIR   = PROJECT_ROOT / "data" / "raw" / "scorecards"
SCORE_CSV = PROJECT_ROOT / "data" / "processed" / "tn_scorecard_metrics.csv"

YEAR_RE = re.compile(r"India Rankings\s*'?(20\d\d)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def extract_year_from_text(path: Path) -> int | None:
    """Return the first NIRF year found in a plain-text scorecard file."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        m = YEAR_RE.search(text)
        if m:
            return int(m.group(1))
    except Exception as exc:
        print(f"  WARNING: could not read {path.name}: {exc}", file=sys.stderr)
    return None


def extract_year_from_pdf(path: Path) -> int | None:
    """Return the first NIRF year found in a PDF scorecard (pdfplumber)."""
    try:
        import pdfplumber  # type: ignore
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                m = YEAR_RE.search(page_text)
                if m:
                    return int(m.group(1))
    except ImportError:
        print(
            "  WARNING: pdfplumber not installed; cannot parse PDF fallback.",
            file=sys.stderr,
        )
    except Exception as exc:
        print(f"  WARNING: could not parse PDF {path.name}: {exc}", file=sys.stderr)
    return None


def get_scorecard_year(institute_id: str, category: str) -> int | None:
    """
    Look up the NIRF year for one (institute_id, category) pair.
    Checks .txt first; falls back to .pdf.
    """
    stem = f"{category}_{institute_id}"
    txt_path = TEXT_DIR / f"{stem}.txt"
    pdf_path = PDF_DIR  / f"{stem}.pdf"

    if txt_path.exists():
        year = extract_year_from_text(txt_path)
        if year:
            return year

    if pdf_path.exists():
        year = extract_year_from_pdf(pdf_path)
        if year:
            return year

    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print(f"Loading: {SCORE_CSV}")
    df = pd.read_csv(SCORE_CSV)
    print(f"  Rows: {len(df)}, Columns: {list(df.columns)}")

    years = []
    missing = []

    for _, row in df.iterrows():
        iid = str(row["institute_id"]).strip()
        cat = str(row["category"]).strip()
        year = get_scorecard_year(iid, cat)
        years.append(year)
        if year is None:
            missing.append(f"{cat}_{iid}")

    df["scorecard_year"] = pd.array(years, dtype=pd.Int64Dtype())

    # ---------------------------------------------------------------------------
    # Report
    # ---------------------------------------------------------------------------
    print("\n--- Year distribution (all rows) ---")
    print(df["scorecard_year"].value_counts(dropna=False).to_string())

    print("\n--- Year distribution by category ---")
    pivot = (
        df.groupby(["category", "scorecard_year"], dropna=False)
        .size()
        .unstack(fill_value=0)
    )
    print(pivot.to_string())

    if missing:
        print(f"\n--- Could not detect year for {len(missing)} file(s) ---")
        for f in missing:
            print(f"  {f}")
    else:
        print("\nAll rows tagged successfully.")

    # ---------------------------------------------------------------------------
    # Save
    # ---------------------------------------------------------------------------
    df.to_csv(SCORE_CSV, index=False)
    print(f"\nSaved: {SCORE_CSV}")


if __name__ == "__main__":
    main()
