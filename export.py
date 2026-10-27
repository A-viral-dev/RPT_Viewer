import pandas as pd
import tempfile
import os

def export_to_csv(df: pd.DataFrame) -> str:
    """Exports DataFrame to a temporary CSV file and returns the path."""
    temp_dir = tempfile.gettempdir()
    filepath = os.path.join(temp_dir, "export.csv")
    df.to_csv(filepath, index=False)
    return filepath

def export_to_excel(df: pd.DataFrame) -> str:
    """Exports DataFrame to a temporary Excel file and returns the path."""
    temp_dir = tempfile.gettempdir()
    filepath = os.path.join(temp_dir, "export.xlsx")
    df.to_excel(filepath, index=False, engine='openpyxl')
    return filepath

def export_to_json(df: pd.DataFrame) -> str:
    """Exports DataFrame to a temporary JSON file and returns the path."""
    temp_dir = tempfile.gettempdir()
    filepath = os.path.join(temp_dir, "export.json")
    df.to_json(filepath, orient='records', indent=4)
    return filepath

def export_to_pdf(df: pd.DataFrame, metadata: dict = None) -> str:
    """Exports DataFrame and metadata to a true physical PDF file."""
    try:
        from fpdf import FPDF
    except ImportError:
        raise Exception("fpdf2 is not installed. Please run: uv add fpdf2")
        
    temp_dir = tempfile.gettempdir()
    filepath = os.path.join(temp_dir, "export.pdf")
    
    # We use landscape to fit wide financial reports
    pdf = FPDF(orientation='L', unit='mm', format='A4')
    pdf.add_page()
    
    # Header
    pdf.set_font("helvetica", style="B", size=16)
    pdf.cell(0, 10, "Finacle Report Statement", ln=True, align="C")
    
    # Metadata context block
    if metadata:
        pdf.set_font("helvetica", size=10)
        pdf.ln(5)
        for k, v in metadata.items():
            if k.startswith('_'):
                continue  # internal keys (e.g. _recon) never leak into exports
            # Replace Rupee symbol with Rs. as Helvetica doesn't support it
            clean_v = str(v).replace('₹', 'Rs.')
            pdf.cell(0, 6, f"{k}: {clean_v}", ln=True)
        recon = metadata.get('_recon')
        if recon:
            verdict = ("Reconciled with the statement's reported Grand Total" if recon.get('match')
                       else "MISMATCH vs the statement's reported Grand Total - review preset and source file")
            pdf.set_font("helvetica", style="B", size=10)
            pdf.cell(0, 6, f"Reconciliation: {verdict}", ln=True)
            
    pdf.ln(5)
    pdf.set_font("helvetica", size=7)
    
    # Prepare data for fpdf2 Table format - replace currency symbol here too
    str_df = df.astype(str).replace('nan', '')
    for col in str_df.columns:
        str_df[col] = str_df[col].str.replace('₹', 'Rs.')
    
    with pdf.table(borders_layout="ALL", text_align="LEFT") as table:
        # Table Headers row - clean column names too
        header_row = table.row()
        for col_name in str_df.columns:
            header_row.cell(str(col_name).replace('₹', 'Rs.'))
            
        # Table Data rows
        for _, raw_row in str_df.iterrows():
            data_row = table.row()
            for val in raw_row:
                data_row.cell(str(val))
                
    pdf.output(filepath)
    return filepath
