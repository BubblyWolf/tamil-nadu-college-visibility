"""
Parse the downloaded NIRF 2024 ranking pages into one tidy CSV.

Source : data/raw/nirf/<Category>.html   (one file per category, from nirfindia.org)
Output : data/processed/nirf_rankings.csv
         columns: category, institute_id, name, city, state, score, rank

NIRF publishes individual scores and ranks only for the top 100 of each
category; institutions below that are placed in unscored rank-bands and are not
included here. We parse every category page present in data/raw/nirf/.

Author: Chitranjan Jegadeesan - https://www.chitranjanjegadeesan.in/
"""
from pathlib import Path
import re
import warnings
import pandas as pd

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "nirf"
OUT = ROOT / "data" / "processed" / "nirf_rankings.csv"


def clean_name(name: str) -> str:
    name = re.sub(r"More Details.*$", "", str(name), flags=re.I)
    return re.sub(r"\s+", " ", name).strip(" |").strip()


def parse_one(path: Path) -> pd.DataFrame:
    tables = pd.read_html(path)
    cand = [t for t in tables if "Rank" in t.columns and "Name" in t.columns and len(t) > 5]
    if not cand:
        return pd.DataFrame()
    t = max(cand, key=len)
    keep = ["Institute ID", "Name", "City", "State", "Score", "Rank"]
    t = t[[c for c in keep if c in t.columns]].copy()
    t["Name"] = t["Name"].map(clean_name)
    t.insert(0, "category", path.stem)
    t.columns = [c.lower().replace(" ", "_") for c in t.columns]
    return t


def main():
    files = sorted(RAW.glob("*.html"))
    frames = []
    for p in files:
        df = parse_one(p)
        if df.empty:
            print(f"  skip {p.stem}: no scored ranking table")
            continue
        frames.append(df)
        print(f"  {p.stem:14} {len(df):>4} institutions")

    out = pd.concat(frames, ignore_index=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False, encoding="utf-8")

    print(f"\nTotal: {len(out)} scored rows across {out['category'].nunique()} categories.")
    print(f"Written -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
