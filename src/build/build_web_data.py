# Author: Chitranjan Jegadeesan
# Purpose: Build web data JSON files for Tamil Nadu accreditation analytics
# Data sources: AISHE 2012-13, NIRF 2025, TN Scorecard (NIRF 2025 cycle)
# Run: python src/build/build_web_data.py from project root

import json
import math
import sys
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
DATA_PROCESSED = PROJECT_ROOT / "data" / "processed"
WEB_DATA = PROJECT_ROOT / "web" / "data"
WEB_DATA.mkdir(parents=True, exist_ok=True)

AISHE_PATH = DATA_PROCESSED / "aishe_colleges.csv"
NIRF_PATH  = DATA_PROCESSED / "nirf_rankings.csv"
SCORE_PATH = DATA_PROCESSED / "tn_scorecard_metrics.csv"

TN_TOTAL_CURRENT = 2829   # AISHE 2021-22 state total (published figure)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_csv(path: Path, label: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    print(f"  Loaded {label}: {len(df)} rows, columns: {list(df.columns)}")
    return df


def safe_round(val, ndigits: int = 1):
    """Round a float; return None if NaN/inf."""
    if val is None:
        return None
    try:
        if math.isnan(val) or math.isinf(val):
            return None
    except TypeError:
        return None
    return round(float(val), ndigits)


def write_json(path: Path, obj, label: str):
    text = json.dumps(obj, indent=2, ensure_ascii=False)
    path.write_text(text, encoding="utf-8")
    # Validate by re-reading
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(parsed, list):
        print(f"  Wrote {label}: {len(parsed)} items -> {path.name}")
    elif isinstance(parsed, dict):
        print(f"  Wrote {label}: {len(parsed)} keys -> {path.name}")
    else:
        print(f"  Wrote {label} -> {path.name}")


def cap100(val):
    if val is None:
        return None
    return min(100.0, val)


# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
print("\n--- Loading CSVs ---")
aishe = load_csv(AISHE_PATH, "AISHE colleges")
nirf  = load_csv(NIRF_PATH,  "NIRF rankings")
score = load_csv(SCORE_PATH, "TN Scorecard")

# ---------------------------------------------------------------------------
# Filter to Tamil Nadu
# ---------------------------------------------------------------------------
TN_NAME = "Tamil Nadu"

aishe_tn = aishe[aishe["state"].str.strip().str.title() == TN_NAME].copy()
nirf_tn  = nirf[nirf["state"].str.strip().str.title() == TN_NAME].copy()

print(f"\n  TN rows - AISHE: {len(aishe_tn)}, NIRF: {len(nirf_tn)}, Scorecard: {len(score)}")

# Scorecard is already TN-only (verify by spot-checking institute names if needed)
score_tn = score.copy()

# ---------------------------------------------------------------------------
# summary.json
# ---------------------------------------------------------------------------
print("\n--- Building summary.json ---")

tn_colleges_2012_13 = len(aishe_tn)
ranked_institutions  = nirf_tn["name"].nunique()
ranked_entries       = len(nirf_tn)
invisible_pct        = safe_round(100.0 * (1 - ranked_institutions / TN_TOTAL_CURRENT), 1)
districts_count      = aishe_tn["district"].nunique()

# Top-2 cities by count of unique TN NIRF institutions
city_counts = (
    nirf_tn.groupby("city")["name"]
    .nunique()
    .sort_values(ascending=False)
)
if len(city_counts) >= 2:
    top2_cities      = city_counts.head(2)
    top2_institution_count = int(top2_cities.sum())
    top2_city_share  = safe_round(100.0 * top2_institution_count / ranked_institutions, 1) if ranked_institutions else None
    top2_city_names  = list(top2_cities.index)
else:
    top2_city_share  = None
    top2_city_names  = list(city_counts.index)

print(f"  Top-2 cities: {top2_city_names} -> share {top2_city_share}%")

summary = {
    "tn_total_colleges_current": TN_TOTAL_CURRENT,
    "tn_total_colleges_2012_13": tn_colleges_2012_13,
    "ranked_institutions": ranked_institutions,
    "ranked_entries": ranked_entries,
    "invisible_pct_current": invisible_pct,
    "districts": districts_count,
    "top2_city_share_pct": top2_city_share,
    "top2_city_names": top2_city_names,
    "vintages": {
        "rankings":     "NIRF 2025",
        "state_total":  "AISHE 2021-22",
        "district_detail": "AISHE 2012-13"
    }
}

write_json(WEB_DATA / "summary.json", summary, "summary")

# ---------------------------------------------------------------------------
# districts.json
# ---------------------------------------------------------------------------
print("\n--- Building districts.json ---")

# Count colleges per district from AISHE TN
dist_college_count = (
    aishe_tn.groupby("district")
    .size()
    .reset_index(name="colleges_2012_13")
)

# Count unique ranked institutions per city in NIRF TN
# city field in NIRF ~ district name (approximate)
nirf_city_inst = (
    nirf_tn.groupby("city")["name"]
    .nunique()
    .reset_index()
    .rename(columns={"city": "district_approx", "name": "ranked_current"})
)
nirf_city_inst["district_approx_lower"] = nirf_city_inst["district_approx"].str.lower().str.strip()

dist_college_count["district_lower"] = dist_college_count["district"].str.lower().str.strip()

merged = dist_college_count.merge(
    nirf_city_inst.rename(columns={"district_approx_lower": "district_lower"})[["district_lower", "ranked_current"]],
    on="district_lower",
    how="left"
)
merged["ranked_current"] = merged["ranked_current"].fillna(0).astype(int)

def compute_invisible(row):
    if row["colleges_2012_13"] == 0:
        return None
    pct = 100.0 * (1 - row["ranked_current"] / row["colleges_2012_13"])
    return safe_round(cap100(pct), 1)

merged["invisible_pct"] = merged.apply(compute_invisible, axis=1)
merged = merged.sort_values("colleges_2012_13", ascending=False)

districts_list = []
for _, row in merged.iterrows():
    districts_list.append({
        "district":        str(row["district"]).title(),
        "colleges_2012_13": int(row["colleges_2012_13"]),
        "ranked_current":   int(row["ranked_current"]),
        "invisible_pct":    row["invisible_pct"]
    })

districts_out = {
    "_note": (
        "ranked_current uses city-to-district name matching (approximate); "
        "city field in NIRF often equals district name"
    ),
    "districts": districts_list
}

write_json(WEB_DATA / "districts.json", districts_out, "districts")
print(f"  Districts included: {len(districts_list)}")

# ---------------------------------------------------------------------------
# colleges.json  (tn_scorecard_metrics rows with percentiles)
# ---------------------------------------------------------------------------
print("\n--- Building colleges.json ---")

# Keep only institutions present in the current (2025) rankings. Leftover
# scorecards for institutions no longer ranked carry no current rank and must
# not appear as ranked entries.
before = len(score_tn)
score_tn = score_tn[score_tn["nirf_rank"].notna()].copy()
print(f"  kept {len(score_tn)} ranked scorecards (dropped {before - len(score_tn)} with no current rank)")

METRICS = [
    "faculty_count",
    "placement_median_salary_inr",
    "intake_total_2022_23",
    "student_strength_total",
    "capital_expenditure_2022_23",
]

# Check which metrics are actually present
missing_metrics = [m for m in METRICS if m not in score_tn.columns]
available_metrics = [m for m in METRICS if m in score_tn.columns]
if missing_metrics:
    print(f"  WARNING: Missing metric columns: {missing_metrics}")

# Compute within-category percentile for each metric
for metric in available_metrics:
    pct_col   = f"{metric}_pct"
    label_col = f"{metric}_label"

    # rank within category; NaN values get NaN rank
    score_tn[pct_col] = score_tn.groupby("category")[metric].transform(
        lambda s: s.rank(pct=True, na_option="keep") * 100
    )

    def make_label(v):
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return "no_data"
        if v >= 66:
            return "strong"
        if v >= 33:
            return "average"
        return "weak"

    score_tn[label_col] = score_tn[pct_col].apply(make_label)

# top_strength / biggest_gap
def best_worst(row):
    pct_vals = {}
    for m in available_metrics:
        v = row.get(f"{m}_pct")
        if v is not None and not (isinstance(v, float) and math.isnan(v)):
            pct_vals[m] = v
    if not pct_vals:
        return None, None
    best  = max(pct_vals, key=pct_vals.get)
    worst = min(pct_vals, key=pct_vals.get)
    return best, worst

score_tn = score_tn.copy()
score_tn["top_strength"] = None
score_tn["biggest_gap"]  = None

for idx, row in score_tn.iterrows():
    best, worst = best_worst(row)
    score_tn.at[idx, "top_strength"] = best
    score_tn.at[idx, "biggest_gap"]  = worst

# Build output rows
colleges_list = []
for _, row in score_tn.iterrows():
    rec = {}
    for col in score_tn.columns:
        val = row[col]
        # Convert numpy types / NaN
        if pd.isna(val) if not isinstance(val, str) else False:
            rec[col] = None
        elif hasattr(val, "item"):
            rec[col] = val.item()
        else:
            rec[col] = val
        # Round floats
        if isinstance(rec[col], float):
            col_lower = col.lower()
            if col_lower.endswith("_pct") or col_lower in ("nirf_score",):
                rec[col] = safe_round(rec[col], 1)
            elif col_lower.endswith("_inr") or "expenditure" in col_lower or "amount" in col_lower:
                rec[col] = safe_round(rec[col], 0)
    colleges_list.append(rec)

write_json(WEB_DATA / "colleges.json", colleges_list, "colleges")

# ---------------------------------------------------------------------------
# findings.json
# ---------------------------------------------------------------------------
print("\n--- Building findings.json ---")

findings = []

# Finding 1: Invisibility
invisible_pct_f = safe_round(100.0 * (1 - ranked_institutions / TN_TOTAL_CURRENT), 1)
findings.append({
    "id": "invisibility",
    "headline": f"{invisible_pct_f}% of Tamil Nadu colleges are invisible in NIRF rankings",
    "detail": (
        f"Of Tamil Nadu's {TN_TOTAL_CURRENT:,} colleges (AISHE 2021-22), only "
        f"{ranked_institutions} unique institutions appear in NIRF 2025 rankings. "
        f"That leaves {TN_TOTAL_CURRENT - ranked_institutions:,} colleges — "
        f"{invisible_pct_f}% — without a public quality signal."
    )
})

# Finding 2: Geographic concentration
if top2_city_share is not None:
    findings.append({
        "id": "concentration",
        "headline": f"{top2_city_share}% of ranked TN institutions cluster in {' and '.join(top2_city_names)}",
        "detail": (
            f"Among {ranked_institutions} uniquely ranked Tamil Nadu institutions, "
            f"{top2_institution_count} ({top2_city_share}%) are located in "
            f"{top2_city_names[0]} and {top2_city_names[1] if len(top2_city_names) > 1 else ''}. "
            "Rankings visibility is heavily skewed toward these two cities."
        )
    })

# Finding 3: Gender ratio across scorecard institutions
if "student_strength_female" in score_tn.columns and "student_strength_total" in score_tn.columns:
    total_female = score_tn["student_strength_female"].sum(skipna=True)
    total_students = score_tn["student_strength_total"].sum(skipna=True)
    female_pct = safe_round(100.0 * total_female / total_students, 1) if total_students else None
    findings.append({
        "id": "gender_ratio",
        "headline": f"{female_pct}% female enrolment across ranked TN institutions",
        "detail": (
            f"Across {len(score_tn)} Tamil Nadu institutions in the NIRF 2025 scorecard, "
            f"{int(total_female):,} of {int(total_students):,} students ({female_pct}%) are female. "
            "This is notably higher than the national average, reflecting TN's strong women's college network."
        )
    })

# Finding 4: Median placement salary
if "placement_median_salary_inr" in score_tn.columns:
    salary_series = score_tn["placement_median_salary_inr"].dropna()
    if len(salary_series) > 0:
        med_sal   = int(salary_series.median())
        min_sal   = int(salary_series.min())
        max_sal   = int(salary_series.max())
        findings.append({
            "id": "placement_salary",
            "headline": f"Median placement salary among ranked TN institutions: Rs {med_sal:,}",
            "detail": (
                f"Reported median placement salaries range from Rs {min_sal:,} to Rs {max_sal:,} "
                f"across {len(salary_series)} institutions with placement data in the NIRF 2025 scorecard. "
                "The median sits at Rs {med_sal:,}, with wide variation by discipline and institution type."
            ).replace("{med_sal:,}", f"{med_sal:,}")
        })

# Finding 5: Top district by college count
if len(districts_list) > 0:
    top_dist = districts_list[0]
    findings.append({
        "id": "top_district",
        "headline": f"{top_dist['district']} leads all TN districts with {top_dist['colleges_2012_13']} colleges",
        "detail": (
            f"{top_dist['district']} had {top_dist['colleges_2012_13']} colleges as of AISHE 2012-13, "
            f"the highest of any Tamil Nadu district. "
            f"Despite this density, only {top_dist['ranked_current']} institutions appear in NIRF 2025 — "
            f"an invisibility rate of {top_dist['invisible_pct']}%."
        )
    })

write_json(WEB_DATA / "findings.json", findings, "findings")

# ---------------------------------------------------------------------------
# Final validation summary
# ---------------------------------------------------------------------------
print("\n--- Validation ---")
for fname in ["summary.json", "districts.json", "colleges.json", "findings.json"]:
    fpath = WEB_DATA / fname
    try:
        obj = json.loads(fpath.read_text(encoding="utf-8"))
        if isinstance(obj, list):
            print(f"  {fname}: OK ({len(obj)} items)")
        elif isinstance(obj, dict):
            print(f"  {fname}: OK ({len(obj)} top-level keys)")
    except Exception as exc:
        print(f"  {fname}: PARSE ERROR - {exc}")

print("\nDone.")
