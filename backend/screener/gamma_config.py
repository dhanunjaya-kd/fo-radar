"""
screener/gamma_config.py

Gamma Blast Strategy -- exact parameters from the purchased package's
config/strategy_config.json (v1.4.0), unchanged. Kept as one Python
dict (matching how this project already keeps SNIPER_V2_CONFIG etc.
in views.py) rather than a separate JSON file to load.
"""

GAMMA_BLAST_CONFIG = {
    "strategy_metadata": {
        "strategy_name": "Gamma_Blast_Options_strategy",
        "version": "1.4.0",
    },
    "market_scanner": {
        "scan_interval_seconds": 3.5,
        "strict_proximity_pct": 0.75,
        "approaching_proximity_pct": 2.0,
        "min_underlying_volume": 500000,
        "min_underlying_turnover_cr": 100.0,
    },
    "macro_trend_gate": {
        "enabled": True,
        "ema_period": 50,
        "bullish_gate": "Spot >= EMA50",
        "bearish_gate": "Spot <= EMA50",
    },
    "options_resolution": {
        "min_dte": 8,
        "options_per_stock": 2,
        "max_ce_stocks": 3,
        "max_pe_stocks": 3,
        "total_options_count": 12,
        "delta_sweet_spot_min": 0.20,
        "delta_sweet_spot_max": 0.45,
        "delta_hard_min": 0.15,
        "delta_hard_max": 0.50,
        "gamma_convexity_min": 0.150,
        "min_option_oi": 50000,
        "min_option_volume": 25000,
        "max_bid_ask_spread_pct": 3.0,
        "otm_moneyness_ce_max_pct": 1.055,   # strike <= spot * 1.055
        "otm_moneyness_pe_min_pct": 0.945,   # strike >= spot * 0.945
        "sweet_spot_distance_min_pct": 0.5,
        "sweet_spot_distance_max_pct": 3.5,
    },
    "microstructure_trigger": {
        "oi_dip_min_pct": 0.80,
        "volume_expansion_ratio_min": 1.5,
        "price_lift_min_pct": 2.0,
        "price_lift_max_pct": 9.0,
        "max_spread_pct_at_trigger": 3.0,
        "cooldown_seconds": 1800.0,
        "buffer_length": 25,
    },
    "zone_engine": {
        "pivot_len": 10,
        "zone_depth": 2.5,
        "guard_mult": 2.0,
        "zone_memory": 20,
        "use_wick": False,
    },
    "risk_management": {
        "initial_capital_inr": 1000000.0,
        "default_risk_budget_per_trade_inr": 7500.0,
        "max_portfolio_risk_pct": 3.0,
        "max_concurrent_positions": 3,
        "initial_stop_loss_pct": 25.0,
        "target_1_pct": 40.0,
        "target_1_r_multiple": 1.6,
        "target_1_exit_fraction": 0.50,
        "trail_sl_to_breakeven_at_t1": True,
        "target_2_pct": 70.0,
        "target_2_r_multiple": 2.8,
        "hard_time_stop_hours": 48,
    },
}
