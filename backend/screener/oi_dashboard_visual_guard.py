"""Deterministic presentation layer for the live OI Excel dashboard.

This module owns only Excel presentation. OI calculations, scanner logic,
qualification, option-chain retrieval, and polling cadence are untouched.

The previous visual patch relied on the older runtime guard's panel-row reuse
logic. That made the panel disappear/interleave in some live workbooks. This
version takes control of ONLY the final row writer and visual panel renderer,
while leaving the runtime guard's workbook-recovery logic intact.
"""


def _unmerge_and_clear(sheet, address):
    try:
        sheet.range(address).api.UnMerge()
    except Exception:
        pass
    try:
        sheet.range(address).clear()
    except Exception:
        pass


def install():
    from . import oi_live_dashboard as dashboard

    if getattr(dashboard, "_visual_guard_installed", False):
        return

    def _style_header(sheet):
        try:
            header = sheet.range("A1:M1")
            header.font.bold = True
            header.font.color = dashboard._HEADER_FONT
            header.color = dashboard._HEADER_FILL
            header.api.HorizontalAlignment = -4108
            header.api.VerticalAlignment = -4108
            header.api.WrapText = True
            header.row_height = 38

            widths = {
                "A": 12, "B": 13, "C": 16, "D": 16, "E": 18,
                "F": 20, "G": 20, "H": 11, "I": 11,
            }
            for col, width in widths.items():
                sheet.range(f"{col}:{col}").column_width = width

            try:
                sheet.range("J:X").api.EntireColumn.Hidden = True
            except Exception:
                pass
            header.api.Borders.LineStyle = 1
        except Exception as exc:
            print(f"[OILiveDashboard] Visual header formatting skipped: {exc}")

    # Keep the runtime guard's semantic colouring and normalize geometry after it.
    previous_style = dashboard._style_live_row

    def _style_live_row(sheet, row_num, values, previous):
        previous_style(sheet, row_num, values, previous)
        try:
            row = sheet.range(f"A{row_num}:I{row_num}")
            row.api.HorizontalAlignment = -4108
            row.api.VerticalAlignment = -4108
            row.api.Borders.LineStyle = 1
            row.row_height = 24
        except Exception as exc:
            print(f"[OILiveDashboard] Visual row formatting skipped for row {row_num}: {exc}")

    def _write_dashboard_row(sheet, index_name, values):
        """Append one data row, never moving/reusing a visible panel row."""
        row_num = dashboard._next_row.get(index_name, 2)
        panel_start = dashboard._panel_start_rows.get(index_name)

        # The previous cycle's panel begins at the current append row. Remove
        # only that old panel before writing the new data row.
        if row_num > 2 and panel_start == row_num:
            _unmerge_and_clear(sheet, f"A{panel_start}:I{panel_start + 5}")
            dashboard._panel_ready.discard(index_name)

        sheet.range(f"A{row_num}:M{row_num}").value = [values]
        _style_live_row(sheet, row_num, values, dashboard._prev_values.get(index_name))
        dashboard._prev_values[index_name] = values
        dashboard._next_row[index_name] = row_num + 1
        dashboard._panel_start_rows[index_name] = row_num + 1
        return row_num

    def _write_boundary_panel(sheet, index_name, row, oi_snap):
        """Render a compact boundary/status panel directly below the table."""
        rows = (oi_snap or {}).get("rows") or []
        calls, puts = dashboard.compute_boundary_pairs(rows)
        call1 = calls[0] if calls else (None, None)
        call2 = calls[1] if len(calls) > 1 else (None, None)
        put1 = puts[0] if puts else (None, None)
        put2 = puts[1] if len(puts) > 1 else (None, None)

        title = dashboard._panel_start_rows.get(index_name, dashboard._FIRST_PANEL_ROW)
        r1, r2, r3, r4, r5 = title + 1, title + 2, title + 3, title + 4, title + 5

        # Always remove the old panel region first. No data row is touched.
        _unmerge_and_clear(sheet, f"A{title}:I{r5}")

        try:
            # Use normal cells rather than a complex merge graph. This is much
            # more reliable with already-open Excel workbooks and keeps the
            # panel visually compact without affecting the data table.
            sheet.range(f"A{title}:D{title}").merge()
            sheet.range(f"F{title}:I{title}").merge()
            sheet.range(f"B{r3}:D{r3}").merge()
            sheet.range(f"B{r4}:D{r4}").merge()
            sheet.range(f"B{r5}:D{r5}").merge()
            sheet.range(f"G{r3}:I{r3}").merge()
            sheet.range(f"G{r4}:I{r4}").merge()
            sheet.range(f"G{r5}:I{r5}").merge()

            sheet.range(f"A{title}").value = "Open Interest Upper Boundary"
            sheet.range(f"F{title}").value = "Open Interest Lower Boundary"

            sheet.range(f"A{r1}:D{r2}").value = [
                ["Strike Price 1", call1[0], "OI (in K)", dashboard._to_k(call1[1])],
                ["Strike Price 2", call2[0], "OI (in K)", dashboard._to_k(call2[1])],
            ]
            sheet.range(f"F{r1}:I{r2}").value = [
                ["Strike Price 1", put1[0], "OI (in K)", dashboard._to_k(put1[1])],
                ["Strike Price 2", put2[0], "OI (in K)", dashboard._to_k(put2[1])],
            ]

            bias = row.get("Bias") or "N/A"
            pcr = row.get("PCR")
            spot = row.get("Spot") or row.get("Value")

            sheet.range(f"A{r3}").value = "Open Interest"
            sheet.range(f"B{r3}").value = bias
            sheet.range(f"A{r4}").value = "Call Exits"
            sheet.range(f"B{r4}").value = "No"
            sheet.range(f"A{r5}").value = "Call ITM"
            sheet.range(f"B{r5}").value = (
                "Yes" if spot is not None and call1[0] is not None and call1[0] < spot else "No"
            )

            sheet.range(f"F{r3}").value = "PCR"
            sheet.range(f"G{r3}").value = pcr
            sheet.range(f"F{r4}").value = "Put Exits"
            sheet.range(f"G{r4}").value = "No"
            sheet.range(f"F{r5}").value = "Put ITM"
            sheet.range(f"G{r5}").value = (
                "Yes" if spot is not None and put1[0] is not None and put1[0] > spot else "No"
            )

            for addr in (f"A{title}", f"F{title}"):
                cell = sheet.range(addr)
                cell.font.bold = True
                cell.api.HorizontalAlignment = -4108
                cell.api.VerticalAlignment = -4108
                cell.api.WrapText = True
                dashboard._fill(cell, dashboard._TITLE_FILL)

            for rr in (r1, r2, r3, r4, r5):
                for col in ("A", "C", "F", "H"):
                    cell = sheet.range(f"{col}{rr}")
                    cell.font.bold = True
                    cell.api.HorizontalAlignment = -4108
                    cell.api.VerticalAlignment = -4108
                    dashboard._fill(cell, dashboard._HEADER_FILL)
                for col in ("B", "D", "G", "I"):
                    cell = sheet.range(f"{col}{rr}")
                    cell.api.HorizontalAlignment = -4108
                    cell.api.VerticalAlignment = -4108
                    dashboard._fill(cell, dashboard._NEUTRAL_FILL)

            status_fill = (
                dashboard._GREEN_FILL if "Bullish" in bias
                else dashboard._RED_FILL if "Bearish" in bias
                else dashboard._AMBER_FILL
            )
            dashboard._fill(sheet.range(f"B{r3}"), status_fill)
            if isinstance(pcr, (int, float)):
                dashboard._fill(sheet.range(f"G{r3}"), status_fill)

            sheet.range(f"B{r1}").number_format = "0.0"
            sheet.range(f"B{r2}").number_format = "0.0"
            sheet.range(f"D{r1}").number_format = "#,##0.0"
            sheet.range(f"D{r2}").number_format = "#,##0.0"
            sheet.range(f"G{r1}").number_format = "0.0"
            sheet.range(f"G{r2}").number_format = "0.0"
            sheet.range(f"I{r1}").number_format = "#,##0.0"
            sheet.range(f"I{r2}").number_format = "#,##0.0"
            sheet.range(f"G{r3}").number_format = "0.00"

            panel = sheet.range(f"A{title}:I{r5}")
            panel.api.Borders.LineStyle = 1
            panel.api.HorizontalAlignment = -4108
            panel.api.VerticalAlignment = -4108
            panel.api.WrapText = True
            sheet.range(f"{title}:{title}").row_height = 29
            for rr in range(r1, r5 + 1):
                sheet.range(f"{rr}:{rr}").row_height = 24

            # Make the separation from the table visually obvious without
            # inserting blank data rows.
            try:
                sheet.range(f"A{title}:I{title}").api.Borders.Weight = 2
            except Exception:
                pass
        except Exception as exc:
            print(f"[OILiveDashboard] Boundary panel render failed: {exc}")

    dashboard._style_header = _style_header
    dashboard._style_live_row = _style_live_row
    dashboard._write_dashboard_row = _write_dashboard_row
    dashboard._write_boundary_panel = _write_boundary_panel
    dashboard._visual_guard_installed = True
