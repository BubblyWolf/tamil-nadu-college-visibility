# Author: Chitranjan Jegadeesan
# Download NIRF 2024 per-institute scorecard PDFs for Tamil Nadu institutions.

import time
import csv
import os
import sys
import requests
import pandas as pd

BASE_URL = "https://www.nirfindia.org/nirfpdfcdn/2024/pdf/{category}/{institute_id}.pdf"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}
MIN_PDF_BYTES = 3000
DELAY_SECONDS = 0.8

RANKINGS_CSV = "D:/opus-kimi-projects/indian-accreditation-analytics/data/processed/nirf_rankings.csv"
OUTPUT_DIR   = "D:/opus-kimi-projects/indian-accreditation-analytics/data/raw/scorecards"
LOG_PATH     = "D:/opus-kimi-projects/indian-accreditation-analytics/data/raw/download_log.csv"


def get_tn_rows():
    df = pd.read_csv(RANKINGS_CSV)
    tn = df[df["state"].str.contains("Tamil Nadu", case=False, na=False)].copy()
    tn = tn.drop_duplicates(subset=["category", "institute_id"])
    return tn.reset_index(drop=True)


def download_pdfs(tn_df):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    log_rows = []

    total = len(tn_df)
    downloaded = 0
    skipped_small = 0
    skipped_http = 0

    for i, row in tn_df.iterrows():
        cat = str(row["category"]).strip()
        iid = str(row["institute_id"]).strip()
        url = BASE_URL.format(category=cat, institute_id=iid)
        fname = f"{cat}_{iid}.pdf"
        fpath = os.path.join(OUTPUT_DIR, fname)

        # skip already downloaded
        if os.path.exists(fpath) and os.path.getsize(fpath) >= MIN_PDF_BYTES:
            log_rows.append({"category": cat, "institute_id": iid, "status": "already_exists", "url": url})
            downloaded += 1
            print(f"[{i+1}/{total}] SKIP (exists) {fname}")
            continue

        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            if resp.status_code == 200:
                content = resp.content
                if len(content) < MIN_PDF_BYTES:
                    log_rows.append({"category": cat, "institute_id": iid, "status": f"too_small_{len(content)}", "url": url})
                    skipped_small += 1
                    print(f"[{i+1}/{total}] SKIP (tiny {len(content)}B) {fname}")
                else:
                    with open(fpath, "wb") as f:
                        f.write(content)
                    downloaded += 1
                    log_rows.append({"category": cat, "institute_id": iid, "status": "ok", "url": url})
                    print(f"[{i+1}/{total}] OK ({len(content)//1024}KB) {fname}")
            else:
                log_rows.append({"category": cat, "institute_id": iid, "status": f"http_{resp.status_code}", "url": url})
                skipped_http += 1
                print(f"[{i+1}/{total}] HTTP {resp.status_code} {fname}")
        except Exception as e:
            log_rows.append({"category": cat, "institute_id": iid, "status": f"error_{type(e).__name__}", "url": url})
            skipped_http += 1
            print(f"[{i+1}/{total}] ERROR {e} {fname}")

        time.sleep(DELAY_SECONDS)

    with open(LOG_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["category", "institute_id", "status", "url"])
        w.writeheader()
        w.writerows(log_rows)

    print(f"\n--- Download summary ---")
    print(f"Total institutes: {total}")
    print(f"Downloaded/exists: {downloaded}")
    print(f"Skipped (HTTP error / exception): {skipped_http}")
    print(f"Skipped (too small): {skipped_small}")
    print(f"Log: {LOG_PATH}")
    return downloaded


if __name__ == "__main__":
    tn_df = get_tn_rows()
    print(f"Tamil Nadu institutes to process: {len(tn_df)}")
    download_pdfs(tn_df)
