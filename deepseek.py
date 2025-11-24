import os, requests
from flask import current_app


class DeepSeekLLM:
    """
    Classe Wrapper para usar a função chat do DeepSeek em contextos como LangChain.
    """

    def __init__(self, model: str = "deepseek-chat", temperature: float = 0.7):
        self.model = model
        self.temperature = temperature

    def invoke(self, prompt) -> str:  # ATENÇÃO: Remova o type hint 'str' do argumento
        """
        Adapta a chamada de string única do LangChain para o formato de mensagens da API.
        """
        if hasattr(prompt, 'to_string'):
            prompt_str = prompt.to_string()
        else:
            prompt_str = str(prompt)

        messages = [{"role": "user", "content": prompt_str}]

        return chat(
            messages=messages,
            model=self.model,
            temperature=self.temperature
        )

    # Opcional: Para compatibilidade com outras interfaces LLM
    def __call__(self, prompt: str) -> str:
        return self.invoke(prompt)

class DeepSeekError(Exception):
    """Erro sanitizado para consumo pelo app."""
    def __init__(self, public_msg: str, http_status: int | None = None, detail: str | None = None):
        super().__init__(public_msg)
        self.public_msg = public_msg
        self.http_status = http_status
        self.detail = detail

def _cfg(key, default=None):
    return (current_app.config.get(key) if current_app else None) or os.getenv(key, default)

def chat(messages: list, model: str = "deepseek-chat", temperature: float = 0.3, timeout: int | None = None) -> str:
    api_key  = _cfg('DEEPSEEK_API_KEY')
    endpoint = _cfg('DEEPSEEK_ENDPOINT', 'https://api.deepseek.com/v1/chat/completions')  # <- /v1
    if not api_key:
        raise DeepSeekError("Serviço de IA não configurado.", detail="DEEPSEEK_API_KEY ausente")

    req_timeout = timeout or int(_cfg('AI_TIMEOUT_SECONDS', 90))     # antes era 30s
    max_tokens  = int(_cfg('AI_MAX_TOKENS', 8000))                   # limite p/ resposta

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens
    }

    try:
        resp = requests.post(endpoint, json=payload, headers=headers, timeout=(10, req_timeout))
    except requests.RequestException as e:
        raise DeepSeekError("Falha de conexão com o serviço de IA. Tente novamente mais tarde.", detail=str(e))

    if resp.status_code == 401:
        raise DeepSeekError("Serviço de IA indisponível no momento.", http_status=401, detail="401 Unauthorized")
    if resp.status_code == 402:
        raise DeepSeekError("Serviço de IA temporariamente indisponível.", http_status=402, detail="402 Payment Required")
    if resp.status_code == 403:
        raise DeepSeekError("Serviço de IA indisponível no momento.", http_status=403, detail="403 Forbidden")
    if resp.status_code >= 400:
        try:
            info = resp.json()
        except Exception:
            info = resp.text
        raise DeepSeekError("Serviço de IA indisponível no momento.", http_status=resp.status_code, detail=str(info))

    try:
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        raise DeepSeekError("Resposta inválida do serviço de IA.", detail=str(e))