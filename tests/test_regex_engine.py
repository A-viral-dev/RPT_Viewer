"""Contract for the regex-first statement engine.

These tests are written before the engine itself. They pin the primitives
(line classification, currency extraction, cheque isolation, balance-delta
classification) and the end-to-end invariants that must survive the refactor:

* every transaction amount equals the absolute running-balance delta;
* withdrawal/deposit is decided by that delta, never by a column offset;
* parsed totals reproduce the report's Grand Total exactly;
* particulars/narrations come out whitespace-clean.
"""

import re

import pytest

from helpers import fixture_path, preset_options
from parser import (
    AmountToken,
    choose_movement,
    classify_line,
    extract_amounts,
    parse_file,
    signed_balance,
    split_cheque,
)

from main import compute_reconciliation, to_number

STATEMENTS = [
    pytest.param(
        "Test2_Statement_term_loan.RPT", "Finacle - Term Loan (.RPT)", 29,
        id="term-loan",
    ),
    pytest.param(
        "test3_statemen_Cash Credit General.RPT", "Cash credit general (CC001)", 64,
        id="cc001",
    ),
    pytest.param(
        "Temp_CC.RPT", "Cash credit general (CC001)", 768,
        id="cc-sample",
    ),
    pytest.param(
        "last_session.rpt", "Cash credit general (CC001)", 768,
        id="cc-last-session",
    ),
]


def load(filename, preset):
    return parse_file(filename, preset_options(preset, merge_narration=False))


def grand_total(filename):
    for line in fixture_path(filename).read_text(encoding="utf-8", errors="replace").splitlines():
        if "grand total" in line.lower():
            numbers = re.findall(r"\d+[\d,]*\.\d{2}", line.split(":", 1)[-1])
            if len(numbers) >= 2:
                return (float(numbers[0].replace(",", "")),
                        float(numbers[1].replace(",", "")))
    raise AssertionError(f"{filename}: no Grand Total line")


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------

def test_extract_amounts_reads_indian_grouping():
    tokens = extract_amounts("05-01-26 RTGS-X    8,46,239.75  2,16,68,522.14Cr")

    assert [t.text for t in tokens] == ["8,46,239.75", "2,16,68,522.14Cr"]
    assert [t.value for t in tokens] == [846239.75, 21668522.14]


def test_extract_amounts_splits_run_together_tokens():
    line = "09-01-26 RTGS-X   93,50,96,546.14102,67,68,817.57Cr"

    tokens = extract_amounts(line)

    assert [t.text for t in tokens] == ["93,50,96,546.14", "102,67,68,817.57Cr"]
    assert [t.value for t in tokens] == [935096546.14, 1026768817.57]
    assert tokens[0].end == tokens[1].start


def test_extract_amounts_ignores_dates_and_references():
    assert extract_amounts("06-01-26 9001IGB582825603/ISS001/BINSTA") == []


def test_extract_amounts_accepts_a_bare_opening_balance():
    tokens = extract_amounts("01-09-25 B/F                                                                   0")

    assert len(tokens) == 1
    assert tokens[0].text == "0"
    assert tokens[0].value == 0.0


@pytest.mark.parametrize(
    "line,kind",
    [
        ("02-09-25  Loan  86,39,22,118.74  86,39,22,118.74Dr", "transaction"),
        ("         51987035565383 Loan Disbursement Debit", "narration"),
        ("transaction(s) in the statement are correct.", "other"),
        ("SAMPLE BRANCH, DEMO", "other"),
        ("----------------------------------------------------------------", "rule"),
        ("Page Total:  1,000.00", "page_total"),
        ("", "blank"),
    ],
)
def test_classify_line(line, kind):
    assert classify_line(line) == kind


@pytest.mark.parametrize(
    "text,expected",
    [
        ("86,39,22,118.74Dr", -863922118.74),
        ("2,16,68,522.14Cr", 21668522.14),
        ("0", 0.0),
        ("", None),
    ],
)
def test_signed_balance(text, expected):
    assert signed_balance(text) == expected


def token(text, value, start=0):
    return AmountToken(text=text, value=value, start=start, end=start + len(text))


def test_movement_follows_a_falling_balance():
    column, amount = choose_movement(100.0, 90.0, [token("10.00", 10.0)])

    assert column == "WITHDRAWALS"
    assert amount.text == "10.00"


def test_movement_follows_a_rising_balance():
    column, amount = choose_movement(100.0, 110.0, [token("10.00", 10.0)])

    assert column == "DEPOSITS"
    assert amount.text == "10.00"


def test_movement_picks_the_token_that_matches_the_delta():
    candidates = [token("10.00", 10.0), token("90.00", 90.0)]

    column, amount = choose_movement(100.0, 190.0, candidates)

    assert column == "DEPOSITS"
    assert amount.text == "90.00"


def test_movement_falls_back_to_header_columns_without_a_previous_balance():
    spans = {"WITHDRAWALS": (40, 51), "DEPOSITS": (60, 68)}

    debit = choose_movement(None, None, [token("10.00", 10.0, start=42)], spans)
    credit = choose_movement(None, None, [token("10.00", 10.0, start=62)], spans)

    assert debit[0] == "WITHDRAWALS"
    assert credit[0] == "DEPOSITS"


def test_split_cheque_isolates_an_aligned_number():
    assert split_cheque(":Normal             661") == (":Normal", "661")


def test_split_cheque_leaves_single_spaced_references_alone():
    assert split_cheque("DEAL ID 7149160") == ("DEAL ID 7149160", "")
    assert split_cheque("RTGS-HDFCR64465004822975445-SAMP") == (
        "RTGS-HDFCR64465004822975445-SAMP", "",
    )


# ---------------------------------------------------------------------------
# End-to-end invariants
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filename,preset,expected_tx", STATEMENTS)
def test_totals_match_grand_total_exactly(filename, preset, expected_tx):
    df = load(filename, preset)
    reported_w, reported_d = grand_total(filename)

    parsed_w = sum(to_number(v) or 0 for v in df["WITHDRAWALS"])
    parsed_d = sum(to_number(v) or 0 for v in df["DEPOSITS"])

    assert round(parsed_w, 2) == reported_w
    assert round(parsed_d, 2) == reported_d


@pytest.mark.parametrize("filename,preset,expected_tx", STATEMENTS)
def test_reconciliation_is_true(filename, preset, expected_tx):
    df = load(filename, preset)
    recon = compute_reconciliation(df, filename)

    assert recon is not None
    assert recon["match"] is True


@pytest.mark.parametrize("filename,preset,expected_tx", STATEMENTS)
def test_every_movement_equals_the_balance_delta(filename, preset, expected_tx):
    df = load(filename, preset)
    previous = None
    checked = 0

    for index, row in df.iterrows():
        balance = to_number(row["BALANCE"])
        withdrawal = to_number(row["WITHDRAWALS"])
        deposit = to_number(row["DEPOSITS"])

        if withdrawal is None and deposit is None:
            if balance is not None:
                previous = balance
            continue

        assert previous is not None, f"row {index}: movement without an opening balance"
        assert balance is not None, f"row {index}: movement without a closing balance"

        delta = round(balance - previous, 2)
        movement = deposit if deposit is not None else withdrawal

        assert movement == pytest.approx(abs(delta), abs=0.01), (
            f"row {index}: amount {movement} does not equal |delta| {abs(delta)}"
        )
        if delta > 0:
            assert deposit is not None and withdrawal is None, f"row {index}: rising balance must be a deposit"
        else:
            assert withdrawal is not None and deposit is None, f"row {index}: falling balance must be a withdrawal"

        checked += 1
        previous = balance

    assert checked == expected_tx


@pytest.mark.parametrize("filename,preset,expected_tx", STATEMENTS)
def test_particulars_and_narrations_have_no_double_spaces(filename, preset, expected_tx):
    df = load(filename, preset)

    for column in ("PARTICULARS", "Narration"):
        hits = df[column].astype(str).str.contains("  ", regex=False)
        assert not hits.any(), f"{filename}: {column} still has padded whitespace"


@pytest.mark.parametrize("filename,preset,expected_tx", STATEMENTS)
def test_cheque_numbers_are_isolated_from_particulars(filename, preset, expected_tx):
    df = load(filename, preset)
    cheques = df["CHQ.NO."].astype(str).str.strip()
    present = cheques[cheques != ""]

    for value in present:
        assert re.fullmatch(r"\d{3,7}", value), f"{filename}: bad cheque {value!r}"
    for particulars in df["PARTICULARS"].astype(str):
        assert not re.search(r"\s{2,}\d{3,7}$", particulars)


def test_known_cheque_column_is_extracted():
    df = load("Test2_Statement_term_loan.RPT", "Finacle - Term Loan (.RPT)")

    assert (df["CHQ.NO."].astype(str).str.strip() == "661").sum() == 7
    assert df.loc[df["CHQ.NO."].astype(str).str.strip() == "661", "PARTICULARS"].iloc[0] == ":Normal"
