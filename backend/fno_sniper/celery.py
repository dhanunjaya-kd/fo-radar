from celery import Celery
import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fno_sniper.settings')

app = Celery('fno_sniper')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

# The live scanner in screener.views owns the production Fyers scan cadence.
# Do not schedule screener.tasks.scan_all_stocks() or update_market_overview()
# here as a second pipeline: doing so duplicates quote/history/option-chain
# traffic and can write competing Signal rows. The Celery task functions
# remain available for explicit/manual execution and for any future worker
# workflow; only their automatic Beat schedules are retired.
app.conf.beat_schedule = {
    'fetch-news-every-30-min': {
        'task': 'news.tasks.fetch_and_save_news',
        'schedule': 1800.0,  # 30 minutes
    },
}
