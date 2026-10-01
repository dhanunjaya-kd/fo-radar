"""
Sep 30 2026: tests for the duplicate-signal Excel logging fix.
No existing tests covered excel_logger.py at all before this file.

Each test gets a fresh, isolated LOG_DIR (a tempdir, patched in) and a
full reset of the module's own in-memory state (_row_index,
_open_positions, _current_date, _initialized_today) -- these are
module-level globals that would otherwise leak between tests.

Uses real file I/O against real .xlsx files via openpyxl -- not mocked
-- since the actual bug (and its fix) lives in how the file itself is
read/written/locked, not just in-memory logic.
"""
import os
import shutil
import tempfile
import threading
from datetime import datetime, timedelta
from unittest.mock import patch

from django.test import SimpleTestCase
from openpyxl import load_workbook

from screener import excel_logger as el


def _signal(symbol, action, strike, option_symbol, **extra):
    base = {
        "symbol": symbol, "action": action, "strike": strike,
        "option_symbol": option_symbol, "grade": "A", "confidence": "80%",
        "price": 100.0, "change_percent": 1.0, "entry": 10.0, "sl": 5.0,
        "target1": 15.0, "target2": 18.0, "target3": 22.0, "quantity": 1,
        "risk_reward": 1.5, "oi_confirmation": "Confirmed", "pattern": "Test",
        "pcr": 1.1, "iv": 20.0, "rsi": 55.0, "adx": 25.0, "sector": "Test",
        "signal_logic_version": "v1", "technical_score": 80,
        "india_vix_at_signal": 12.0, "stock_vs_sector_pct": 1.0,
        "stock_vs_index_pct": 1.0, "expiry_date": "2026-10-27",
    }
    base.update(extra)
    return base


class ExcelLoggerDedupTestCase(SimpleTestCase):
    """Base class handling the real isolation every test here needs."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._log_dir_patch = patch.object(el, "LOG_DIR", self._tmpdir)
        self._log_dir_patch.start()
        el._row_index = {}
        el._open_positions = {}
        el._current_date = None
        el._initialized_today = False

    def tearDown(self):
        self._log_dir_patch.stop()
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _read_signal_rows(self):
        """Reads back the actual saved file's Symbol/Action/Option
        Symbol/Exited At columns -- real verification against what's
        genuinely on disk, not just in-memory state."""
        path, _ = el._today_path()
        if not os.path.exists(path):
            return []
        wb = load_workbook(path)
        ws = wb["Signals"]
        headers = [c.value for c in ws[1]]
        col = {name: i for i, name in enumerate(headers)}
        rows = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            if row[col["Symbol"]] is None:
                continue
            rows.append({
                "symbol": row[col["Symbol"]], "action": row[col["Action"]],
                "option_symbol": row[col["Option Symbol"]], "exited_at": row[col["Exited At"]],
                "strike": row[col["Strike"]],
            })
        return rows


class Test1_SameSignalTwice(ExcelLoggerDedupTestCase):
    """TEST 1: Same signal appears twice. Expected: 1 Excel row."""

    def test_same_signal_logged_twice_produces_one_row(self):
        sig = _signal("RELIANCE", "BUY", 1400, "NSE:RELIANCE26OCT1400CE")
        self.assertTrue(el.log_new_signal(sig))
        self.assertFalse(el.log_new_signal(sig))  # second call: must be refused
        rows = self._read_signal_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["option_symbol"], "NSE:RELIANCE26OCT1400CE")


class Test2_DisappearsThenReappears(ExcelLoggerDedupTestCase):
    """TEST 2: Signal appears -> disappears -> appears again. Expected: 1 Excel row."""

    def test_full_lifecycle_via_sync_active_signals(self):
        sig = _signal("RELIANCE", "BUY", 1400, "NSE:RELIANCE26OCT1400CE")
        # Appears
        el.sync_active_signals([sig])
        self.assertEqual(len(self._read_signal_rows()), 1)
        # Disappears (empty active list)
        el.sync_active_signals([])
        rows = self._read_signal_rows()
        self.assertEqual(len(rows), 1)
        self.assertIsNotNone(rows[0]["exited_at"])  # marked exited, not deleted
        # Reappears
        el.sync_active_signals([sig])
        rows = self._read_signal_rows()
        self.assertEqual(len(rows), 1, "reappearance must not create a second row")


class Test3_MultipleScannerCycles(ExcelLoggerDedupTestCase):
    """TEST 3: Same signal appears across multiple scanner cycles. Expected: 1 Excel row."""

    def test_ten_consecutive_scan_cycles_one_row(self):
        sig = _signal("RELIANCE", "BUY", 1400, "NSE:RELIANCE26OCT1400CE")
        for _ in range(10):
            el.sync_active_signals([sig])
        self.assertEqual(len(self._read_signal_rows()), 1)


class Test4_BackendRestart(ExcelLoggerDedupTestCase):
    """TEST 4: Backend restarts and same signal appears again. Expected: 1 Excel row."""

    def test_restart_rebuilds_state_from_file_not_from_scratch(self):
        sig = _signal("RELIANCE", "BUY", 1400, "NSE:RELIANCE26OCT1400CE")
        el.log_new_signal(sig)
        self.assertEqual(len(self._read_signal_rows()), 1)

        # Simulate a full backend restart: wipe every in-memory
        # module-level variable, exactly as a fresh process would have.
        el._row_index = {}
        el._open_positions = {}
        el._current_date = None
        el._initialized_today = False

        # The "new process" now sees the same signal again.
        self.assertFalse(el.log_new_signal(sig), "restart must not forget an already-logged signal")
        self.assertEqual(len(self._read_signal_rows()), 1)


class Test5_BrowserRefresh(ExcelLoggerDedupTestCase):
    """TEST 5: Browser refresh and same signal appears again. Expected: 1 Excel row.

    A browser refresh has no effect on the BACKEND's persistent state
    at all (React state was never the source of truth here -- this
    project's own excel log always was) -- this test exists to confirm
    that explicitly: repeated identical scan cycles (which is all a
    browser refresh could possibly trigger, via a fresh poll) still
    produce exactly one row.
    """

    def test_repeated_identical_polls_one_row(self):
        sig = _signal("RELIANCE", "BUY", 1400, "NSE:RELIANCE26OCT1400CE")
        for _ in range(5):
            el.sync_active_signals([sig])
        self.assertEqual(len(self._read_signal_rows()), 1)


class Test6_DifferentStrike(ExcelLoggerDedupTestCase):
    """TEST 6: Same symbol but different strike. Expected: 2 separate trades."""

    def test_different_strike_creates_two_rows(self):
        sig_a = _signal("RELIANCE", "BUY", 1400, "NSE:RELIANCE26OCT1400CE")
        sig_b = _signal("RELIANCE", "BUY", 1450, "NSE:RELIANCE26OCT1450CE")
        self.assertTrue(el.log_new_signal(sig_a))
        self.assertTrue(el.log_new_signal(sig_b))
        rows = self._read_signal_rows()
        self.assertEqual(len(rows), 2)
        option_symbols = {r["option_symbol"] for r in rows}
        self.assertEqual(option_symbols, {"NSE:RELIANCE26OCT1400CE", "NSE:RELIANCE26OCT1450CE"})


class Test7_DifferentExpiry(ExcelLoggerDedupTestCase):
    """TEST 7: Same symbol + strike but different expiry. Expected: 2 separate trades."""

    def test_different_expiry_creates_two_rows(self):
        sig_a = _signal("RELIANCE", "BUY", 1400, "NSE:RELIANCE26OCT1400CE", expiry_date="2026-10-27")
        sig_b = _signal("RELIANCE", "BUY", 1400, "NSE:RELIANCE26NOV1400CE", expiry_date="2026-11-24")
        self.assertTrue(el.log_new_signal(sig_a))
        self.assertTrue(el.log_new_signal(sig_b))
        rows = self._read_signal_rows()
        self.assertEqual(len(rows), 2)


class Test8_DifferentDirection(ExcelLoggerDedupTestCase):
    """TEST 8: Different direction where the project's trade identity
    treats it as different. Expected: separate legitimate trade.

    This project's own signal shape always pairs BUY with CE and SELL
    with PE (confirmed directly in trading/telegram_bot.py:
    opt_side = "CE" if action == "BUY" else "PE") -- so a genuinely
    different direction for the same symbol also means a different
    option contract, which the (option_symbol, action) key already
    treats as different. Verified here with both action AND
    option_symbol differing, matching how this system actually
    produces the two cases.
    """

    def test_buy_and_sell_for_same_symbol_are_separate_trades(self):
        sig_buy = _signal("RELIANCE", "BUY", 1400, "NSE:RELIANCE26OCT1400CE")
        sig_sell = _signal("RELIANCE", "SELL", 1400, "NSE:RELIANCE26OCT1400PE")
        self.assertTrue(el.log_new_signal(sig_buy))
        self.assertTrue(el.log_new_signal(sig_sell))
        rows = self._read_signal_rows()
        self.assertEqual(len(rows), 2)
        actions = {r["action"] for r in rows}
        self.assertEqual(actions, {"BUY", "SELL"})


class Test9_ConcurrentRequests(ExcelLoggerDedupTestCase):
    """TEST 9: Two simultaneous requests try to log the same signal.
    Expected: exactly 1 Excel row.

    This is the actual race-condition fix's own test. Runs two REAL
    threads concurrently, each independently rebuilding their own view
    of state (simulating the confirmed real risk: two separate
    processes, e.g. Django's autoreloader watcher+child, each with
    their own in-memory _row_index) and both racing to log the exact
    same signal.
    """

    def test_two_concurrent_threads_produce_exactly_one_row(self):
        sig = _signal("RELIANCE", "BUY", 1400, "NSE:RELIANCE26OCT1400CE")
        results = []
        barrier = threading.Barrier(2)

        def attempt():
            barrier.wait()  # both threads reach log_new_signal() as close to simultaneously as possible
            results.append(el.log_new_signal(dict(sig)))

        threads = [threading.Thread(target=attempt) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(sum(results), 1, "exactly one of the two concurrent attempts must succeed")
        rows = self._read_signal_rows()
        self.assertEqual(len(rows), 1, "the file itself must contain exactly one row, not two")

    def test_race_fix_rechecks_actual_file_state_not_stale_memory(self):
        """More direct proof of the actual mechanism: manually
        simulates the exact race window described in this project's
        own docstring -- a second 'process' checking with a
        deliberately stale in-memory _row_index that doesn't yet know
        about a row the 'first process' already wrote and saved."""
        sig = _signal("RELIANCE", "BUY", 1400, "NSE:RELIANCE26OCT1400CE")
        # "Process A" logs it for real.
        self.assertTrue(el.log_new_signal(sig))
        # Simulate "Process B" -- a separate process would have its OWN,
        # independently-stale in-memory _row_index that never saw
        # Process A's write. Force that exact condition here.
        el._row_index = {}
        # Process B's log_new_signal() must still refuse, because it
        # re-checks the ACTUAL FILE under the lock, not just its own
        # (deliberately emptied) memory.
        self.assertFalse(el.log_new_signal(sig))
        self.assertEqual(len(self._read_signal_rows()), 1)


class Test10_HistoricalDataUntouched(ExcelLoggerDedupTestCase):
    """TEST 10: Existing historical duplicate rows remain untouched.
    Expected: no historical P&L modification.
    """

    def test_pre_existing_duplicate_rows_are_not_modified_or_removed(self):
        # Manually create a file with a pre-existing duplicate (as if
        # written by the OLD, buggy code before this fix) -- confirms
        # this fix never touches past rows, only prevents NEW ones.
        path, today = el._today_path()
        wb = load_workbook(path) if os.path.exists(path) else None
        if wb is None:
            from openpyxl import Workbook
            wb = Workbook()
            ws = wb.active
            ws.title = "Signals"
            ws.append(el.COLUMNS)
        ws = wb["Signals"]
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for _ in range(2):  # two pre-existing "duplicate" rows, same contract
            row = ["" for _ in el.COLUMNS]
            row[el.COLUMNS.index("Timestamp")] = now_str
            row[el.COLUMNS.index("Symbol")] = "OLDSTOCK"
            row[el.COLUMNS.index("Action")] = "BUY"
            row[el.COLUMNS.index("Option Symbol")] = "NSE:OLDSTOCK26OCT100CE"
            row[el.COLUMNS.index("Outcome")] = "Target 1 Hit"
            ws.append(row)
        wb.save(path)

        rows_before = self._read_signal_rows()
        self.assertEqual(len(rows_before), 2, "test setup: two pre-existing duplicate rows")

        # Now log a genuinely NEW, different signal -- must not touch
        # the pre-existing rows in any way.
        new_sig = _signal("NEWSTOCK", "BUY", 200, "NSE:NEWSTOCK26OCT200CE")
        el.log_new_signal(new_sig)

        rows_after = self._read_signal_rows()
        self.assertEqual(len(rows_after), 3, "the 2 old rows plus the 1 new one")
        old_rows_after = [r for r in rows_after if r["symbol"] == "OLDSTOCK"]
        self.assertEqual(len(old_rows_after), 2, "both pre-existing duplicate rows must still be present, untouched")


class TestCooldownStillCollapsesRapidFlicker(ExcelLoggerDedupTestCase):
    """Confirms the cooldown's ORIGINAL, still-valid purpose survives
    this fix: a signal that exits and reappears within COOLDOWN_MINUTES
    reuses the same row (Exited At cleared), rather than either
    creating a new row OR permanently refusing to reopen it."""

    def test_exit_and_reopen_within_cooldown_reuses_same_row(self):
        sig = _signal("RELIANCE", "BUY", 1400, "NSE:RELIANCE26OCT1400CE")
        el.log_new_signal(sig)
        row_key = ("NSE:RELIANCE26OCT1400CE", "BUY")
        # Simulate a very recent exit (well within the 30-minute cooldown).
        el._row_index[row_key]["exited_at"] = datetime.now() - timedelta(minutes=2)

        result = el.log_new_signal(sig)
        self.assertFalse(result, "reopening within cooldown returns False (reactivated, not a fresh row)")
        rows = self._read_signal_rows()
        self.assertEqual(len(rows), 1, "must still be exactly one row -- reopened, not duplicated")
        self.assertIsNone(rows[0]["exited_at"], "Exited At must be cleared -- the row is active again")

    def test_exit_and_reopen_after_cooldown_expires_never_relogs(self):
        """The actual behavioral change from this fix: per the user's
        explicit, unconditional requirement, a genuinely closed EXACT
        contract is never re-logged, even after the old 30-minute
        cooldown window has passed."""
        sig = _signal("RELIANCE", "BUY", 1400, "NSE:RELIANCE26OCT1400CE")
        el.log_new_signal(sig)
        row_key = ("NSE:RELIANCE26OCT1400CE", "BUY")
        el._row_index[row_key]["exited_at"] = datetime.now() - timedelta(minutes=45)  # well past COOLDOWN_MINUTES=30

        result = el.log_new_signal(sig)
        self.assertFalse(result, "must still refuse -- unconditional, not time-limited")
        rows = self._read_signal_rows()
        self.assertEqual(len(rows), 1, "no second row, even after the old cooldown window")


class TestOpenPositionsUnaffected(ExcelLoggerDedupTestCase):
    """Confirms _open_positions / get_locked_plan() -- which answer a
    genuinely different question (what contract is CURRENTLY locked in
    for this symbol+direction) -- were correctly left untouched by
    this fix, still keyed by (symbol, action)."""

    def test_get_locked_plan_still_works_by_symbol_and_action(self):
        sig = _signal("RELIANCE", "BUY", 1400, "NSE:RELIANCE26OCT1400CE")
        el.log_new_signal(sig)
        plan = el.get_locked_plan("RELIANCE", "BUY")
        self.assertIsNotNone(plan)
        self.assertEqual(plan["option_symbol"], "NSE:RELIANCE26OCT1400CE")
        self.assertEqual(plan["sl"], 5.0)
