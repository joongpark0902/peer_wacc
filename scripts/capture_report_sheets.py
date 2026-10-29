"""Capture real Excel cell rendering without modifying the source workbook.

Requirements: Windows, installed Microsoft Excel, pywin32, Pillow, openpyxl.
Example:
    python scripts/capture_report_sheets.py path/to/report.xlsx

Every PNG is assembled from native Range.CopyPicture bitmap captures. No cell
values or formatting are redrawn. Excel opens in a private DispatchEx instance,
with links/macros/recalculation disabled and ReadOnly=True, then closes unsaved.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import shutil
import time

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from PIL import Image, ImageGrab
import pythoncom
import win32clipboard
import win32com.client


SLUGS = {
    "요약": "01_summary",
    "WACC": "02_wacc",
    "후보군": "03_candidates",
    "피어": "04_peers",
    "이자부부채 산정내역": "05_interest_bearing_debt",
    "주가": "06_prices",
    "베타": "07_beta",
    "목표DE": "08_target_de",
    "금투협": "09_kofia",
}


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def backup_existing(path: Path) -> None:
    if path.exists():
        stamp = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y%m%d_%H%M%S_%f")
        backup_dir = Path(__file__).resolve().parents[1] / "cache/ui-backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / f"backup_{stamp}_recapture_{path.name}"
        shutil.copy2(path, backup)
        if sha256(path) != sha256(backup):
            raise RuntimeError(f"Backup verification failed: {path}")


def copy_bitmap(sheet, address: str) -> Image.Image:
    """Read only the clipboard bitmap just produced by this Excel instance."""
    area = sheet.Range(address)
    last_error = None
    for attempt in range(5):
        try:
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
            finally:
                win32clipboard.CloseClipboard()
            area.CopyPicture(Appearance=1, Format=2)  # xlScreen, xlBitmap
            for _ in range(20):
                time.sleep(0.1)
                pythoncom.PumpWaitingMessages()
                bitmap = ImageGrab.grabclipboard()
                if isinstance(bitmap, Image.Image):
                    result = bitmap.convert("RGB")
                    if result.width < 2 or result.height < 2:
                        raise RuntimeError(f"Empty bitmap for {address}")
                    return result
            raise RuntimeError(f"Excel did not publish a bitmap for {address}")
        except Exception as exc:
            last_error = exc
            time.sleep(0.4 * (attempt + 1))
    raise RuntimeError(f"CopyPicture failed for {sheet.Name}!{address}: {last_error}")


def save_image(image: Image.Image, path: Path) -> dict:
    backup_existing(path)
    image.save(path, format="PNG", optimize=True)
    with Image.open(path) as check:
        check.verify()
    return {"file": path.name, "width_px": image.width,
            "height_px": image.height, "sha256": sha256(path)}


def presentation_adjustments(sheet, source_sheet) -> list[dict]:
    """Apply authorized, unsaved display adjustments; never touch cell content."""
    changes = []
    name = source_sheet.title
    note_ranges = {
        "요약": [f"A{row}:B{row}" for row in range(13, 20)],
        "WACC": ["B2:N2", "B29:N29"],
        "이자부부채 산정내역": ["B2:G2", "B3:G3"],
    }.get(name, [])
    for address in note_ranges:
        source_cells = list(source_sheet[address])[0]
        if any(cell.value is not None for cell in source_cells[1:]):
            raise RuntimeError(f"Refusing to merge nonempty note cells: {name}!{address}")
        area = sheet.Range(address)
        text = str(source_cells[0].value or "")
        area.Merge()
        area.WrapText = True
        area.VerticalAlignment = -4160  # xlTop
        # Excel does not AutoFit merged rows. Conservative glyph-width estimate
        # reserves sufficient height for both Korean and Latin text at source font.
        weighted_chars = sum(2 if ord(char) > 255 else 1 for char in text)
        font_size = float(area.Cells(1, 1).Font.Size)
        line_capacity = max(1, float(area.Width) / (font_size * 0.58))
        lines = max(1, math.ceil(weighted_chars / line_capacity))
        area.EntireRow.RowHeight = max(22, lines * font_size * 1.6 + 6)
        changes.append({"range": address, "merge_empty_note_span": True,
                        "wrap_text": True, "row_height_points": area.EntireRow.RowHeight})
    if name == "피어":
        sheet.UsedRange.Columns.AutoFit()
        for column, width in (("Z", 36), ("AE", 52)):
            sheet.Columns(column).ColumnWidth = width
        sheet.UsedRange.WrapText = True
        sheet.UsedRange.Rows.AutoFit()
        sheet.Rows(1).RowHeight = max(45, sheet.Rows(1).RowHeight)
        changes.append({"range": source_sheet.calculate_dimension(),
                        "columns_autofit": True, "column_width_overrides": {"Z": 36, "AE": 52},
                        "wrap_text": True, "rows_autofit": True, "header_min_height_points": 45})
    elif name == "WACC":
        sheet.Range("D14:D27").WrapText = True
        for row in range(14, 28):
            cell = sheet.Cells(row, 4)
            if cell.Value is not None:
                weighted = sum(2 if ord(char) > 255 else 1 for char in str(cell.Value))
                capacity = max(1, float(cell.Width) / (float(cell.Font.Size) * 0.58))
                cell.EntireRow.RowHeight = max(float(cell.EntireRow.RowHeight),
                                              math.ceil(weighted / capacity) * float(cell.Font.Size) * 1.6 + 6)
        changes.append({"range": "D14:D27", "wrap_text": True,
                        "row_heights": "expanded for full explanatory text"})
    elif name in {"후보군", "금투협"}:
        # Header/body wraps retain the source column widths. Long product and
        # industry descriptions now remain fully visible instead of clipping.
        if name == "후보군":
            for col in range(1, source_sheet.max_column + 1):
                sheet.Columns(col).ColumnWidth = max(12, float(sheet.Columns(col).ColumnWidth))
            changes.append({"range": "A:R", "minimum_column_width": 12,
                            "reason": "Reserve space for table filter buttons and complete header labels"})
        sheet.UsedRange.WrapText = True
        sheet.UsedRange.Rows.AutoFit()
        if name == "후보군":
            sheet.Rows(1).RowHeight = 32
        changes.append({"range": source_sheet.calculate_dimension(),
                        "wrap_text": True, "rows_autofit": True})
    return changes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbook", type=Path)
    parser.add_argument("--output", type=Path,
                        default=Path(__file__).resolve().parents[1] / "docs/img/report")
    parser.add_argument("--tile-rows", type=int, default=35)
    args = parser.parse_args()
    source = args.workbook.resolve(strict=True)
    if args.tile_rows < 1:
        parser.error("--tile-rows must be positive")
    original_hash = sha256(source)
    cached = load_workbook(source, data_only=True)
    formulas = load_workbook(source, data_only=False)
    if set(cached.sheetnames) != set(SLUGS):
        raise RuntimeError(f"Review sheet inventory before capture: {cached.sheetnames}")
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = {
        "source_file": source.name,
        "source_sha256": original_hash,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "method": "Microsoft Excel Range.CopyPicture(xlScreen, xlBitmap); native tiles stitched vertically",
        "source_opened_read_only": True,
        "source_saved": False,
        "recalculation": "disabled; source cached results preserved",
        "gridlines": "hidden only in the private unsaved Excel session",
        "presentation_only": "Column widths, wrapping, row heights and empty note-cell spans adjusted in memory for readability; source values/formulas preserved",
        "sheets": [],
    }
    pythoncom.CoInitialize()
    excel = None
    workbook = None
    try:
        excel = win32com.client.DispatchEx("Excel.Application")
        excel.DisplayAlerts = False
        excel.AskToUpdateLinks = False
        excel.AutomationSecurity = 3  # msoAutomationSecurityForceDisable
        excel.Visible = True
        # Calculation may only be set once a workbook exists. A private blank
        # workbook ensures the report opens with manual calculation already set.
        blank = excel.Workbooks.Add()
        excel.Calculation = -4135  # xlCalculationManual
        workbook = excel.Workbooks.Open(str(source), UpdateLinks=0, ReadOnly=True,
                                       IgnoreReadOnlyRecommended=True, AddToMru=False)
        blank.Close(SaveChanges=False)
        if not workbook.ReadOnly:
            raise RuntimeError("Report was not opened read-only")
        for source_sheet in cached:
            name = source_sheet.title
            sheet = workbook.Worksheets(name)
            sheet.Activate()
            excel.ActiveWindow.DisplayGridlines = False
            excel.ActiveWindow.Zoom = 100
            source_content = sheet.Range(source_sheet.calculate_dimension()).Formula
            adjustments = presentation_adjustments(sheet, source_sheet)
            if sheet.Range(source_sheet.calculate_dimension()).Formula != source_content:
                raise RuntimeError(f"Display adjustment changed values/formulas: {name}")
            last_row = source_sheet.max_row
            visible_cols = [col for col in range(1, source_sheet.max_column + 1)
                            if not bool(sheet.Columns(col).Hidden)]
            first_col, last_col = min(visible_cols), max(visible_cols)
            left, right = get_column_letter(first_col), get_column_letter(last_col)
            tiles = []
            coverage = []
            for row in range(1, last_row + 1, args.tile_rows):
                end = min(last_row, row + args.tile_rows - 1)
                address = f"{left}{row}:{right}{end}"
                picture = copy_bitmap(sheet, address)
                tiles.append(picture)
                coverage.append({"range": address, "width_px": picture.width,
                                 "height_px": picture.height})
            widths = {picture.width for picture in tiles}
            if len(widths) != 1:
                raise RuntimeError(f"Inconsistent native capture widths: {name}: {widths}")
            full = Image.new("RGB", (tiles[0].width, sum(p.height for p in tiles)), "white")
            top = 0
            for picture in tiles:
                full.paste(picture, (0, top))
                top += picture.height
            errors = [{"cell": cell.coordinate, "value": cell.value}
                      for row in source_sheet for cell in row if cell.data_type == "e"]
            missing_cache = [cell.coordinate for row in formulas[name] for cell in row
                             if cell.data_type == "f" and source_sheet[cell.coordinate].value is None]
            entry = {
                "sheet": name,
                "range": f"{left}1:{right}{last_row}",
                "source_dimensions": source_sheet.calculate_dimension(),
                "visible_columns": [get_column_letter(col) for col in visible_cols],
                "excluded_hidden_columns": [get_column_letter(col) for col in range(1, source_sheet.max_column + 1)
                                            if col not in visible_cols],
                "hidden_rows": [row for row in range(1, last_row + 1) if sheet.Rows(row).Hidden],
                "unsaved_presentation_adjustments": adjustments,
                "cell_values_and_formulas_unchanged": True,
                "tiles": coverage,
                "image": save_image(full, args.output / f"{SLUGS[name]}.png"),
                "source_cached_errors": errors,
                "formula_cells_without_cached_values": missing_cache,
            }
            if last_row > 35:
                preview_end = min(25, last_row)
                preview = copy_bitmap(sheet, f"{left}1:{right}{preview_end}")
                entry["preview"] = {"range": f"{left}1:{right}{preview_end}",
                                    **save_image(preview, args.output / f"{SLUGS[name]}_preview.png")}
            manifest["sheets"].append(entry)
            print(f"Captured {name}: {entry['range']} -> {entry['image']['file']}", flush=True)
    finally:
        if workbook is not None:
            workbook.Close(SaveChanges=False)
        if excel is not None:
            excel.Quit()  # Only our private DispatchEx instance.
        pythoncom.CoUninitialize()
    final_hash = sha256(source)
    if original_hash != final_hash:
        raise RuntimeError("Source file changed during capture")
    manifest["source_sha256_after"] = final_hash
    manifest["source_unchanged"] = True
    manifest_path = args.output / "manifest.json"
    backup_existing(manifest_path)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Verified source unchanged; manifest: {manifest_path}", flush=True)


if __name__ == "__main__":
    main()
