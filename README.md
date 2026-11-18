# Mini SFCR Extraction Demo

A small, report-specific Python proof of concept that extracts three financial
metrics from Allianz p.l.c.'s public 2024 Solvency and Financial Condition Report.
It uses PyMuPDF and explicit rules, with no OCR, model training or LLM API.

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
year, source labels, evidence excerpts and source pages. Report metadata
includes the official reference URL, page count, reporting-period evidence and
a SHA-256 fingerprint of the processed file. The URL is a reference, not proof
that an arbitrary supplied file was downloaded from that address.

## Method and limits

The script extracts each page's selectable text with
`page.get_text("text", sort=True)`, confirms the cover's entity and year, and
matches Table 25's header and rows. The year header determines which column to
read. Eligible own funds requires the explicit E.1.2 statement and its year.
Missing, conflicting or ambiguous required evidence causes an error; output is
written only after extraction succeeds.

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

Three local macOS arm64 / Python 3.13.7 process runs took 2.622, 2.478 and
2.574 seconds for the 93-page report (median 2.574 seconds). This is a small
local timing sample; rerun on the intended environment before estimating costs.

This excludes installation, downloading and human review. The script makes no
LLM API calls. Local elapsed time alone is not a per-period production cost
estimate; that also needs document volume, infrastructure rates and review time.

This demo supports only this English-language 2024 Allianz p.l.c. report and
its observed text layout. Other insurers, reporting years, scanned PDFs,
changed wording or redesigned tables require further work. There is no general
table parser, OCR fallback or financial-data accuracy benchmark.
