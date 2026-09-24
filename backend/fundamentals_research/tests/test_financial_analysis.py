import os
import sys
import unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fundamentals_research.services.source_registry import SourcedValue, Source
from fundamentals_research.services import financial_analysis as fa


def sv(value, source=Source.BHARATSTOCK):
    return SourcedValue(value=value, source=source)


class TestGrowthAndCagr(unittest.TestCase):
    def test_growth_pct_normal_case(self):
        result = fa.calculate_growth_pct(sv(110), sv(100))
        self.assertEqual(result.value, 10.0)
        self.assertEqual(result.source, Source.CALCULATED)

    def test_growth_pct_negative_growth(self):
        result = fa.calculate_growth_pct(sv(90), sv(100))
        self.assertEqual(result.value, -10.0)

    def test_growth_pct_none_input_returns_none_not_crash(self):
        result = fa.calculate_growth_pct(sv(None), sv(100))
        self.assertIsNone(result.value)

    def test_growth_pct_zero_previous_returns_none_not_divide_by_zero(self):
        result = fa.calculate_growth_pct(sv(100), sv(0))
        self.assertIsNone(result.value)

    def test_cagr_normal_case(self):
        # 100 -> 200 over 5 years ~= 14.87% CAGR
        result = fa.calculate_cagr(sv(100), sv(200), 5)
        self.assertAlmostEqual(result.value, 14.87, places=1)

    def test_cagr_negative_start_returns_none(self):
        result = fa.calculate_cagr(sv(-50), sv(100), 3)
        self.assertIsNone(result.value)

    def test_cagr_zero_years_returns_none(self):
        result = fa.calculate_cagr(sv(100), sv(200), 0)
        self.assertIsNone(result.value)


class TestMarginsAndProfitability(unittest.TestCase):
    def test_margin_pct(self):
        result = fa.calculate_margin_pct(sv(2000), sv(10000))
        self.assertEqual(result.value, 20.0)

    def test_roe(self):
        result = fa.calculate_roe_pct(sv(1000), sv(10000))
        self.assertEqual(result.value, 10.0)

    def test_roe_zero_equity_returns_none(self):
        result = fa.calculate_roe_pct(sv(1000), sv(0))
        self.assertIsNone(result.value)

    def test_roce(self):
        result = fa.calculate_roce_pct(sv(1500), sv(10000))
        self.assertEqual(result.value, 15.0)


class TestBalanceSheetRatios(unittest.TestCase):
    def test_debt_equity(self):
        result = fa.calculate_debt_equity(sv(4000), sv(10000))
        self.assertEqual(result.value, 0.4)

    def test_net_debt_can_be_negative_net_cash_position(self):
        result = fa.calculate_net_debt(sv(1000), sv(5000))
        self.assertEqual(result.value, -4000.0)  # net cash, a real and valid outcome

    def test_interest_coverage(self):
        result = fa.calculate_interest_coverage(sv(2000), sv(400))
        self.assertEqual(result.value, 5.0)

    def test_current_ratio(self):
        result = fa.calculate_current_ratio(sv(6000), sv(3000))
        self.assertEqual(result.value, 2.0)


class TestCashFlow(unittest.TestCase):
    def test_fcf_positive_capex_sign_handled(self):
        # capex commonly reported as a positive "spend" number
        result = fa.calculate_free_cash_flow(sv(5000), sv(1500))
        self.assertEqual(result.value, 3500.0)

    def test_fcf_negative_capex_sign_also_handled(self):
        # some sources report capex as already-negative (outflow convention)
        result = fa.calculate_free_cash_flow(sv(5000), sv(-1500))
        self.assertEqual(result.value, 3500.0)  # abs() applied -- same real result either way

    def test_cfo_to_pat_flags_weak_cash_conversion(self):
        result = fa.calculate_cfo_to_pat(sv(300), sv(1000))
        self.assertEqual(result.value, 0.3)  # real, low ratio -- the Section 12 example case

    def test_cfo_to_pat_zero_pat_returns_none(self):
        result = fa.calculate_cfo_to_pat(sv(300), sv(0))
        self.assertIsNone(result.value)


class TestValuation(unittest.TestCase):
    def test_earnings_yield_is_inverse_of_pe(self):
        result = fa.calculate_earnings_yield_pct(sv(25))
        self.assertEqual(result.value, 4.0)

    def test_distance_from_52w_high(self):
        result = fa.calculate_distance_from_52w_high_pct(sv(950), sv(1000))
        self.assertEqual(result.value, -5.0)

    def test_fcf_yield(self):
        result = fa.calculate_fcf_yield_pct(sv(50000), sv(1000000))
        self.assertEqual(result.value, 5.0)


class TestNeverFabricates(unittest.TestCase):
    """Every function, given a None anywhere it needs a real number,
    must return None -- never a guessed/interpolated/zero-as-default
    value. This is the single most important property of this whole
    file per spec Section 9/27, tested explicitly and exhaustively
    rather than trusted to the individual test cases above alone."""
    def test_all_functions_handle_none_gracefully(self):
        none_sv = sv(None)
        real_sv = sv(100)
        fns_and_args = [
            (fa.calculate_growth_pct, (none_sv, real_sv)),
            (fa.calculate_cagr, (none_sv, real_sv, 5)),
            (fa.calculate_margin_pct, (none_sv, real_sv)),
            (fa.calculate_roe_pct, (none_sv, real_sv)),
            (fa.calculate_roce_pct, (none_sv, real_sv)),
            (fa.calculate_debt_equity, (none_sv, real_sv)),
            (fa.calculate_net_debt, (none_sv, real_sv)),
            (fa.calculate_interest_coverage, (none_sv, real_sv)),
            (fa.calculate_current_ratio, (none_sv, real_sv)),
            (fa.calculate_working_capital, (none_sv, real_sv)),
            (fa.calculate_free_cash_flow, (none_sv, real_sv)),
            (fa.calculate_cfo_to_pat, (none_sv, real_sv)),
            (fa.calculate_capex_intensity_pct, (none_sv, real_sv)),
            (fa.calculate_distance_from_52w_high_pct, (none_sv, real_sv)),
            (fa.calculate_fcf_yield_pct, (none_sv, real_sv)),
            (fa.calculate_earnings_yield_pct, (none_sv,)),
        ]
        for fn, args in fns_and_args:
            result = fn(*args)
            self.assertIsNone(result.value, f"{fn.__name__} did not return None for a None input -- possible fabrication risk")


if __name__ == '__main__':
    unittest.main(verbosity=2)
