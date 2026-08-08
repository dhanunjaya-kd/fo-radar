from celery import Celery
import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fno_sniper.settings')

app = Celery('fno_sniper')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

app.conf.beat_schedule = {
    'scan-stocks-every-5-min': {
        'task': 'screener.tasks.scan_all_stocks',
        'schedule': 300.0,  # 5 minutes
    },
    'update-market-overview': {
        'task': 'screener.tasks.update_market_overview',
        'schedule': 300.0,
    },
    'fetch-news-every-30-min': {
        'task': 'news.tasks.fetch_and_save_news',
        'schedule': 1800.0,  # 30 minutes
    },
}
