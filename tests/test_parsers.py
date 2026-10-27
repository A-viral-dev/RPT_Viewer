"""Shape and column contract for every parser route.

Each case pairs a fixture with the preset the UI would use. The expected
shapes are the shapes of the pristine source reports, so a change here means
the parser started dropping or inventing rows.
"""

import pytest

from helpers import preset_options
from parser import parse_file

STATEMENT_COLUMNS = [
    "DATE", "PARTICULARS", "CHQ.NO.", "WITHDRAWALS", "DEPOSITS", "BALANCE",
    "Narration",
]

DEPRECIATION_COLUMNS = [
    "SNO", "ASSET_NO", "ITEM NAME", "PURCH DATE", "BLOCK_AMT", "D_RATE",
    "ACTUAL_DEP", "QTR_DEP", "MAJOR_CATEGORY", "CATEGORY", "METHOD",
]

INTEREST_COLUMNS = [
    "SCHM CODE", "SCHM DESCRIPTION", "ACCOUNT NUMBER",
    "NAME OF ACCOUNT HOLDER", "INTRST PEGGED", "APPLI INT. TABLE",
    "RATE AS INT. TABLE", "CUST LVL INT. PREF", "ACCT LVL INT. PREF",
    "EFFECTIVE ROI", "MIN RATE", "MAX RATE", "SANCTIONED LIMIT",
    "BALANCE OUTSTANDING", "LIM LEVEL FLAG", "MATURITY DT", "NEXT INT CALC",
    "ASSET CLASS", "INT FREQ TYPE",
]

NO_MERGE = {"merge_narration": False}

CASES = [
    pytest.param(
        "Test2_Statement_term_loan.RPT", "Finacle - Term Loan (.RPT)",
        (60, 7), STATEMENT_COLUMNS, NO_MERGE, id="term-loan",
    ),
    pytest.param(
        "Test2_Statement_term_loan.RPT", " Escrow Account",
        (60, 7), STATEMENT_COLUMNS, NO_MERGE, id="escrow",
    ),
    pytest.param(
        "test3_statemen_Cash Credit General.RPT", "Cash credit general (CC001)",
        (66, 7), STATEMENT_COLUMNS, NO_MERGE, id="cc001",
    ),
    pytest.param(
        "Temp_CC.RPT", "Cash credit general (CC001)",
        (1537, 7), STATEMENT_COLUMNS, NO_MERGE, id="cc-sample",
    ),
    pytest.param(
        "last_session.rpt", "Cash credit general (CC001)",
        (1537, 7), STATEMENT_COLUMNS, NO_MERGE, id="cc-last-session",
    ),
    pytest.param(
        "Test4_Depreciation.rpt", "Fixed Asset Depreciation",
        (308, 11), DEPRECIATION_COLUMNS, {}, id="depreciation",
    ),
    pytest.param(
        "Test5_intrest report_LA001.rpt", "Interest Report (LA001)",
        (33, 19), INTEREST_COLUMNS, {}, id="interest-la001",
    ),
    pytest.param(
        "Test6_intrest report_LA030.rpt", "Interest Report (LA030)",
        (7, 19), INTEREST_COLUMNS, {}, id="interest-la030",
    ),
    pytest.param(
        "Test7_intrest report_OD028.rpt", "Interest Report (OD028)",
        (6, 19), INTEREST_COLUMNS, {}, id="interest-od028",
    ),
    pytest.param(
        "Test8_intrest report_CC001.rpt", "Interest Report (CC001 & CC002)",
        (47, 19), INTEREST_COLUMNS, {}, id="interest-cc001",
    ),
]


@pytest.mark.parametrize("filename,preset,expected_shape,columns,overrides", CASES)
def test_parse_shape_and_columns(filename, preset, expected_shape, columns, overrides):
    df = parse_file(filename, preset_options(preset, **overrides))

    assert df is not None, f"{filename} parsed to None with preset {preset!r}"
    assert not df.empty, f"{filename} parsed to an empty frame"
    assert list(df.columns) == columns
    assert df.shape == expected_shape


@pytest.mark.parametrize("filename,preset,expected_shape,columns,overrides", CASES)
def test_no_row_is_completely_blank(filename, preset, expected_shape, columns, overrides):
    df = parse_file(filename, preset_options(preset, **overrides))

    def is_blank(row):
        return all(str(v).strip() in ("", "nan") for v in row)

    blank = [i for i, row in df.iterrows() if is_blank(row.values)]
    assert blank == [], f"{filename}: blank rows at {blank[:5]}"


@pytest.mark.parametrize("filename,preset,expected_shape,columns,overrides", CASES)
def test_parsing_is_deterministic(filename, preset, expected_shape, columns, overrides):
    first = parse_file(filename, preset_options(preset, **overrides))
    second = parse_file(filename, preset_options(preset, **overrides))

    assert first.equals(second)
