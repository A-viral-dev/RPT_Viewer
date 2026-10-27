import json
import os

# Standard Finacle Page/Boilerplate Cleanup rules
FINACLE_CLEANUP = {
    "ignore_prefixes": [
        'page tota', 'grand tot', 'note:', 'note: ch', 'returning', 'unless th', 'within 15', 
        'a/c', 'a/c numbe', 'sta', 'statement', 'date', 'address', 'helpline', 'branch', 
        'micr', 'micr code', 'for detai', 'please co', 
        'abbreviat', 'retd -', 'ec -', 'ec   -', 'sp -', 'sp   -', 'int -', 'int  -', 
        'obc -', 'obc  -', 'daue -', 'this is a', '****end', 'bank of', '---', 'as on',
        # sanitised sample fixtures use a generic bank/branch header
        'sample bank', 'sample branch'
    ],
    "stop_markers": [
        'as on ', 'clrbal:', 'we  are', 'we are', 'to get tr', 'pending p'
    ]
}

# Shared configuration for Term Loans and Escrow Accounts to keep them linked
TERM_LOAN_CONFIG = { 
    "skip_rows": 24, 
    "separator": "", 
    "fixed_widths": "9, 15, 11, 18, 18, 50", 
    "merge_narration": True,
    "metadata_mappings": {
        "A/C Name": "A/C Name",
        "A/C Number": "A/C Number",
        "Account Open Date": "Account Open Date",
        "Scheme Description": "Scheme Description",
        "Statement Period": "Statement of account"
    },
    **FINACLE_CLEANUP
}

# Registry of all known parser profile presets
PRESETS = {
    "Custom (Manual)": { 
        "skip_rows": 0, 
        "separator": "", 
        "fixed_widths": "", 
        "merge_narration": False,
        "metadata_mappings": {},
        "ignore_prefixes": [],
        "stop_markers": []
    },
    "Finacle - Term Loan (.RPT)": TERM_LOAN_CONFIG,
    " Escrow Account": TERM_LOAN_CONFIG,
    "Cash credit general (CC001)": {
        "skip_rows": 22,
        "separator": "",
        "fixed_widths": "9, 33, 12, 19, 15, 40",
        "merge_narration": True,
        "metadata_mappings": {
            "A/C Name": "A/C Name",
            "A/C Number": "A/C Number",
            "Scheme Description": "Scheme Description",
            "Statement Period": "Statement of account"
        },
        **FINACLE_CLEANUP
    },
    "Fixed Asset Depreciation": {
        "enabled": True,
        "skip_rows": 13,
        "separator": "|",
        "fixed_widths": "",
        "merge_narration": False,
        "ignore_prefixes": [
            "TOTAL :", "CATEGORY:", "MAJOR CATEGORY", "-------", "NOTE :", 
            "SNO|", "-", "SAMPLE BANK", "FIXED ASSET"
        ],
        "stop_markers": ["SUMMARY:", "END OF REPORT"],
        "metadata_mappings": {
            "SOL ID": "SOLID",
            "Generated On": "GENERATED ON"
        }
    },
    "Interest Report (LA001)": {
        "skip_rows": 12,
        "separator": "|",
        "fixed_widths": "",
        "merge_narration": False,
        "ignore_prefixes": ["-------", "|SCHM |", "|CODE |", "|     |", "\x0c"],
        "stop_markers": ["NOTE :"],
        "metadata_mappings": {
            "SOL ID": "SOL ID",
            "SOL NAME": "SOL NAME",
            "As On": "AS ON",
            "Scheme Code": "SCHEME CODE",
            "Total Outstanding": "Total Outstanding             :"
        }
    },
    "Interest Report (LA030)": {
        "skip_rows": 12,
        "separator": "|",
        "fixed_widths": "",
        "merge_narration": False,
        "ignore_prefixes": ["-------", "|SCHM |", "|CODE |", "|     |", "\x0c"],
        "stop_markers": ["NOTE :"],
        "metadata_mappings": {
            "SOL ID": "SOL ID",
            "SOL NAME": "SOL NAME",
            "As On": "AS ON",
            "Scheme Code": "SCHEME CODE",
            "Total Outstanding": "Total Outstanding             :"
        }
    },
    "Interest Report (OD028)": {
        "skip_rows": 12,
        "separator": "|",
        "fixed_widths": "",
        "merge_narration": False,
        "ignore_prefixes": ["-------", "|SCHM |", "|CODE |", "|     |", "\x0c"],
        "stop_markers": ["NOTE :"],
        "metadata_mappings": {
            "SOL ID": "SOL ID",
            "SOL NAME": "SOL NAME",
            "As On": "AS ON",
            "Scheme Code": "SCHEME CODE",
            "Total Outstanding": "Total Outstanding             :"
        }
    },
    "Interest Report (CC001 & CC002)": {
        "skip_rows": 12,
        "separator": "|",
        "fixed_widths": "",
        "merge_narration": False,
        "ignore_prefixes": ["-------", "|SCHM |", "|CODE |", "|     |", "\x0c"],
        "stop_markers": ["NOTE :"],
        "metadata_mappings": {
            "SOL ID": "SOL ID",
            "SOL NAME": "SOL NAME",
            "As On": "AS ON",
            "Scheme Code": "SCHEME CODE",
            "Total Outstanding": "Total Outstanding             :"
        }
    }
}

CONFIG_FILE = "app_settings.json"

def get_saved_settings() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {'preset': 'Custom (Manual)', 'last_file': None, 'original_filename': None}

def get_saved_preset() -> str:
    settings = get_saved_settings()
    preset = settings.get('preset', 'Custom (Manual)')
    return preset if preset in PRESETS else 'Custom (Manual)'

def save_preset(preset: str):
    save_settings(preset=preset)

def save_settings(preset: str = None, last_file: str = None, original_filename: str = None):
    settings = get_saved_settings()
    if preset is not None: settings['preset'] = preset
    if last_file is not None: settings['last_file'] = last_file
    if original_filename is not None: settings['original_filename'] = original_filename
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(settings, f)
    except Exception:
        pass
