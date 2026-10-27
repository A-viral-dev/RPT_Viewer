import pandas as pd
import clevercsv
import re
import logging
from dataclasses import dataclass

# =============================================================================
# BASE UTILITIES (Shared helpers, used by individual logics if needed)
# =============================================================================

def apply_base_cleanup(df: pd.DataFrame, ignore_prefixes=None, stop_markers=None) -> pd.DataFrame:
    """Standard row-by-row cleaning for Finacle RPT noise."""
    if df.empty or (not ignore_prefixes and not stop_markers):
        return df
    
    ignore_prefixes = [str(p).strip().lower() for p in (ignore_prefixes or [])]
    stop_markers = [str(s).strip().lower() for s in (stop_markers or [])]
    
    valid_rows = []
    first_col = df.columns[0]
    
    for _, row in df.iterrows():
        val = str(row[first_col]).strip().lower()
        if not val or val == "nan": 
            val = " ".join([str(v) for v in row.values if pd.notna(v)]).strip().lower()
            
        should_stop = False
        for marker in stop_markers:
            if marker in val:
                should_stop = True
                break
        if should_stop:
            break
            
        is_garbage = False
        for prefix in ignore_prefixes:
            if val.startswith(prefix):
                is_garbage = True
                break
        if not is_garbage:
            valid_rows.append(row)
                
    return pd.DataFrame(valid_rows) if valid_rows else pd.DataFrame(columns=df.columns)

def apply_narration_merger(df: pd.DataFrame, ignore_prefixes=None, stop_markers=None) -> pd.DataFrame:
    """Merges lines with empty dates into a dedicated 'Narration' column."""
    if df.empty:
        return df
    
    df = apply_base_cleanup(df, ignore_prefixes, stop_markers)
    if df.empty: return df
    
    valid_rows = []
    current_row = None
    first_col = df.columns[0]
    
    # Always target 'Narration' as per user request
    target_col = 'Narration'
    
    for _, row in df.iterrows():
        val = str(row[first_col]).strip()
        is_empty_date = pd.isna(row[first_col]) or val == "" or val == "nan" or val == "nat"
        
        if is_empty_date:
            if current_row is not None:
                texts = []
                for col in df.columns:
                    # Skip date col and numeric columns if they are empty
                    if col != first_col and col != target_col and pd.notna(row[col]):
                        s = str(row[col]).strip()
                        if s and s != "nan" and s != "0.00" and s != "0":
                            texts.append(s)
                if texts:
                    msg = " ".join(texts)
                    if current_row.get(target_col):
                        current_row[target_col] = (str(current_row[target_col]) + " " + msg).strip()
                    else:
                        current_row[target_col] = msg
        else:
            if current_row is not None:
                valid_rows.append(current_row)
            current_row = row.copy().to_dict()
            if target_col not in current_row:
                current_row[target_col] = ""
                
    if current_row is not None:
        valid_rows.append(current_row)
        
    return pd.DataFrame(valid_rows) if valid_rows else df

# =============================================================================
# REGEX-FIRST STATEMENT ENGINE
# =============================================================================

STATEMENT_COLUMNS = [
    "DATE", "PARTICULARS", "CHQ.NO.", "WITHDRAWALS", "DEPOSITS", "BALANCE", "Narration",
]

# Line types
BLANK = "blank"
RULE = "rule"
PAGE_TOTAL = "page_total"
TRANSACTION = "transaction"
NARRATION = "narration"
OTHER = "other"

# A transaction line must start with dd-mm-yy and a separator; this deliberately
# excludes "As On 31-03-2026" style headers.
DATE_LINE = re.compile(r'^(?P<date>\d{2}-\d{2}-\d{2})(?:\s|$)')
# Finacle narrations are indented continuation lines.
INDENTED_LINE = re.compile(r'^\s{2,}\S')
RULE_LINE = re.compile(r'-{3,}')
PAGE_TOTAL_LINE = re.compile(r'page\s+total', re.IGNORECASE)

# Currency tokens: Indian grouping (1,77,76,480.46), plain decimals (150.00),
# optional Cr/Dr. No lookbehind, so two tokens running together still split.
AMOUNT_TOKEN_RE = re.compile(r'\d+(?:,\d{2,3})*\.\d{2}(?:Cr|Dr)?')
# Opening-balance rows can print a bare integer ("0").
BARE_BALANCE_RE = re.compile(r'(?<=\s)\d+(?:Cr|Dr)?\s*$')
# A cheque/reference sits in its own column, separated by at least two spaces.
CHEQUE_SUFFIX_RE = re.compile(r'\s{2,}(?P<cheque>\d{3,7})$')
HEADER_COLUMN_RE = re.compile(r'WITHDRAWALS|DEPOSITS')
HEADER_REQUIRED = ("withdrawals", "deposits", "balance")

# Header line such as "SAMPLE BRANCH, DEMO": a short branch code followed by
# "BRANCH,". Matched generically so no real branch acronym has to be kept in
# the config or the fixtures.
BRANCH_HEADER = re.compile(r'^[A-Z]{3,6}\s+BRANCH,', re.IGNORECASE)


@dataclass(frozen=True)
class AmountToken:
    """One currency token found on a statement line."""

    text: str
    value: float
    start: int
    end: int


def numeric_text(text: str) -> str:
    if text.endswith(("Cr", "Dr")):
        return text[:-2]
    return text


def clean_text(value: str) -> str:
    """Collapse fixed-width padding into single spaces."""
    return re.sub(r'\s+', ' ', str(value)).strip()


def classify_line(line: str) -> str:
    """Classify a raw report line by shape, not by fixed offsets."""
    if not line.strip():
        return BLANK
    if DATE_LINE.match(line):
        return TRANSACTION
    if RULE_LINE.search(line):
        return RULE
    if PAGE_TOTAL_LINE.search(line):
        return PAGE_TOTAL
    if INDENTED_LINE.match(line):
        return NARRATION
    return OTHER


def extract_amounts(line: str) -> list:
    """Return every currency token on the line, left to right."""
    tokens = []
    for match in AMOUNT_TOKEN_RE.finditer(line):
        text = match.group()
        tokens.append(AmountToken(
            text=text,
            value=float(numeric_text(text).replace(",", "")),
            start=match.start(),
            end=match.end(),
        ))
    if tokens:
        return tokens

    bare = BARE_BALANCE_RE.search(line)
    if bare:
        text = bare.group().strip()
        return [AmountToken(
            text=text,
            value=float(numeric_text(text).replace(",", "")),
            start=bare.start(),
            end=bare.end(),
        )]
    return []


def signed_balance(text: str):
    """Signed balance: Cr positive, Dr negative, plain balances debit-side."""
    if text is None:
        return None
    raw = str(text).strip()
    if not raw:
        return None
    try:
        value = float(numeric_text(raw).replace(",", ""))
    except ValueError:
        return None
    if raw.endswith("Cr"):
        return value
    if raw.endswith("Dr"):
        return -value
    return -value if value else 0.0


def header_column_spans(line: str) -> dict:
    """Map WITHDRAWALS/DEPOSITS to their column spans from the report header."""
    return {m.group().upper(): (m.start(), m.end())
            for m in HEADER_COLUMN_RE.finditer(line)}


def nearest_column(token: AmountToken, column_spans: dict) -> str:
    center = (token.start + token.end) / 2
    return min(
        column_spans,
        key=lambda name: abs((column_spans[name][0] + column_spans[name][1]) / 2 - center),
    )


def choose_movement(previous_balance, current_balance, candidates, column_spans=None):
    """Pick the transaction token and its column.

    The running-balance delta is authoritative: the transaction amount is the
    token whose value equals |delta|, and the sign of the delta decides debit
    vs credit. Column position is only used when no previous balance exists.
    """
    if not candidates:
        return None, None

    if previous_balance is not None and current_balance is not None:
        delta = round(current_balance - previous_balance, 2)
        if abs(delta) > 0.005:
            for candidate in candidates:
                if abs(candidate.value - abs(delta)) <= 0.005:
                    return ("DEPOSITS" if delta > 0 else "WITHDRAWALS"), candidate
            # The balance moved but no token reproduces it: fall through to the
            # report's own column layout instead of guessing from the delta.

    if column_spans:
        return nearest_column(candidates[0], column_spans), candidates[0]
    return "WITHDRAWALS", candidates[0]


def split_cheque(text: str):
    """Split an aligned trailing reference number off the particulars."""
    raw = str(text).strip()
    match = CHEQUE_SUFFIX_RE.search(raw)
    if not match:
        return clean_text(raw), ""
    return clean_text(raw[:match.start()]), match.group("cheque")


def transaction_row(line, previous_balance, column_spans):
    """Parse one dated line. Returns (row, current signed balance)."""
    date_match = DATE_LINE.match(line)
    date = date_match.group("date")
    tokens = extract_amounts(line)

    if tokens:
        balance_token = tokens[-1]
        candidates = tokens[:-1]
        first_amount = candidates[0] if candidates else balance_token
        particulars_text = line[date_match.end():first_amount.start]
    else:
        balance_token = None
        candidates = []
        particulars_text = line[date_match.end():]

    particulars, cheque = split_cheque(particulars_text)
    current_balance = signed_balance(balance_token.text) if balance_token else None
    column, amount = choose_movement(
        previous_balance, current_balance, candidates, column_spans
    )

    row = [date, particulars, cheque, "", "",
           balance_token.text if balance_token else "", ""]
    if amount is not None:
        row[3 if column == "WITHDRAWALS" else 4] = amount.text
    return row, current_balance


def parse_statement(filepath, options, *, require_narration_indent,
                    stop_at_footer, default_skip_rows):
    """Shared regex-first parser for Term Loan, Escrow and Cash Credit reports."""
    options = options or {}
    skip_rows = options.get("skip_rows", default_skip_rows)
    stop_markers = [str(s).strip().lower() for s in (options.get("stop_markers") or [])]
    ignore_prefixes = [str(p).strip().lower() for p in (options.get("ignore_prefixes") or [])]

    rows = []
    previous_balance = None
    column_spans = {}

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()[skip_rows:]

        for raw_line in lines:
            line = raw_line.rstrip("\r\n")
            kind = classify_line(line)
            if kind in (BLANK, RULE, PAGE_TOTAL):
                continue

            stripped = line.strip()
            low = stripped.lower()

            if not column_spans and all(word in low for word in HEADER_REQUIRED):
                column_spans = header_column_spans(line)
                continue

            if stop_at_footer and any(marker in low for marker in stop_markers):
                break
            if any(low.startswith(prefix) for prefix in ignore_prefixes):
                continue
            if BRANCH_HEADER.match(stripped):
                continue

            if kind == TRANSACTION:
                row, previous_balance = transaction_row(line, previous_balance, column_spans)
                rows.append(row)
            else:
                if require_narration_indent and kind != NARRATION:
                    continue
                rows.append(["", clean_text(stripped), "", "", "", "", ""])

        df = pd.DataFrame(rows, columns=STATEMENT_COLUMNS)
        if options.get("merge_narration"):
            df = apply_narration_merger(
                df, options.get("ignore_prefixes"), options.get("stop_markers")
            )
        return df
    except Exception as exc:
        logging.error(f"Statement Logic Error ({filepath}): {exc}")
        return None


def logic_cc_general_cc001(filepath, options):
    """Cash Credit General (CC001)."""
    return parse_statement(
        filepath, options,
        require_narration_indent=False,  # CC footers can be unindented
        stop_at_footer=True,
        default_skip_rows=22,
    )


def logic_term_loan(filepath, options):
    """Term Loan and Escrow statements."""
    return parse_statement(
        filepath, options,
        require_narration_indent=True,  # ignore unindented report headers
        stop_at_footer=False,
        default_skip_rows=24,
    )

def logic_depreciation(filepath, options):
    """
    Dedicated logic for Fixed Asset Depreciation.
    Tracks hierarchical state (Major Category/Method) while parsing.
    """
    data = []
    current_major, current_cat, current_method = "", "", ""
    headers = ["SNO", "ASSET_NO", "ITEM NAME", "PURCH DATE", "BLOCK_AMT", "D_RATE", "ACTUAL_DEP", "QTR_DEP", "MAJOR_CATEGORY", "CATEGORY", "METHOD"]

    major_line = re.compile(r'MAJOR\s+CATEGORY\s+(?P<major>.+?)\s*$', re.IGNORECASE)
    category_line = re.compile(
        r'CATEGORY:\s*(?P<category>.*?)'
        r'(?:\s+DEPRECIATION\s+METHOD:\s*(?P<method>.+?))?\s*$',
        re.IGNORECASE,
    )
    asset_row = re.compile(r'^\s*\d+\s*\|')

    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                line_plain = line.strip()
                if not line_plain: continue

                major_match = major_line.search(line_plain)
                if major_match:
                    current_major = major_match.group("major").strip()
                    continue

                category_match = category_line.search(line_plain)
                if category_match:
                    current_cat = category_match.group("category").strip()
                    if category_match.group("method"):
                        current_method = category_match.group("method").strip()
                    continue

                if asset_row.match(line_plain):
                    parts = [p.strip() for p in line.split("|")]
                    if len(parts) >= 8 and parts[0].isdigit():
                        row = parts[:8] + [current_major, current_cat, current_method]
                        data.append(row)
        
        if data:
            df = pd.DataFrame(data, columns=headers)
            for col in ["BLOCK_AMT", "ACTUAL_DEP", "QTR_DEP", "D_RATE"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', '').str.strip(), errors='coerce').fillna(0)
            return df
    except Exception as e:
        logging.error(f"Depreciation Logic Error: {e}")
    return None

def logic_interest_report(filepath, options):
    """Dedicated logic for Interest Reports (LA001, LA030, OD028 etc.) using Pipe delimiters."""
    data = []
    cols = [
        "SCHM CODE", "SCHM DESCRIPTION", "ACCOUNT NUMBER", "NAME OF ACCOUNT HOLDER",
        "INTRST PEGGED", "APPLI INT. TABLE", "RATE AS INT. TABLE", "CUST LVL INT. PREF",
        "ACCT LVL INT. PREF", "EFFECTIVE ROI", "MIN RATE", "MAX RATE",
        "SANCTIONED LIMIT", "BALANCE OUTSTANDING", "LIM LEVEL FLAG", 
        "MATURITY DT", "NEXT INT CALC", "ASSET CLASS", "INT FREQ TYPE"
    ]
    skip_rows = options.get('skip_rows', 12)
    interest_row = re.compile(r'^\|.*\|$')
    caption_cell = re.compile(r'^(?:SCHM|CODE)$', re.IGNORECASE)
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()[skip_rows:]
            for line in lines:
                line = line.strip()
                if not line or "----" in line or "SAMPLE BANK" in line: continue
                if interest_row.match(line):
                    parts = [p.strip() for p in line.split("|")][1:-1]
                    # Skip header caption lines ("SCHM"/"CODE") and their
                    # continuation line, which has no scheme/account values.
                    if len(parts) >= 15 and not caption_cell.match(parts[0]) \
                            and any(parts[i] for i in (0, 1, 2, 3)):
                        final_row = parts[:len(cols)] + [""] * max(0, len(cols) - len(parts))
                        data.append(final_row)
        
        if data:
            df = pd.DataFrame(data, columns=cols)
            num_cols = ["EFFECTIVE ROI", "MIN RATE", "MAX RATE", "SANCTIONED LIMIT", "BALANCE OUTSTANDING"]
            for c in num_cols:
                if c in df.columns:
                    df[c] = pd.to_numeric(df[c].astype(str).str.replace(',', '').str.replace('Cr', '').str.replace('Dr', '').str.strip(), errors='coerce').fillna(0)
            return df
    except Exception as e:
        logging.error(f"Interest Logic Error: {e}")
    return None

# =============================================================================
# GENERIC FALLBACK PARSERS
# =============================================================================

def parse_fixed_width_generic(filepath, options):
    widths_str = options.get('fixed_widths', '')
    if not widths_str: return None
    try:
        widths = [int(w.strip()) for w in widths_str.split(',') if w.strip().isdigit()]
        df = pd.read_fwf(filepath, widths=widths, skiprows=options.get('skip_rows', 0))
        if options.get('merge_narration'):
            return apply_narration_merger(df, options.get('ignore_prefixes'), options.get('stop_markers'))
        return apply_base_cleanup(df, options.get('ignore_prefixes'), options.get('stop_markers'))
    except Exception:
        return None

def parse_delimited_generic(filepath, options):
    sep = options.get('separator', '')
    skip = options.get('skip_rows', 0)
    try:
        if sep == '\\t': sep = '\t'
        if not sep:
            with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                sample = f.read(20000)
            dialect = clevercsv.Sniffer().sniff(sample)
            # pandas rejects clevercsv's SimpleDialect, so pass its detected
            # settings as plain keyword arguments instead.
            kwargs = {'sep': dialect.delimiter, 'skiprows': skip,
                      'encoding': 'utf-8', 'index_col': False}
            if getattr(dialect, 'quotechar', ''):
                kwargs['quotechar'] = dialect.quotechar
            if getattr(dialect, 'escapechar', ''):
                kwargs['escapechar'] = dialect.escapechar
            df = pd.read_csv(filepath, **kwargs)
        else:
            df = pd.read_csv(filepath, sep=sep, skiprows=skip, engine='python', on_bad_lines='skip', index_col=False)
        
        if options.get('merge_narration'):
            return apply_narration_merger(df, options.get('ignore_prefixes'), options.get('stop_markers'))
        return apply_base_cleanup(df, options.get('ignore_prefixes'), options.get('stop_markers'))
    except Exception:
        return None

# =============================================================================
# MAIN DISPATCHER
# =============================================================================

def parse_file(filepath: str, custom_options: dict = None) -> pd.DataFrame:
    """Main entry point. Dispatches to specialized logic or generic parsers."""
    
    if not custom_options or not custom_options.get('enabled'):
        # Automatic RPT detection fallback
        df = parse_fixed_width_generic(filepath, {'fixed_widths': "9, 15, 11, 18, 18, 50", 'skip_rows': 24}) # Default guess
        return df if df is not None else parse_delimited_generic(filepath, {})

    preset = custom_options.get('preset_name', 'Custom (Manual)')
    
    # --- ROUTING TABLE ---
    if preset == "Cash credit general (CC001)":
        return logic_cc_general_cc001(filepath, custom_options)
    
    if preset in ["Finacle - Term Loan (.RPT)", " Escrow Account"]:
        return logic_term_loan(filepath, custom_options)
    
    if preset == "Fixed Asset Depreciation":
        return logic_depreciation(filepath, custom_options)
    
    if preset and "Interest Report" in preset:
        return logic_interest_report(filepath, custom_options)
    
    # --- GENERIC PATHS ---
    if custom_options.get('fixed_widths'):
        return parse_fixed_width_generic(filepath, custom_options)
    
    if custom_options.get('separator'):
        return parse_delimited_generic(filepath, custom_options)
        
    return parse_delimited_generic(filepath, custom_options)
