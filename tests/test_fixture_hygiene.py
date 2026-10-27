"""Hygiene guards for the synthetic fixtures that ship with the public repo.

The fixtures preserve the layout of anonymised bank reports, but every account,
name, branch and credential-bearing value must be synthetic. These tests make
sure a regenerated fixture cannot silently reintroduce a real identifier or
change the report layout (line counts) that the parser tests depend on.
"""

import hashlib
import re

import pytest

from helpers import ROOT, read_text

# Real identifiers that must never appear in a fixture. Only SHA-256 digests are
# checked in, so this guard can ship publicly without repeating the values it
# protects. Each entry is (sha256 of the UPPERCASED value, its length, a label).
# The label is what a failure reports.
FORBIDDEN = [
    ("91d7de05392d41ad57e835378b6a71a1d8c9e1e4e5e3a948122389359de9782d", 14, "real account number"),
    ("816aaedd39a1270a937d51df643824d73549f61347401cc58317cd9ff5030e18", 14, "real account number"),
    ("ce25177698a7a10171f6afd5314e27d7e64e312829a59da9d8c5ad16cbe4d914", 14, "real account number"),
    ("e4f0e8e5041d90e8a9b956556af775fef1e1add3f91f55c717b47132478f02c8", 14, "real account number"),
    ("c4711310c779d7062b2e8a2f0b3e46a2079870b309387af78ec4e20a16c17d86", 14, "real account number"),
    ("cc618b5de3f4758478c0af67531294e5235c0d4b24ddc61e9f9372f46f61b21a", 4, "real branch acronym"),
    ("d41faf2b02624edbcdc0c13fbed91c96f0f6dc0a8dccb56b0615b0a155b8f77a", 4, "real branch id"),
    ("59996f75434abb03c52657e03a89c79ad2ab4883d83930b7989706f6aef3109c", 4, "real bank voucher prefix"),
    ("3b0eeedd70fa3bf9167fd867afb8144eb134178b542a7b2a2f64463d7855527f", 9, "real city"),
    ("7fe5c62a6c8e39e63207d63491f0478d6e124bb4661dbd5d60c87f3845dc4d6e", 6, "real city"),
    ("fa442f18c57050c0ca85fc3ee4ac19de786f016cb6cb67a7fe1ff877ee52b676", 11, "real city"),
    ("3bf0432eb4addfe45c0057fa575ab7140c265dd6246b9e68ee1999c7e3b0ab83", 4, "placeholder city"),
    ("40bfdadac865ad5a23452e17a822824842fc3c164247a16117029b2a2548ea6e", 5, "real receipt voucher prefix"),
    ("dd5b311de63a313310bed8040c5d76b947bc59bfea19a6f406fa1304b7d33a1b", 5, "real debit voucher prefix"),
    ("c81dcbb71be4d4bc78dfc6f49973ed398bf02ad85a010955c39430421de07540", 6, "real bank name"),
    ("b6e7d15a25cd166abaf9768876782ec2f41ae34fbdce5fad2fad9fa3dc4735ca", 12, "real bank name"),
    ("bc1e2b1624b7fe6e8bad7bd368311c8ce3d976333adf6082517c2405b9ac32d8", 8, "real counterparty name"),
    ("4ccd8d41c3448160973992cb9727a8fbed06d0675723d3068edd4f8a123f40af", 7, "leaked credential"),
]

FIXTURES = {
    "Test2_Statement_term_loan.RPT": 214,
    "test3_statemen_Cash Credit General.RPT": 133,
    "Temp_CC.RPT": 3551,
    "last_session.rpt": 3551,
    "Test4_Depreciation.rpt": 403,
    "Test5_intrest report_LA001.rpt": 115,
    "Test6_intrest report_LA030.rpt": 59,
    "Test7_intrest report_OD028.rpt": 59,
    "Test8_intrest report_CC001.rpt": 171,
}


def forbidden_hits(text):
    hits = []
    tokens = set(re.findall(r"[A-Z0-9]+", text.upper()))
    for token in tokens:
        for digest, length, label in FORBIDDEN:
            if length > len(token):
                continue
            for start in range(len(token) - length + 1):
                window = token[start:start + length]
                if hashlib.sha256(window.encode()).hexdigest() == digest:
                    hits.append((label, token))
    return hits


@pytest.mark.parametrize("filename", sorted(FIXTURES))
def test_fixture_has_no_real_identifier(filename):
    hits = forbidden_hits(read_text(filename))
    assert not hits, f"{filename}: {hits[:3]}"


@pytest.mark.parametrize("filename,expected_lines", sorted(FIXTURES.items()))
def test_fixture_line_count_is_unchanged(filename, expected_lines):
    actual = len(read_text(filename).splitlines())

    assert actual == expected_lines, (
        f"{filename}: {actual} lines, expected {expected_lines}. "
        "A sanitised fixture must keep the original report layout."
    )


def test_private_helpers_are_gitignored():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "anonymize_fixtures.py" in ignored
    assert "leak_patterns.txt" in ignored


@pytest.mark.parametrize("script", ["deploy2Web.sh", "deployToTailscale.sh"])
def test_deploy_scripts_do_not_hardcode_credentials(script):
    path = ROOT / script
    if not path.exists():
        pytest.skip(f"{script} is not part of this checkout")

    text = path.read_text(encoding="utf-8", errors="replace")
    hits = forbidden_hits(text)
    assert not hits, f"{script}: {hits[:3]}"
    assert 'BASIC_USER="${BASIC_USER' in text
    assert 'BASIC_PASS="${BASIC_PASS' in text


@pytest.mark.parametrize("filename", ["config.py", "parser.py", "README.md", "PUBLISHING.md"])
def test_source_has_no_real_identifier(filename):
    path = ROOT / filename
    if not path.exists():
        pytest.skip(f"{filename} is not part of this checkout")

    hits = forbidden_hits(path.read_text(encoding="utf-8", errors="replace"))
    assert not hits, f"{filename}: {hits[:3]}"
