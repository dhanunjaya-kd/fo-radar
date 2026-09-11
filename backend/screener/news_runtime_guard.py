"""Reliability guards for the live news path.

feedparser's URL fetcher does not provide a per-call network timeout in the
way requests does, so a slow RSS host could hold a scanner/news worker much
longer than intended. This guard makes remote RSS fetches explicit HTTP
requests with connect/read timeouts, then lets feedparser parse the returned
bytes.

The existing news sender also marked a headline as sent even when Telegram
failed. The wrapper records those failed links and removes them from the
sent-set after the call, so the next polling cycle retries them instead of
silently losing the alert.
"""
import threading

_install_lock = threading.Lock()
_installed = False


def install():
    global _installed
    with _install_lock:
        if _installed:
            return

        from . import news
        import requests

        if news.FEEDPARSER_AVAILABLE:
            original_parse = news.feedparser.parse

            def timed_parse(source, *args, **kwargs):
                if isinstance(source, str) and source.lower().startswith(("http://", "https://")):
                    response = requests.get(
                        source,
                        timeout=(3.0, 7.0),
                        headers={"User-Agent": "FO-Radar/1.0 RSS reader"},
                    )
                    response.raise_for_status()
                    return original_parse(response.content, *args, **kwargs)
                return original_parse(source, *args, **kwargs)

            news.feedparser.parse = timed_parse

        original_send_news_alerts = news.send_new_news_alerts
        send_lock = threading.Lock()

        def guarded_send_news_alerts(*args, **kwargs):
            from trading.telegram_bot import TelegramBot

            failed_links = set()
            original_send_message = TelegramBot.send_message

            def monitored_send_message(self, message, parse_mode='HTML'):
                result = original_send_message(self, message, parse_mode=parse_mode)
                if not (isinstance(result, dict) and result.get('ok') is True):
                    lines = [line.strip() for line in str(message).splitlines() if line.strip()]
                    if lines:
                        candidate = lines[-1]
                        if candidate.startswith(('http://', 'https://')):
                            failed_links.add(candidate)
                return result

            # Serialize this temporary class-level hook so another thread
            # cannot observe the wrapper halfway through a news send.
            with send_lock:
                TelegramBot.send_message = monitored_send_message
                try:
                    result = original_send_news_alerts(*args, **kwargs)
                finally:
                    TelegramBot.send_message = original_send_message

            if failed_links:
                news._sent_links.difference_update(failed_links)
                print(f"[NewsGuard] {len(failed_links)} Telegram alert(s) failed; kept for retry")
            return result

        guarded_send_news_alerts.__name__ = original_send_news_alerts.__name__
        guarded_send_news_alerts.__doc__ = original_send_news_alerts.__doc__
        news.send_new_news_alerts = guarded_send_news_alerts
        _installed = True
