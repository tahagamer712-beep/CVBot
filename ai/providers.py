"""AI providers for CV bot — same architecture as wallet bot.

- Keys come from DB (obfuscated), never from code.
- OpenRouter model is read live from settings ('openrouter_model') on every
  call so admin changes apply without restart.
"""
import httpx

TIMEOUT = 30.0


class BaseProvider:
    name = 'base'

    def __init__(self, api_key: str, client: httpx.AsyncClient = None):
        self.api_key = api_key
        self._injected_client = client

    async def _post(self, url: str, **kwargs) -> dict:
        if self._injected_client is not None:
            resp = await self._injected_client.post(url, **kwargs)
            resp.raise_for_status()
            return resp.json()
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(url, **kwargs)
            resp.raise_for_status()
            return resp.json()

    async def complete(self, system: str, user: str,
                       max_tokens: int = 600) -> str:
        raise NotImplementedError


class OpenRouterProvider(BaseProvider):
    """OpenRouter — free models (:free) via OpenAI-compatible API."""
    name = 'openrouter'
    DEFAULT_MODEL = 'cohere/north-mini-code:free'

    async def complete(self, system: str, user: str,
                       max_tokens: int = 600) -> str:
        import db
        model = db.get_setting('openrouter_model', self.DEFAULT_MODEL)
        url = 'https://openrouter.ai/api/v1/chat/completions'
        headers = {'Authorization': f'Bearer {self.api_key}'}
        body = {
            'model': model,
            'temperature': 0.4,
            'max_tokens': max_tokens,
            'messages': [
                {'role': 'system', 'content': system},
                {'role': 'user', 'content': user},
            ],
        }
        data = await self._post(url, headers=headers, json=body)
        return data['choices'][0]['message']['content'].strip()


async def fetch_openrouter_free_models(api_key: str = None,
                                       timeout: float = 20.0) -> list:
    """Live list of OpenRouter models filtered to free-only."""
    url = 'https://openrouter.ai/api/v1/models'
    headers = {'Authorization': f'Bearer {api_key}'} if api_key else {}
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    free_models = []
    for m in data.get('data', []):
        model_id = m.get('id', '')
        pricing = m.get('pricing', {}) or {}
        try:
            pp = float(pricing.get('prompt', '1') or '1')
            cp = float(pricing.get('completion', '1') or '1')
        except (TypeError, ValueError):
            pp = cp = 1.0
        is_free = (pp == 0 and cp == 0) or model_id.endswith(':free')
        if is_free and model_id:
            free_models.append({'id': model_id,
                                'name': m.get('name') or model_id})
    free_models.sort(key=lambda m: m['name'].lower())
    return free_models


PROVIDER_CLASSES = {
    'openrouter': OpenRouterProvider,
}
