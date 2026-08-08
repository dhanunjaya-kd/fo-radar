"""
Django settings for F&O Sniper Scanner v3.0
"""
import os
from pathlib import Path
import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(DEBUG=(bool, True))
environ.Env.read_env(str(BASE_DIR / '.env'))

SECRET_KEY = env.str('SECRET_KEY', default='django-insecure-change-me-in-production-123456789')
DEBUG = env.bool('DEBUG', default=True)
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['*'])

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'corsheaders',
    'channels',
    'screener',
    'options',
    'news',
    'trading',
    'backtest',
    'fyers_api',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'fno_sniper.urls'
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'fno_sniper.wsgi.application'
ASGI_APPLICATION = 'fno_sniper.asgi.application'

REDIS_URL = env.str('REDIS_URL', default='redis://127.0.0.1:6379/0')

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {'hosts': [REDIS_URL]},
    },
}

CELERY_BROKER_URL = env.str('CELERY_BROKER_URL', default=REDIS_URL)
CELERY_RESULT_BACKEND = env.str('CELERY_RESULT_BACKEND', default=REDIS_URL)
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'Asia/Kolkata'

DATABASES = {
    'default': env.db('DATABASE_URL', default=f'sqlite:///{BASE_DIR / "db.sqlite3"}')
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Kolkata'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

CORS_ALLOW_ALL_ORIGINS = True

REST_FRAMEWORK = {
    'DEFAULT_RENDERER_CLASSES': ['rest_framework.renderers.JSONRenderer'],
}

# NOTE: the .env file in this project defines the secret as FYERS_SECRET_KEY.
# This used to look up FYERS_APP_SECRET / FYERS_SECRET_ID only, neither of
# which exist in .env, so it silently fell through to a hardcoded stale
# default ('ROTJ53EW72') on every run -- the real secret from .env was never
# actually read. Same story for FYERS_APP_ID: it used to default to
# '6OWXIMCOXF-100', an old app id that doesn't match the Fyers app actually
# connected (LYNP1Z6GGG-100). Both defaults are removed below: if .env is
# missing a value now, you get a loud KeyError at startup instead of a
# silent wrong credential.
FYERS_APP_ID = env.str('FYERS_APP_ID', default='LYNP1Z6GGG-100')
FYERS_APP_SECRET = env.str('FYERS_APP_SECRET', default=env.str('FYERS_SECRET_ID', default=env.str('FYERS_SECRET_KEY', default=None)))
FYERS_REDIRECT_URI = env.str('FYERS_REDIRECT_URI', default=env.str('FYERS_REDIRECT_URL', default='http://127.0.0.1:5000'))

TELEGRAM_BOT_TOKEN = env.str('TELEGRAM_BOT_TOKEN', default='')
TELEGRAM_CHAT_ID = env.str('TELEGRAM_CHAT_ID', default='')
NEWSAPI_KEY = env.str('NEWSAPI_KEY', default='')
PAPER_TRADING_ENABLED = env.bool('PAPER_TRADING_ENABLED', default=True)
BACKTEST_MASTER_PATH = env.str('BACKTEST_MASTER_PATH', default='')
