# Mini SFCR Extraction Demo

A small, report-specific Python proof of concept that extracts three financial
metrics from Allianz p.l.c.'s public 2024 Solvency and Financial Condition Report.
It uses PyMuPDF and explicit rules, with no OCR, model training or LLM API.
All three figures are labelled `Reported`; calculated metrics and estimates are
not supported. The published coverage ratio is extracted directly.

## Run

Python 3.10 or later is required. Tested with Python 3.13.7 and PyMuPDF 1.26.7.
Run these commands from this project directory:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
mkdir -p data
curl --fail --location --output data/allianz_sfcr_2024.pdf \
  https://www.allianz.ie/content/dam/onemarketing/azie/allianz-ireland/en_us/documents/regulatory-information/eaa/allianz-sfcr-2024.pdf
python extract.py
python -m unittest discover -s tests -v
```

The downloaded report remains local and is excluded from Git. Its official
[source PDF](https://www.allianz.ie/content/dam/onemarketing/azie/allianz-ireland/en_us/documents/regulatory-information/eaa/allianz-sfcr-2024.pdf)
can also be saved manually as `data/allianz_sfcr_2024.pdf`.

Optional paths: `python extract.py path/to/report.pdf --output result.json`.

## Verified results

| Metric | Reported value | Unit | Year | PDF page | Source |
| --- | ---: | --- | ---: | ---: | --- |
| Solvency coverage ratio | 169 | % | 2024 | 70 | Table 25, Coverage Ratio |
| Solvency Capital Requirement (SCR) | 160 | EUR million | 2024 | 70 | Table 25, SCR |
| Eligible own funds to cover the SCR | 271.1 | EUR million | 2024 | 67 | E.1.2, explicit eligibility statement |

All three figures refer to **Allianz p.l.c. on a solo Solvency II basis**.
Each metric records the scope and framework, with supporting excerpts from
E.1.2 on PDF page 67. This demo recognizes this report's basis and rejects
missing or changed basis evidence; it does not resolve arbitrary reporting bases.

Pages are **1-based positions in the PDF, including the cover**. The contents
list points to page 68 for Table 25, but the table is actually on PDF page 70;
the extractor locates its content rather than hardcoding a page number.

Table 25 rounds own funds to EUR 271 million. E.1.2 explicitly identifies
EUR 271.1 million as eligible to cover the SCR, so that more precise figure is
retained. The extractor checks that this rounds to the table's own-funds value.
SCR and coverage ratio retain Table 25's rounded precision. The annex contains
more precise figures; this demo does not extract those or recompute the ratio.

`output.json` contains numeric values, raw number strings, units, the reporting
year, the company's source labels, plain definitions, `Reported` labels and
page/table evidence. Each metric also identifies its entity and point-in-time
date, 31 December 2024, separately from the report's financial year.

## Source metadata

The document title is **Solvency and Financial Condition Report**, and the
publisher is **Allianz p.l.c.** These were checked against the official PDF's
cover and Allianz Ireland's
[regulatory information page](https://www.allianz.ie/about/about-allianz/regulatory-information.html),
whose 2024 report link resolves to the source PDF above (checked 18 November 2026).

The document record includes the title, publisher, original HTTPS `source_url`,
the two official `metadata_sources`, cover-page evidence, page count and file
SHA-256. Each metric's evidence links to that document's ID and a PDF page;
Table 25 rows also have an explicit table reference. The eligible-own-funds
figure is from prose, so its table field is `null` and its section is recorded.
The URL is a reference, not proof that an arbitrary supplied file came from it;
the SHA-256 identifies the processed bytes. Metadata is reviewed manually,
not fetched from the web during extraction.

**Publication date: unknown (`publication_date: null`).** No publication date
could be verified in the official PDF or issuer listing. The reporting year,
year-end date, PDF creation/modification timestamps and HTTP timestamps are not
used as a publication date. `publication_date_status` and a note retain this gap.

The checks are informed by Sections B and C of C&C's
[published methodology](https://www.insurancecapitalandcraft.com/methodology):
preserve definitions, bases and periods; retain source evidence; distinguish
reported from calculated figures; and never fill missing reported figures.
Section C requires a publication date for a publishable source. This demo's
explicit unknown-date exception does **not** satisfy that requirement and is
not a claim to implement the entire methodology.

## Validation and comparability

Required figures are never estimated, interpolated, inferred from other values
or replaced with zero. A complete source cannot hide an incomplete or conflicting
duplicate of the recognized Table 25 or E.1.2 statement. Missing values, units,
years or basis evidence, and ambiguous source captions/headers, raise an error.
The rounding check only validates the two reported own-funds disclosures; it
does not generate or replace an output figure.

Every output metric passes `validate_reported_metric`. Only `Reported` records
with explicit raw values and source evidence are accepted. `Calculated`,
`Estimate`, missing labels and calculation metadata such as formulas or source
inputs are rejected. Adding calculated metrics later would require explicit
formula and input provenance; that feature is intentionally absent here.

`assert_comparable(left, right)` is a small pre-comparison guard. It requires the
same metric and definition, units, Allianz p.l.c. entity, solo Solvency II basis,
and supported point-in-time date. Missing context or a different scope,
framework, period type, date or entity raises `ValueError` before a comparison.
For example, the tests copy an extracted SCR record, change its scope to `group`,
and confirm that the guard rejects it. This conservative demo permits only the
same supported 2024 snapshot; it implements no peer, time-series or year-on-year
analysis. The guard checks supplied record metadata; the real-PDF tests check
provenance for the supported file. It does not authenticate arbitrary external
records or harmonize differing definitions.

## Method and limits

The script extracts each page's selectable text with
`page.get_text("text", sort=True)`, confirms the cover's entity and year, and
matches Table 25's header and rows. The year header determines which column to
read. Eligible own funds requires the explicit E.1.2 statement and its year.
Missing, conflicting or ambiguous required evidence causes an error; output is
written only after extraction succeeds. The CLI exits non-zero with a clear
error on failure; an existing output file remains the previous result.

The source pages were also rendered and visually checked against these results.
The real-PDF tests compare all three figures against manually checked reference
values, units, years and pages. They also verify that every saved value and basis
excerpt exists on its claimed page and that `output.json` can be reproduced.
Separate synthetic cases test column selection, changed values, whitespace,
missing units, ambiguity and missing basis evidence. Passing these tests
demonstrates this report-specific extraction, not accuracy across other SFCRs
or the entire PDF.

To measure local elapsed time, including Python startup and PDF extraction:

```sh
/usr/bin/time -p python extract.py
```

Three local macOS arm64 / Python 3.13.7 process runs of the initial demo took
2.622, 2.478 and 2.574 seconds for the 93-page report (median 2.574 seconds). This is a small
local timing sample; rerun on the intended environment before estimating costs.

This excludes installation, downloading and human review. The script makes no
LLM API calls. Local elapsed time alone is not a per-period production cost
estimate; that also needs document volume, infrastructure rates and review time.

This demo supports only this English-language 2024 Allianz p.l.c. report and
its observed text layout. Other insurers, reporting years, scanned PDFs,
changed wording or redesigned tables require further work. There is no general
table parser, OCR fallback or financial-data accuracy benchmark.
