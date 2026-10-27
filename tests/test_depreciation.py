"""Fixed Asset Depreciation parser: block structure and totals.

The report restarts ``SNO`` for every category block and closes each block with
a ``TOTAL :`` line. Those totals are the ground truth for the parsed rows.
"""

import re

import pytest

from helpers import fixture_path, preset_options
from parser import parse_file

FILENAME = "Test4_Depreciation.rpt"
PRESET = "Fixed Asset Depreciation"
NUMBER_RE = re.compile(r"-?[\d,]+(?:\.\d+)?")
DATE_RE = re.compile(r"^\d{2}-\d{2}-\d{4}$")


@pytest.fixture(scope="module")
def frame():
    df = parse_file(FILENAME, preset_options(PRESET))
    assert df is not None and not df.empty
    return df


@pytest.fixture(scope="module")
def source_lines():
    return fixture_path(FILENAME).read_text(encoding="utf-8", errors="replace").splitlines()


def as_number(text):
    return float(text.replace(",", "").strip())


def block_totals(source_lines):
    """The three numeric columns of every per-category ``TOTAL :`` line."""
    totals = []
    for line in source_lines:
        if line.strip().startswith("TOTAL :"):
            numbers = NUMBER_RE.findall(line.split(":", 1)[1])
            assert len(numbers) == 3, f"unexpected TOTAL line: {line!r}"
            totals.append(tuple(as_number(n) for n in numbers))
    return totals


def test_block_sno_restarts_at_one(frame):
    # SNO runs continuously through the categories of a major category and only
    # restarts when a new MAJOR CATEGORY begins.
    for major, block in frame.groupby("MAJOR_CATEGORY", sort=False):
        numbers = [int(v) for v in block["SNO"]]
        assert numbers == list(range(1, len(numbers) + 1)), (
            f"{major}: SNO is not contiguous from 1"
        )


def test_block_count_and_row_count(frame):
    blocks = list(frame.groupby(["MAJOR_CATEGORY", "CATEGORY"], sort=False))

    assert len(frame) == 308
    assert len(blocks) == 8
    assert [len(block) for _, block in blocks] == [68, 4, 1, 66, 46, 6, 72, 45]


def test_block_sums_match_reported_totals(frame, source_lines):
    reported = block_totals(source_lines)
    grouped = list(
        frame.groupby(["MAJOR_CATEGORY", "CATEGORY"], sort=False)[
            ["BLOCK_AMT", "ACTUAL_DEP", "QTR_DEP"]
        ]
    )

    assert len(grouped) == len(reported), "block count differs from TOTAL line count"

    for (key, block), (total_block, total_actual, total_qtr) in zip(grouped, reported):
        assert block["BLOCK_AMT"].sum() == pytest.approx(total_block, abs=0.01), key
        assert block["ACTUAL_DEP"].sum() == pytest.approx(total_actual, abs=0.01), key
        assert block["QTR_DEP"].sum() == pytest.approx(total_qtr, abs=0.01), key


def test_summary_rows_are_not_parsed_as_assets(frame):
    # The report's SUMMARY block (``TOTAL   |`` / ``Net Debit``) is an aggregate
    # over GL categories, not part of the per-asset detail.
    assert frame["SNO"].astype(str).str.strip().str.isdigit().all()
    assert (frame["ASSET_NO"].astype(str).str.strip() != "").all()
    assert not frame["ITEM NAME"].astype(str).str.upper().str.contains("TOTAL").any()


def test_summary_total_line_arithmetic(source_lines):
    grand = next(line for line in source_lines if line.strip().startswith("TOTAL   |"))
    parts = [p.strip() for p in grand.split("|")[1:] if p.strip()]
    block, actual, net = (as_number(p) for p in parts[:3])

    assert net == pytest.approx(block - actual, abs=0.01)

    line = next(l for l in source_lines if "Net Debit(-)/Credit(+)" in l)
    assert as_number(line.split("=", 1)[1]) == pytest.approx(net, abs=0.01)


def test_columns_are_typed_and_populated(frame):
    for column in ("BLOCK_AMT", "ACTUAL_DEP", "QTR_DEP", "D_RATE"):
        assert frame[column].dtype.kind in "if", f"{column} is not numeric"
        assert frame[column].notna().all(), f"{column} has gaps"

    for column in ("ASSET_NO", "ITEM NAME", "PURCH DATE", "MAJOR_CATEGORY", "CATEGORY", "METHOD"):
        values = frame[column].astype(str).str.strip()
        assert (values != "").all(), f"{column} has empty values"
        assert (values.str.lower() != "nan").all(), f"{column} has NaN strings"


def test_purchase_dates_and_amounts_are_sane(frame):
    assert frame["BLOCK_AMT"].gt(0).all()
    assert frame["D_RATE"].gt(0).all()
    for value in frame["PURCH DATE"]:
        assert DATE_RE.match(str(value).strip()), f"bad purchase date {value!r}"


def test_asset_numbers_are_unique_per_block(frame):
    for (major, category), block in frame.groupby(["MAJOR_CATEGORY", "CATEGORY"], sort=False):
        assets = block["ASSET_NO"].astype(str).str.strip()
        assert assets.is_unique, f"{major}/{category}: duplicate asset numbers"
