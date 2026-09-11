"""Runtime guards for the live OI Excel dashboard.

Keeps the existing OI calculations untouched while replacing the expensive
whole-row insertion path with append-and-rebuild-panel behavior, making raw
OI movement formatting neutral, and restoring the append cursor from the
existing workbook after a backend restart.
"""

from datetime import datetime, time as dt_time


def install():
    from . import oi_live_dashboard as dashboard

    if getattr(dashboard, "_runtime_guard_installed", False):
        return

    original_style = dashboard._style_live_row
    original_prepare_sheet = dashboard._prepare_sheet

    def style_live_row(sheet, row_num, values, previous):
        """Style the row without implying direction from raw OI movement."""
        for i, col in enumerate(dashboard._COL_LETTERS):
            try:
                cell = sheet.range(f"{col}{row_num}")
                cell.api.HorizontalAlignment = -4108
                cell.api.VerticalAlignment = -4108
                cell.api.Borders.LineStyle = 1

                if i == dashboard._BIAS_COL_INDEX:
                    bias = values[i] or ""
                    dashboard._fill(
                        cell,
                        dashboard._GREEN_FILL if "Bullish" in bias
                        else dashboard._RED_FILL if "Bearish" in bias
                        else dashboard._AMBER_FILL,
                    )
                elif i == dashboard._PCR_COL_INDEX:
                    pcr = values[i]
                    dashboard._fill(
                        cell,
                        dashboard._GREEN_FILL if pcr is not None and pcr > 1.3
                        else dashboard._RED_FILL if pcr is not None and pcr < 0.7
                        else dashboard._AMBER_FILL if pcr is not None
                        else dashboard._HEADER_FILL,
                    )
                elif i == 1 and previous is not None:
                    old, new = previous[i], values[i]
                    if isinstance(old, (int, float)) and isinstance(new, (int, float)):
                        if new > old:
                            dashboard._fill(cell, dashboard._GREEN_FILL)
                        elif new < old:
                            dashboard._fill(cell, dashboard._RED_FILL)
            except Exception as exc:
                print(f"[OILiveDashboard] Row formatting skipped for {col}{row_num}: {exc}")

    dashboard._style_live_row = style_live_row

    def _coerce_time(value):
        """Read the dashboard's Time cell without depending on Excel's exact type."""
        if isinstance(value, datetime):
            return value.time()
        if isinstance(value, dt_time):
            return value
        if isinstance(value, str):
            text = value.strip()
            for fmt in ("%H:%M:%S", "%H:%M"):
                try:
                    return datetime.strptime(text, fmt).time()
                except ValueError:
                    pass
        return None

    def _find_existing_rows(sheet):
        """Return (last_data_row, last_values) from the existing live table."""
        try:
            last_used = sheet.used_range.last_cell.row
            if last_used < 2:
                return 1, None
            raw = sheet.range(f"A2:M{last_used}").value
        except Exception as exc:
            print(f"[OILiveDashboard] Existing-row recovery skipped: {exc}")
            return 1, None

        if raw is None:
            return 1, None
        if not isinstance(raw, list):
            raw = [[raw]]
        elif raw and not isinstance(raw[0], list):
            raw = [raw]

        last_row = 1
        last_values = None
        for offset, values in enumerate(raw, start=2):
            if not values:
                break
            t = _coerce_time(values[0] if len(values) > 0 else None)
            if t is None:
                # The boundary panel begins here (its A cell contains text),
                # so the contiguous live-data block has ended.
                break
            row_values = list(values[:13])
            if len(row_values) < 13:
                row_values.extend([None] * (13 - len(row_values)))
            last_row = offset
            last_values = row_values
        return last_row, last_values

    def prepare_sheet(book, index_name):
        """Resume today's existing workbook instead of restarting at row 2."""
        today = datetime.now().strftime("%Y-%m-%d")
        try:
            sheet_names = [s.name for s in book.sheets]
            if index_name in sheet_names:
                sheet = book.sheets[index_name]
                header = sheet.range("A1").expand("right").value
                if header == dashboard._LIVE_LOG_COLUMNS:
                    last_row, last_values = _find_existing_rows(sheet)
                    if last_row >= 2 and last_values:
                        latest_time = _coerce_time(last_values[0])
                        now_time = datetime.now().time()
                        if latest_time is not None:
                            # A later clock time than now means the workbook is
                            # from a previous trading day. A small tolerance avoids
                            # resetting because of a few seconds of clock skew.
                            latest_seconds = (
                                latest_time.hour * 3600 + latest_time.minute * 60 + latest_time.second
                            )
                            now_seconds = now_time.hour * 3600 + now_time.minute * 60 + now_time.second
                            if latest_seconds <= now_seconds + 300:
                                dashboard._next_row[index_name] = last_row + 1
                                dashboard._panel_start_rows[index_name] = last_row + 1
                                dashboard._sheet_day_seen[index_name] = today
                                dashboard._prev_values[index_name] = last_values
                                dashboard._panel_ready.discard(index_name)
                                print(
                                    f"[OILiveDashboard] Resuming {index_name} from row {last_row + 1}; "
                                    f"preserving {last_row - 1} existing snapshots."
                                )
                                return sheet
        except Exception as exc:
            print(f"[OILiveDashboard] Workbook resume check failed: {exc}")

        return original_prepare_sheet(book, index_name)

    dashboard._prepare_sheet = prepare_sheet

    def _unmerge_panel(sheet, title):
        """Remove only the previous compact panel merges before relocating it."""
        ranges = (
            f"A{title}:D{title}", f"F{title}:I{title}",
            f"B{title + 3}:D{title + 3}", f"B{title + 4}:D{title + 4}",
            f"B{title + 5}:D{title + 5}", f"G{title + 3}:I{title + 3}",
            f"G{title + 4}:I{title + 4}", f"G{title + 5}:I{title + 5}",
        )
        for address in ranges:
            try:
                sheet.range(address).unmerge()
            except Exception:
                pass

    def write_dashboard_row(sheet, index_name, values):
        """Append directly into the old panel row, then relocate the panel down."""
        next_row = dashboard._next_row.get(index_name, 2)
        panel_row = dashboard._panel_start_rows.get(index_name, dashboard._FIRST_PANEL_ROW)

        if next_row == 2:
            row_num = 2
            dashboard._panel_start_rows[index_name] = 3
        else:
            row_num = panel_row
            _unmerge_panel(sheet, panel_row)
            try:
                sheet.range(f"A{panel_row}:I{panel_row + 5}").clear_contents()
                sheet.range(f"A{panel_row}:I{panel_row + 5}").clear_formats()
            except Exception as exc:
                print(f"[OILiveDashboard] Panel cleanup skipped: {exc}")
            dashboard._panel_ready.discard(index_name)
            dashboard._panel_start_rows[index_name] = panel_row + 1

        sheet.range(f"A{row_num}:M{row_num}").value = [values]
        dashboard._style_live_row(sheet, row_num, values, dashboard._prev_values.get(index_name))
        dashboard._prev_values[index_name] = values
        dashboard._next_row[index_name] = row_num + 1
        return row_num

    dashboard._write_dashboard_row = write_dashboard_row
    dashboard._runtime_guard_installed = True
