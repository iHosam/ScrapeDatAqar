"""
Memory-efficient export module converting streamed CSV to RTL styled Excel spreadsheet.
Supports custom source CSV and output Excel paths.
"""

import csv
import os
import time
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.cell import WriteOnlyCell
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

from config import DATA_DIR

def export_to_excel(csv_path=None, excel_path=None):
    if not csv_path:
        csv_path = os.path.join(DATA_DIR, 'aqar_latest_53cols.csv')
    if not excel_path:
        excel_path = os.path.splitext(csv_path)[0] + '.xlsx'

    if not os.path.exists(csv_path):
        print(f"Error: CSV file {csv_path} not found.")
        return None

    print(f"Reading {csv_path} and generating styled Excel workbook...")
    t0 = time.time()
    wb = openpyxl.Workbook(write_only=True)
    ws = wb.create_sheet(title="عقارات المملكة")
    ws.views.sheetView[0].rightToLeft = True

    header_fill = PatternFill(start_color="0A5C36", end_color="0A5C36", fill_type="solid")
    header_font = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)

    thin_border = Border(
        left=Side(style='thin', color='D9D9D9'), right=Side(style='thin', color='D9D9D9'),
        top=Side(style='thin', color='D9D9D9'), bottom=Side(style='thin', color='D9D9D9')
    )
    data_font = Font(name="Segoe UI", size=10)
    center_align = Alignment(horizontal="center", vertical="center")
    right_align = Alignment(horizontal="right", vertical="center")

    def clean_val(v):
        return ILLEGAL_CHARACTERS_RE.sub('', v) if isinstance(v, str) else v

    num_indices = {0, 4, 6, 7, 8, 22, 23, 24, 41, 42, 43, 50}
    float_indices = {39, 40}

    with open(csv_path, 'r', encoding='utf-8-sig', errors='ignore') as f:
        reader = csv.reader(f)
        headers = next(reader, None)
        if headers:
            header_cells = []
            for h in headers:
                c = WriteOnlyCell(ws, value=clean_val(h))
                c.font, c.fill, c.alignment, c.border = header_font, header_fill, header_align, thin_border
                header_cells.append(c)
            ws.append(header_cells)

        count = 0
        for row in reader:
            if not row:
                continue
            row_cells = []
            for idx, val in enumerate(row):
                cell_val = val
                if idx in num_indices:
                    try:
                        cell_val = float(val) if '.' in val else int(val)
                    except Exception:
                        cell_val = clean_val(val)
                elif idx in float_indices:
                    try:
                        cell_val = float(val)
                    except Exception:
                        cell_val = clean_val(val)
                else:
                    cell_val = clean_val(val)

                c = WriteOnlyCell(ws, value=cell_val)
                c.font, c.border = data_font, thin_border
                c.alignment = center_align if isinstance(cell_val, (int, float)) else right_align
                row_cells.append(c)
            ws.append(row_cells)
            count += 1
            if count % 10000 == 0:
                print(f"  Exported {count:,} records...", flush=True)

    wb.save(excel_path)
    file_size_mb = os.path.getsize(excel_path) / (1024 * 1024)
    print(f"[Export] Saved {excel_path} ({file_size_mb:.2f} MB, {count:,} rows) in {time.time()-t0:.1f}s.")
    return excel_path

if __name__ == '__main__':
    export_to_excel()
