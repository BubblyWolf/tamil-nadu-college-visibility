"""
Parse the UGC 'State-wise list of Colleges Accredited by NAAC' PDF into a tidy CSV.

Source : data/raw/ugc_naac.pdf  (downloaded from ugc.gov.in)
Output : data/processed/naac_accredited_colleges.csv  (columns: state, college_name)

The PDF lays out, per page, a 3-column table [State, Sl No, HEI Name] where the
State cell is only filled on the first row of each state block. Long college names
wrap onto extra rows. We forward-fill the state and stitch wrapped names back.

Built by Chitranjan Jegadeesan - https://www.chitranjanjegadeesan.in/
"""
from pathlib import Path
import csv
import re
import pdfplumber

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "ugc_naac.pdf"
OUT = ROOT / "data" / "processed" / "naac_accredited_colleges.csv"

HEADER_NOISE = {
    "state wise list of colleges accreditated by naac",
    "state", "sl no", "hei name",
}

# Canonical list of Indian States + UTs. We anchor on these KNOWN values instead
# of trusting the PDF's merged-cell position (which renders unpredictably).
STATES = {
    "andaman & nicobar islands", "andhra pradesh", "arunachal pradesh", "assam",
    "bihar", "chandigarh", "chhattisgarh", "dadra & nagar haveli", "daman & diu",
    "delhi", "goa", "gujarat", "haryana", "himachal pradesh", "jammu & kashmir",
    "jharkhand", "karnataka", "kerala", "ladakh", "lakshadweep", "madhya pradesh",
    "maharashtra", "manipur", "meghalaya", "mizoram", "nagaland", "odisha",
    "puducherry", "punjab", "rajasthan", "sikkim", "tamil nadu", "telangana",
    "tripura", "uttar pradesh", "uttarakhand", "west bengal",
}


def normalize_state(cell: str) -> str | None:
    """Return the canonical state name if this cell IS a known state, else None."""
    if not cell:
        return None
    key = re.sub(r"\s+", " ", cell.strip().lower())
    key = key.replace(" and ", " & ")
    return key if key in STATES else None


def norm(line: str) -> str:
    return re.sub(r"\s+", " ", line.strip().lower()).replace(" and ", " & ")


def state_prefix(line: str) -> str | None:
    """If the line STARTS with a known state name, return that state, else None.
    We require a start-anchored match so a state mentioned inside a college's
    address (e.g. '...SAMASTIPUR, BIHAR') is never mistaken for a header."""
    low = norm(line)
    # longest match first (e.g. 'andhra pradesh' before any shorter prefix)
    for s in sorted(STATES, key=len, reverse=True):
        if low == s or low.startswith(s + " "):
            return s
    return None


def parse() -> list[dict]:
    rows: list[dict] = []
    current_state = None
    pending_name_parts: list[str] = []
    pending_sl = None

    def flush():
        nonlocal pending_name_parts, pending_sl
        if pending_sl is not None and pending_name_parts and current_state:
            name = re.sub(r"\s+", " ",
                          " ".join(p.strip() for p in pending_name_parts)).strip()
            if name:
                rows.append({"state": current_state, "sl_no": pending_sl,
                             "college_name": name})
        pending_name_parts = []
        pending_sl = None

    with pdfplumber.open(RAW) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for line in text.split("\n"):
                line = line.strip()
                if not line or norm(line) in HEADER_NOISE:
                    continue

                st = state_prefix(line)
                if st:
                    flush()
                    current_state = st
                    # strip the state header; the college part starts at first digit
                    m = re.search(r"\d", line)
                    if not m:
                        continue           # line was ONLY the state name
                    line = line[m.start():]

                # Now line is 'SlNo Name...' (new record) or a wrapped continuation
                m = re.match(r"(\d+)\s+(.+)", line)
                if m:
                    flush()
                    pending_sl, pending_name_parts = m.group(1), [m.group(2)]
                elif pending_sl is not None:
                    pending_name_parts.append(line)
        flush()
    return rows


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    rows = parse()
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["state", "sl_no", "college_name"])
        w.writeheader()
        w.writerows(rows)

    states = {}
    for r in rows:
        states[r["state"]] = states.get(r["state"], 0) + 1
    print(f"Parsed {len(rows)} accredited colleges across {len(states)} states.")
    print("Top 10 states by accredited-college count:")
    for st, n in sorted(states.items(), key=lambda x: -x[1])[:10]:
        print(f"  {n:>5}  {st}")
    print(f"\nWritten -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
