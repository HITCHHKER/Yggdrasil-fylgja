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
            blocks = [{'type': 'text', 'text': static_text, 'cache_control': {'type': 'ephemeral'}}]
            if dynamic_text:
                blocks.append({'type': 'text', 'text': dynamic_text})
            return blocks
        return system or None
    def _effort(self, user_message=None):
        """Sonnet 5 a la réflexion adaptative activée par défaut à effort 'high' —
        chaque requête déclenche un vrai bloc de raisonnement interne AVANT le
        premier mot visible, même en streaming. Pour du chat conversationnel,
        'medium' réduit fortement ce délai sans casser la cohérence de personnage.

        Si le routing académique est activé (config) et qu'un message est
        fourni, on utilise le classifieur V1 (academic_router.py) pour décider
        si 'low' est sûr, sinon on retombe sur le réglage fixe de config.json."""
        default_effort = cfg('provider', 'claude', 'effort', default='medium')
        routing_enabled = cfg('routing', 'enabled', default=False)
        if routing_enabled and user_message:
            try:
                import academic_router
                result = academic_router.classify(user_message)
                from logger import log
                log('ROUTER', f"{result['chosen_route']}", message=user_message[:60], reasons=result['reason_codes'])
                if result['safe_for_low']:
                    return 'low'
            except ImportError:
                pass
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

    def generate(self, system, user, max_tokens=1200, skip_routing=False):
        model = os.getenv('FYLGJA_CLAUDE_MODEL', cfg('provider', 'claude', 'model', default=DEFAULT_MODEL))
        url = os.getenv('FYLGJA_CLAUDE_URL', cfg('provider', 'claude', 'base_url', default=DEFAULT_URL))
        payload = {
            'model': model,
            'max_tokens': max_tokens,
            'system': self._build_system(system),
            'messages': self._build_messages(user),
            'output_config': {'effort': self._effort(None if skip_routing else self._last_user_text(user))},
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

    def generate_stream(self, system, user, max_tokens=1200, skip_routing=False):
        model = os.getenv('FYLGJA_CLAUDE_MODEL', cfg('provider', 'claude', 'model', default=DEFAULT_MODEL))
        url = os.getenv('FYLGJA_CLAUDE_URL', cfg('provider', 'claude', 'base_url', default=DEFAULT_URL))
        payload = {
            'model': model,
            'max_tokens': max_tokens,
            'system': self._build_system(system),
            'messages': self._build_messages(user),
            'output_config': {'effort': self._effort(None if skip_routing else self._last_user_text(user))},
            'stream': True,
        }
        req = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode(), headers={
            'Content-Type': 'application/json',
            'x-api-key': self._key(),
            'anthropic-version': '2023-06-01',
            'anthropic-beta': 'prompt-caching-2024-07-31',
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