"""
Generates the weekly report and sends it via Telegram. Meant to be run
from Windows Task Scheduler on Friday afternoon (after CAS settles and
derivatives trading ends ~3:40 PM -- schedule this for 4:00 PM or later
so the day's data is actually complete first).

Run manually any time with:
    python manage.py generate_weekly_report

Doesn't need the Django dev server or Celery running -- it's a
standalone read of the Excel files already on disk.
"""
import os
from django.core.management.base import BaseCommand
from screener.weekly_report import generate_weekly_report


class Command(BaseCommand):
    help = "Generate the weekly signals + index report and send it via Telegram"

    def handle(self, *args, **options):
        path = generate_weekly_report()

        if not path:
            self.stderr.write(self.style.ERROR(
                "Report generation failed (openpyxl not available)."
            ))
            return

        self.stdout.write(self.style.SUCCESS(f"Report saved: {path}"))

        try:
            from trading.telegram_bot import TelegramBot
            bot = TelegramBot()
            result = bot.send_document(
                path,
                caption=f"📊 <b>F&O Radar — Weekly Report</b>\n{os.path.basename(path)}"
            )
            if result and result.get("ok"):
                self.stdout.write(self.style.SUCCESS("Sent to Telegram."))
            else:
                self.stdout.write(self.style.WARNING(
                    f"Report saved but Telegram send didn't confirm success: {result}"
                ))
        except Exception as e:
            self.stdout.write(self.style.WARNING(
                f"Report saved but Telegram send failed: {e}"
            ))
