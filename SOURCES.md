# Data sources

Every dataset used in this project, its official origin, licensing, and access
status. All sources are public and free; no paid data is used.

| Dataset | Official source | Authority | Access | Status |
|---|---|---|---|---|
| NIRF 2025 rankings + scores | https://www.nirfindia.org/Rankings/2025/ | Ministry of Education, Govt. of India | Public HTML ranking tables | Official, in use (13 categories) |
| NAAC-accredited college list | https://www.ugc.gov.in/ (state-wise PDF) | University Grants Commission, Govt. of India | Public PDF | Official, in use |
| NAAC grades / CGPA / validity | http://naac.gov.in/ | National Assessment and Accreditation Council | Public search + downloadable files | Official, pending (site outage) |
| AISHE college base (38,376 colleges, 2012-13) | https://www.data.gov.in/catalog/list-colleges-aishe-survey ("List of all colleges - 2012-2013") | Dept. of Higher Education, Ministry of Education (NDSAP) | Official CSV download | Official, in use |
| NIRF per-institute scorecards (data submitted by institutions) | https://www.nirfindia.org/nirfpdfcdn/2025/pdf/ | Ministry of Education, Govt. of India | Public per-institute PDFs | Official, in use; 2025 PDFs are published progressively, so where a 2025 scorecard was not yet available the latest prior submission is used |

## Notes on legitimacy

- NIRF, NAAC, UGC and AISHE are all Government of India bodies. Their published
  rankings, accreditation lists and survey data are public records.
- The AISHE base is the official "List of all colleges - 2012-2013" CSV downloaded
  directly from data.gov.in (Ministry of Education, NDSAP licence). It is dated
  2012-13 - the most recent cleanly-downloadable official college-level list with
  district. Newer AISHE data exists on aishe.gov.in via interactive export and can
  be layered in later. An earlier third-party mirror of this same file was removed.
- Each raw file is stored with its collection date. Government portals can lag or
  change; the pipeline keeps the last good copy if a source is unreachable.

## Cost

All sources are free and public. Hosting (GitHub, Streamlit Community Cloud) and
automation (GitHub Actions) are used on their free tiers. The project incurs no
monetary cost.
