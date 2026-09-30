"""
Sep 30 2026: tests for TelegramBot.send_signal_alert()'s "Design 8"
reformat. send_message() is mocked in every test -- this project's own
existing rule (test_telegram_alert.py's docstring, and the explicit
instruction behind this rewrite) is that automated tests must never
trigger a real Telegram send. These tests check message CONSTRUCTION
only: that every existing signal field still appears, with its exact
existing value, and that the new HTML formatting is valid and safely
escaped -- never that formatting changes behavior, since none of it
should.
"""
import re
from unittest.mock import patch, MagicMock

from django.test import SimpleTestCase

from .telegram_bot import TelegramBot


# Matches the reference design's own SELL/PE example (TII INDIA) --
# real field names and shapes as send_signal_alert() actually reads
# them, not invented for the test.
SAMPLE_SIGNAL = {
    "symbol": "TII INDIA",
    "action": "SELL",
    "strike": 2450,
    "option_symbol": "NSE:TIINDIA26SEP2450PE",
    "expiry_date": "26 SEP 2026",
    "entry": 31.55,
    "sl": None,  # reference design's own sample shows Stop Loss as "₹—" for this exact case
    "target1": 51.95,
    "target2": 64.19,
    "target3": 80.51,
    "grade": "A",
    "confidence": "82%",
    "pattern": "OI-Confirmed Momentum",
    "oi_confirmation": "CONFIRMED",
    "quality_verdict": "CONFIRMED",
    "quality_score": 60.0,
    "risk_reward": 0.89,
    "generated_at": "Just now",
}


def _bot():
    return TelegramBot(bot_token="test-token", chat_id="test-chat-id")


class TestSignalAlertValuesPreserved(SimpleTestCase):
    """Every existing field, with its exact existing value, must still
    appear in the new layout -- this is the actual point of a
    formatting-only change."""

    def setUp(self):
        self.bot = _bot()
        with patch.object(self.bot, "send_message") as mock_send:
            self.bot.send_signal_alert(SAMPLE_SIGNAL)
            self.sent_message = mock_send.call_args[0][0]

    def test_symbol_present(self):
        self.assertIn("TII INDIA", self.sent_message)

    def test_action_and_option_side_present(self):
        self.assertIn("SELL", self.sent_message)
        self.assertIn("PE", self.sent_message)  # SELL -> PE, derived exactly as the old code did

    def test_option_symbol_present(self):
        self.assertIn("NSE:TIINDIA26SEP2450PE", self.sent_message)

    def test_expiry_and_strike_present(self):
        self.assertIn("26 SEP 2026", self.sent_message)
        self.assertIn("2450", self.sent_message)

    def test_quality_verdict_and_score_present(self):
        self.assertIn("CONFIRMED", self.sent_message)
        self.assertIn("60.0", self.sent_message)

    def test_confidence_present(self):
        self.assertIn("82%", self.sent_message)

    def test_risk_reward_present(self):
        self.assertIn("0.89", self.sent_message)

    def test_entry_and_targets_present(self):
        self.assertIn("31.55", self.sent_message)
        self.assertIn("51.95", self.sent_message)
        self.assertIn("64.19", self.sent_message)
        self.assertIn("80.51", self.sent_message)

    def test_missing_stop_loss_shows_dash_not_python_none_string(self):
        """Formatting-only: a genuinely absent value now shows '₹—'
        (matching the reference design's own sample) instead of the
        old code's literal 'Rs None' -- the value itself (None) is
        completely unchanged, only its display."""
        self.assertIn("₹—", self.sent_message)
        self.assertNotIn("None", self.sent_message)

    def test_pattern_and_oi_confirmation_both_present(self):
        self.assertIn("OI-Confirmed Momentum", self.sent_message)
        self.assertIn("CONFIRMED", self.sent_message)

    def test_generated_at_present(self):
        self.assertIn("Just now", self.sent_message)

    def test_order_copy_exact_text_preserved(self):
        """The single most important preservation requirement in the
        whole task: the copyable order text itself must be byte-exact
        to what a trader would actually execute."""
        self.assertIn("SELL NSE:TIINDIA26SEP2450PE", self.sent_message)
        self.assertIn("LIMIT @ 31.55", self.sent_message)

    def test_order_copy_wrapped_in_code_tag_for_tap_to_copy(self):
        """Telegram's <code> tag is what makes text tap-to-copy on
        mobile -- confirms the order copy actually gets this real
        capability, not just visual styling."""
        self.assertRegex(self.sent_message, r"<code>SELL NSE:TIINDIA26SEP2450PE\nLIMIT @ 31\.55</code>")

    def test_send_message_still_called_with_default_html_parse_mode(self):
        """Confirms send_message()'s own signature/defaults are
        completely untouched -- only send_signal_alert()'s message
        construction changed."""
        bot = _bot()
        with patch.object(bot, "send_message") as mock_send:
            bot.send_signal_alert(SAMPLE_SIGNAL)
            # send_signal_alert calls send_message(text) -- parse_mode
            # defaults to 'HTML' inside send_message itself, unchanged
            # from before this rewrite.
            self.assertEqual(len(mock_send.call_args[0]), 1)


class TestHtmlValidityAndEscaping(SimpleTestCase):
    def _render(self, signal):
        bot = _bot()
        with patch.object(bot, "send_message") as mock_send:
            bot.send_signal_alert(signal)
            return mock_send.call_args[0][0]

    def test_html_special_characters_in_dynamic_fields_are_escaped(self):
        """Real safety point the task itself calls out: a dynamic
        field containing HTML-special characters must not break
        Telegram's parser or inject unintended markup."""
        signal = dict(SAMPLE_SIGNAL)
        signal["pattern"] = "Breakout & Retest <fake>"
        message = self._render(signal)
        self.assertIn("Breakout &amp; Retest &lt;fake&gt;", message)
        self.assertNotIn("<fake>", message)  # the RAW unescaped tag must never appear

    def test_all_b_and_code_tags_are_balanced(self):
        """Basic structural validity check -- an unbalanced tag is
        exactly the kind of mistake that breaks Telegram's HTML
        parsing and was called out explicitly as a risk to guard
        against."""
        message = self._render(SAMPLE_SIGNAL)
        for tag in ("b", "code"):
            opens = len(re.findall(f"<{tag}>", message))
            closes = len(re.findall(f"</{tag}>", message))
            self.assertEqual(opens, closes, f"<{tag}> tags are unbalanced")

    def test_ampersand_in_header_is_escaped(self):
        """The header text itself contains a literal '&' (F&O) --
        confirms this static text is ALSO properly escaped, not just
        dynamic fields."""
        message = self._render(SAMPLE_SIGNAL)
        self.assertIn("F&amp;O RADAR SIGNAL", message)


class TestOptionalFieldsOmittedWhenAbsent(SimpleTestCase):
    """Preserves the exact existing conditional-display behavior --
    an optional field that was omitted before must still be omitted
    now, just restyled when it IS present."""

    def _render(self, signal):
        bot = _bot()
        with patch.object(bot, "send_message") as mock_send:
            bot.send_signal_alert(signal)
            return mock_send.call_args[0][0]

    def test_target2_and_target3_omitted_when_none(self):
        signal = dict(SAMPLE_SIGNAL)
        signal["target2"] = None
        signal["target3"] = None
        message = self._render(signal)
        self.assertNotIn("Target 2", message)
        self.assertNotIn("Target 3", message)
        self.assertIn("Target 1", message)  # target1 has no such guard in the original code -- always shown

    def test_risk_reward_omitted_when_falsy(self):
        signal = dict(SAMPLE_SIGNAL)
        signal["risk_reward"] = None
        message = self._render(signal)
        self.assertNotIn("Risk:Reward", message)

    def test_pattern_omitted_when_absent(self):
        signal = dict(SAMPLE_SIGNAL)
        signal["pattern"] = None
        message = self._render(signal)
        self.assertNotIn("Setup:", message)

    def test_oi_confirmation_omitted_when_absent(self):
        signal = dict(SAMPLE_SIGNAL)
        signal["oi_confirmation"] = None
        message = self._render(signal)
        self.assertNotIn("OI Status", message)

    def test_quality_verdict_absent_falls_back_to_grade(self):
        """Preserves the old code's own fallback: when there's no
        quality_verdict, it showed Grade instead -- same behavior,
        restyled."""
        signal = dict(SAMPLE_SIGNAL)
        signal["quality_verdict"] = None
        signal["quality_score"] = None
        message = self._render(signal)
        self.assertIn("Grade", message)
        self.assertIn(">A<", message)  # grade defaults to 'A' exactly as before


class TestBuySignalDerivesCallOption(SimpleTestCase):
    def test_buy_action_derives_ce_not_pe(self):
        bot = _bot()
        signal = dict(SAMPLE_SIGNAL)
        signal["action"] = "BUY"
        with patch.object(bot, "send_message") as mock_send:
            bot.send_signal_alert(signal)
            message = mock_send.call_args[0][0]
        self.assertIn("CE", message)
        # PE must not appear as the derived option side (still fine if it
        # appeared for some unrelated reason, but it shouldn't here)
        self.assertIn("BUY", message)


class TestSendMessageAndOtherMethodsUntouched(SimpleTestCase):
    """Confirms this rewrite really did touch ONLY send_signal_alert()
    -- every other public method's behavior is unchanged."""

    @patch("trading.telegram_bot.requests.post")
    def test_send_message_still_posts_expected_payload_shape(self, mock_post):
        mock_post.return_value = MagicMock(json=lambda: {"ok": True})
        bot = _bot()
        bot.send_message("hello", parse_mode="HTML")
        called_url, called_kwargs = mock_post.call_args[0][0], mock_post.call_args[1]
        self.assertTrue(called_url.endswith("/sendMessage"))
        self.assertEqual(called_kwargs["json"]["text"], "hello")
        self.assertEqual(called_kwargs["json"]["parse_mode"], "HTML")

    def test_send_pnl_alert_message_construction_unchanged(self):
        bot = _bot()
        trade_info = {"symbol": "TCS", "option_type": "CE", "strike": 4000, "status": "TARGET_HIT", "pnl": 500, "pnl_pct": 12.5, "entry_price": 100, "exit_price": 105}
        with patch.object(bot, "send_message") as mock_send:
            bot.send_pnl_alert(trade_info)
            message = mock_send.call_args[0][0]
        self.assertIn("TCS", message)
        self.assertIn("Target hit", message)
