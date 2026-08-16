"""Minimal Claude provider. The API key is read only from the environment."""
from __future__ import annotations
import json, os, urllib.request, urllib.error
from config import cfg

DEFAULT_URL = 'https://api.anthropic.com/v1/messages'
DEFAULT_MODEL = 'claude-sonnet-5'

class ClaudeError(RuntimeError):
    pass

class ClaudeProvider:
    name = 'claude'

    def _key(self):
        env_name = cfg('provider', 'claude', 'api_key_env', default='ANTHROPIC_API_KEY')
        key = os.getenv(env_name, '').strip()
        if not key:
            raise ClaudeError(f'{env_name} is not set')
        return key

    def _build_system(self, system):
        """Accepte soit une simple chaîne (comportement d'origine), soit un tuple
        (static_text, dynamic_text) pour activer le prompt caching Anthropic : la
        partie statique (identité + canon, inchangée d'un tour à l'autre) est marquée
        cache_control pour n'être facturée plein tarif qu'une fois par session, tant
        qu'elle ne change pas — la partie dynamique (relation/état/mémoires du tour)
        reste hors cache car elle change à chaque appel."""
        if isinstance(system, tuple):
            static_text, dynamic_text = system
            blocks = [{'type': 'text', 'text': static_text, 'cache_control': {'type': 'ephemeral'}}]
            if dynamic_text:
                blocks.append({'type': 'text', 'text': dynamic_text})
            return blocks
        return system or None

    def generate(self, system, user, max_tokens=1200):
        model = os.getenv('FYLGJA_CLAUDE_MODEL', cfg('provider', 'claude', 'model', default=DEFAULT_MODEL))
        url = os.getenv('FYLGJA_CLAUDE_URL', cfg('provider', 'claude', 'base_url', default=DEFAULT_URL))
        payload = {
            'model': model,
            'max_tokens': max_tokens,
            'system': self._build_system(system),
            'messages': [{'role': 'user', 'content': user}],
        }
        req = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode(), headers={
            'Content-Type': 'application/json',
            'x-api-key': self._key(),
            'anthropic-version': '2023-06-01',
            'anthropic-beta': 'prompt-caching-2024-07-31',
        }, method='POST')
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                data = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            detail = e.read().decode('utf-8', errors='replace')
            raise ClaudeError(f'Claude HTTP {e.code}: {detail[:800]}') from e
        except urllib.error.URLError as e:
            raise ClaudeError(f'Claude connection error: {e}') from e
        texts = [b.get('text', '') for b in data.get('content', []) if b.get('type') == 'text']
        if not texts:
            raise ClaudeError('Claude returned no text content')
        usage = data.get('usage', {})
        cache_read = usage.get('cache_read_input_tokens', 0)
        cache_write = usage.get('cache_creation_input_tokens', 0)
        if cache_read or cache_write:
            from logger import log
            log('CACHE', 'Prompt caching actif', read_tokens=cache_read, write_tokens=cache_write)
        return '\n'.join(texts).strip()
