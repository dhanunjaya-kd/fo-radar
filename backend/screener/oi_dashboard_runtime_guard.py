"""Runtime guards for the live OI Excel dashboard.

Keeps the existing OI calculations untouched while replacing the expensive
whole-row insertion path with append-and-rebuild-panel behavior and makes raw
OI movement formatting neutral.
"""


def install():
    from . import oi_live_dashboard as dashboard

    if getattr(dashboard, "_runtime_guard_installed", False):
        return

    original_style = dashboard._style_live_row

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
