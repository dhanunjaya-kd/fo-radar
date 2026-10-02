"""List the models each configured AI provider currently offers (reads backend/.env; never prints keys).

    python list_llm_models.py            # every provider that has a key
    python list_llm_models.py groq       # just one

Model names get retired (e.g. Groq's llama-3.3-70b-versatile was deprecated) -- run this and put a current id
in .env as GROQ_MODEL / OPENROUTER_MODEL / GEMINI_MODEL / LLM_MODEL.
"""
import os
import sys
from pathlib import Path

import requests

env_file = Path(__file__).resolve().parent / '.env'
if env_file.exists():
    for line in env_file.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.split('#')[0].strip().strip('"\''))

ENDPOINTS = {
    'groq': ('GROQ_API_KEY', 'https://api.groq.com/openai/v1/models', 'bearer'),
    'openrouter': ('OPENROUTER_API_KEY', 'https://openrouter.ai/api/v1/models', 'bearer'),
    'gemini': ('GEMINI_API_KEY', 'https://generativelanguage.googleapis.com/v1beta/models', 'google'),
    'anthropic': ('ANTHROPIC_API_KEY', 'https://api.anthropic.com/v1/models', 'anthropic'),
}


def show(name):
    key_env, url, style = ENDPOINTS[name]
    key = (os.environ.get(key_env) or '').strip()
    if not key:
        print(f'[{name}] {key_env} not set -- skipped')
        return
    headers = {'Authorization': f'Bearer {key}'} if style == 'bearer' else \
              {'x-goog-api-key': key} if style == 'google' else {'x-api-key': key, 'anthropic-version': '2023-06-01'}
    try:
        r = requests.get(url, headers=headers, timeout=20)
    except requests.RequestException as e:
        print(f'[{name}] request failed: {e}')
        return
    if r.status_code != 200:
        print(f'[{name}] HTTP {r.status_code}: {r.text[:200]}')
        return
    data = r.json()
    items = data.get('data') or data.get('models') or []
    ids = sorted((m.get('id') or m.get('name') or '').replace('models/', '') for m in items)
    if name == 'openrouter':
        ids = [i for i in ids if i.endswith(':free')] or ids
        print(f'[{name}] free models:')
    else:
        print(f'[{name}] models:')
    for i in ids:
        print('   ', i)


if __name__ == '__main__':
    for n in (sys.argv[1:] or list(ENDPOINTS)):
        if n in ENDPOINTS:
            show(n)
        else:
            print(f'unknown provider {n}; choose from {", ".join(ENDPOINTS)}')
