import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest
import requests
from ankindle import model as model_module
from ankindle.config import Config
from ankindle.errors import DefinitionCurationError, DefinitionsUnavailableError
from ankindle.model import (
    DEFAULT_URL,
    ChatModel,
    ModelSettings,
)


@pytest.fixture
def config():
    with tempfile.TemporaryDirectory() as directory:
        yield Config(os.path.join(directory, "config.json"))


@pytest.fixture
def no_environment():
    """Settings must not be read off the developer's own shell."""
    leftovers = {k: v for k, v in os.environ.items() if k.startswith("ANKINDLE_")}
    for key in leftovers:
        del os.environ[key]
    yield
    os.environ.update(leftovers)


def answer(content: str = '{"items": []}', status: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.ok = 200 <= status < 300
    response.json.return_value = {
        "choices": [{"finish_reason": "stop", "message": {"content": content}}]
    }
    return response


class TestSettingsResolution:
    def test_defaults_when_nothing_is_configured(self, config, no_environment):
        settings = ModelSettings.load(config)

        assert settings.url == DEFAULT_URL
        assert settings.model is None
        assert settings.api_key is None

    def test_the_command_line_wins_and_is_remembered(self, config, no_environment):
        ModelSettings.load(config, url="http://box:8081/v1", model="a-model")

        assert ModelSettings.load(config).model == "a-model"
        assert ModelSettings.load(config).url == "http://box:8081/v1"

    def test_the_environment_beats_the_config_file(self, config, no_environment):
        ModelSettings.load(config, model="remembered")

        with patch.dict(os.environ, {"ANKINDLE_MODEL": "from-the-shell"}):
            assert ModelSettings.load(config).model == "from-the-shell"

        assert ModelSettings.load(config).model == "remembered"

    def test_the_environment_is_not_written_to_the_config_file(
        self, config, no_environment
    ):
        with patch.dict(os.environ, {"ANKINDLE_MODEL": "from-the-shell"}):
            ModelSettings.load(config)

        assert config.get("model") is None

    def test_numbers_and_flags_survive_the_environment(self, config, no_environment):
        environment = {
            "ANKINDLE_BATCH_SIZE": "5",
            "ANKINDLE_TEMPERATURE": "0.7",
            "ANKINDLE_DISABLE_THINKING": "true",
        }
        with patch.dict(os.environ, environment):
            settings = ModelSettings.load(config)

        assert settings.batch_size == 5
        assert settings.temperature == 0.7
        assert settings.disable_thinking is True

    def test_a_trailing_slash_does_not_double_up(self, config, no_environment):
        settings = ModelSettings.load(config, url="http://box:8081/v1/")

        assert settings.url == "http://box:8081/v1"


class TestRequestShape:
    def _sent(self, settings: ModelSettings) -> dict:
        with patch.object(model_module.requests, "request") as request:
            request.return_value = answer()
            ChatModel(settings).complete("a prompt")
        return request.call_args

    def test_the_model_and_prompt_are_sent(self):
        sent = self._sent(ModelSettings(model="a-model"))

        assert sent.kwargs["json"]["model"] == "a-model"
        assert sent.kwargs["json"]["messages"] == [
            {"role": "user", "content": "a prompt"}
        ]

    def test_no_key_means_no_authorization_header(self):
        assert "Authorization" not in self._sent(ModelSettings()).kwargs["headers"]

    def test_a_key_is_sent_as_a_bearer_token(self):
        sent = self._sent(ModelSettings(api_key="sk-test"))

        assert sent.kwargs["headers"]["Authorization"] == "Bearer sk-test"

    def test_the_thinking_switch_is_only_sent_when_asked_for(self):
        assert "chat_template_kwargs" not in self._sent(ModelSettings()).kwargs["json"]

        body = self._sent(ModelSettings(disable_thinking=True)).kwargs["json"]
        assert body["chat_template_kwargs"] == {"enable_thinking": False}

    def test_the_schema_is_asked_for_by_default(self):
        body = self._sent(ModelSettings()).kwargs["json"]

        assert body["response_format"]["type"] == "json_schema"

    def test_a_server_that_wants_no_response_format_is_sent_none(self):
        body = self._sent(ModelSettings(json_mode="none")).kwargs["json"]

        assert "response_format" not in body


class TestJsonModeFallback:
    """Half the OpenAI-compatible servers reject a schema. That is not fatal."""

    def test_a_refused_schema_steps_down_to_json_object(self):
        refusal = answer(status=400)

        with patch.object(model_module.requests, "request") as request:
            request.side_effect = [refusal, answer()]
            ChatModel(ModelSettings()).complete("a prompt")

        first, second = [call.kwargs["json"] for call in request.call_args_list]
        assert first["response_format"]["type"] == "json_schema"
        assert second["response_format"] == {"type": "json_object"}

    def test_a_server_that_refuses_both_is_asked_without_a_format(self):
        refusal = answer(status=400)

        with patch.object(model_module.requests, "request") as request:
            request.side_effect = [refusal, refusal, answer()]
            ChatModel(ModelSettings()).complete("a prompt")

        assert "response_format" not in request.call_args_list[2].kwargs["json"]

    def test_the_step_down_is_remembered_for_the_rest_of_the_run(self):
        with patch.object(model_module.requests, "request") as request:
            request.side_effect = [answer(status=400), answer(), answer()]
            chat = ChatModel(ModelSettings())
            chat.complete("a prompt")
            chat.complete("another prompt")

        last = request.call_args_list[2].kwargs["json"]
        assert last["response_format"] == {"type": "json_object"}

    def test_a_refusal_that_outlives_every_format_is_reported(self):
        with patch.object(model_module.requests, "request") as request:
            request.return_value = answer(status=400)
            request.return_value.text = "bad request"

            with pytest.raises(DefinitionsUnavailableError, match="400"):
                ChatModel(ModelSettings()).complete("a prompt")


class TestFailuresAreExplained:
    def _failure(self, status: int) -> str:
        with patch.object(model_module.requests, "request") as request:
            request.return_value = answer(status=status)
            request.return_value.text = "denied"

            with pytest.raises(DefinitionsUnavailableError) as raised:
                ChatModel(ModelSettings()).complete("a prompt")
        return str(raised.value)

    def test_an_unauthorized_endpoint_names_the_key_to_set(self):
        assert "ANKINDLE_API_KEY" in self._failure(401)

    def test_a_missing_endpoint_suggests_the_v1_suffix(self):
        assert "/v1" in self._failure(404)

    def test_an_unreachable_server_is_explained_rather_than_raised_raw(self):
        with (
            patch.object(
                model_module.requests,
                "request",
                side_effect=requests.ConnectionError("connection refused"),
            ),
            pytest.raises(DefinitionsUnavailableError, match="not answering"),
        ):
            ChatModel(ModelSettings()).complete("a prompt")

    def test_an_answer_cut_off_by_the_token_limit_is_not_a_blank_card(self):
        cut_off = answer()
        cut_off.json.return_value = {
            "choices": [{"finish_reason": "length", "message": {"content": None}}]
        }

        with (
            patch.object(model_module.requests, "request", return_value=cut_off),
            pytest.raises(DefinitionCurationError, match="unfinished"),
        ):
            ChatModel(ModelSettings()).complete("a prompt")


class TestAvailableModels:
    def test_the_listing_is_read_off_the_server(self):
        listing = answer()
        listing.json.return_value = {
            "data": [{"id": "qwen3:32b"}, {"id": "gemma3:27b"}]
        }

        with patch.object(model_module.requests, "request") as request:
            request.return_value = listing
            names = ChatModel(ModelSettings()).available_models()

        assert names == ["gemma3:27b", "qwen3:32b"]
        assert request.call_args.args[0] == "GET"

    def test_a_server_that_lists_nothing_is_not_an_error(self):
        listing = answer()
        listing.json.return_value = {}

        with patch.object(model_module.requests, "request", return_value=listing):
            assert ChatModel(ModelSettings()).available_models() == []


def test_the_answer_is_taken_from_the_chat_completion():
    content = json.dumps({"items": []})

    with patch.object(model_module.requests, "request", return_value=answer(content)):
        assert ChatModel(ModelSettings()).complete("a prompt") == content
