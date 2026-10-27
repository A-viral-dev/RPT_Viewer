"""Interest Report parsers (LA001 / LA030 / OD028 / CC001 & CC002).

These reports are pipe-delimited and start with a three-line caption block.
The parser must skip the caption and keep exactly one row per account, and the
sum of ``BALANCE OUTSTANDING`` must agree with the report's own total.
"""

import re

import pytest

from helpers import fixture_path, preset_options
from parser import parse_file

TOTAL_RE = re.compile(r"Total Outstanding\s*:\s*(-?[\d,]+\.\d{2})")
RECORDS_RE = re.compile(r"Number of Records\s*:\s*(\d+)")

CASES = [
    pytest.param(
        "Test5_intrest report_LA001.rpt", "Interest Report (LA001)",
        33, "LA001", id="la001",
    ),
    pytest.param(
        "Test6_intrest report_LA030.rpt", "Interest Report (LA030)",
        7, "LA030", id="la030",
    ),
    pytest.param(
        "Test7_intrest report_OD028.rpt", "Interest Report (OD028)",
        6, "OD028", id="od028",
    ),
    pytest.param(
        "Test8_intrest report_CC001.rpt", "Interest Report (CC001 & CC002)",
        47, "CC001", id="cc001",
    ),
]


def load(filename, preset):
    return parse_file(filename, preset_options(preset))


def final_total(filename):
    """The closing ``Total Outstanding :`` line (per-SOL subtotals do not match)."""
    text = fixture_path(filename).read_text(encoding="utf-8", errors="replace")
    matches = TOTAL_RE.findall(text)
    assert matches, f"{filename}: no closing Total Outstanding line"
    return float(matches[-1].replace(",", ""))


def reported_records(filename):
    for line in fixture_path(filename).read_text(encoding="utf-8", errors="replace").splitlines():
        match = RECORDS_RE.search(line)
        if match:
            return int(match.group(1))
    return None


@pytest.mark.parametrize("filename,preset,expected_rows,scheme", CASES)
def test_row_count_matches_report(filename, preset, expected_rows, scheme):
    df = load(filename, preset)

    assert len(df) == expected_rows
    records = reported_records(filename)
    if records is not None:
        assert records == expected_rows, f"{filename}: header says {records} records"


@pytest.mark.parametrize("filename,preset,expected_rows,scheme", CASES)
def test_scheme_code_is_consistent(filename, preset, expected_rows, scheme):
    df = load(filename, preset)
    codes = set(df["SCHM CODE"].astype(str).str.strip())

    assert codes == {scheme}
    for column in ("SCHM CODE", "SCHM DESCRIPTION", "NAME OF ACCOUNT HOLDER"):
        values = df[column].astype(str).str.strip()
        assert (values != "").all(), f"{column} has empty values"


@pytest.mark.parametrize("filename,preset,expected_rows,scheme", CASES)
def test_caption_block_is_not_parsed_as_data(filename, preset, expected_rows, scheme):
    df = load(filename, preset)
    first_column = df.iloc[:, 0].astype(str).str.strip().str.upper()

    assert "SCHM" not in set(first_column)
    assert "CODE" not in set(first_column)


@pytest.mark.parametrize("filename,preset,expected_rows,scheme", CASES)
def test_accounts_are_unique_fourteen_digit_numbers(filename, preset, expected_rows, scheme):
    df = load(filename, preset)
    accounts = [str(v).strip() for v in df["ACCOUNT NUMBER"]]

    assert len(accounts) == expected_rows
    assert all(len(a) == 14 and a.isdigit() for a in accounts), "non 14-digit account found"
    assert len(set(accounts)) == len(accounts), "duplicate account number"


@pytest.mark.parametrize("filename,preset,expected_rows,scheme", CASES)
def test_outstanding_total_reconciles(filename, preset, expected_rows, scheme):
    df = load(filename, preset)
    parsed = sum(float(str(v).replace(",", "")) for v in df["BALANCE OUTSTANDING"])
    expected = final_total(filename)

    # The source report rounds each row, so allow a few paise of drift.
    assert parsed == pytest.approx(expected, abs=0.05)


@pytest.mark.parametrize("filename,preset,expected_rows,scheme", CASES)
def test_numeric_columns_are_parsed(filename, preset, expected_rows, scheme):
    df = load(filename, preset)
    for column in ("EFFECTIVE ROI", "MIN RATE", "MAX RATE", "SANCTIONED LIMIT", "BALANCE OUTSTANDING"):
        assert df[column].dtype.kind == "f", f"{column} is not numeric"
        assert df[column].notna().all(), f"{column} has gaps"

    assert (df["MAX RATE"] >= 0).all()
    assert (df["EFFECTIVE ROI"] >= 0).all()
