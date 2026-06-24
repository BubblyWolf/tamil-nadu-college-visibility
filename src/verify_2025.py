import json
import pandas as pd

root = "D:/opus-kimi-projects/indian-accreditation-analytics"

s = json.loads(open(f"{root}/web/data/summary.json").read())
print("summary.json:")
for k, v in s.items():
    print(f"  {k}: {v}")

df = pd.read_csv(f"{root}/data/processed/nirf_rankings.csv")
print(f"\nnirf_rankings.csv:")
print(f"  Total rows: {len(df)}")
cats = sorted(df["category"].unique())
print(f"  Categories ({len(cats)}): {cats}")
tn = df[df["state"].str.contains("Tamil", na=False)]
print(f"  TN rows: {len(tn)}, unique institutions: {tn['name'].nunique()}")

sc = pd.read_csv(f"{root}/data/processed/tn_scorecard_metrics.csv")
print(f"\ntn_scorecard_metrics.csv:")
print(f"  Rows: {len(sc)}")
print(f"  nirf_rank filled: {int(sc['nirf_rank'].notna().sum())}")
print(f"  First row institute: {sc['institute_name'].iloc[0]}")

ac = json.loads(open(f"{root}/web/data/all_colleges.json").read())
ranked = sum(1 for e in ac if e["ranked"])
print(f"\nall_colleges.json:")
print(f"  Total: {len(ac)}, ranked: {ranked}")

print(f"\nVintage check:")
print(json.dumps(s["vintages"], indent=2))
