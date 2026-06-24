# The State of Tamil Nadu's Colleges

An independent analysis of how ranking and accreditation visibility is
distributed across Tamil Nadu's higher education, built entirely from public
government data. Tamil Nadu is known for the reach of its college system; this
project asks a sharper question — which colleges the national systems actually
see, and which they don't.

**Live site:** _coming soon_ (static site in `web/`, deploys free on GitHub Pages)
**Author:** [Chitranjan Jegadeesan](https://www.chitranjanjegadeesan.in/) ·
[LinkedIn](https://www.linkedin.com/in/chitranjan-jegadeesan/)

## What it shows

- **The visibility deserts** — every Tamil Nadu district by number of colleges
  versus how many are nationally ranked. Several large districts have none.
- **Check a college** — search any Tamil Nadu college, ranked or not, or browse
  the ranked institutions by field. For a ranked college you see, from its own
  NIRF data submission, where it is strong, where it lags its category peers, and
  the single biggest gap to close; for an unranked one, what that means.
- **Findings** — the headline numbers, drawn from current figures.

## Headline findings

- About **97.0%** of Tamil Nadu's 2,829 colleges do not appear in any NIRF
  ranking — only 84 unique institutions are ranked (NIRF 2025), leaving the large
  majority without a public quality signal.
- **51.2%** of the state's ranked institutions sit in just two cities, Chennai
  and Coimbatore.
- Multiple large districts (Kancheepuram, Namakkal, Kanniyakumari, Viluppuram)
  have **zero** nationally ranked institutions despite 80+ colleges each.

## Data sources and vintage

| Layer | Source | Vintage |
|---|---|---|
| Rankings and scores | NIRF (Ministry of Education) | 2025 |
| Per-institution scorecards | NIRF (Ministry of Education) | 2025 where published, else latest prior |
| State total number of colleges | AISHE Report 2021-22 | 2021-22 |
| District-level college counts | AISHE "List of all colleges", data.gov.in | 2012-13 |
| Accredited-college list | UGC state-wise NAAC list | as published |

All sources are official and public. See [SOURCES.md](SOURCES.md) for exact
origins and [DISCLAIMER.md](DISCLAIMER.md) for limitations and intended use.

## Repository layout

```
data/
  raw/         source files as collected (incl. 153 NIRF scorecards)
  processed/   cleaned, analysis-ready CSVs
src/
  clean/       parsers for each source
  build/       builds the web data bundle (web/data/*.json)
web/           the static site (index.html + data/*.json)
```

## Reproduce

```bash
pip install -r requirements.txt
python src/clean/parse_nirf.py
python src/clean/parse_aishe.py
python src/clean/download_nirf_scorecards.py
python src/clean/parse_nirf_scorecards.py
python src/build/build_web_data.py
# then serve the site:
cd web && python -m http.server 8530
```

## License

Code is MIT. Analysis, charts and written content are CC BY 4.0 (attribution
required). See [LICENSE](LICENSE).
