"""Final deterministic presentation/repair guard for the live OI Excel dashboard.

Presentation/data-display repair only. OI calculations, scanner qualification,
option-chain retrieval and polling cadence are untouched.
"""
from datetime import datetime, time as dt_time


def _unmerge_clear(sheet, address):
    try:
        sheet.range(address).api.UnMerge()
    except Exception:
        pass
    try:
        sheet.range(address).clear()
    except Exception:
        pass


def _as_time(value):
    if isinstance(value, datetime):
        return value.time()
    if isinstance(value, dt_time):
        return value
    if isinstance(value, str):
        for fmt in ("%H:%M:%S", "%H:%M"):
            try:
                return datetime.strptime(value.strip(), fmt).time()
            except ValueError:
                pass
    return None


def install():
    from . import oi_live_dashboard as d
    if getattr(d, "_final_guard_installed", False):
        return

    # ---------- Header / visible layout ----------
    def style_header(sheet):
        try:
            h = sheet.range("A1:M1")
            h.font.bold = True
            h.font.color = d._HEADER_FONT
            h.color = d._HEADER_FILL
            h.api.HorizontalAlignment = -4108
            h.api.VerticalAlignment = -4108
            h.api.WrapText = True
            h.row_height = 38
            for col, width in {"A":12,"B":13,"C":16,"D":16,"E":18,"F":20,"G":20,"H":11,"I":11}.items():
                sheet.range(f"{col}:{col}").column_width = width
            try:
                sheet.range("J:XFD").api.EntireColumn.Hidden = True
            except Exception:
                try:
                    sheet.range("J:X").api.EntireColumn.Hidden = True
                except Exception:
                    pass
            h.api.Borders.LineStyle = 1
        except Exception as exc:
            print(f"[OILiveDashboard] Final header guard skipped: {exc}")

    # ---------- Main table colouring ----------
    base_style = d._style_live_row
    def style_live_row(sheet, row_num, values, previous):
        try:
            base_style(sheet, row_num, values, previous)
        except Exception:
            pass
        try:
            for i, col in enumerate("ABCDEFGHI"):
                cell = sheet.range(f"{col}{row_num}")
                cell.api.HorizontalAlignment = -4108
                cell.api.VerticalAlignment = -4108
                cell.api.Borders.LineStyle = 1
                d._fill(cell, d._NEUTRAL_FILL)
                value = values[i] if i < len(values) else None
                if i == 4 and isinstance(value, (int, float)):
                    d._fill(cell, d._GREEN_FILL if value > 0 else d._RED_FILL if value < 0 else d._AMBER_FILL)
                elif i in (1, 2, 3, 5, 6, 7, 8) and previous is not None and len(previous) > i:
                    old = previous[i]
                    if isinstance(old, (int, float)) and isinstance(value, (int, float)):
                        d._fill(cell, d._GREEN_FILL if value > old else d._RED_FILL if value < old else d._AMBER_FILL)
            sheet.range(f"A{row_num}:I{row_num}").row_height = 24
        except Exception as exc:
            print(f"[OILiveDashboard] Final row styling skipped for {row_num}: {exc}")

    # ---------- Repair legacy workbooks where data exists after the panel ----------
    base_prepare = d._prepare_sheet
    def prepare_sheet(book, index_name):
        sheet = base_prepare(book, index_name)
        try:
            last = sheet.used_range.last_cell.row
            nxt = d._next_row.get(index_name, 2)
            if last > nxt:
                tail = sheet.range(f"A{nxt}:A{last}").value
                if tail is not None:
                    if not isinstance(tail, list):
                        tail = [[tail]]
                    elif tail and not isinstance(tail[0], list):
                        tail = [[x] for x in tail]
                    late_data = any(_as_time(x[0] if x else None) is not None for x in tail)
                    if late_data:
                        raw = sheet.range(f"A2:M{last}").value
                        if not isinstance(raw, list):
                            raw = [[raw]]
                        elif raw and not isinstance(raw[0], list):
                            raw = [raw]
                        rows = []
                        for x in raw:
                            if x and _as_time(x[0] if len(x) else None) is not None:
                                r = list(x[:13])
                                r += [None] * (13-len(r))
                                rows.append(r[:13])
                        if rows:
                            clear_end = max(last, len(rows)+8)
                            _unmerge_clear(sheet, f"A2:I{clear_end}")
                            try:
                                sheet.range(f"A2:M{clear_end}").clear_contents()
                                sheet.range(f"A2:M{clear_end}").clear_formats()
                            except Exception:
                                pass
                            sheet.range(f"A2:M{len(rows)+1}").value = rows
                            prev = None
                            for rr, vals in enumerate(rows, start=2):
                                style_live_row(sheet, rr, vals, prev)
                                prev = vals
                            last_data = len(rows)+1
                            d._next_row[index_name] = last_data+1
                            d._panel_start_rows[index_name] = last_data+1
                            d._prev_values[index_name] = rows[-1]
                            d._panel_ready.discard(index_name)
                            print(f"[OILiveDashboard] Final repair: compacted {index_name} to {len(rows)} rows; panel={last_data+1}")
            style_header(sheet)
        except Exception as exc:
            print(f"[OILiveDashboard] Final workbook repair skipped for {index_name}: {exc}")
        return sheet

    # ---------- Enrich missing Difference / ITM values from the cached OI snapshot ----------
    base_write = d.write_live_dashboard
    def write_live_dashboard(results):
        enriched = dict(results or {})
        for index_name, row in list(enriched.items()):
            if not row or index_name not in ("NIFTY", "BANKNIFTY", "SENSEX"):
                continue
            try:
                snap = d.get_last_oi_snapshot(index_name) or {}
                chain = snap.get("rows") or []
                r = dict(row)
                tc = r.get("Total Call OI")
                tp = r.get("Total Put OI")
                if tc is None and chain:
                    tc = sum(((x.get("ce", {}) or {}).get("oi") or 0) for x in chain)
                    r["Total Call OI"] = tc
                if tp is None and chain:
                    tp = sum(((x.get("pe", {}) or {}).get("oi") or 0) for x in chain)
                    r["Total Put OI"] = tp
                if r.get("Difference") is None and isinstance(tc, (int,float)) and isinstance(tp, (int,float)):
                    r["Difference"] = tc - tp
                if (r.get("Call ITM Ratio") is None or r.get("Put ITM Ratio") is None) and chain:
                    spot = r.get("Spot") if r.get("Spot") is not None else r.get("Value")
                    ci, pi = d.compute_itm_ratios(chain, spot, tc, tp)
                    if r.get("Call ITM Ratio") is None:
                        r["Call ITM Ratio"] = ci
                    if r.get("Put ITM Ratio") is None:
                        r["Put ITM Ratio"] = pi
                enriched[index_name] = r
            except Exception as exc:
                print(f"[OILiveDashboard] Final value enrichment skipped for {index_name}: {exc}")
        return base_write(enriched)

    # ---------- Deterministic row writer ----------
    def write_dashboard_row(sheet, index_name, values):
        row_num = d._next_row.get(index_name, 2)
        panel = d._panel_start_rows.get(index_name)
        if row_num > 2 and panel == row_num:
            _unmerge_clear(sheet, f"A{panel}:I{panel+5}")
            d._panel_ready.discard(index_name)
        sheet.range(f"A{row_num}:M{row_num}").value = [values]
        style_live_row(sheet, row_num, values, d._prev_values.get(index_name))
        d._prev_values[index_name] = values
        d._next_row[index_name] = row_num + 1
        d._panel_start_rows[index_name] = row_num + 1
        return row_num

    # ---------- Clean UB/LB panel ----------
    def fill_status(sheet, addr, value, yes_green=True):
        text = str(value or "").lower().strip()
        if text == "yes":
            colour = d._GREEN_FILL if yes_green else d._RED_FILL
        elif text == "no":
            colour = d._RED_FILL if yes_green else d._GREEN_FILL
        else:
            colour = d._AMBER_FILL
        d._fill(sheet.range(addr), colour)

    def write_boundary_panel(sheet, index_name, row, snap):
        rows = (snap or {}).get("rows") or []
        calls, puts = d.compute_boundary_pairs(rows)
        c1 = calls[0] if calls else (None,None); c2 = calls[1] if len(calls)>1 else (None,None)
        p1 = puts[0] if puts else (None,None); p2 = puts[1] if len(puts)>1 else (None,None)
        title = d._panel_start_rows.get(index_name, d._FIRST_PANEL_ROW)
        r1,r2,r3,r4,r5 = title+1,title+2,title+3,title+4,title+5
        _unmerge_clear(sheet, f"A{title}:I{r5}")
        try:
            sheet.range(f"A{title}:D{title}").merge(); sheet.range(f"F{title}:I{title}").merge()
            for rr in (r3,r4,r5):
                sheet.range(f"B{rr}:D{rr}").merge(); sheet.range(f"G{rr}:I{rr}").merge()
            sheet.range(f"A{title}").value="Open Interest Upper Boundary"; sheet.range(f"F{title}").value="Open Interest Lower Boundary"
            sheet.range(f"A{r1}:D{r2}").value=[["Strike Price 1",c1[0],"OI (in K)",d._to_k(c1[1])],["Strike Price 2",c2[0],"OI (in K)",d._to_k(c2[1])]]
            sheet.range(f"F{r1}:I{r2}").value=[["Strike Price 1",p1[0],"OI (in K)",d._to_k(p1[1])],["Strike Price 2",p2[0],"OI (in K)",d._to_k(p2[1])]]
            bias=row.get("Bias") or "N/A"; pcr=row.get("PCR"); spot=row.get("Spot") if row.get("Spot") is not None else row.get("Value")
            call_itm="Yes" if spot is not None and c1[0] is not None and c1[0] < spot else "No"
            put_itm="Yes" if spot is not None and p1[0] is not None and p1[0] > spot else "No"
            vals=[(f"A{r3}","Open Interest"),(f"B{r3}",bias),(f"A{r4}","Call Exits"),(f"B{r4}","No"),(f"A{r5}","Call ITM"),(f"B{r5}",call_itm),(f"F{r3}","PCR"),(f"G{r3}",pcr),(f"F{r4}","Put Exits"),(f"G{r4}","No"),(f"F{r5}","Put ITM"),(f"G{r5}",put_itm)]
            for addr,val in vals: sheet.range(addr).value=val
            for addr in (f"A{title}:D{title}",f"F{title}:I{title}"):
                cell=sheet.range(addr); cell.font.bold=True; cell.api.HorizontalAlignment=-4108; cell.api.VerticalAlignment=-4108; cell.api.WrapText=True; d._fill(cell,d._TITLE_FILL)
            for rr in (r1,r2,r3,r4,r5):
                for col in ("A","C","F","H"):
                    cell=sheet.range(f"{col}{rr}"); cell.font.bold=True; cell.api.HorizontalAlignment=-4108; cell.api.VerticalAlignment=-4108; d._fill(cell,d._HEADER_FILL)
                for col in ("B","D","G","I"):
                    cell=sheet.range(f"{col}{rr}"); cell.api.HorizontalAlignment=-4108; cell.api.VerticalAlignment=-4108; d._fill(cell,d._NEUTRAL_FILL)
            oi_fill=d._GREEN_FILL if "Bullish" in bias else d._RED_FILL if "Bearish" in bias else d._AMBER_FILL
            d._fill(sheet.range(f"B{r3}:D{r3}"),oi_fill)
            if isinstance(pcr,(int,float)):
                d._fill(sheet.range(f"G{r3}:I{r3}"), d._GREEN_FILL if pcr>1.05 else d._RED_FILL if pcr<0.95 else d._AMBER_FILL)
            fill_status(sheet,f"B{r4}:D{r4}","No",True); fill_status(sheet,f"G{r4}:I{r4}","No",True)
            fill_status(sheet,f"B{r5}:D{r5}",call_itm,True); fill_status(sheet,f"G{r5}:I{r5}",put_itm,True)
            panel=sheet.range(f"A{title}:I{r5}"); panel.api.Borders.LineStyle=1; panel.api.HorizontalAlignment=-4108; panel.api.VerticalAlignment=-4108; panel.api.WrapText=True
            sheet.range(f"{title}:{title}").row_height=29
            for rr in range(r1,r5+1): sheet.range(f"{rr}:{rr}").row_height=24
        except Exception as exc:
            print(f"[OILiveDashboard] Final UB/LB render failed: {exc}")

    d._style_header=style_header; d._style_live_row=style_live_row; d._prepare_sheet=prepare_sheet
    d._write_dashboard_row=write_dashboard_row; d._write_boundary_panel=write_boundary_panel; d.write_live_dashboard=write_live_dashboard
    d._final_guard_installed=True
