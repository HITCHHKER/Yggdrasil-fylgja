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
        if isinstance(system, tuple):
            static_text, dynamic_text = system
            blocks = [{'type': 'text', 'text': static_text, 'cache_control': {'type': 'ephemeral', 'ttl': '1h'}}]
            if dynamic_text:
                blocks.append({'type': 'text', 'text': dynamic_text})
            return blocks
        return system or None
    def _effort(self, user_message=None, router_result=None):
        """router_result vient d'un appel UNIQUE à get_router().classify() fait en
        amont dans server.py : on ne reclassifie jamais ici, pour ne pas fausser
        les compteurs de calibration (sinon incrémentés deux fois par tour).
        LOW est traité comme MEDIUM côté effort réel : le cache Anthropic est
        indexé sur output_config.effort, donc changer d'effort à chaque tour
        casse le cache. Seul HIGH justifie de le casser."""
        default_effort = cfg('provider', 'claude', 'effort', default='medium')
        routing_enabled = cfg('routing', 'enabled', default=False)
        if routing_enabled and router_result:
            from logger import log
            log('ROUTER', router_result['level'], input_text=(user_message or '')[:60], reason=router_result['reason'])
            if router_result['level'] == 'HIGH':
                return 'high'
        return default_effort

    def _build_messages(self, user):
        """Accepte soit une simple chaine (comportement d'origine, un seul
        message utilisateur), soit une liste de dicts {role, content} deja
        prete (vraie conversation multi-tours). Normalise vers le format
        attendu par l'API Anthropic dans les deux cas."""
        if isinstance(user, list):
            return user
        return [{'role': 'user', 'content': user}]

    def _last_user_text(self, user):
        """Extrait le texte du dernier message utilisateur, pour le routage
        (_effort) qui a besoin d'une seule chaine a classifier, meme quand
        'user' est une liste de messages multi-tours."""
        if isinstance(user, list):
            for m in reversed(user):
                if m.get('role') == 'user':
                    return m.get('content', '')
            return ''
        return user

    def _supports_effort(self, model):
        """Haiku 4.5 ne supporte pas output_config.effort (reflexion adaptative
        reservee aux modeles Sonnet/Opus/Fable) -- l'envoyer declenche une
        erreur HTTP 400. On construit le payload conditionnellement selon
        le modele cible."""
        return 'haiku' not in (model or '').lower()
    def generate(self, system, user, max_tokens=1200, skip_routing=False, router_result=None, model=None):
        model = model or os.getenv('FYLGJA_CLAUDE_MODEL', cfg('provider', 'claude', 'model', default=DEFAULT_MODEL))
        url = os.getenv('FYLGJA_CLAUDE_URL', cfg('provider', 'claude', 'base_url', default=DEFAULT_URL))
        payload = {
            'model': model,
            'max_tokens': max_tokens,
            'system': self._build_system(system),
            'messages': self._build_messages(user),
        }
        if self._supports_effort(model):
            payload['output_config'] = {'effort': self._effort(None if skip_routing else self._last_user_text(user), router_result=router_result)}
        req = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode(), headers={
            'Content-Type': 'application/json',
            'x-api-key': self._key(),
            'anthropic-version': '2023-06-01',
            'anthropic-beta': 'extended-cache-ttl-2025-04-11',
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

    def generate_stream(self, system, user, max_tokens=1200, skip_routing=False, router_result=None, model=None):
        model = model or os.getenv('FYLGJA_CLAUDE_MODEL', cfg('provider', 'claude', 'model', default=DEFAULT_MODEL))
        url = os.getenv('FYLGJA_CLAUDE_URL', cfg('provider', 'claude', 'base_url', default=DEFAULT_URL))
        payload = {
            'model': model,
            'max_tokens': max_tokens,
            'system': self._build_system(system),
            'messages': self._build_messages(user),
            'stream': True,
        }
        if self._supports_effort(model):
            payload['output_config'] = {'effort': self._effort(None if skip_routing else self._last_user_text(user), router_result=router_result)}
        req = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode(), headers={
            'Content-Type': 'application/json',
            'x-api-key': self._key(),
            'anthropic-version': '2023-06-01',
            'anthropic-beta': 'extended-cache-ttl-2025-04-11',
        }, method='POST')
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                for raw_line in r:
                    line = raw_line.decode('utf-8', errors='replace').strip()
                    if not line.startswith('data:'):
                        continue
                    data_str = line[len('data:'):].strip()
                    if not data_str or data_str == '[DONE]':
                        continue
                    try:
                        event = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    if event.get('type') == 'message_start':
                        usage = event.get('message', {}).get('usage', {})
                        cache_read = usage.get('cache_read_input_tokens', 0)
                        cache_write = usage.get('cache_creation_input_tokens', 0)
                        if cache_read or cache_write:
                            from logger import log
                            log('CACHE', 'Prompt caching actif (stream)', read_tokens=cache_read, write_tokens=cache_write)
                    if event.get('type') == 'content_block_delta':
                        delta = event.get('delta', {})
                        if delta.get('type') == 'text_delta':
                            text = delta.get('text', '')
                            if text:
                                yield text
        except urllib.error.HTTPError as e:
            detail = e.read().decode('utf-8', errors='replace')
            raise ClaudeError(f'Claude HTTP {e.code}: {detail[:800]}') from e
        except urllib.error.URLError as e:
            raise ClaudeError(f'Claude connection error: {e}') from e