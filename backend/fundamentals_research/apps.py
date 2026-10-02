from django.apps import AppConfig
from django.db.backends.signals import connection_created


def _tune_sqlite(sender, connection, **kwargs):
    """WAL = readers don't block the writer (and vice versa); busy_timeout = wait for a lock instead of
    failing instantly. Fixes the "database is locked" errors seen when research writes overlapped other
    requests. No-op on Postgres etc."""
    if connection.vendor != 'sqlite':
        return
    cur = connection.cursor()
    cur.execute('PRAGMA journal_mode=WAL;')
    cur.execute('PRAGMA synchronous=NORMAL;')
    cur.execute('PRAGMA busy_timeout=30000;')


class FundamentalsResearchConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'fundamentals_research'
    verbose_name = 'Fundamental Research'

    def ready(self):
        connection_created.connect(_tune_sqlite, dispatch_uid='fo_radar_sqlite_tuning')
