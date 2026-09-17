"""Visual layout guard for the live OI Excel dashboard.

Matches the compact desktop reference layout for NIFTY, BANKNIFTY and SENSEX:
- nine visible market columns (Time through Put ITM)
- compact, uniform rows with centered text and thin borders
- boundary/status panel directly below the live table
- no hidden/legacy side-panel content visible to the user

This module changes presentation only. It does not change OI calculations,
qualification, signal generation, or polling cadence.
"""


def install():
    from . import oi_live_dashboard as dashboard

    if getattr(dashboard, "_visual_guard_installed", False):
        return

    def _style_header(sheet):
        """Apply a fixed, compact Excel layout matching the reference UI."""
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
                "A": 12,  # Time
                "B": 13,  # Value
                "C": 16,  # Call Sum
                "D": 16,  # Put Sum
                "E": 17,  # Difference
                "F": 19,  # Call Boundary
                "G": 19,  # Put Boundary
                "H": 11,  # Call ITM
                "I": 11,  # Put ITM
            }
            for col, width in widths.items():
                sheet.range(f"{col}:{col}").column_width = width

            # The underlying writer still stores four metadata columns J:M;
            # keep them available to the guard logic but never show them.
            try:
                sheet.range("J:X").api.EntireColumn.Hidden = True
            except Exception:
                pass

            # Normalize all existing live-data rows too, so a workbook that
            # was already open/restarted does not retain uneven old sizing.
            try:
                last_used = sheet.used_range.last_cell.row
                if last_used >= 2:
                    body = sheet.range(f"A2:I{last_used}")
                    body.api.HorizontalAlignment = -4108
                    body.api.VerticalAlignment = -4108
                    body.api.Borders.LineStyle = 1
                    body.row_height = 24
            except Exception:
                pass

            # Remove the legacy fixed right-side panel produced by older
            # versions. The live panel now belongs below the table.
            try:
                legacy = sheet.range("P2:X8")
                legacy.api.UnMerge()
                legacy.clear()
            except Exception:
                pass

            header.api.Borders.LineStyle = 1
        except Exception as exc:
            print(f"[OILiveDashboard] Visual header formatting skipped: {exc}")

    # The runtime guard replaces this function during app startup, so install
    # the visual wrapper after the runtime guard. We keep all semantic coloring
    # from the existing guard and only normalize geometry/spacing here.
    base_style_live_row = dashboard._style_live_row

    def _style_live_row(sheet, row_num, values, previous):
        base_style_live_row(sheet, row_num, values, previous)
        try:
            row = sheet.range(f"A{row_num}:I{row_num}")
            row.api.HorizontalAlignment = -4108
            row.api.VerticalAlignment = -4108
            row.api.Borders.LineStyle = 1
            row.row_height = 24
        except Exception as exc:
            print(f"[OILiveDashboard] Visual row sizing skipped for row {row_num}: {exc}")

    def _unmerge_panel(sheet, title):
        addresses = (
            f"A{title}:D{title}",
            f"F{title}:I{title}",
            f"B{title + 3}:D{title + 3}",
            f"B{title + 4}:D{title + 4}",
            f"B{title + 5}:D{title + 5}",
            f"G{title + 3}:I{title + 3}",
            f"G{title + 4}:I{title + 4}",
            f"G{title + 5}:I{title + 5}",
        )
        for address in addresses:
            try:
                sheet.range(address).unmerge()
            except Exception:
                pass

    def _write_boundary_panel(sheet, index_name, row, oi_snap):
        """Render the status/boundary block directly under the live table."""
        rows = (oi_snap or {}).get("rows") or []
        calls, puts = dashboard.compute_boundary_pairs(rows)
        call1 = calls[0] if calls else (None, None)
        call2 = calls[1] if len(calls) > 1 else (None, None)
        put1 = puts[0] if puts else (None, None)
        put2 = puts[1] if len(puts) > 1 else (None, None)

        # _write_dashboard_row (including the runtime guard replacement) sets
        # this to one row below the just-written data row. That gives the
        # reference layout: continuous table, then the compact panel.
        title = dashboard._panel_start_rows.get(index_name, dashboard._FIRST_PANEL_ROW)
        r1, r2, r3, r4, r5 = title + 1, title + 2, title + 3, title + 4, title + 5

        # Compact reference layout: A:D on the left, F:I on the right.
        L1, L2, L3, L4 = "A", "B", "C", "D"
        R1, R2, R3, R4 = "F", "G", "H", "I"

        try:
            _unmerge_panel(sheet, title)
            panel = sheet.range(f"A{title}:I{r5}")
            panel.clear()

            sheet.range(f"{L1}{title}:{L4}{title}").merge()
            sheet.range(f"{R1}{title}:{R4}{title}").merge()
            for rr in (r3, r4, r5):
                sheet.range(f"{L2}{rr}:{L4}{rr}").merge()
                sheet.range(f"{R2}{rr}:{R4}{rr}").merge()

            sheet.range(f"{L1}{title}").value = "Open Interest Upper Boundary"
            sheet.range(f"{R1}{title}").value = "Open Interest Lower Boundary"

            sheet.range(f"{L1}{r1}:{L4}{r2}").value = [
                ["Strike Price 1", call1[0], "OI (in K)", dashboard._to_k(call1[1])],
                ["Strike Price 2", call2[0], "OI (in K)", dashboard._to_k(call2[1])],
            ]
            sheet.range(f"{R1}{r1}:{R4}{r2}").value = [
                ["Strike Price 1", put1[0], "OI (in K)", dashboard._to_k(put1[1])],
                ["Strike Price 2", put2[0], "OI (in K)", dashboard._to_k(put2[1])],
            ]

            bias = row.get("Bias") or "N/A"
            pcr = row.get("PCR")
            spot = row.get("Spot") or row.get("Value")

            sheet.range(f"{L1}{r3}").value = "Open Interest"
            sheet.range(f"{L2}{r3}").value = bias
            sheet.range(f"{L1}{r4}").value = "Call Exits"
            sheet.range(f"{L2}{r4}").value = "No"
            sheet.range(f"{L1}{r5}").value = "Call ITM"
            sheet.range(f"{L2}{r5}").value = (
                "Yes" if spot is not None and call1[0] is not None and call1[0] < spot else "No"
            )

            sheet.range(f"{R1}{r3}").value = "PCR"
            sheet.range(f"{R2}{r3}").value = pcr
            sheet.range(f"{R1}{r4}").value = "Put Exits"
            sheet.range(f"{R2}{r4}").value = "No"
            sheet.range(f"{R1}{r5}").value = "Put ITM"
            sheet.range(f"{R2}{r5}").value = (
                "Yes" if spot is not None and put1[0] is not None and put1[0] > spot else "No"
            )

            # Typography and fills.
            for addr in (f"{L1}{title}", f"{R1}{title}"):
                cell = sheet.range(addr)
                cell.font.bold = True
                cell.api.HorizontalAlignment = -4108
                cell.api.VerticalAlignment = -4108
                cell.api.WrapText = True
                dashboard._fill(cell, dashboard._TITLE_FILL)

            label_fill = dashboard._HEADER_FILL
            for rr in (r1, r2, r3, r4, r5):
                for addr in (f"{L1}{rr}", f"{L3}{rr}", f"{R1}{rr}", f"{R3}{rr}"):
                    cell = sheet.range(addr)
                    cell.font.bold = True
                    cell.api.HorizontalAlignment = -4108
                    cell.api.VerticalAlignment = -4108
                    cell.api.WrapText = True
                    dashboard._fill(cell, label_fill)

            for rr in (r1, r2, r3, r4, r5):
                for addr in (f"{L2}{rr}", f"{L4}{rr}", f"{R2}{rr}", f"{R4}{rr}"):
                    cell = sheet.range(addr)
                    cell.api.HorizontalAlignment = -4108
                    cell.api.VerticalAlignment = -4108
                    dashboard._fill(cell, dashboard._NEUTRAL_FILL)

            # Match the reference's straightforward status coloring: the
            # directional Open Interest status and PCR carry the same side.
            status_fill = (
                dashboard._GREEN_FILL if "Bullish" in bias
                else dashboard._RED_FILL if "Bearish" in bias
                else dashboard._AMBER_FILL
            )
            dashboard._fill(sheet.range(f"{L2}{r3}"), status_fill)
            if isinstance(pcr, (int, float)):
                dashboard._fill(sheet.range(f"{R2}{r3}"), status_fill)

            sheet.range(f"{L2}{r1}:{L2}{r2}").number_format = "0.0"
            sheet.range(f"{L4}{r1}:{L4}{r2}").number_format = "#,##0.0"
            sheet.range(f"{R2}{r1}:{R2}{r2}").number_format = "0.0"
            sheet.range(f"{R4}{r1}:{R4}{r2}").number_format = "#,##0.0"
            sheet.range(f"{R2}{r3}").number_format = "0.00"

            panel.api.Borders.LineStyle = 1
            panel.api.VerticalAlignment = -4108
            panel.api.WrapText = True
            sheet.range(f"{title}:{title}").row_height = 29
            for rr in range(r1, r5 + 1):
                sheet.range(f"{rr}:{rr}").row_height = 24
        except Exception as exc:
            print(f"[OILiveDashboard] Reference panel formatting skipped: {exc}")

    dashboard._style_header = _style_header
    dashboard._style_live_row = _style_live_row
    dashboard._write_boundary_panel = _write_boundary_panel
    dashboard._visual_guard_installed = True
