from claude_provider import ClaudeProvider

class ProviderError(Exception):
    pass


def get_provider(name='claude'):
    name = (name or 'claude').lower()
    if name == 'claude':
        return ClaudeProvider()
    raise ProviderError(f'Provider inconnu: {name}')
