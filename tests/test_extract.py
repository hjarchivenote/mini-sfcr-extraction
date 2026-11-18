"""Check year selection, evidence requirements, failures and the real PDF."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import pymupdf

from extract import extract_from_pages, extract_pdf


ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "data/allianz_sfcr_2024.pdf"
COVER = """Allianz p.l.c.
Solvency and Financial Condition Report
For the year ended 31 December 2024"""
ELIGIBLE = """E.1.2 Structure amount and quality of Own Funds
The amount of Basic Own Funds that is eligible to cover the Solvency Capital
Requirement is €271.1m (2023: €329.1m)
In €’m as at 31 December 2024
Solvency II Directive 2009/138/EC
Total Basic Own Funds after adjustments (solo)"""
TABLE = """€’m       YE 2024  YE 2023
SCR                      160      166
Own Funds                271      329
Coverage Ratio           169%     198%
Table 25: Overview of diversified risk capital, Own Funds and solvency coverage ratio"""


class RuleTests(unittest.TestCase):
    def pages(self):
        # The contents entry and unrelated numbers must not be treated as evidence.
        return [COVER, "Table 25: Overview ... 68\nSCR 999 888", ELIGIBLE, TABLE]

    def test_uses_current_year_and_explicit_eligible_amount(self):
        result = extract_from_pages(self.pages())
        metrics = result["metrics"]
        self.assertEqual(metrics["scr"]["value"], 160)
        self.assertEqual(metrics["solvency_ratio"]["value"], 169)
        self.assertEqual(metrics["eligible_own_funds"]["value"], 271.1)
        self.assertEqual(metrics["scr"]["source"]["pdf_page"], 4)
        self.assertEqual(metrics["eligible_own_funds"]["source"]["pdf_page"], 3)

    def test_selects_year_by_header_when_columns_are_reversed(self):
        pages = self.pages()
        pages[-1] = """€’m YE 2023 YE 2024
SCR 166 160
Own Funds 329 271
Coverage Ratio 198% 169%
Table 25: Overview of diversified risk capital, Own Funds and solvency coverage ratio"""
        self.assertEqual(extract_from_pages(pages)["metrics"]["scr"]["value"], 160)

    def test_reads_changed_values_instead_of_returning_constants(self):
        pages = self.pages()
        pages[2] = ELIGIBLE.replace("271.1", "300.2")
        pages[3] = TABLE.replace("160", "150").replace("271", "300").replace("169%", "200%")
        metrics = extract_from_pages(pages)["metrics"]
        self.assertEqual([metrics[key]["value"] for key in ["scr", "eligible_own_funds", "solvency_ratio"]], [150, 300.2, 200])

    def test_handles_layout_whitespace_and_alternate_apostrophe(self):
        pages = [page.replace(" ", "\u00a0").replace("’", "'") for page in self.pages()]
        self.assertEqual(extract_from_pages(pages)["metrics"]["scr"]["value"], 160)

    def test_rejects_missing_or_changed_table_evidence(self):
        variants = [
            TABLE.replace("€’m", "USD million"),
            TABLE.replace("YE 2024", "YE 2022"),
            TABLE.replace("YE 2023", "YE 2024"),
            TABLE.replace("169%", "169"),
            TABLE.replace("SCR                      160      166", ""),
            TABLE.replace("Table 25:", "Table 99:"),
        ]
        for variant in variants:
            with self.subTest(table=variant), self.assertRaises(ValueError):
                extract_from_pages([COVER, ELIGIBLE, variant])

    def test_rejects_ambiguous_duplicate_tables(self):
        with self.assertRaises(ValueError):
            extract_from_pages(self.pages() + [TABLE])

    def test_rejects_duplicate_rows_in_the_table(self):
        pages = self.pages()
        pages[-1] = TABLE.replace("Coverage Ratio", "SCR 160 166\nCoverage Ratio")
        with self.assertRaises(ValueError):
            extract_from_pages(pages)

    def test_requires_explicit_eligibility_and_its_reporting_year(self):
        variants = [
            ELIGIBLE.replace("eligible to cover", "available to cover"),
            ELIGIBLE.replace("2023:", "2022:"),
            ELIGIBLE.replace("December 2024", "December 2023"),
            ELIGIBLE.replace("€271.1m", "$271.1m"),
        ]
        for variant in variants:
            with self.subTest(eligible=variant), self.assertRaises(ValueError):
                extract_from_pages([COVER, variant, TABLE])

    def test_rejects_ambiguous_eligible_statements(self):
        with self.assertRaises(ValueError):
            extract_from_pages(self.pages() + [ELIGIBLE])

    def test_checks_own_funds_agreement_at_reported_precision(self):
        with self.assertRaises(ValueError):
            extract_from_pages([COVER, ELIGIBLE.replace("271.1", "280.1"), TABLE])

    def test_requires_evidence_for_the_expected_reporting_basis(self):
        for eligible in [
            ELIGIBLE.replace("(solo)", "(group)"),
            ELIGIBLE.replace("Solvency II Directive 2009/138/EC", "IFRS"),
        ]:
            with self.subTest(eligible=eligible), self.assertRaises(ValueError):
                extract_from_pages([COVER, eligible, TABLE])

    def test_rejects_other_reports_and_empty_text(self):
        for cover in ["", COVER.replace("2024", "2023"), COVER.replace("Allianz p.l.c.", "Other insurer")]:
            with self.subTest(cover=cover), self.assertRaises(ValueError):
                extract_from_pages([cover, ELIGIBLE, TABLE])
        with self.assertRaises(ValueError):
            extract_from_pages([])


class RealPdfTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not PDF.is_file():
            raise FileNotFoundError("Download the official source PDF using the README before running tests.")
        cls.result = extract_pdf(PDF)

    def test_real_report_values_units_years_and_page_numbers(self):
        expected = {
            "solvency_ratio": (169, "%", 70),
            "scr": (160, "EUR million", 70),
            "eligible_own_funds": (271.1, "EUR million", 67),
        }
        for key, (value, unit, page) in expected.items():
            with self.subTest(metric=key):
                actual = self.result["metrics"][key]
                self.assertEqual((actual["value"], actual["unit"], actual["source"]["pdf_page"]), (value, unit, page))
                self.assertEqual(actual["report_year"], 2024)
                self.assertEqual(actual["reporting_basis"]["scope"], "solo")
                self.assertEqual(actual["reporting_basis"]["framework"], "Solvency II")
                self.assertIn(actual["raw_value"], actual["source"]["text"])
        self.assertEqual(self.result["document"]["page_count"], 93)
        self.assertEqual(self.result["document"]["sha256"], hashlib.sha256(PDF.read_bytes()).hexdigest())

    def test_committed_json_is_reproducible(self):
        stored = json.loads((ROOT / "output.json").read_text(encoding="utf-8"))
        self.assertEqual(stored, self.result)

    def test_every_evidence_excerpt_exists_on_its_claimed_pdf_page(self):
        with pymupdf.open(PDF) as document:
            for metric in self.result["metrics"].values():
                for evidence in [metric["source"], metric["reporting_basis"]["source"]]:
                    text = " ".join(document[evidence["pdf_page"] - 1].get_text("text", sort=True).split())
                    for excerpt in evidence["text"].splitlines():
                        self.assertIn(" ".join(excerpt.split()), text)

    def test_cli_writes_expected_json(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.json"
            process = subprocess.run([sys.executable, str(ROOT / "extract.py"), str(PDF), "--output", str(output)], capture_output=True, text=True)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), self.result)

    def test_failed_cli_preserves_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.json"
            output.write_text("previous result", encoding="utf-8")
            process = subprocess.run([sys.executable, str(ROOT / "extract.py"), str(Path(directory) / "missing.pdf"), "--output", str(output)], capture_output=True, text=True)
            self.assertNotEqual(process.returncode, 0)
            self.assertIn("Extraction failed", process.stderr)
            self.assertEqual(output.read_text(encoding="utf-8"), "previous result")


if __name__ == "__main__":
    unittest.main()
