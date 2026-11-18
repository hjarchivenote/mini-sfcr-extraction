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
SOURCE_LISTING_URL = "https://www.allianz.ie/about/about-allianz/regulatory-information.html"
DOCUMENT_ID = "allianz-plc-sfcr-2024"
DOCUMENT_TITLE = "Solvency and Financial Condition Report"
PUBLISHER = "Allianz p.l.c."
REPORT_YEAR = 2024
PERIOD_END = "2024-12-31"
METRIC_SPECS = {
    "solvency_ratio": ("%", "Reported solvency coverage ratio of own funds to SCR."),
    "scr": ("EUR million", "Solvency Capital Requirement under Solvency II."),
    "eligible_own_funds": (
        "EUR million", "Basic own funds eligible to cover the Solvency Capital Requirement."
    ),
}
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
ELIGIBLE_LABEL = (
    "amount of Basic Own Funds that is eligible to cover the Solvency Capital Requirement"
)
ELIGIBLE_PATTERN = re.compile(
    re.escape(ELIGIBLE_LABEL) + rf" is €(?P<value>{NUMBER})m "
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


def validate_reported_metric(record):
    """Validate this demo's reported records; calculated/estimated figures are unsupported."""
    if not isinstance(record, dict):
        raise ValueError("A reported figure must be a record with explicit evidence.")
    if record.get("figure_type") != "Reported" or any(
        key in record for key in ("formula", "inputs", "source_inputs")
    ):
        raise ValueError("Only Reported figures are supported; calculations and estimates are unsupported.")
    try:
        unit, definition = METRIC_SPECS[record["metric"]]
        if (
            record["entity"] != PUBLISHER
            or type(record["report_year"]) is not int
            or record["report_year"] != REPORT_YEAR
            or record["reporting_period"] != {"type": "point_in_time", "date": PERIOD_END}
            or record["reporting_basis"]["scope"] != "solo"
            or record["reporting_basis"]["framework"] != "Solvency II"
            or record["unit"] != unit or record["definition"] != definition
        ):
            raise ValueError("Unsupported metric, entity, period, unit, definition or reporting basis.")
        raw, value = record["raw_value"], record["value"]
        if (
            not isinstance(raw, str) or not re.fullmatch(NUMBER, raw)
            or type(value) not in (int, float) or decimal(raw) != Decimal(str(value))
        ):
            raise ValueError("A figure must retain its explicit reported numeric value.")
        for evidence in (record["source"], record["reporting_basis"]["source"]):
            if (
                evidence["document_id"] != DOCUMENT_ID
                or type(evidence["pdf_page"]) is not int or evidence["pdf_page"] < 1
                or not evidence["section"].strip() or not evidence["text"].strip()
            ):
                raise ValueError("A reported figure requires document, page and source evidence.")
        if raw not in record["source"]["text"]:
            raise ValueError("The reported numeric value is missing from its source excerpt.")
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError("Missing or invalid reported-figure evidence or comparison context.") from error


def assert_comparable(left, right):
    """Guard comparisons; only the same measure at this report's supported date is allowed."""
    try:
        validate_reported_metric(left)
        validate_reported_metric(right)
        if left["metric"] != right["metric"]:
            raise ValueError("Different metric definitions cannot be compared.")
    except ValueError as error:
        raise ValueError(f"Incompatible comparison: {error}") from error


def metric(name, raw, unit, label, page, section, evidence, basis):
    value = decimal(raw)
    record = {
        "metric": name,
        "entity": PUBLISHER,
        "definition": METRIC_SPECS[name][1],
        "figure_type": "Reported",
        "value": int(value) if value == value.to_integral_value() else float(value),
        "raw_value": raw,
        "unit": unit,
        "report_year": REPORT_YEAR,
        "reporting_period": {"type": "point_in_time", "date": PERIOD_END},
        "reporting_basis": basis,
        "source_label": label,
        "source": {
            "document_id": DOCUMENT_ID, "pdf_page": page, "section": section,
            "table": section if section.startswith("Table ") else None, "text": evidence,
        },
    }
    validate_reported_metric(record)
    return record


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
        cover.count(PUBLISHER) != 1
        or cover.count(DOCUMENT_TITLE) != 1
        or int(period) != REPORT_YEAR
    ):
        raise ValueError("Only Allianz p.l.c.'s 2024 SFCR is supported.")

    # Count candidate captions before matching values: a valid table must not
    # hide a second incomplete or conflicting copy of the same required table.
    table_page = exactly_one(
        [i for i, text in enumerate(pages, 1)
         for _ in re.finditer(re.escape(TABLE_CAPTION), text)],
        "Table 25 source caption",
    )
    table = exactly_one(
        list(TABLE_PATTERN.finditer(pages[table_page - 1])),
        "complete Table 25 with units, years and all three rows",
    )
    years = [int(table["year_a"]), int(table["year_b"])]
    if sorted(years) != [REPORT_YEAR - 1, REPORT_YEAR]:
        raise ValueError("Table 25 does not identify the expected reporting years.")
    column = "a" if years[0] == REPORT_YEAR else "b"

    eligible_page = exactly_one(
        [i for i, text in enumerate(pages, 1)
         if "E.1.2 Structure amount and quality of Own Funds" in text
         for _ in re.finditer(re.escape(ELIGIBLE_LABEL), text)],
        "eligible-own-funds source statement",
    )
    eligible = exactly_one(
        list(ELIGIBLE_PATTERN.finditer(pages[eligible_page - 1])),
        "explicit statement of own funds eligible to cover the SCR",
    )
    eligible_year_header = exactly_one(
        list(re.finditer(r"In €[’‘']m as at 31 December (\d{4})\b", pages[eligible_page - 1])),
        "eligible-own-funds year header",
    )
    if int(eligible["previous_year"]) != REPORT_YEAR - 1 or int(eligible_year_header[1]) != REPORT_YEAR:
        raise ValueError("The eligible-own-funds reporting year is not confirmed.")

    basis_text = pages[eligible_page - 1]
    scope = exactly_one(
        list(re.finditer(r"Total Basic Own Funds after adjustments \(([^)]+)\)", basis_text)),
        "own-funds scope statement",
    )
    framework = exactly_one(
        list(re.finditer(r"(Solvency II) Directive 2009/138/EC", basis_text)),
        "Solvency II framework statement",
    )
    if scope[1] != "solo":
        raise ValueError("The expected solo Solvency II reporting basis is not confirmed.")
    basis = {
        "scope": scope[1],
        "framework": framework[1],
        "source": {
            "document_id": DOCUMENT_ID,
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
            "solvency_ratio", table[f"ratio_{column}"], "%", "Coverage Ratio",
            table_page, "Table 25", table_evidence, basis,
        ),
        "scr": metric(
            "scr", table[f"scr_{column}"], "EUR million", "SCR",
            table_page, "Table 25", table_evidence, basis,
        ),
        "eligible_own_funds": metric(
            "eligible_own_funds", eligible["value"], "EUR million",
            "Basic Own Funds eligible to cover the Solvency Capital Requirement",
            eligible_page, "E.1.2 Structure amount and quality of Own Funds",
            eligible[0] + "\n" + eligible_year_header[0], basis,
        ),
    }
    return {
        "entity": PUBLISHER,
        "report_year": REPORT_YEAR,
        "report_period_end": PERIOD_END,
        "method": "Report-specific rules on PyMuPDF page text; no OCR or AI model.",
        "page_numbering": "1-based PDF page position, including the cover.",
        "report_period_source": {
            "document_id": DOCUMENT_ID,
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
        "id": DOCUMENT_ID,
        "title": DOCUMENT_TITLE,
        "publisher": PUBLISHER,
        "publication_date": None,
        "publication_date_status": "unknown",
        "publication_date_note": (
            "No publication date verified in the official PDF or issuer listing. "
            "The reporting year and PDF creation/modification timestamps are not publication dates."
        ),
        "metadata_sources": [SOURCE_URL, SOURCE_LISTING_URL],
        "cover_source": {
            "document_id": DOCUMENT_ID, "pdf_page": 1,
            "text": f"{PUBLISHER}\n{DOCUMENT_TITLE}\nFor the year ended 31 December {REPORT_YEAR}",
        },
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
