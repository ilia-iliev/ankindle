from dataclasses import dataclass

import requests

from ankindle.config import Config
from ankindle.definition_curator import RESPONSE_SCHEMA
from ankindle.errors import DefinitionCurationError, DefinitionsUnavailableError

# Ollama's port, because it is the local server most people already have. Any
# OpenAI-compatible endpoint does: llama.cpp, LM Studio, vLLM, or a hosted one
# such as OpenAI, OpenRouter or Groq.
DEFAULT_URL = "http://localhost:11434/v1"

DEFAULT_BATCH_SIZE = 25
DEFAULT_MAX_TOKENS = 8000
DEFAULT_TIMEOUT = 300
DEFAULT_TEMPERATURE = 0.2
DEFAULT_JSON_MODE = "schema"

# How the JSON shape is asked for. Servers disagree about which of these they
# accept, so the strictest is tried first and the run steps down on refusal.
JSON_FORMATS = {
    "schema": {
        "type": "json_schema",
        "json_schema": {"name": "definitions", "schema": RESPONSE_SCHEMA},
    },
    "object": {"type": "json_object"},
    "none": None,
}
WEAKER_JSON_MODE = {"schema": "object", "object": "none"}

MISSING_KEY_MESSAGE = (
    "{url} rejected the request as unauthorized ({status}). Hosted providers "
    "need a key: set ANKINDLE_API_KEY in your environment and run this again."
)

NO_ENDPOINT_MESSAGE = (
    "Nothing answers at {url} ({status}). Most servers want the '/v1' suffix "
    "on the base URL - 'http://localhost:11434/v1', not 'http://localhost:11434'. "
    "Set it with --model-url."
)


def _as_bool(value) -> bool:
    """Config holds a real bool; the environment can only hand over a string."""
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class ModelSettings:
    """Which model answers, and how it is asked.

    Every field comes from the command line, else the environment, else what
    was remembered from an earlier run, else a default - so a setting is given
    once and never again.
    """

    url: str = DEFAULT_URL
    model: str | None = None
    api_key: str | None = None
    batch_size: int = DEFAULT_BATCH_SIZE
    max_tokens: int = DEFAULT_MAX_TOKENS
    timeout: int = DEFAULT_TIMEOUT
    temperature: float = DEFAULT_TEMPERATURE
    json_mode: str = DEFAULT_JSON_MODE
    disable_thinking: bool = False

    @classmethod
    def load(cls, config: Config, url: str | None = None, model: str | None = None):
        return cls(
            url=config.remember("model_url", url, DEFAULT_URL).rstrip("/"),
            model=config.remember("model", model, None),
            api_key=config.remember("api_key", None, None),
            batch_size=int(config.remember("batch_size", None, DEFAULT_BATCH_SIZE)),
            max_tokens=int(config.remember("max_tokens", None, DEFAULT_MAX_TOKENS)),
            timeout=int(config.remember("timeout", None, DEFAULT_TIMEOUT)),
            temperature=float(
                config.remember("temperature", None, DEFAULT_TEMPERATURE)
            ),
            json_mode=config.remember("json_mode", None, DEFAULT_JSON_MODE),
            disable_thinking=_as_bool(config.remember("disable_thinking", None, False)),
        )


class ChatModel:
    """Any OpenAI-compatible chat completions endpoint.

    The same request shape serves a local llama.cpp and a hosted OpenAI, so the
    only thing that tells them apart here is the URL and whether a key is sent.
    """

    def __init__(self, settings: ModelSettings):
        self.settings = settings
        self.json_mode = settings.json_mode

    def available_models(self) -> list[str]:
        """What the endpoint is serving, for the first-run question."""
        listing = self._checked(self._send("models")).json()
        return sorted(item["id"] for item in listing.get("data", []))

    def complete(self, prompt: str) -> str:
        response = self._send("chat/completions", self._body(prompt))
        while response.status_code == 400 and self._ask_for_json_more_simply():
            response = self._send("chat/completions", self._body(prompt))

        choice = self._checked(response).json()["choices"][0]
        if choice.get("finish_reason") == "length":
            raise DefinitionCurationError(
                f"The model stopped after {self.settings.max_tokens} tokens with "
                "the answer unfinished. Nothing was added. Raise max_tokens or "
                "lower batch_size in the config file, then run this again."
            )
        return choice["message"]["content"]

    def _body(self, prompt: str) -> dict:
        body = {
            "model": self.settings.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": self.settings.max_tokens,
            "temperature": self.settings.temperature,
        }

        # Deciding which senses of 'fell' matter is not a reasoning problem, and
        # a thinking model spends the whole budget on it and never reaches the
        # answer. Only vLLM and SGLang understand the switch, so it is sent only
        # when asked for; elsewhere turn thinking off on the server.
        if self.settings.disable_thinking:
            body["chat_template_kwargs"] = {"enable_thinking": False}

        response_format = JSON_FORMATS[self.json_mode]
        if response_format:
            body["response_format"] = response_format
        return body

    def _ask_for_json_more_simply(self) -> bool:
        """Step down to a format the server might accept, once per step.

        Left to write freely a model does eventually produce a broken string, so
        the schema is worth asking for - but half the servers in the wild reject
        one, and the prompt states the shape anyway.
        """
        weaker = WEAKER_JSON_MODE.get(self.json_mode)
        if weaker is None:
            return False

        print(
            f"\n  {self.settings.url} refused json_mode '{self.json_mode}'; "
            f"asking for '{weaker}' instead."
        )
        self.json_mode = weaker
        return True

    def _headers(self) -> dict:
        if not self.settings.api_key:
            return {}
        return {"Authorization": f"Bearer {self.settings.api_key}"}

    def _send(self, path: str, body: dict | None = None):
        try:
            return requests.request(
                "POST" if body else "GET",
                f"{self.settings.url}/{path}",
                json=body,
                headers=self._headers(),
                timeout=self.settings.timeout,
            )
        except requests.RequestException as error:
            raise DefinitionsUnavailableError(
                f"{self._unreachable_message()}\n\n({error})"
            ) from error

    def _checked(self, response):
        if response.ok:
            return response
        raise DefinitionsUnavailableError(self._failure_message(response))

    def _failure_message(self, response) -> str:
        if response.status_code in (401, 403):
            return MISSING_KEY_MESSAGE.format(
                url=self.settings.url, status=response.status_code
            )
        if response.status_code == 404:
            return NO_ENDPOINT_MESSAGE.format(
                url=self.settings.url, status=response.status_code
            )
        return (
            f"{self.settings.url} answered {response.status_code}: "
            f"{response.text[:400]}"
        )

    def _unreachable_message(self) -> str:
        return (
            f"The model at {self.settings.url} is not answering, so every "
            "remaining word would come back blank. Nothing was added and the "
            "last-run marker was left alone - run this again once it is back."
        )
