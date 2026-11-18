"""Extract three reported metrics from Allianz p.l.c.'s 2024 SFCR.

This is a report-specific, text-only proof of concept. No OCR or model is used.
"""

import argparse
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import re

import pymupdf


SOURCE_URL = (
    "https://www.allianz.ie/content/dam/onemarketing/azie/allianz-ireland/"
    "en_us/documents/regulatory-information/eaa/allianz-sfcr-2024.pdf"
)
REPORT_YEAR = 2024
NUMBER = r"\d+(?:,\d{3})*(?:\.\d+)?"
TABLE_CAPTION = (
    "Table 25: Overview of diversified risk capital, Own Funds "
    "and solvency coverage ratio"
)
TABLE_PATTERN = re.compile(
    rf"(?P<header>€[’‘']m YE (?P<year_a>\d{{4}}) YE (?P<year_b>\d{{4}})) "
    rf"(?P<scr>SCR (?P<scr_a>{NUMBER}) (?P<scr_b>{NUMBER})) "
    rf"(?P<funds>Own Funds (?P<funds_a>{NUMBER}) (?P<funds_b>{NUMBER})) "
    rf"(?P<ratio>Coverage Ratio (?P<ratio_a>{NUMBER})% (?P<ratio_b>{NUMBER})%) "
    + re.escape(TABLE_CAPTION)
)
ELIGIBLE_PATTERN = re.compile(
    r"amount of Basic Own Funds that is eligible to cover the "
    rf"Solvency Capital Requirement is €(?P<value>{NUMBER})m "
    rf"\((?P<previous_year>\d{{4}}): €(?P<previous_value>{NUMBER})m\)"
)


def normalize(text):
    """Collapse layout whitespace without changing labels, numbers or punctuation."""
    return " ".join(text.split())


def exactly_one(items, description):
    if len(items) != 1:
        raise ValueError(f"Expected one {description}; found {len(items)}.")
    return items[0]


def decimal(raw):
    return Decimal(raw.replace(",", ""))


def metric(raw, unit, label, page, section, evidence, basis):
    value = decimal(raw)
    return {
        "value": int(value) if value == value.to_integral_value() else float(value),
        "raw_value": raw,
        "unit": unit,
        "report_year": REPORT_YEAR,
        "reporting_basis": basis,
        "source_label": label,
        "source": {"pdf_page": page, "section": section, "text": evidence},
    }


def extract_from_pages(page_texts):
    """Apply narrow rules to page text; missing or ambiguous evidence is an error."""
    pages = [normalize(text) for text in page_texts]
    if not pages:
        raise ValueError("The PDF has no pages.")
    cover = pages[0]
    period = exactly_one(
        re.findall(r"For the year ended 31 December (\d{4})", cover),
        "reporting period on the cover",
    )
    if (
        "Allianz p.l.c." not in cover
        or "Solvency and Financial Condition Report" not in cover
        or int(period) != REPORT_YEAR
    ):
        raise ValueError("Only Allianz p.l.c.'s 2024 SFCR is supported.")

    table_page, table = exactly_one(
        [(i, match) for i, text in enumerate(pages, 1)
         for match in TABLE_PATTERN.finditer(text)],
        "complete Table 25 with units, years and all three rows",
    )
    years = [int(table["year_a"]), int(table["year_b"])]
    if sorted(years) != [REPORT_YEAR - 1, REPORT_YEAR]:
        raise ValueError("Table 25 does not identify the expected reporting years.")
    column = "a" if years[0] == REPORT_YEAR else "b"

    eligible_page, eligible = exactly_one(
        [(i, match) for i, text in enumerate(pages, 1)
         if "E.1.2 Structure amount and quality of Own Funds" in text
         for match in ELIGIBLE_PATTERN.finditer(text)],
        "explicit statement of own funds eligible to cover the SCR",
    )
    eligible_year_header = re.search(
        rf"In €[’‘']m as at 31 December {REPORT_YEAR}\b", pages[eligible_page - 1]
    )
    if int(eligible["previous_year"]) != REPORT_YEAR - 1 or not eligible_year_header:
        raise ValueError("The eligible-own-funds reporting year is not confirmed.")

    basis_text = pages[eligible_page - 1]
    scope = re.search(r"Total Basic Own Funds after adjustments \((solo)\)", basis_text)
    framework = re.search(r"(Solvency II) Directive 2009/138/EC", basis_text)
    if not scope or not framework:
        raise ValueError("The expected solo Solvency II reporting basis is not confirmed.")
    basis = {
        "scope": scope[1],
        "framework": framework[1],
        "source": {
            "pdf_page": eligible_page,
            "section": "E.1.2 Structure amount and quality of Own Funds",
            "text": framework[0] + "\n" + scope[0],
        },
    }

    # Table 25 rounds own funds to whole millions; retain the explicit eligible
    # amount from E.1.2 instead, and check that the two sources agree when rounded.
    rounded_funds = decimal(table[f"funds_{column}"])
    quantum = Decimal(1).scaleb(rounded_funds.as_tuple().exponent)
    if decimal(eligible["value"]).quantize(quantum, rounding=ROUND_HALF_UP) != rounded_funds:
        raise ValueError("Eligible own funds disagree with Table 25 at its precision.")

    table_evidence = "\n".join(
        [table["header"], table["scr"], table["funds"], table["ratio"], TABLE_CAPTION]
    )
    metrics = {
        "solvency_ratio": metric(
            table[f"ratio_{column}"], "%", "Coverage Ratio",
            table_page, "Table 25", table_evidence, basis,
        ),
        "scr": metric(
            table[f"scr_{column}"], "EUR million", "SCR",
            table_page, "Table 25", table_evidence, basis,
        ),
        "eligible_own_funds": metric(
            eligible["value"], "EUR million",
            "Basic Own Funds eligible to cover the Solvency Capital Requirement",
            eligible_page, "E.1.2 Structure amount and quality of Own Funds",
            eligible[0] + "\n" + eligible_year_header[0], basis,
        ),
    }
    return {
        "entity": "Allianz p.l.c.",
        "report_year": REPORT_YEAR,
        "report_period_end": f"{REPORT_YEAR}-12-31",
        "method": "Report-specific rules on PyMuPDF page text; no OCR or AI model.",
        "page_numbering": "1-based PDF page position, including the cover.",
        "report_period_source": {
            "pdf_page": 1,
            "text": f"For the year ended 31 December {period}",
        },
        "metrics": metrics,
    }


def extract_pdf(pdf_path):
    path = Path(pdf_path)
    payload = path.read_bytes()
    with pymupdf.open(stream=payload, filetype="pdf") as document:
        if document.needs_pass:
            raise ValueError("Password-protected PDFs are not supported.")
        pages = [page.get_text("text", sort=True) for page in document]
    result = extract_from_pages(pages)
    result["document"] = {
        "filename": path.name,
        "source_url": SOURCE_URL,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "page_count": len(pages),
        "source_url_note": "Official reference URL; the supplied file is identified by SHA-256.",
    }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", nargs="?", type=Path, default=Path("data/allianz_sfcr_2024.pdf"))
    parser.add_argument("--output", type=Path, default=Path("output.json"))
    args = parser.parse_args()
    try:
        if args.pdf.resolve() == args.output.resolve():
            raise ValueError("The output path must differ from the source PDF.")
        result = extract_pdf(args.pdf)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, RuntimeError, pymupdf.FileDataError) as error:
        parser.exit(1, f"Extraction failed: {error}\n")
    print(f"Extracted {len(result['metrics'])} metrics -> {args.output}")


if __name__ == "__main__":
    main()
