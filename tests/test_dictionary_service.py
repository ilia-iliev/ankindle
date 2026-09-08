import pytest
import requests
import time
from unittest.mock import Mock, patch
from dictionary_service import DictionaryService
from errors import DictionaryServiceError, DictionaryUnavailableError


def make_response(status_code: int, payload=None, error: str | None = None) -> Mock:
    response = Mock()
    response.status_code = status_code
    if error is not None:
        response.raise_for_status.side_effect = requests.HTTPError(error)
    if payload is not None:
        response.json.return_value = payload
    return response


def entry(part_of_speech: str | None, *definitions: str) -> dict:
    meaning = {"definitions": [{"definition": d} for d in definitions]}
    if part_of_speech:
        meaning["partOfSpeech"] = part_of_speech
    return {"meanings": [meaning]}


def hello_response() -> Mock:
    return make_response(200, [entry("noun", "A greeting used when meeting someone")])


@pytest.fixture
def service():
    """A service whose retry backoff is instant, so tests do not wait on it."""
    service = DictionaryService()
    with patch("dictionary_service.time.sleep"):
        yield service


class TestDictionaryService:
    def test_init(self, service):
        assert service.session is not None

    def test_get_definition_success(self, service):
        with patch.object(service.session, "get", return_value=hello_response()):
            definition = service.get_definition("hello")

        assert definition == "(n) 1. A greeting used when meeting someone"

    def test_get_definition_word_not_found(self, service):
        with patch.object(service.session, "get", return_value=make_response(404)):
            assert service.get_definition("xyzabc123") is None

    def test_get_definition_empty_word(self, service):
        with pytest.raises(ValueError, match="Word cannot be empty"):
            service.get_definition("")

    def test_get_definition_none_word(self, service):
        with pytest.raises(ValueError, match="Word cannot be None"):
            service.get_definition(None)

    def test_get_definition_network_error(self, service):
        with patch.object(
            service.session,
            "get",
            side_effect=requests.RequestException("Network error"),
        ):
            with pytest.raises(
                DictionaryServiceError, match="Failed to fetch definition"
            ):
                service.get_definition("hello")

    def test_get_definition_invalid_response(self, service):
        response = make_response(500, error="Server error")

        with patch.object(service.session, "get", return_value=response):
            with pytest.raises(
                DictionaryServiceError, match="Failed to fetch definition"
            ):
                service.get_definition("hello")

    def test_get_definition_multiple_words(self, service):
        words = ["hello", "world", "test"]

        with patch.object(service.session, "get", return_value=hello_response()):
            definitions = service.get_definitions(words)

        assert len(definitions) == len(words)
        assert all(isinstance(d, str) for d in definitions)

    def test_get_definitions_keeps_position_of_failed_lookups(self, service):
        by_word = {
            "hello": hello_response(),
            "boom": make_response(500, error="Server error"),
            "missing": make_response(404),
        }

        def respond(url, **kwargs):
            return by_word[url.rsplit("/", 1)[1]]

        with patch.object(service.session, "get", side_effect=respond):
            definitions = service.get_definitions(["hello", "boom", "missing"])

        assert definitions[0] is not None
        assert definitions[1] is None
        assert definitions[2] is None

    def test_get_definition_special_characters(self, service):
        response = make_response(200, [entry("noun", "A small restaurant")])

        with patch.object(service.session, "get", return_value=response) as get:
            definition = service.get_definition("café")

        assert definition == "(n) 1. A small restaurant"
        assert get.call_args[0][0].endswith("caf%C3%A9")

    def test_get_definition_case_insensitive(self, service):
        with patch.object(service.session, "get", return_value=hello_response()) as get:
            service.get_definition("hello")
            service.get_definition("HELLO")

        assert get.call_args_list[0] == get.call_args_list[1]

    def test_word_cleaning_via_definition(self, service):
        with patch.object(service.session, "get", return_value=hello_response()) as get:
            service.get_definition("hello")
            service.get_definition("  HELLO  ")

        assert get.call_args_list[0] == get.call_args_list[1]

    def test_retry_logic_on_temporary_failure(self, service):
        failure = make_response(503, error="Service unavailable")
        success = make_response(200, [entry(None, "test definition")])

        with patch.object(
            service.session, "get", side_effect=[failure, failure, success]
        ) as get:
            definition = service.get_definition("test")

        assert definition == "1. test definition"
        assert get.call_count == 3

    def test_retry_logic_gives_up_after_max_retries(self, service):
        response = make_response(503, error="Service unavailable")

        with patch.object(service.session, "get", return_value=response) as get:
            with pytest.raises(
                DictionaryServiceError, match="Failed to fetch definition"
            ):
                service.get_definition("test")

            assert get.call_count == 4

    def test_retry_logic_does_not_retry_on_404(self, service):
        with patch.object(
            service.session, "get", return_value=make_response(404)
        ) as get:
            assert service.get_definition("nonexistentword") is None
            assert get.call_count == 1

    def test_retry_logic_does_not_retry_on_400(self, service):
        response = make_response(400, error="Bad request")

        with patch.object(service.session, "get", return_value=response) as get:
            with pytest.raises(DictionaryServiceError):
                service.get_definition("test")

            assert get.call_count == 4

    def test_extract_definition_with_word_category(self, service):
        response = make_response(200, [entry("verb", "To move swiftly on foot")])

        with patch.object(service.session, "get", return_value=response):
            assert service.get_definition("run") == "(v) 1. To move swiftly on foot"

    def test_extract_definition_with_multiple_definitions(self, service):
        response = make_response(
            200,
            [entry("noun", "Act of running", "A journey or trip", "A flow of liquid")],
        )

        with patch.object(service.session, "get", return_value=response):
            expected = (
                "(n) 1. Act of running\n"
                "(n) 2. A journey or trip\n"
                "(n) 3. A flow of liquid"
            )
            assert service.get_definition("run") == expected

    def test_extract_definition_with_multiple_parts_of_speech(self, service):
        response = make_response(
            200,
            [
                {
                    "meanings": [
                        entry("verb", "To move swiftly")["meanings"][0],
                        entry("noun", "Act of running")["meanings"][0],
                        entry("adjective", "In a liquid state")["meanings"][0],
                    ]
                }
            ],
        )

        with patch.object(service.session, "get", return_value=response):
            expected = (
                "(v) 1. To move swiftly\n"
                "(n) 2. Act of running\n"
                "(adj) 3. In a liquid state"
            )
            assert service.get_definition("run") == expected

    def test_extract_definition_removes_quotes(self, service):
        response = make_response(200, [entry("noun", '"A person who runs"')])

        with patch.object(service.session, "get", return_value=response):
            assert service.get_definition("runner") == "(n) 1. A person who runs"

    def test_extract_definition_with_complex_quotes(self, service):
        response = make_response(
            200, [entry("noun", '"Hello" means "greeting"', "A word without quotes")]
        )

        with patch.object(service.session, "get", return_value=response):
            expected = "(n) 1. Hello means greeting\n(n) 2. A word without quotes"
            assert service.get_definition("hello") == expected

    def test_extract_definition_handles_empty_definitions(self, service):
        response = make_response(200, [entry("noun")])

        with patch.object(service.session, "get", return_value=response):
            assert service.get_definition("test") is None

    def test_extract_definition_handles_missing_part_of_speech(self, service):
        response = make_response(200, [entry(None, "A test definition")])

        with patch.object(service.session, "get", return_value=response):
            assert service.get_definition("test") == "1. A test definition"

    def test_extract_definition_handles_malformed_response(self, service):
        response = make_response(200, [{"meanings": "not a list"}])

        with patch.object(service.session, "get", return_value=response):
            assert service.get_definition("test") is None


class TestRateLimiting:
    """The limiter sleeps for real, so these use a small window to stay quick."""

    def test_rate_limiting_delays_the_request_over_the_limit(self):
        service = DictionaryService(max_requests_per_second=2)

        with patch.object(service.session, "get", return_value=hello_response()):
            service.get_definition("first")
            service.get_definition("second")

            start = time.time()
            service.get_definition("third")
            elapsed = time.time() - start

        assert elapsed >= 0.5

    def test_rate_limiting_applies_to_bulk_operations(self):
        service = DictionaryService(max_requests_per_second=2)
        words = [f"word{i}" for i in range(4)]

        with patch.object(service.session, "get", return_value=hello_response()):
            start = time.time()
            definitions = service.get_definitions(words)
            elapsed = time.time() - start

        assert elapsed >= 0.5
        assert len(definitions) == 4


class TestServiceDownBreaker:
    """A dead API costs a full retry cycle per word; stop once it is clearly down."""

    def _service(self):
        return DictionaryService(max_consecutive_failures=2)

    def test_stops_calling_once_enough_words_fail_in_a_row(self):
        service = self._service()
        failure = make_response(503, error="Service unavailable")

        with patch("dictionary_service.time.sleep"):
            with patch.object(service.session, "get", return_value=failure) as get:
                with pytest.raises(DictionaryUnavailableError, match="not responding"):
                    service.get_definitions(["a", "b", "c", "d"])

        # two words retried in full, then nothing more was attempted
        assert get.call_count == 2 * (service.max_retries + 1)

    def test_a_success_resets_the_count(self):
        service = self._service()
        by_word = {
            "a": make_response(503, error="down"),
            "b": hello_response(),
            "c": make_response(503, error="down"),
            "d": hello_response(),
        }

        def respond(url, **kwargs):
            return by_word[url.rsplit("/", 1)[1]]

        with patch("dictionary_service.time.sleep"):
            with patch.object(service.session, "get", side_effect=respond):
                definitions = service.get_definitions(["a", "b", "c", "d"])

        assert [d is None for d in definitions] == [True, False, True, False]

    def test_words_not_found_do_not_trip_it(self):
        """A 404 is a real answer about the word, not a sign the service is down."""
        service = self._service()

        with patch.object(
            service.session, "get", return_value=make_response(404)
        ) as get:
            definitions = service.get_definitions(["a", "b", "c", "d"])

        assert definitions == [None, None, None, None]
        assert get.call_count == 4

    def test_a_long_backlog_gives_up_early_rather_than_grinding(self):
        service = self._service()
        failure = make_response(503, error="Service unavailable")

        with patch("dictionary_service.time.sleep"):
            with patch.object(service.session, "get", return_value=failure) as get:
                with pytest.raises(DictionaryUnavailableError):
                    service.get_definitions([f"w{i}" for i in range(2000)])

        assert get.call_count == 2 * (service.max_retries + 1)


@pytest.mark.live
class TestLiveDictionaryApi:
    """Hits api.dictionaryapi.dev. Deselected by default; run with -m live."""

    def test_known_word_comes_back_defined(self):
        definition = DictionaryService().get_definition("hello")

        assert definition is not None
        assert "greeting" in definition.lower()

    def test_unknown_word_comes_back_empty(self):
        assert DictionaryService().get_definition("xyzabc123") is None
