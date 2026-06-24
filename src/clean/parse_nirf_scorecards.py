# Author: Chitranjan Jegadeesan
# Parse NIRF 2025 per-institute scorecard PDFs and produce a clean metrics CSV.
# Handles all 12 categories present in the Tamil Nadu dataset.

import os
import re
import csv
import glob
import pdfplumber
import pandas as pd

SCORECARDS_DIR  = "D:/opus-kimi-projects/indian-accreditation-analytics/data/raw/scorecards"
TEXT_OUT_DIR    = "D:/opus-kimi-projects/indian-accreditation-analytics/data/raw/scorecards_text"
RANKINGS_CSV    = "D:/opus-kimi-projects/indian-accreditation-analytics/data/processed/nirf_rankings.csv"
OUTPUT_CSV      = "D:/opus-kimi-projects/indian-accreditation-analytics/data/processed/tn_scorecard_metrics.csv"

OUTPUT_FIELDS = [
    "institute_id",
    "category",
    "institute_name",
    # Intake (latest year = 2022-23 column)
    "intake_total_2022_23",
    # Student strength
    "student_strength_total",
    "student_strength_male",
    "student_strength_female",
    # Faculty
    "faculty_count",
    "phd_students_fulltime",
    "phd_students_parttime",
    "phd_graduated_2022_23",
    # Placement - most recent cohort median salary (numeric, INR)
    "placement_median_salary_inr",
    # Financial resources latest year (2022-23) numeric only
    "capital_expenditure_2022_23",
    "operational_expenditure_2022_23",
    # Research
    "sponsored_projects_2022_23",
    "sponsored_amount_2022_23",
    # Metadata
    "nirf_score",
    "nirf_rank",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def extract_full_text(pdf_path):
    """Return concatenated plain text from all pages."""
    parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            txt = page.extract_text()
            if txt:
                parts.append(txt)
    return "\n".join(parts)


def safe_int(val):
    """Convert string to int, stripping commas and whitespace; return None on failure."""
    if val is None:
        return None
    try:
        return int(str(val).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def first_number_on_line(line):
    """Return the first integer found in the line, or None."""
    m = re.search(r"\b(\d[\d,]*)\b", line)
    if m:
        return safe_int(m.group(1))
    return None


# ---------------------------------------------------------------------------
# Field extractors
# ---------------------------------------------------------------------------

def parse_institute_name(text):
    """Extract institute name from 'Institute Name: FOO [IR-...]' line."""
    m = re.search(r"Institute Name:\s*(.+?)\s*\[IR-", text)
    if m:
        return m.group(1).strip()
    return ""


def parse_intake_2022_23(text):
    """
    Sum all program-level intake values for academic year 2022-23
    (the first numeric column after the header row listing years).

    The Sanctioned Intake table looks like:
      Academic Year 2022-23 2021-22 ...
      UG [3 Years ...] 1100 900 700 ...
      UG [4 Years ...] 3480 ...
    We capture only the first number on each data row.
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
            # The year header row — skip it
            if re.match(r"^\s*Academic Year", line):
                continue
            # Stop at next major section
            if re.search(r"Total Actual Student Strength|Placement|PhD|Financial|Faculty", line, re.IGNORECASE):
                break
            # Data row: starts with UG or PG
            # e.g. "UG [4 Years Program(s)] 877 877 877 762 - -"
            # Extract numbers AFTER the closing ']' to skip digits in "4 Years" etc.
            if re.match(r"\s*(UG|PG)", line, re.IGNORECASE):
                after = re.sub(r"^.*?\]", "", line)  # strip up to first ']'
                nums = re.findall(r"(\d[\d,]*)", after)
                if nums:
                    val = safe_int(nums[0])
                    if val is not None and val > 0:
                        total += val
                        found_any = True

    return total if found_any else None


def parse_student_strength(text):
    """
    Sum Total Students column (3rd numeric column) across all program rows in the
    'Total Actual Student Strength' table.

    Approach: extract the entire section as a single string, then use a regex that
    matches each program row regardless of whether it is on one line or split across two.
    Pattern: a row starts with UG or PG (possibly 'PG-Integrated'), followed by
    numbers interspersed with the program label text.

    The column order (after program label) is: Male, Female, Total, ...
    We identify the Total as the 3rd large number (>9) after stripping the year-digit
    that appears in labels like "[3 Years", "[4 Years", "2 Year", "6 Years".

    Returns (total_students, total_male, total_female) or (None, None, None).
    """
    # Extract section between "Total Actual Student Strength" and "Placement"
    m = re.search(
        r"Total Actual Student Strength.*?(?=Placement\s*&\s*Higher|Placement\s*for|$)",
        text, re.DOTALL | re.IGNORECASE
    )
    if not m:
        return None, None, None

    section = m.group(0)
    # Collapse newlines so split rows become one line per row
    section_flat = section.replace("\n", " ")

    # Find all UG/PG program rows.
    # Each row ends just before the next "UG", "PG", or section terminator.
    # We find each "row block" by splitting on word boundaries of UG/PG.
    row_blocks = re.split(r"(?=\bUG\b|\bPG\b)", section_flat)

    total = male = female = 0
    found = False

    for block in row_blocks:
        block = block.strip()
        if not re.match(r"(UG|PG)", block, re.IGNORECASE):
            continue
        # Pull all integers from the block
        all_nums = re.findall(r"(\d[\d,]*)", block)
        # Filter to numbers > 9 to skip the year label digits (3, 4, 5, 6, 2)
        big_nums = [safe_int(n) for n in all_nums if safe_int(n) is not None and safe_int(n) > 9]
        # Need at least Male, Female, Total (3 columns)
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
    """Extract 'Number of faculty members entered NNN' line."""
    m = re.search(r"Number of faculty members entered\s+(\d[\d,]*)", text)
    if m:
        return safe_int(m.group(1))
    return None


def parse_phd_details(text):
    """
    Extract PhD student counts and 2022-23 graduates.
    Returns (fulltime, parttime, graduated_2022_23).
    """
    # Full-time pursuing
    ft = None
    pt = None
    grad = None

    m = re.search(r"Full Time\s+(\d[\d,]*)", text)
    if m:
        ft = safe_int(m.group(1))
    m = re.search(r"Part Time\s+(\d[\d,]*)", text)
    if m:
        pt = safe_int(m.group(1))

    # No. of PhD students graduated 2022-23
    # The graduated block: header "2022-23 2021-22 2020-21" then "Full Time NNN NNN NNN"
    m = re.search(
        r"No\. of Ph\.?D students graduated.*?2022-23\s+2021-22\s+2020-21\s+Full Time\s+(\d[\d,]*)",
        text,
        re.DOTALL | re.IGNORECASE
    )
    if m:
        grad = safe_int(m.group(1))

    return ft, pt, grad


def parse_median_salary(text):
    """
    Extract the most recent median salary.
    Salary appears as: NNN(text description) in placement rows.
    We collect all salary numbers and return the last (most recent) one found
    (since cohorts are listed oldest-to-newest).
    Returns INR as integer or None.
    """
    # Pattern: integer immediately followed by (
    salaries = re.findall(r"(\d{4,10})\(", text)
    if not salaries:
        return None
    # Filter plausible salary range: 50000 to 50000000 (50L)
    valid = [int(s) for s in salaries if 50000 <= int(s) <= 50_000_000]
    if valid:
        return valid[-1]  # most recent cohort is last
    return None


def parse_financial_capital(text):
    """
    Extract capital expenditure 2022-23.
    Sum of all line items under 'Financial Resources: Utilised Amount for the Capital expenditure'.
    Each line has: description NNNNNN (text) NNNNNN (text) NNNNNN (text)
    First number = 2022-23.
    """
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
            # Extract first large number (>= 100) on the line = 2022-23 value
            nums = re.findall(r"(\d[\d,]{3,})", line)
            if nums:
                val = safe_int(nums[0])
                if val is not None and val >= 100:
                    total += val
                    found = True

    return total if found else None


def parse_financial_operational(text):
    """
    Extract operational expenditure 2022-23. Sum of Salaries + Maintenance + Seminars.
    """
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
    """Return (project_count_2022_23, amount_2022_23) from Sponsored Research block."""
    projects = None
    amount = None

    m = re.search(
        r"Sponsored Research Details.*?2022-23\s+2021-22\s+2020-21\s+"
        r"Total no\. of Sponsored Projects\s+(\d[\d,]*)",
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


# ---------------------------------------------------------------------------
# Main parse function
# ---------------------------------------------------------------------------

def parse_one_pdf(pdf_path):
    """Parse a single scorecard PDF and return a dict of metrics."""
    fname = os.path.basename(pdf_path)
    # Filename pattern: {category}_{institute_id}.pdf
    parts = fname[:-4].split("_", 1)
    category = parts[0] if len(parts) == 2 else ""
    institute_id = parts[1] if len(parts) == 2 else ""

    row = {f: None for f in OUTPUT_FIELDS}
    row["institute_id"] = institute_id
    row["category"] = category

    try:
        text = extract_full_text(pdf_path)
    except Exception as e:
        row["_parse_error"] = str(e)
        return row

    # Save full raw text
    os.makedirs(TEXT_OUT_DIR, exist_ok=True)
    text_out = os.path.join(TEXT_OUT_DIR, fname.replace(".pdf", ".txt"))
    with open(text_out, "w", encoding="utf-8") as f:
        f.write(text)

    row["institute_name"] = parse_institute_name(text)
    row["intake_total_2022_23"] = parse_intake_2022_23(text)

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


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def load_rankings():
    df = pd.read_csv(RANKINGS_CSV)
    tn = df[df["state"].str.contains("Tamil Nadu", case=False, na=False)].copy()
    tn = tn.drop_duplicates(subset=["category", "institute_id"])
    # Build lookup dict: (category, institute_id) -> (score, rank)
    lookup = {}
    for _, r in tn.iterrows():
        key = (str(r["category"]).strip(), str(r["institute_id"]).strip())
        lookup[key] = (r.get("score", None), r.get("rank", None))
    return lookup


def run_all():
    rankings = load_rankings()
    pdf_files = sorted(glob.glob(os.path.join(SCORECARDS_DIR, "*.pdf")))

    if not pdf_files:
        print("No PDFs found in", SCORECARDS_DIR)
        return

    print(f"Processing {len(pdf_files)} PDFs...")
    rows = []
    parse_errors = 0
    field_hit = {f: 0 for f in OUTPUT_FIELDS if f not in ("institute_id", "category", "institute_name")}

    for pdf_path in pdf_files:
        row = parse_one_pdf(pdf_path)
        key = (row["category"], row["institute_id"])
        score, rank = rankings.get(key, (None, None))
        row["nirf_score"] = score
        row["nirf_rank"] = rank
        if "_parse_error" in row:
            parse_errors += 1
        rows.append(row)

        for f in field_hit:
            if row.get(f) is not None:
                field_hit[f] += 1

    # Write CSV
    os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    total = len(rows)
    print(f"\n=== Parse Summary ===")
    print(f"PDFs processed  : {total}")
    print(f"Parse errors    : {parse_errors}")
    print(f"\nField fill rates (out of {total}):")
    for field, count in sorted(field_hit.items(), key=lambda x: -x[1]):
        pct = 100 * count / total if total else 0
        reliability = "RELIABLE" if pct >= 80 else ("PARTIAL" if pct >= 40 else "SPARSE")
        print(f"  {field:<42s}  {count:3d}/{total}  ({pct:5.1f}%)  {reliability}")
    print(f"\nOutput CSV: {OUTPUT_CSV}")
    print(f"Raw text files: {TEXT_OUT_DIR}")


if __name__ == "__main__":
    run_all()
