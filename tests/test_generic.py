"""Generic parser paths: fixed-width, delimited and the cleanup helpers.

The presets cover Finacle layouts; these tests cover the fallback parsers used
by the "Custom (Manual)" preset and by auto-detection.
"""

import pandas as pd

from parser import (
    apply_narration_merger,
    parse_delimited_generic,
    parse_file,
    parse_fixed_width_generic,
)

FIXED_WIDTH = """Report Generated On: 2026-04-06
Page 1

CustomerID   FirstName   LastName      Balance
1            Alice       Smith         150.00
2            Bob         Johnson       23.50
3            Carol       Williams      0.00
"""

COMMA = """CustomerID,FirstName,LastName,Balance
1,Alice,Smith,150.00
2,Bob,Johnson,23.50
"""

SEMICOLON = """CustomerID;FirstName;LastName;Balance
1;Alice;Smith;150.00
2;Bob;Johnson;23.50
"""

TAB = "CustomerID\tFirstName\tLastName\tBalance\n1\tAlice\tSmith\t150.00\n"


def write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def fixed_options(**overrides):
    options = {
        "enabled": True,
        "preset_name": "Custom (Manual)",
        "fixed_widths": "13,12,14,10",
        "skip_rows": 3,
    }
    options.update(overrides)
    return options


def delimited_options(separator, **overrides):
    options = {
        "enabled": True,
        "preset_name": "Custom (Manual)",
        "separator": separator,
        "skip_rows": 0,
    }
    options.update(overrides)
    return options


def test_fixed_width_generic(tmp_path):
    path = write(tmp_path, "fixed.txt", FIXED_WIDTH)
    df = parse_file(path, fixed_options())

    assert list(df.columns) == ["CustomerID", "FirstName", "LastName", "Balance"]
    assert df.shape == (3, 4)
    assert df["FirstName"].tolist() == ["Alice", "Bob", "Carol"]
    assert df["Balance"].tolist() == [150.0, 23.5, 0.0]


def test_fixed_width_generic_direct_call(tmp_path):
    path = write(tmp_path, "fixed.txt", FIXED_WIDTH)
    df = parse_fixed_width_generic(path, fixed_options())

    assert df is not None
    assert df.shape == (3, 4)


def test_fixed_width_without_widths_returns_none(tmp_path):
    path = write(tmp_path, "fixed.txt", FIXED_WIDTH)

    assert parse_fixed_width_generic(path, {"fixed_widths": ""}) is None


def test_comma_delimited(tmp_path):
    path = write(tmp_path, "data.csv", COMMA)
    df = parse_file(path, delimited_options(","))

    assert list(df.columns) == ["CustomerID", "FirstName", "LastName", "Balance"]
    assert df.shape == (2, 4)
    assert df["LastName"].tolist() == ["Smith", "Johnson"]


def test_semicolon_delimited(tmp_path):
    path = write(tmp_path, "data.csv", SEMICOLON)
    df = parse_file(path, delimited_options(";"))

    assert df.shape == (2, 4)
    assert df["FirstName"].tolist() == ["Alice", "Bob"]


def test_tab_delimited(tmp_path):
    path = write(tmp_path, "data.tsv", TAB)
    df = parse_file(path, delimited_options("\\t"))

    assert df.shape == (1, 4)
    assert df.iloc[0]["Balance"] == 150.0


def test_auto_detected_delimiter(tmp_path):
    header = "CustomerID,FirstName,LastName,Balance"
    body = "\n".join(f"{i},Name{i},Last{i},{i * 10}.00" for i in range(1, 51))
    path = write(tmp_path, "auto.csv", header + "\n" + body + "\n")

    df = parse_file(path, delimited_options(""))

    assert df is not None, "auto delimiter detection failed"
    assert df.shape == (50, 4)
    assert df["CustomerID"].iloc[-1] == 50


def test_unknown_preset_falls_back_to_delimited(tmp_path):
    path = write(tmp_path, "data.csv", COMMA)
    options = {"enabled": True, "preset_name": "No Such Preset", "separator": ","}

    df = parse_file(path, options)

    assert df is not None
    assert df.shape == (2, 4)


def test_ignore_prefixes_drops_noise_rows(tmp_path):
    path = write(tmp_path, "data.csv", COMMA)
    df = parse_file(path, delimited_options(",", ignore_prefixes=["1"]))

    assert df["CustomerID"].tolist() == [2]


def test_stop_markers_truncate_the_file(tmp_path):
    path = write(tmp_path, "data.csv", COMMA)
    df = parse_file(path, delimited_options(",", stop_markers=["2"]))

    assert df["CustomerID"].tolist() == [1]


def test_narration_merger_joins_continuation_rows():
    raw = pd.DataFrame(
        [
            {"DATE": "01-04-25", "PARTICULARS": "Opening", "WITHDRAWALS": "", "Narration": ""},
            {"DATE": "", "PARTICULARS": "continued text", "WITHDRAWALS": "", "Narration": ""},
            {"DATE": "02-04-25", "PARTICULARS": "Next", "WITHDRAWALS": "10.00", "Narration": ""},
        ]
    )

    merged = apply_narration_merger(raw)

    assert len(merged) == 2
    assert merged["Narration"].tolist() == ["continued text", ""]


def test_delimited_parser_returns_none_for_missing_file(tmp_path):
    missing = str(tmp_path / "does-not-exist.csv")

    assert parse_delimited_generic(missing, delimited_options(",")) is None
