# Author: Chitranjan Jegadeesan
# Purpose: Refresh NIRF data from 2024 to 2025.
# Steps:
#   1. Download 2025 NIRF category HTML pages into data/raw/nirf/ (overwrite 2024 files).
#   2. Parse into data/processed/nirf_rankings.csv.
#   3. Download TN institute scorecard PDFs for 2025 into data/raw/scorecards/.
#   4. Parse scorecards into data/processed/tn_scorecard_metrics.csv.
#   5. Rebuild web/data/*.json.
#
# Run from project root:
#   python src/refresh_2025.py

import csv
import glob
import math
import os
import re
import sys
import time
import urllib.request
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
RAW_NIRF = ROOT / "data" / "raw" / "nirf"
RAW_SCORECARDS = ROOT / "data" / "raw" / "scorecards"
RAW_SCORECARDS_TEXT = ROOT / "data" / "raw" / "scorecards_text"
PROCESSED = ROOT / "data" / "processed"
WEB_DATA = ROOT / "web" / "data"

RAW_NIRF.mkdir(parents=True, exist_ok=True)
RAW_SCORECARDS.mkdir(parents=True, exist_ok=True)
RAW_SCORECARDS_TEXT.mkdir(parents=True, exist_ok=True)
PROCESSED.mkdir(parents=True, exist_ok=True)
WEB_DATA.mkdir(parents=True, exist_ok=True)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

NIRF_YEAR = "2025"

# Candidate categories (standard + new 2025 additions to try)
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
    # new 2025 candidates
    "StatePublicUniversity",
    "SkillUniversity",
    "OpenUniversity",
    "Innovation",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fetch_url(url: str, dest: Path, min_bytes: int = 40_000) -> bool:
    """Download url to dest. Returns True if file is >= min_bytes."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
        if len(data) < min_bytes:
            print(f"    SKIP {url}: only {len(data)} bytes (< {min_bytes})")
            return False
        dest.write_bytes(data)
        print(f"    OK   {url}: {len(data):,} bytes -> {dest.name}")
        return True
    except Exception as exc:
        print(f"    FAIL {url}: {exc}")
        return False


def clean_name(name: str) -> str:
    name = re.sub(r"More Details.*$", "", str(name), flags=re.I)
    return re.sub(r"\s+", " ", name).strip(" |").strip()


# ---------------------------------------------------------------------------
# Step 1 – Download 2025 category HTML pages
# ---------------------------------------------------------------------------

def step1_download_category_pages() -> list[str]:
    """Download each category page. Returns list of category stems that succeeded."""
    print("\n=== Step 1: Download 2025 NIRF category pages ===")
    found = []
    for cat in CATEGORIES:
        url = f"https://www.nirfindia.org/Rankings/{NIRF_YEAR}/{cat}Ranking.html"
        dest = RAW_NIRF / f"{cat}.html"
        ok = fetch_url(url, dest, min_bytes=40_000)
        if ok:
            # Verify it has a parseable rank table
            try:
                import pandas as pd
                tables = pd.read_html(dest)
                cand = [t for t in tables if "Rank" in t.columns and "Name" in t.columns and len(t) > 5]
                if cand:
                    found.append(cat)
                    print(f"    -> table found ({len(cand[0])} rows)")
                else:
                    print(f"    -> no Rank/Name table found; discarding")
                    dest.unlink(missing_ok=True)
            except Exception as exc:
                print(f"    -> table parse error: {exc}; discarding")
                dest.unlink(missing_ok=True)
        time.sleep(0.5)
    print(f"\n  Categories with valid tables: {found}")
    return found


# ---------------------------------------------------------------------------
# Step 2 – Parse HTML into nirf_rankings.csv
# ---------------------------------------------------------------------------

def step2_parse_rankings(found_cats: list[str]) -> Path:
    """Parse all downloaded HTML files into nirf_rankings.csv."""
    import pandas as pd
    print("\n=== Step 2: Parse rankings into CSV ===")
    out_path = PROCESSED / "nirf_rankings.csv"
    frames = []
    for cat in found_cats:
        p = RAW_NIRF / f"{cat}.html"
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
        t = max(cand, key=len)
        keep = ["Institute ID", "Name", "City", "State", "Score", "Rank"]
        t = t[[c for c in keep if c in t.columns]].copy()
        t["Name"] = t["Name"].map(clean_name)
        t.insert(0, "category", cat)
        t.columns = [c.lower().replace(" ", "_") for c in t.columns]
        frames.append(t)
        print(f"  {cat:22s} {len(t):>4} institutions")

    out = pd.concat(frames, ignore_index=True)
    out.to_csv(out_path, index=False, encoding="utf-8")
    print(f"\n  Total: {len(out)} scored rows across {out['category'].nunique()} categories.")
    tn = out[out["state"].str.contains("Tamil Nadu", case=False, na=False)]
    print(f"  Tamil Nadu rows: {len(tn)} entries, {tn['name'].nunique()} unique institutions")
    print(f"  Written -> {out_path.relative_to(ROOT)}")
    return out_path


# ---------------------------------------------------------------------------
# Step 3 – Download TN scorecard PDFs for 2025
# ---------------------------------------------------------------------------

def step3_download_scorecards(rankings_csv: Path) -> list[Path]:
    """Download 2025 scorecard PDFs for TN institutes."""
    import pandas as pd
    print("\n=== Step 3: Download 2025 TN scorecard PDFs ===")
    df = pd.read_csv(rankings_csv)
    tn = df[df["state"].str.contains("Tamil Nadu", case=False, na=False)].copy()
    tn = tn.drop_duplicates(subset=["category", "institute_id"])
    print(f"  TN ranked rows to process: {len(tn)}")

    downloaded = []
    failed = []
    for _, row in tn.iterrows():
        cat = str(row["category"]).strip()
        iid = str(row["institute_id"]).strip()
        url = f"https://www.nirfindia.org/nirfpdfcdn/{NIRF_YEAR}/pdf/{cat}/{iid}.pdf"
        dest = RAW_SCORECARDS / f"{cat}_{iid}.pdf"
        ok = fetch_url(url, dest, min_bytes=10_000)
        if ok:
            downloaded.append(dest)
        else:
            failed.append((cat, iid, url))
        time.sleep(0.3)

    print(f"\n  Downloaded: {len(downloaded)}, Failed: {len(failed)}")
    if failed:
        print("  Failed downloads:")
        for cat, iid, url in failed[:10]:
            print(f"    {cat}/{iid}")
        if len(failed) > 10:
            print(f"    ... and {len(failed)-10} more")
    return downloaded


# ---------------------------------------------------------------------------
# Step 4 – Parse scorecards into tn_scorecard_metrics.csv
# ---------------------------------------------------------------------------

def safe_int(val):
    if val is None:
        return None
    try:
        return int(str(val).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def extract_full_text(pdf_path):
    import pdfplumber
    parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            txt = page.extract_text()
            if txt:
                parts.append(txt)
    return "\n".join(parts)


def parse_institute_name(text):
    m = re.search(r"Institute Name:\s*(.+?)\s*\[IR-", text)
    if m:
        return m.group(1).strip()
    return ""


def parse_intake_latest(text):
    """
    Sum program-level intake values for the most recent academic year
    (first numeric column after the year header row).
    Does NOT hardcode 2022-23: takes whatever is the leftmost year column.
    """
    lines = text.split("\n")
    in_intake = False
    total = 0
    found_any = False

    for line in lines:
        if "Sanctioned (Approved) Intake" in line:
            in_intake = True
            continue
        if in_intake:
            if re.match(r"^\s*Academic Year", line):
                continue
            if re.search(r"Total Actual Student Strength|Placement|PhD|Financial|Faculty", line, re.IGNORECASE):
                break
            if re.match(r"\s*(UG|PG)", line, re.IGNORECASE):
                after = re.sub(r"^.*?\]", "", line)
                nums = re.findall(r"(\d[\d,]*)", after)
                if nums:
                    val = safe_int(nums[0])
                    if val is not None and val > 0:
                        total += val
                        found_any = True

    return total if found_any else None


def parse_student_strength(text):
    m = re.search(
        r"Total Actual Student Strength.*?(?=Placement\s*&\s*Higher|Placement\s*for|$)",
        text, re.DOTALL | re.IGNORECASE
    )
    if not m:
        return None, None, None
    section = m.group(0)
    section_flat = section.replace("\n", " ")
    row_blocks = re.split(r"(?=\bUG\b|\bPG\b)", section_flat)
    total = male = female = 0
    found = False
    for block in row_blocks:
        block = block.strip()
        if not re.match(r"(UG|PG)", block, re.IGNORECASE):
            continue
        all_nums = re.findall(r"(\d[\d,]*)", block)
        big_nums = [safe_int(n) for n in all_nums if safe_int(n) is not None and safe_int(n) > 9]
        if len(big_nums) >= 3:
            m_val = big_nums[0]
            f_val = big_nums[1]
            t_val = big_nums[2]
            if t_val is not None and t_val > 0:
                male += m_val or 0
                female += f_val or 0
                total += t_val
                found = True
    if found:
        return total, male, female
    return None, None, None


def parse_faculty_count(text):
    m = re.search(r"Number of faculty members entered\s+(\d[\d,]*)", text)
    if m:
        return safe_int(m.group(1))
    return None


def parse_phd_details(text):
    """
    Extract PhD pursuing counts and most-recent-year graduates.
    Uses the rightmost year column to find graduated count generically.
    """
    ft = pt = grad = None
    m = re.search(r"Full Time\s+(\d[\d,]*)", text)
    if m:
        ft = safe_int(m.group(1))
    m = re.search(r"Part Time\s+(\d[\d,]*)", text)
    if m:
        pt = safe_int(m.group(1))

    # Most-recent-year graduated: find "No. of PhD students graduated" block,
    # then take the first number after the year header row (= rightmost/most recent year).
    m = re.search(
        r"No\. of Ph\.?D students graduated.*?Full Time\s+(\d[\d,]*)",
        text, re.DOTALL | re.IGNORECASE
    )
    if m:
        grad = safe_int(m.group(1))
    return ft, pt, grad


def parse_median_salary(text):
    salaries = re.findall(r"(\d{4,10})\(", text)
    if not salaries:
        return None
    valid = [int(s) for s in salaries if 50000 <= int(s) <= 50_000_000]
    if valid:
        return valid[-1]
    return None


def parse_financial_capital(text):
    lines = text.split("\n")
    in_cap = False
    total = 0
    found = False
    for line in lines:
        if re.search(r"Capital expenditure for previous 3 years", line, re.IGNORECASE):
            in_cap = True
            continue
        if in_cap:
            if re.search(r"Operational expenditure|Sponsored Research|Consultancy|Faculty|PCS Facilities|OPD", line, re.IGNORECASE):
                break
            if re.search(r"Financial Year|Utilised Amount|Annual Capital", line, re.IGNORECASE):
                continue
            nums = re.findall(r"(\d[\d,]{3,})", line)
            if nums:
                val = safe_int(nums[0])
                if val is not None and val >= 100:
                    total += val
                    found = True
    return total if found else None


def parse_financial_operational(text):
    lines = text.split("\n")
    in_op = False
    total = 0
    found = False
    for line in lines:
        if re.search(r"Operational expenditure for previous 3 years", line, re.IGNORECASE):
            in_op = True
            continue
        if in_op:
            if re.search(r"Sponsored Research|Consultancy|Faculty|PCS Facilities|OPD|Executive Development", line, re.IGNORECASE):
                break
            if re.search(r"Financial Year|Utilised Amount|Annual Operational", line, re.IGNORECASE):
                continue
            nums = re.findall(r"(\d[\d,]{3,})", line)
            if nums:
                val = safe_int(nums[0])
                if val is not None and val >= 100:
                    total += val
                    found = True
    return total if found else None


def parse_sponsored_research(text):
    projects = amount = None
    m = re.search(
        r"Sponsored Research Details.*?Total no\. of Sponsored Projects\s+(\d[\d,]*)",
        text, re.DOTALL | re.IGNORECASE
    )
    if m:
        projects = safe_int(m.group(1))
    m = re.search(
        r"Total Amount Received \(Amount in Rupees\)\s+(\d[\d,]+)\s+\d",
        text
    )
    if m:
        amount = safe_int(m.group(1))
    return projects, amount


# Output fields — renamed "latest" instead of hardcoded year to reflect generic handling
OUTPUT_FIELDS = [
    "institute_id",
    "category",
    "institute_name",
    "intake_total_2022_23",          # kept same column name for web compatibility
    "student_strength_total",
    "student_strength_male",
    "student_strength_female",
    "faculty_count",
    "phd_students_fulltime",
    "phd_students_parttime",
    "phd_graduated_2022_23",         # kept same column name for web compatibility
    "placement_median_salary_inr",
    "capital_expenditure_2022_23",   # kept same column name for web compatibility
    "operational_expenditure_2022_23",
    "sponsored_projects_2022_23",
    "sponsored_amount_2022_23",
    "nirf_score",
    "nirf_rank",
]


def parse_one_pdf(pdf_path: Path) -> dict:
    fname = pdf_path.name
    parts = fname[:-4].split("_", 1)
    category = parts[0] if len(parts) == 2 else ""
    institute_id = parts[1] if len(parts) == 2 else ""

    row = {f: None for f in OUTPUT_FIELDS}
    row["institute_id"] = institute_id
    row["category"] = category

    try:
        text = extract_full_text(pdf_path)
    except Exception as exc:
        row["_parse_error"] = str(exc)
        return row

    RAW_SCORECARDS_TEXT.mkdir(parents=True, exist_ok=True)
    text_out = RAW_SCORECARDS_TEXT / fname.replace(".pdf", ".txt")
    text_out.write_text(text, encoding="utf-8")

    row["institute_name"] = parse_institute_name(text)
    row["intake_total_2022_23"] = parse_intake_latest(text)

    total_s, male_s, female_s = parse_student_strength(text)
    row["student_strength_total"] = total_s
    row["student_strength_male"] = male_s
    row["student_strength_female"] = female_s

    row["faculty_count"] = parse_faculty_count(text)

    ft, pt, grad = parse_phd_details(text)
    row["phd_students_fulltime"] = ft
    row["phd_students_parttime"] = pt
    row["phd_graduated_2022_23"] = grad

    row["placement_median_salary_inr"] = parse_median_salary(text)
    row["capital_expenditure_2022_23"] = parse_financial_capital(text)
    row["operational_expenditure_2022_23"] = parse_financial_operational(text)

    proj, amt = parse_sponsored_research(text)
    row["sponsored_projects_2022_23"] = proj
    row["sponsored_amount_2022_23"] = amt

    return row


def step4_parse_scorecards(rankings_csv: Path):
    import pandas as pd
    print("\n=== Step 4: Parse scorecard PDFs ===")
    out_path = PROCESSED / "tn_scorecard_metrics.csv"

    # Load TN rankings lookup
    df = pd.read_csv(rankings_csv)
    tn = df[df["state"].str.contains("Tamil Nadu", case=False, na=False)].copy()
    tn = tn.drop_duplicates(subset=["category", "institute_id"])
    lookup = {}
    for _, r in tn.iterrows():
        key = (str(r["category"]).strip(), str(r["institute_id"]).strip())
        lookup[key] = (r.get("score", None), r.get("rank", None))

    pdf_files = sorted(RAW_SCORECARDS.glob("*.pdf"))
    if not pdf_files:
        print("  No PDFs found.")
        return

    print(f"  Processing {len(pdf_files)} PDFs...")
    rows = []
    parse_errors = 0
    field_hit = {f: 0 for f in OUTPUT_FIELDS if f not in ("institute_id", "category", "institute_name")}

    for pdf_path in pdf_files:
        row = parse_one_pdf(pdf_path)
        key = (row["category"], row["institute_id"])
        score, rank = lookup.get(key, (None, None))
        row["nirf_score"] = score
        row["nirf_rank"] = rank
        if "_parse_error" in row:
            parse_errors += 1
        rows.append(row)
        for f in field_hit:
            if row.get(f) is not None:
                field_hit[f] += 1

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    total = len(rows)
    print(f"\n  PDFs processed  : {total}")
    print(f"  Parse errors    : {parse_errors}")
    print(f"\n  Field fill rates:")
    for field, count in sorted(field_hit.items(), key=lambda x: -x[1]):
        pct = 100 * count / total if total else 0
        reliability = "RELIABLE" if pct >= 80 else ("PARTIAL" if pct >= 40 else "SPARSE")
        print(f"    {field:<42s}  {count:3d}/{total}  ({pct:5.1f}%)  {reliability}")
    print(f"\n  Output CSV: {out_path.relative_to(ROOT)}")
    return out_path


# ---------------------------------------------------------------------------
# Step 5 – Rebuild web data JSONs
# ---------------------------------------------------------------------------

def safe_round(val, ndigits=1):
    if val is None:
        return None
    try:
        if math.isnan(val) or math.isinf(val):
            return None
    except TypeError:
        return None
    return round(float(val), ndigits)


def cap100(val):
    if val is None:
        return None
    return min(100.0, val)


def write_json(path: Path, obj, label: str):
    import json
    text = json.dumps(obj, indent=2, ensure_ascii=False)
    path.write_text(text, encoding="utf-8")
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(parsed, list):
        print(f"  Wrote {label}: {len(parsed)} items -> {path.name}")
    elif isinstance(parsed, dict):
        print(f"  Wrote {label}: {len(parsed)} keys -> {path.name}")
    else:
        print(f"  Wrote {label} -> {path.name}")


def step5_rebuild_web_data():
    import json
    import pandas as pd
    print("\n=== Step 5: Rebuild web/data JSONs ===")

    AISHE_PATH = PROCESSED / "aishe_colleges.csv"
    NIRF_PATH  = PROCESSED / "nirf_rankings.csv"
    SCORE_PATH = PROCESSED / "tn_scorecard_metrics.csv"

    aishe = pd.read_csv(AISHE_PATH)
    nirf  = pd.read_csv(NIRF_PATH)
    score = pd.read_csv(SCORE_PATH)

    TN_TOTAL_CURRENT = 2829  # AISHE 2021-22 state total (published figure) — unchanged
    TN_NAME = "Tamil Nadu"

    aishe_tn = aishe[aishe["state"].str.strip().str.title() == TN_NAME].copy()
    nirf_tn  = nirf[nirf["state"].str.strip().str.title() == TN_NAME].copy()
    score_tn = score.copy()

    print(f"  TN rows - AISHE: {len(aishe_tn)}, NIRF: {len(nirf_tn)}, Scorecard: {len(score_tn)}")

    # -- summary.json --
    ranked_institutions  = nirf_tn["name"].nunique()
    ranked_entries       = len(nirf_tn)
    invisible_pct        = safe_round(100.0 * (1 - ranked_institutions / TN_TOTAL_CURRENT), 1)
    districts_count      = aishe_tn["district"].nunique()

    city_counts = nirf_tn.groupby("city")["name"].nunique().sort_values(ascending=False)
    if len(city_counts) >= 2:
        top2_cities            = city_counts.head(2)
        top2_institution_count = int(top2_cities.sum())
        top2_city_share        = safe_round(100.0 * top2_institution_count / ranked_institutions, 1) if ranked_institutions else None
        top2_city_names        = list(top2_cities.index)
    else:
        top2_institution_count = int(city_counts.sum())
        top2_city_share        = None
        top2_city_names        = list(city_counts.index)

    summary = {
        "tn_total_colleges_current": TN_TOTAL_CURRENT,
        "tn_total_colleges_2012_13": len(aishe_tn),
        "ranked_institutions": ranked_institutions,
        "ranked_entries": ranked_entries,
        "invisible_pct_current": invisible_pct,
        "districts": districts_count,
        "top2_city_share_pct": top2_city_share,
        "top2_city_names": top2_city_names,
        "vintages": {
            "rankings":        "NIRF 2025",
            "state_total":     "AISHE 2021-22",
            "district_detail": "AISHE 2012-13"
        }
    }
    write_json(WEB_DATA / "summary.json", summary, "summary")

    # -- districts.json --
    dist_college_count = (
        aishe_tn.groupby("district").size().reset_index(name="colleges_2012_13")
    )
    nirf_city_inst = (
        nirf_tn.groupby("city")["name"].nunique().reset_index()
        .rename(columns={"city": "district_approx", "name": "ranked_current"})
    )
    nirf_city_inst["district_approx_lower"] = nirf_city_inst["district_approx"].str.lower().str.strip()
    dist_college_count["district_lower"] = dist_college_count["district"].str.lower().str.strip()
    merged = dist_college_count.merge(
        nirf_city_inst.rename(columns={"district_approx_lower": "district_lower"})[["district_lower", "ranked_current"]],
        on="district_lower", how="left"
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
            "district":         str(row["district"]).title(),
            "colleges_2012_13": int(row["colleges_2012_13"]),
            "ranked_current":   int(row["ranked_current"]),
            "invisible_pct":    row["invisible_pct"]
        })
    districts_out = {
        "_note": "ranked_current uses city-to-district name matching (approximate)",
        "districts": districts_list
    }
    write_json(WEB_DATA / "districts.json", districts_out, "districts")

    # -- colleges.json --
    METRICS = [
        "faculty_count",
        "placement_median_salary_inr",
        "intake_total_2022_23",
        "student_strength_total",
        "capital_expenditure_2022_23",
    ]
    available_metrics = [m for m in METRICS if m in score_tn.columns]
    missing_metrics   = [m for m in METRICS if m not in score_tn.columns]
    if missing_metrics:
        print(f"  WARNING: Missing metric columns: {missing_metrics}")

    for metric in available_metrics:
        pct_col   = f"{metric}_pct"
        label_col = f"{metric}_label"
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

    def best_worst(row):
        pct_vals = {}
        for m in available_metrics:
            v = row.get(f"{m}_pct")
            if v is not None and not (isinstance(v, float) and math.isnan(v)):
                pct_vals[m] = v
        if not pct_vals:
            return None, None
        return max(pct_vals, key=pct_vals.get), min(pct_vals, key=pct_vals.get)

    score_tn = score_tn.copy()
    score_tn["top_strength"] = None
    score_tn["biggest_gap"]  = None
    for idx, row in score_tn.iterrows():
        best, worst = best_worst(row)
        score_tn.at[idx, "top_strength"] = best
        score_tn.at[idx, "biggest_gap"]  = worst

    colleges_list = []
    for _, row in score_tn.iterrows():
        rec = {}
        for col in score_tn.columns:
            val = row[col]
            if pd.isna(val) if not isinstance(val, str) else False:
                rec[col] = None
            elif hasattr(val, "item"):
                rec[col] = val.item()
            else:
                rec[col] = val
            if isinstance(rec[col], float):
                col_lower = col.lower()
                if col_lower.endswith("_pct") or col_lower in ("nirf_score",):
                    rec[col] = safe_round(rec[col], 1)
                elif col_lower.endswith("_inr") or "expenditure" in col_lower or "amount" in col_lower:
                    rec[col] = safe_round(rec[col], 0)
        colleges_list.append(rec)
    write_json(WEB_DATA / "colleges.json", colleges_list, "colleges")

    # -- findings.json --
    findings = []
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
    if "student_strength_female" in score_tn.columns and "student_strength_total" in score_tn.columns:
        total_female   = score_tn["student_strength_female"].sum(skipna=True)
        total_students = score_tn["student_strength_total"].sum(skipna=True)
        female_pct = safe_round(100.0 * total_female / total_students, 1) if total_students else None
        findings.append({
            "id": "gender_ratio",
            "headline": f"{female_pct}% female enrolment across ranked TN institutions",
            "detail": (
                f"Across {len(score_tn)} Tamil Nadu institutions in the NIRF 2025 scorecard, "
                f"{int(total_female):,} of {int(total_students):,} students ({female_pct}%) are female."
            )
        })
    if "placement_median_salary_inr" in score_tn.columns:
        salary_series = score_tn["placement_median_salary_inr"].dropna()
        if len(salary_series) > 0:
            med_sal = int(salary_series.median())
            min_sal = int(salary_series.min())
            max_sal = int(salary_series.max())
            findings.append({
                "id": "placement_salary",
                "headline": f"Median placement salary among ranked TN institutions: Rs {med_sal:,}",
                "detail": (
                    f"Reported median placement salaries range from Rs {min_sal:,} to Rs {max_sal:,} "
                    f"across {len(salary_series)} institutions with placement data in the NIRF 2025 scorecard. "
                    f"The median sits at Rs {med_sal:,}, with wide variation by discipline and institution type."
                )
            })
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
    print(f"\n  invisible_pct_current: {invisible_pct}%")
    return invisible_pct


# ---------------------------------------------------------------------------
# Step 6 – Rebuild all_colleges.json
# ---------------------------------------------------------------------------

def step6_rebuild_all_colleges():
    import csv as _csv
    import json
    from rapidfuzz import fuzz

    print("\n=== Step 6: Rebuild all_colleges.json ===")

    AISHE_FILE    = PROCESSED / "aishe_colleges.csv"
    NIRF_FILE     = PROCESSED / "nirf_rankings.csv"
    SCORECARD_FILE = PROCESSED / "tn_scorecard_metrics.csv"
    OUT = WEB_DATA / "all_colleges.json"

    FUZZY_THRESHOLD = 88
    GENERIC_WORDS = {
        "college", "of", "arts", "science", "engineering", "technology",
        "and", "the", "for", "women", "institute", "management", "pharmacy",
        "education", "medical", "dental", "law", "commerce", "polytechnic",
        "university", "school", "centre", "center", "research", "studies",
        "a", "an", "in", "at", "to", "by", "dr", "prof", "sri", "sree",
    }

    def title_case(s):
        return s.strip().title() if s else ""

    def distinctive_words(name):
        tokens = re.split(r"[\s,.\-/&'`]+", name.lower())
        return {t for t in tokens if t and t not in GENERIC_WORDS and len(t) > 2}

    def best_match(query, candidates):
        best_name, best_score = "", 0.0
        q = query.lower()
        q_words = distinctive_words(query)
        for c in candidates:
            raw_score = fuzz.token_sort_ratio(q, c.lower())
            if raw_score < FUZZY_THRESHOLD:
                continue
            if raw_score < 95:
                if not (q_words & distinctive_words(c)):
                    continue
            if raw_score > best_score:
                best_score = raw_score
                best_name = c
        return best_name, best_score

    # Load data
    aishe_rows, nirf_rows = [], []
    with open(AISHE_FILE, encoding="utf-8") as f:
        for r in _csv.DictReader(f):
            if "tamil nadu" in r.get("state", "").lower():
                aishe_rows.append(r)
    with open(NIRF_FILE, encoding="utf-8") as f:
        for r in _csv.DictReader(f):
            if "tamil nadu" in r.get("state", "").lower():
                nirf_rows.append(r)

    scorecard_rank = {}
    with open(SCORECARD_FILE, encoding="utf-8") as f:
        for r in _csv.DictReader(f):
            iid = r.get("institute_id", "").strip()
            try:
                rank = int(float(r.get("nirf_rank", "")))
            except (ValueError, TypeError):
                rank = None
            if iid and rank is not None:
                if iid not in scorecard_rank or rank < scorecard_rank[iid]:
                    scorecard_rank[iid] = rank

    # Build NIRF index
    by_id = {}
    for r in nirf_rows:
        iid = r["institute_id"].strip()
        cat = r["category"].strip()
        try:
            rank = int(float(r["rank"]))
        except (ValueError, TypeError):
            rank = 9999
        if iid not in by_id:
            by_id[iid] = {"name": r["name"].strip(), "city": r["city"].strip(),
                           "categories": [], "best_rank": rank, "best_category": cat}
        by_id[iid]["categories"].append({"category": cat, "rank": rank})
        if rank < by_id[iid]["best_rank"]:
            by_id[iid]["best_rank"] = rank
            by_id[iid]["best_category"] = cat
    for iid, meta in by_id.items():
        if iid in scorecard_rank:
            meta["best_rank"] = scorecard_rank[iid]

    nirf_names = [meta["name"] for meta in by_id.values()]
    nirf_name_to_id = {meta["name"]: iid for iid, meta in by_id.items()}

    # Phase 1: AISHE rows
    entries = []
    matched_nirf_ids = set()
    for row in aishe_rows:
        aishe_name = row["college_name"].strip()
        district   = title_case(row.get("district", ""))
        col_type   = row.get("college_type", "").strip() or "Unknown"
        best_name, score = best_match(aishe_name, nirf_names)
        if score >= FUZZY_THRESHOLD and best_name:
            iid  = nirf_name_to_id[best_name]
            meta = by_id[iid]
            matched_nirf_ids.add(iid)
            entry = {
                "name": title_case(aishe_name), "district": district, "type": col_type,
                "ranked": True, "institute_id": iid, "category": meta["best_category"],
                "nirf_rank": meta["best_rank"],
                "categories": sorted(meta["categories"], key=lambda x: x["rank"])
            }
        else:
            entry = {
                "name": title_case(aishe_name), "district": district, "type": col_type,
                "ranked": False, "institute_id": None, "category": None,
                "nirf_rank": None, "categories": []
            }
        entries.append(entry)

    # Phase 2: NIRF-only
    unmatched_nirf_count = 0
    for iid, meta in by_id.items():
        if iid not in matched_nirf_ids:
            unmatched_nirf_count += 1
            entries.append({
                "name": title_case(meta["name"]), "district": title_case(meta["city"]),
                "type": "University", "ranked": True, "institute_id": iid,
                "category": meta["best_category"], "nirf_rank": meta["best_rank"],
                "categories": sorted(meta["categories"], key=lambda x: x["rank"])
            })

    # Dedupe
    seen = {}
    for e in entries:
        key = (e["name"].lower(), e["district"].lower())
        if key not in seen:
            seen[key] = e
        elif e["ranked"] and not seen[key]["ranked"]:
            seen[key] = e
    entries = sorted(seen.values(), key=lambda x: x["name"].lower())

    ranked_count   = sum(1 for e in entries if e["ranked"])
    unranked_count = len(entries) - ranked_count
    print(f"  Total entries: {len(entries)} (ranked: {ranked_count}, unranked: {unranked_count})")
    print(f"  Unmatched NIRF-only additions: {unmatched_nirf_count}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    print(f"  Written: {OUT.relative_to(ROOT)}, {OUT.stat().st_size/1024:.1f} KB")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print(f"NIRF 2025 Refresh — {ROOT.name}")
    print("=" * 60)

    found_cats = step1_download_category_pages()
    if not found_cats:
        print("ERROR: No valid 2025 category pages found. Aborting.")
        sys.exit(1)

    rankings_csv = step2_parse_rankings(found_cats)
    step3_download_scorecards(rankings_csv)
    step4_parse_scorecards(rankings_csv)
    invisible_pct = step5_rebuild_web_data()
    step6_rebuild_all_colleges()

    print("\n" + "=" * 60)
    print("Refresh complete.")
    print(f"  NIRF vintage: 2025")
    print(f"  Invisible %:  {invisible_pct}%")
    print("=" * 60)
