"""
Clean the AISHE college base table and extract embedded AISHE IDs.

Source : data/raw/aishe_official_2012-13.csv
         ("List of all colleges - 2012-2013", data.gov.in, Ministry of Education)
Output : data/processed/aishe_colleges.csv
         columns: college_id, university_id, college_name, university_name,
                  college_type, state, district

Names arrive like 'Aazad College of Education (Id: C-39230)'. We split the
'(Id: ...)' suffix into its own column - those IDs are clean join keys.

Built by Chitranjan Jegadeesan - https://www.chitranjanjegadeesan.in/
"""
from pathlib import Path
import re
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "aishe_official_2012-13.csv"
OUT = ROOT / "data" / "processed" / "aishe_colleges.csv"

ID_RE = re.compile(r"\s*\(Id:\s*([A-Za-z0-9\-]+)\)\s*$")


def split_id(value: str):
    """Return (clean_name, id) by peeling the trailing '(Id: X)' marker."""
    m = ID_RE.search(str(value))
    if m:
        return ID_RE.sub("", str(value)).strip(), m.group(1)
    return str(value).strip(), None


def main():
    # Source is Windows-1252 encoded (smart quotes), not UTF-8.
    df = pd.read_csv(RAW, dtype=str, encoding="cp1252").fillna("")
    df["college_name"], df["college_id"] = zip(*df["College Name"].map(split_id))
    df["university_name"], df["university_id"] = zip(*df["University Name"].map(split_id))
    out = df.rename(columns={
        "College Type": "college_type",
        "State Name": "state",
        "District Name": "district",
    })[["college_id", "university_id", "college_name", "university_name",
        "college_type", "state", "district"]]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False, encoding="utf-8")
    print(f"Cleaned {len(out)} colleges | {out['state'].nunique()} states "
          f"| {out['college_id'].ne('').sum()} have AISHE IDs")
    print("\nTop 8 states by total colleges (AISHE):")
    for st, n in out["state"].value_counts().head(8).items():
        print(f"  {n:>5}  {st}")
    print(f"\nWritten -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
