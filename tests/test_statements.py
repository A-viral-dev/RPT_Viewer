"""Statement parsers: reconciliation, transaction counts and balance chains.

The statements are parsed twice in the app: once for display and once for the
Grand Total reconciliation. These tests pin both, plus the running-balance
invariant that the specialised parsers rely on to decide debit vs credit.
"""

import re

import pytest

from helpers import preset_options
from parser import parse_file

from main import compute_reconciliation, to_number

DATE_RE = re.compile(r"^\d{2}-\d{2}-\d{2}$")

CASES = [
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


def amount(row, column):
    return to_number(row[column])


def is_transaction(row):
    return str(row["WITHDRAWALS"]).strip() != "" or str(row["DEPOSITS"]).strip() != ""


@pytest.mark.parametrize("filename,preset,expected_tx", CASES)
def test_reconciliation_matches_grand_total(filename, preset, expected_tx):
    df = load(filename, preset)
    recon = compute_reconciliation(df, filename)

    assert recon is not None, f"{filename}: no Grand Total line found"
    assert recon["match"] is True
    assert recon["withdrawals"] == pytest.approx(recon["reported_w"], abs=0.01)
    assert recon["deposits"] == pytest.approx(recon["reported_d"], abs=0.01)


@pytest.mark.parametrize("filename,preset,expected_tx", CASES)
def test_transaction_count(filename, preset, expected_tx):
    df = load(filename, preset)

    assert sum(1 for _, row in df.iterrows() if is_transaction(row)) == expected_tx


@pytest.mark.parametrize("filename,preset,expected_tx", CASES)
def test_a_row_never_has_both_withdrawal_and_deposit(filename, preset, expected_tx):
    df = load(filename, preset)
    both = df[
        (df["WITHDRAWALS"].astype(str).str.strip() != "")
        & (df["DEPOSITS"].astype(str).str.strip() != "")
    ]

    assert both.empty, f"{filename}: rows with both amounts:\n{both.head()}"


@pytest.mark.parametrize("filename,preset,expected_tx", CASES)
def test_balance_chain_is_consistent(filename, preset, expected_tx):
    """Every movement must reproduce the next running balance exactly."""
    df = load(filename, preset)
    previous = None
    checked = 0
    mismatches = []

    for index, row in df.iterrows():
        balance = amount(row, "BALANCE")
        withdrawal = amount(row, "WITHDRAWALS")
        deposit = amount(row, "DEPOSITS")

        if withdrawal is None and deposit is None:
            # Continuation (narration) row, or the opening B/F balance.
            if balance is not None:
                previous = balance
            continue

        if previous is None or balance is None:
            previous = balance
            continue

        expected = previous - (withdrawal or 0) + (deposit or 0)
        checked += 1
        if abs(expected - balance) > 0.02:
            mismatches.append((index, previous, withdrawal, deposit, balance, expected))
        previous = balance

    assert checked == expected_tx
    assert mismatches == [], f"{filename}: {len(mismatches)} broken rows, first {mismatches[:3]}"


@pytest.mark.parametrize("filename,preset,expected_tx", CASES)
def test_every_transaction_has_a_date_and_positive_amounts(filename, preset, expected_tx):
    df = load(filename, preset)

    for index, row in df.iterrows():
        if not is_transaction(row):
            continue
        assert DATE_RE.match(str(row["DATE"]).strip()), f"row {index}: bad date {row['DATE']!r}"
        for column in ("WITHDRAWALS", "DEPOSITS"):
            value = amount(row, column)
            if value is not None:
                assert value > 0, f"row {index}: {column} = {value}"


@pytest.mark.parametrize("filename,preset,expected_tx", CASES)
def test_continuation_rows_carry_no_amounts(filename, preset, expected_tx):
    df = load(filename, preset)
    leaked = df[
        (df["DATE"].astype(str).str.strip() == "")
        & (
            (df["WITHDRAWALS"].astype(str).str.strip() != "")
            | (df["DEPOSITS"].astype(str).str.strip() != "")
        )
    ]

    assert leaked.empty, f"{filename}: narration rows parsed as transactions:\n{leaked.head()}"


@pytest.mark.parametrize("filename,preset,expected_tx", CASES)
def test_footer_text_never_reaches_the_dataframe(filename, preset, expected_tx):
    df = load(filename, preset)
    forbidden = ("grand total", "page total", "statement of account", "end of statement")
    particulars = df["PARTICULARS"].astype(str).str.lower()

    for marker in forbidden:
        hits = particulars[particulars.str.contains(marker, regex=False)]
        assert hits.empty, f"{filename}: footer {marker!r} leaked into PARTICULARS: {hits.head()}"
