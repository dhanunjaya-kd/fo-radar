"""Keep the live OI dashboard header readable in existing workbooks.

Some previously-created workbooks retained a black header format. The dashboard
writer correctly stores the header labels, but an existing sheet could bypass
the daily/schema reset and keep that old formatting. This small guard reapplies
only the header formatting; it does not change OI calculations or polling.
"""


def install():
    try:
        from . import oi_live_dashboard as dashboard
    except Exception as exc:
        print(f"[OILiveDashboard] Header guard import skipped: {exc}")
        return

    if getattr(dashboard, "_header_guard_installed", False):
        return

    original_prepare = dashboard._prepare_sheet

    def prepare_with_visible_header(book, index_name):
        sheet = original_prepare(book, index_name)
        try:
            header = sheet.range("A1:M1")
            header.clear_formats()
            header.value = [dashboard._LIVE_LOG_COLUMNS]
            dashboard._style_header(sheet)
        except Exception as exc:
            print(f"[OILiveDashboard] Header guard skipped: {exc}")
        return sheet

    dashboard._prepare_sheet = prepare_with_visible_header
    dashboard._header_guard_installed = True
