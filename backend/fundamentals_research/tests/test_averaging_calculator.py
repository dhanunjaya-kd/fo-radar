import os
import sys
import unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fundamentals_research.services import averaging_calculator as ac


class TestCurrentPosition(unittest.TestCase):
    def test_profit_position(self):
        # Bought 100 shares @ 100, now at 120 -> invested 10000, value 12000, pnl +2000 (+20%)
        result = ac.calculate_current_position(100, 100, 120)
        self.assertEqual(result['invested_capital'], 10000)
        self.assertEqual(result['current_holding_value'], 12000)
        self.assertEqual(result['unrealized_pnl'], 2000)
        self.assertEqual(result['unrealized_pnl_pct'], 20.0)

    def test_loss_position(self):
        # Bought 50 @ 200, now at 150 -> invested 10000, value 7500, pnl -2500 (-25%)
        result = ac.calculate_current_position(200, 50, 150)
        self.assertEqual(result['unrealized_pnl'], -2500)
        self.assertEqual(result['unrealized_pnl_pct'], -25.0)

    def test_invalid_inputs_raise(self):
        with self.assertRaises(ac.AveragingInputError):
            ac.calculate_current_position(-100, 50, 150)
        with self.assertRaises(ac.AveragingInputError):
            ac.calculate_current_position(100, 0, 150)
        with self.assertRaises(ac.AveragingInputError):
            ac.calculate_current_position(100, 50, 0)


class TestAveragingScenario(unittest.TestCase):
    def test_by_quantity_hand_verified(self):
        # Own 100 @ Rs200 (invested 20000). Buy 100 more @ current Rs150 (invest 15000).
        # New: 200 shares, invested 35000, weighted avg = 35000/200 = 175
        result = ac.calculate_averaging_scenario(
            existing_avg_price=200, existing_qty=100, current_price=150,
            additional_qty=100, label='Add 100 shares',
        )
        self.assertEqual(result.new_total_qty, 200)
        self.assertEqual(result.new_total_invested, 35000)
        self.assertEqual(result.new_weighted_avg_price, 175)
        self.assertEqual(result.breakeven_price, 175)
        # exposure increase = 15000/20000*100 = 75%
        self.assertEqual(result.exposure_increase_pct, 75.0)
        # pnl at current price 150: value=200*150=30000, invested=35000, pnl=-5000
        self.assertEqual(result.unrealized_pnl_at_current_price, -5000)

    def test_by_investment_amount_hand_verified(self):
        # Own 100 @ Rs200. Invest Rs10000 more @ current Rs150 -> additional_qty = 10000/150 = 66.667
        result = ac.calculate_averaging_scenario(
            existing_avg_price=200, existing_qty=100, current_price=150,
            additional_investment=10000, label='Invest 10k more',
        )
        self.assertAlmostEqual(result.additional_qty, 66.6667, places=2)
        # new total qty = 166.6667, new invested = 20000+10000=30000
        self.assertAlmostEqual(result.new_total_qty, 166.6667, places=2)
        self.assertEqual(result.new_total_invested, 30000)
        # weighted avg = 30000/166.6667 = 180
        self.assertAlmostEqual(result.new_weighted_avg_price, 180.0, places=1)

    def test_both_qty_and_amount_given_raises(self):
        with self.assertRaises(ac.AveragingInputError):
            ac.calculate_averaging_scenario(200, 100, 150, additional_qty=50, additional_investment=5000)

    def test_neither_given_raises(self):
        with self.assertRaises(ac.AveragingInputError):
            ac.calculate_averaging_scenario(200, 100, 150)

    def test_negative_additional_qty_raises(self):
        with self.assertRaises(ac.AveragingInputError):
            ac.calculate_averaging_scenario(200, 100, 150, additional_qty=-10)

    def test_averaging_up_still_computed_correctly(self):
        """Not just averaging DOWN -- adding at a HIGHER current price
        than the existing average must also compute correctly (a real
        scenario: existing holder considering adding to a position
        that's already in profit)."""
        # Own 100 @ Rs100, current price is Rs150 (already up), add 50 more @ 150
        result = ac.calculate_averaging_scenario(
            existing_avg_price=100, existing_qty=100, current_price=150, additional_qty=50,
        )
        # new invested = 100*100 + 50*150 = 10000+7500=17500, new qty=150, weighted avg = 17500/150 = 116.667
        self.assertAlmostEqual(result.new_weighted_avg_price, 116.67, places=1)
        # this correctly RAISES the average (not lowers it) -- averaging up, not down
        self.assertGreater(result.new_weighted_avg_price, 100)


class TestDownsideScenarios(unittest.TestCase):
    def test_hand_verified_pnl_at_each_level(self):
        # 200 shares, invested 35000 (from the averaging test above)
        levels = [150, 175, 200]
        results = ac.calculate_downside_scenarios(new_total_qty=200, new_total_invested=35000, price_levels=levels)
        self.assertEqual(len(results), 3)
        # at 150: value=30000, pnl=-5000
        self.assertEqual(results[0]['pnl'], -5000)
        # at 175 (breakeven): value=35000, pnl=0
        self.assertEqual(results[1]['pnl'], 0)
        # at 200: value=40000, pnl=+5000
        self.assertEqual(results[2]['pnl'], 5000)

    def test_invalid_price_levels_skipped_not_crashed(self):
        results = ac.calculate_downside_scenarios(100, 10000, [0, -50, 120])
        self.assertEqual(len(results), 1)  # only the valid 120 survives
        self.assertEqual(results[0]['price'], 120)


class TestNeverFabricatesOrRecommends(unittest.TestCase):
    def test_scenario_never_contains_recommendation_language(self):
        """Spec explicit: 'Do not automatically recommend averaging
        simply because the stock is down.' This module returns pure
        numbers only -- verified here that no output field is a
        string containing advice language."""
        result = ac.calculate_averaging_scenario(200, 100, 150, additional_qty=100)
        result_dict = ac.scenario_to_dict(result)
        for key, value in result_dict.items():
            if isinstance(value, str) and key != 'label':
                self.assertNotIn('should', value.lower())
                self.assertNotIn('recommend', value.lower())


if __name__ == '__main__':
    unittest.main(verbosity=2)
