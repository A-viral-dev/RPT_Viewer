import os
import re
import tempfile
import logging
import inspect
import sys
import argparse
import pandas as pd
from nicegui import ui
from parser import parse_file
from export import export_to_csv, export_to_excel, export_to_json, export_to_pdf
from config import PRESETS, get_saved_preset, save_preset, get_saved_settings, save_settings
import shutil

# Fix for PyInstaller
if sys.stdout is None: sys.stdout = open(os.devnull, 'w')
if sys.stderr is None: sys.stderr = open(os.devnull, 'w')
if sys.stdin is None: sys.stdin = open(os.devnull, 'r')

logging.basicConfig(level=logging.INFO)

def format_indian_currency(num):
    try:
        s_num = str(num).strip()
        suffix = ""
        if s_num.endswith(('Dr', 'Cr')):
            suffix = s_num[-2:]
            s_num = s_num[:-2].strip()

        num_val = float(s_num.replace(',', ''))
        is_neg = num_val < 0
        num_val = abs(num_val)

        s = f"{num_val:.2f}"
        whole, frac = s.split(".")
        if len(whole) > 3:
            last_three = whole[-3:]
            rest = whole[:-3]
            groups = []
            while rest:
                groups.append(rest[-2:])
                rest = rest[:-2]
            res = ",".join(groups[::-1]) + "," + last_three + "." + frac
        else: res = s

        main_val = f"-{res}" if is_neg else res
        return f"{main_val}{suffix}"
    except: return str(num)

def to_number(val):
    """Parse a display amount ('1,68,000.00', '12.25Dr') into a signed float."""
    try:
        s = str(val).strip().replace(',', '')
        if s.endswith('Cr'): return float(s[:-2])
        if s.endswith('Dr'): return -float(s[:-2])
        if s in ('', 'nan', 'None'): return None
        return float(s)
    except ValueError:
        return None

def compute_reconciliation(df, filepath):
    """Compare parsed WITHDRAWALS/DEPOSITS totals with the statement's own Grand Total line."""
    recon = None
    if {'WITHDRAWALS', 'DEPOSITS'}.issubset(df.columns):
        sum_w = sum(v for v in (to_number(v) for v in df['WITHDRAWALS']) if v is not None)
        sum_d = sum(v for v in (to_number(v) for v in df['DEPOSITS']) if v is not None)
        reported = None
        try:
            with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                for line in f:
                    if 'grand total' in line.lower():
                        nums = re.findall(r'(\d+[\d,]*\.\d{2})', line.split(':', 1)[-1])
                        if len(nums) >= 2:
                            try:
                                reported = (float(nums[0].replace(',', '')),
                                            float(nums[1].replace(',', '')))
                            except ValueError:
                                reported = None
                        break
        except Exception:
            reported = None
        if reported is not None:
            ok = abs(sum_w - reported[0]) < 0.01 and abs(sum_d - reported[1]) < 0.01
            recon = {'match': ok, 'withdrawals': sum_w, 'deposits': sum_d,
                     'reported_w': reported[0], 'reported_d': reported[1]}
    return recon

AUDIT_CSS = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Spectral:wght@600;700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root {
    --paper: #FAFAF7; --ink: #1B1E1B; --rule: #DAD8CF; --rule-strong: #8F8D83;
    --ledger: #0E6E4B; --debit: #B3362B; --pen: #23408E; --muted: #6B6E66;
    --panel: #FFFFFF;
}
body.body--dark {
    --paper: #15171A; --ink: #E7E9E4; --rule: #2C2F33; --rule-strong: #565A5F;
    --ledger: #4FBF8F; --debit: #E07B6E; --pen: #7C9BE8; --muted: #9AA09B;
    --panel: #1E2124;
}
body { background: var(--paper) !important; color: var(--ink);
       font-family: 'IBM Plex Sans', 'Segoe UI', sans-serif; }
.serif { font-family: 'Spectral', Georgia, serif; }
.num-cell { font-family: 'IBM Plex Mono', Consolas, monospace; font-variant-numeric: tabular-nums; }
.num-cell .Cr { color: var(--ledger); font-weight: 500; }
.num-cell .Dr { color: var(--debit); font-weight: 500; }
.wp-panel { background: var(--panel); border: 1px solid var(--rule); border-radius: 6px; }
.rule-b { border-bottom: 1px solid var(--rule); }
.identity-label { color: var(--muted); font-size: 11px; }
.identity-value { color: var(--ink); font-weight: 600; }
.q-table { background: transparent !important; }
.q-table thead th {
    border-bottom: 2px solid var(--rule-strong) !important;
    color: var(--ink) !important; font-weight: 600; background: var(--panel);
}
.q-table tbody td { border-bottom: 1px solid var(--rule) !important; color: var(--ink); }
.q-table tbody tr:hover td { background: rgba(35, 64, 142, 0.04) !important; }
.q-table__bottom { color: var(--muted); border-top: 1px solid var(--rule); }
.totals-row td { border-top: 2px solid var(--rule-strong) !important; font-weight: 600; }
/* Responsive visibility — Quasar's .hidden uses !important, so use explicit media rules */
@media (max-width: 639.98px) { .hide-phone { display: none !important; } }
@media (max-width: 767.98px) { .hide-tablet { display: none !important; } }
@media (max-width: 1279.98px) { .hide-below-wide { display: none !important; } }
</style>
"""

@ui.page('/')
def index():
    # 1. State Hub
    dark_mode = ui.dark_mode(False)
    ui.colors(primary='#23408E', secondary='#1B1E1B', accent='#23408E',
              positive='#0E6E4B', negative='#B3362B', info='#23408E', warning='#8A6D1D')
    ui.add_head_html(AUDIT_CSS)

    state = {
        'df': pd.DataFrame(),
        'current_file': None,
        'original_filename': 'No file loaded',
        'metadata': {},
        'pending_df': None,
        'pending_metadata': None,
        'pending_filename': '',
        'dark': False,
    }
    ui_elements = {}

    # 1.5 Auto-Restore State
    saved_settings = get_saved_settings()
    last_file = saved_settings.get('last_file')
    if last_file and os.path.exists(last_file):
        state['current_file'] = last_file
        state['original_filename'] = saved_settings.get('original_filename', 'Restored Session')
        ui.timer(0.5, lambda: (do_parse({**PRESETS.get(get_saved_preset(), {}), 'enabled': True, 'preset_name': get_saved_preset()}), update_grid()), once=True)

    def toggle_dark():
        state['dark'] = not state['dark']
        dark_mode.enable() if state['dark'] else dark_mode.disable()
        update_grid()

    def confirm_merge(merge=True):
        if merge:
            try:
                state['df'] = pd.concat([state['df'], state['pending_df']], ignore_index=True, sort=False)
                state['original_filename'] += f" + {state['pending_filename']}"

                new_meta = state.get('metadata', {}).copy()
                if state['pending_metadata']:
                    new_meta.update(state['pending_metadata'])

                df = state['df']
                p_n = get_saved_preset()
                if p_n == "Fixed Asset Depreciation":
                    for ci, lab in [('BLOCK_AMT', 'Total Block Amt'), ('ACTUAL_DEP', 'Total Depreciation (Year)'), ('QTR_DEP', 'Total Depreciation (Quarter)')]:
                        if ci in df.columns:
                            tot = pd.to_numeric(df[ci].astype(str).str.replace(',', ''), errors='coerce').sum()
                            new_meta[lab] = f"₹ {tot}"
                if p_n and "Interest Report" in p_n:
                    for ci, lab in [('SANCTIONED LIMIT', 'Total Sanc. Limit'), ('BALANCE OUTSTANDING', 'Total O/S Balance')]:
                        if ci in df.columns:
                            tot = pd.to_numeric(df[ci].astype(str).str.replace(',', ''), errors='coerce').sum()
                            new_meta[lab] = f"₹ {tot}"

                state['metadata'] = new_meta
                ui.notify(f"Merged successfully! Total records: {len(state['df'])}", type='positive', icon='join_full')
            except Exception as ex:
                logging.error(f"Merge error: {ex}")
                ui.notify("Merge failed. Columns may be incompatible.", type='negative')
        else:
            state['df'] = state['pending_df']
            state['metadata'] = state['pending_metadata']
            state['original_filename'] = state['pending_filename']
            ui.notify("Previous data replaced.", type='info', icon='refresh')

        state['pending_df'] = None
        state['pending_metadata'] = None
        update_grid()
        merge_diag.close()

    # 2. Logic Engines
    def update_grid():
        df = state['df']
        ui_elements['results_container'].clear()
        with ui_elements['results_container']:
            if df is None or df.empty:
                # Empty state: an invitation, not a dead end
                with ui.column().classes('w-full items-center py-24 gap-4'):
                    ui.icon('fact_check', size='3.5rem').classes('text-[var(--muted)]')
                    ui.label('Load a statement to begin.').classes('serif text-2xl text-[var(--ink)]')
                    ui.label('Upload a Finacle .RPT file, or restore happens automatically from your last session.').classes('text-sm text-[var(--muted)]')
                    ui.button('Upload statement', on_click=lambda: up_diag.open()).props('unelevated no-caps icon=upload_file').classes('text-white bg-[var(--pen)]')
                return

            records = []
            for n, (_, row) in enumerate(df.iterrows(), start=1):
                row_dict = {'num': str(n)}
                for i, (col_name, val) in enumerate(zip(df.columns, row)):
                    u_col = str(col_name).upper()
                    if any(x in u_col for x in ['AMT', 'DEP', 'BALANCE', 'WITHDRAWAL', 'DEPOSIT', 'RATE']):
                        display_val = format_indian_currency(val)
                    else:
                        display_val = str(val) if pd.notna(val) else ""
                    row_dict[f"col_{i}"] = display_val
                records.append(row_dict)

            is_numeric = [any(x in str(c).upper() for x in ['AMT', 'DEP', 'BALANCE', 'WITHDRAWAL', 'DEPOSIT', 'RATE']) for c in df.columns]
            column_defs = [{'name': 'num', 'label': 'Entry', 'field': 'num', 'sortable': False, 'align': 'left'}]
            column_defs += [
                {
                    'name': f"col_{i}",
                    'label': str(c),
                    'field': f"col_{i}",
                    'sortable': True,
                    'align': 'right' if is_numeric[i] else 'left',
                    'headerClass': 'num-cell' if is_numeric[i] else '',
                } for i, c in enumerate(df.columns)
            ]

            # Statement identity strip
            if state.get('metadata'):
                meta = state['metadata']
                identity_keys = ['A/C Name', 'A/C Number', 'Scheme Description', 'Statement Period']
                with ui.card().classes('w-full wp-panel mb-3 px-6 py-4'):
                    with ui.row().classes('w-full items-baseline gap-6 flex-wrap'):
                        if meta.get('A/C Name'):
                            ui.label(meta['A/C Name']).classes('serif text-2xl text-[var(--ink)] leading-tight')
                        for k in identity_keys[1:]:
                            if meta.get(k):
                                with ui.column().classes('gap-0'):
                                    ui.label(k).classes('identity-label')
                                    ui.label(meta[k]).classes('identity-value text-sm')
                    if meta.get('Opening Balance') or meta.get('Closing Balance'):
                        with ui.row().classes('gap-8 mt-2 pt-2 rule-b border-t'):
                            for k in ('Opening Balance', 'Closing Balance'):
                                if meta.get(k):
                                    with ui.row().classes('items-baseline gap-2'):
                                        ui.label(k).classes('identity-label')
                                        ui.label(meta[k]).classes('num-cell text-sm font-semibold text-[var(--ink)]')

                # Reconciliation: parsed totals vs the statement's reported Grand Total
                recon = meta.get('_recon')
                if recon:
                    if recon['match']:
                        with ui.row().classes('w-full wp-panel mb-3 px-6 py-3 items-center gap-3 border-l-4 !border-l-[var(--ledger)]'):
                            ui.icon('verified', size='sm').classes('text-[var(--ledger)]')
                            ui.label('Reconciled: parsed totals match the statement\u2019s reported Grand Total.').classes('text-sm font-medium text-[var(--ledger)]')
                            ui.label(f"Withdrawals {format_indian_currency(recon['withdrawals'])} | Deposits {format_indian_currency(recon['deposits'])}").classes('num-cell text-xs text-[var(--muted)]')
                    else:
                        with ui.row().classes('w-full wp-panel mb-3 px-6 py-3 items-center gap-3 border-l-4 !border-l-[var(--debit)]'):
                            ui.icon('warning', size='sm').classes('text-[var(--debit)]')
                            ui.label('Mismatch: parsed totals differ from the reported Grand Total. Review the preset and the source file.').classes('text-sm font-medium text-[var(--debit)]')
                            ui.label(f"Parsed W {format_indian_currency(recon['withdrawals'])} / D {format_indian_currency(recon['deposits'])} vs reported W {format_indian_currency(recon['reported_w'])} / D {format_indian_currency(recon['reported_d'])}").classes('num-cell text-xs text-[var(--muted)]')

                # Remaining summary figures (totals for depreciation / interest reports)
                extra = {k: v for k, v in meta.items()
                         if not k.startswith('_') and k not in identity_keys + ['Opening Balance', 'Closing Balance'] and v}
                if extra:
                    with ui.row().classes('w-full gap-8 mb-3 px-6 py-3 wp-panel flex-wrap'):
                        for k, v in extra.items():
                            with ui.column().classes('gap-0'):
                                ui.label(k).classes('identity-label')
                                fmt_v = format_indian_currency(v.replace('₹', '').strip()) if str(v).startswith('₹') else v
                                ui.label(v if not str(v).startswith('₹') else f"₹ {fmt_v}").classes('num-cell text-sm font-semibold text-[var(--ink)]')

            table = ui.table(columns=column_defs, rows=records, row_key='num', pagination=100)
            table.classes('w-full wp-panel').props('flat sticky-header virtual-scroll'
                                                   + (' dark' if state['dark'] else ''))
            table.bind_filter(ui_elements['search_input'], 'value')

            # Ledger typography: mono digits, colored Cr/Dr suffixes
            table.add_slot('body-cell', '''
                <q-td :props="props" :class="props.col.align === 'right' ? 'num-cell' : ''">
                    <span v-if="props.col.align === 'right'"
                          v-html="String(props.value).replace(/(Cr|Dr)$/, '&nbsp;<span class=&quot;$1&quot;>$1</span>')"></span>
                    <span v-else>{{ props.value }}</span>
                </q-td>
            ''')

            # Pinned totals row for statement columns
            if {'WITHDRAWALS', 'DEPOSITS'}.issubset(df.columns):
                sum_w = sum(v for v in (to_number(v) for v in df['WITHDRAWALS']) if v is not None)
                sum_d = sum(v for v in (to_number(v) for v in df['DEPOSITS']) if v is not None)
                table.add_slot('bottom-row', f'''
                    <q-tr :props="props" class="totals-row">
                        <q-td></q-td>
                        <q-td colspan="3">Totals (parsed from rows)</q-td>
                        <q-td class="num-cell text-right">{format_indian_currency(sum_w)}</q-td>
                        <q-td class="num-cell text-right">{format_indian_currency(sum_d)}</q-td>
                        <q-td></q-td>
                        <q-td></q-td>
                    </q-tr>
                ''')

    def do_parse(custom_options=None, return_df=False):
        if not state['current_file']: return (pd.DataFrame(), {}) if return_df else None
        try:
            df = parse_file(state['current_file'], custom_options)
            if df is None: df = pd.DataFrame()

            metadata = {}
            preset_name = custom_options.get('preset_name') if custom_options else get_saved_preset()
            mapping = PRESETS.get(preset_name, {}).get('metadata_mappings', {})

            if mapping and custom_options and custom_options.get('skip_rows', 0) > 0:
                with open(state['current_file'], 'r', encoding='utf-8', errors='replace') as f:
                    lines = [f.readline() for _ in range(custom_options.get('skip_rows', 0) + 12)]
                    for line in lines:
                        if not line: break
                        line = line.strip()
                        for k, s in mapping.items():
                            if s in line:
                                val = line.split(s, 1)[-1].strip()
                                for other_key in mapping.values():
                                    if other_key != s and other_key in val: val = val.split(other_key, 1)[0].strip()
                                metadata[k] = val.strip(": ").strip()

            if not df.empty:
                bal_cols = [c for c in df.columns if 'BALANCE' in str(c).upper()]
                if bal_cols:
                    bal_col = bal_cols[0]
                    op_val = str(df.iloc[0][bal_col]).strip()
                    metadata["Opening Balance"] = f"₹ {format_indian_currency(op_val)}"
                    cl_val = str(df.iloc[-1][bal_col]).strip()
                    metadata["Closing Balance"] = f"₹ {format_indian_currency(cl_val)}"

                # Audit reconciliation against the statement's own Grand Total
                recon = compute_reconciliation(df, state['current_file'])
                if recon:
                    metadata['_recon'] = recon
                    metadata["Withdrawals (parsed)"] = f"₹ {format_indian_currency(recon['withdrawals'])}"
                    metadata["Deposits (parsed)"] = f"₹ {format_indian_currency(recon['deposits'])}"

                if preset_name == "Fixed Asset Depreciation":
                    for ci, lab in [('BLOCK_AMT', 'Total Block Amt'), ('ACTUAL_DEP', 'Total Depreciation (Year)'), ('QTR_DEP', 'Total Depreciation (Quarter)')]:
                        if ci in df.columns:
                            tot = pd.to_numeric(df[ci].astype(str).str.replace(',', ''), errors='coerce').sum()
                            metadata[lab] = f"₹ {tot}"

                if preset_name and "Interest Report" in preset_name:
                    for ci, lab in [('SANCTIONED LIMIT', 'Total Sanc. Limit'), ('BALANCE OUTSTANDING', 'Total O/S Balance')]:
                        if ci in df.columns:
                            tot = pd.to_numeric(df[ci].astype(str).str.replace(',', ''), errors='coerce').sum()
                            metadata[lab] = f"₹ {tot}"

            if return_df:
                return df, metadata

            state['df'] = df
            state['metadata'] = metadata
            update_grid()
            ui.notify(f'Analyzed {len(df)} entries.', type='positive', icon='cloud_done')
        except Exception as ex:
            logging.error(f"Engine Error: {ex}")
            ui.notify('Operation failed during parsing.', type='negative')
            if return_df: return pd.DataFrame(), {}

    async def handle_upload(e):
        try:
            u_f = getattr(e, 'file', None) or getattr(e, 'content', None)
            if not u_f and hasattr(e, 'content'): u_f = e.content
            fname = getattr(e, 'name', None) or getattr(u_f, 'name', 'file.rpt')
            if hasattr(u_f, 'filename'): fname = u_f.filename

            if not u_f: return ui.notify("File transfer failed.", type='negative')
            if inspect.iscoroutinefunction(getattr(u_f, 'read', None)): r_data = await u_f.read()
            else: r_data = u_f.read()

            temp_path = os.path.join(tempfile.gettempdir(), f"parse_{fname}")
            with open(temp_path, 'wb') as f: f.write(r_data if isinstance(r_data, bytes) else b'')

            persistent_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_session.rpt")
            shutil.copy2(temp_path, persistent_path)
            save_settings(last_file=persistent_path, original_filename=fname)

            state['current_file'] = persistent_path
            p_n = get_saved_preset()
            cf = PRESETS.get(p_n, PRESETS['Custom (Manual)'])

            custom_opts = {**cf, 'enabled': True, 'preset_name': p_n}
            new_df, new_meta = do_parse(custom_opts, return_df=True)

            if new_df is None or new_df.empty:
                ui.notify("No records could be parsed from this file.", type="warning")
                return

            if not state['df'].empty:
                state['pending_df'] = new_df
                state['pending_metadata'] = new_meta
                state['pending_filename'] = fname
                merge_diag.open()
            else:
                state['df'] = new_df
                state['metadata'] = new_meta
                state['original_filename'] = fname
                update_grid()
        except Exception as err:
            logging.error(f"Upl Fail: {err}")
            ui.notify(f"Communication issue: {err}", type='negative')

    def do_export(fmt):
        if state['df'].empty: return ui.notify('No active data for export', type='warning')
        try:
            if fmt == 'pdf':
                path = export_to_pdf(state['df'], state['metadata'])
            else:
                exporters = {'csv': export_to_csv, 'xlsx': export_to_excel, 'json': export_to_json}
                path = exporters[fmt](state['df'])
            ui.download(path, f"export.{fmt}")
        except Exception as ex:
            logging.error(f"Export Critical Fail: {ex}")
            ui.notify(f"Export system offline: {ex}", type='negative')

    async def process_and_close(e):
        await handle_upload(e)
        up_diag.close()

    def do_reset():
        state['df'] = pd.DataFrame()
        state['current_file'] = None
        state['original_filename'] = 'No file loaded'
        state['metadata'] = {}
        save_settings(last_file="", original_filename="")
        update_grid()
        ui.notify("System reset complete.", type="info", icon="restart_alt")

    # 3. Header: quiet working-paper chrome (stacks cleanly on phones)
    with ui.header(elevated=False).classes('bg-[var(--panel)] border-b border-[var(--rule)] py-2 px-3 sm:px-4'):
        with ui.row().classes('w-full items-center gap-2 flex-wrap sm:flex-nowrap'):
            with ui.row().classes('items-baseline gap-2 shrink-0 order-1'):
                ui.label('Statement Audit').classes('serif text-xl font-semibold text-[var(--ink)]')
                ui.label('Finacle .RPT verification').classes('text-xs text-[var(--muted)] hide-below-wide')

            with ui.row().classes('items-center gap-2 shrink-0 ml-auto order-2 sm:order-3'):
                ui.button(on_click=toggle_dark).props('icon=dark_mode flat round size=sm').tooltip('Toggle light / dark')
                with ui.row().classes('gap-1 p-1 rounded-lg border border-[var(--rule)] hide-phone'):
                    ui.button(on_click=lambda: do_export('csv')).props('icon=description flat round size=sm').tooltip('Export CSV')
                    ui.button(on_click=lambda: do_export('xlsx')).props('icon=file_download flat round size=sm').tooltip('Export Excel')
                    ui.button(on_click=lambda: do_export('pdf')).props('icon=picture_as_pdf flat round size=sm').tooltip('Export PDF')
                ui.button(on_click=do_reset).props('icon=restart_alt flat round color=negative size=sm').tooltip('Reset')

            with ui.row().classes('items-center gap-2 w-full sm:w-auto sm:flex-1 min-w-0 order-3 sm:order-2 flex-wrap sm:flex-nowrap'):
                with ui.row().classes('items-center gap-2 border border-[var(--rule)] px-3 py-1 rounded-full w-full sm:w-auto min-w-0'):
                    ui.icon('tune', size='xs').classes('text-[var(--muted)] shrink-0')
                    cur_p = get_saved_preset()
                    ui.select(list(PRESETS.keys()), value=cur_p,
                              on_change=lambda e: (save_preset(e.value), do_parse({**PRESETS[e.value], 'enabled': True, 'preset_name': e.value}))
                              ).classes('w-full sm:w-48 xl:w-72 text-xs').props('borderless dense hide-bottom-space options-dense')

                ui.button('Upload', on_click=lambda: up_diag.open()).props('unelevated no-caps icon=upload_file').classes('text-white bg-[var(--pen)] font-medium px-3 rounded-full h-9 shrink-0 w-full sm:w-auto justify-center')

                with ui.row().classes('items-center gap-2 pl-3 sm:border-l border-[var(--rule)] hide-below-wide'):
                    ui.icon('description', size='xs').classes('text-[var(--muted)]')
                    ui.label().bind_text_from(state, 'original_filename').classes('font-medium text-xs text-[var(--ink)] truncate max-w-[240px]')

    # 4. Dialogs
    with ui.dialog() as merge_diag, ui.card().classes('p-6 w-96 wp-panel'):
        with ui.column().classes('items-center gap-2 mb-4'):
            ui.icon('join_inner', size='3rem').classes('text-[var(--pen)]')
            ui.label('Combine datasets?').classes('serif text-lg font-semibold text-[var(--ink)]')

        ui.label('Data is already loaded. Merge the new statement into it, or replace it?').classes('text-[var(--muted)] text-sm mb-6 text-center')

        with ui.row().classes('w-full gap-2'):
            ui.button('Merge (append)', on_click=lambda: confirm_merge(True)).classes('flex-grow bg-[var(--pen)] text-white font-medium rounded-lg h-11')
            ui.button('Replace', on_click=lambda: confirm_merge(False)).props('outline').classes('flex-grow font-medium rounded-lg h-11')

    with ui.dialog() as up_diag, ui.card().classes('p-8 w-96 wp-panel'):
        ui.label('Upload statement').classes('serif text-lg font-semibold text-[var(--ink)] mb-4')
        ui.upload(on_upload=process_and_close, label="Drop the .RPT file here", auto_upload=True).classes('w-full').props('flat hide-upload-button border accept=".txt,.csv,.rpt"')
        ui.button('Close', on_click=up_diag.close).props('flat no-caps').classes('mt-4 w-full text-[var(--muted)]')

    # 5. Main canvas
    with ui.column().classes('w-full p-4 sm:p-8 max-w-[1600px] mx-auto'):
        with ui.row().classes('w-full items-center gap-3 mb-3 flex-wrap sm:flex-nowrap'):
            ui_elements['search_input'] = ui.input(placeholder='Search narrations, dates, amounts…').classes('w-full sm:w-64 lg:w-72 bg-[var(--paper)] border border-[var(--rule)] px-4 rounded-full text-xs').props('borderless dense icon=search clearable')
            with ui.row().classes('items-center gap-2 pl-3 md:border-l border-[var(--rule)] hide-tablet min-w-0'):
                ui.icon('description', size='xs').classes('text-[var(--muted)] shrink-0')
                ui.label().bind_text_from(state, 'original_filename').classes('font-medium text-xs text-[var(--ink)] truncate max-w-[220px]')
        ui_elements['results_container'] = ui.column().classes('w-full')

if __name__ in {"__main__", "__mp_main__"}:
    import webbrowser
    from threading import Timer

    parser = argparse.ArgumentParser(description="Finacle RPT Pro")
    parser.add_argument('--broadcast', action='store_true', help='Broadcast on all network interfaces')
    args, unknown = parser.parse_known_args()

    host_addr = '0.0.0.0' if args.broadcast else '127.0.0.1'
    url = f"http://{host_addr}:8080"

    def open_chrome():
        chrome_paths = [
            'C:/Program Files/Google/Chrome/Application/chrome.exe',
            'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe'
        ]
        opened = False
        for path in chrome_paths:
            if os.path.exists(path):
                try:
                    webbrowser.get(f'"{path}" %s').open(url)
                    opened = True
                    break
                except: continue
        if not opened:
            webbrowser.open(url)

    Timer(1.5, open_chrome).start()

    ui.run(title='Finacle Statement Audit', reload=False, port=8080, host=host_addr, show=False)
