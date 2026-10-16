"""Tests for backend reliability and security fixes."""
import threading
import time
from unittest.mock import MagicMock, patch

import pytest
import torch
from openai import APITimeoutError

from app import config, llm
from app.detector import Detector


def test_detector_loads_weights_only() -> None:
    """Ensure the detector model checkpoint loads safely with weights_only=True."""
    with patch("torch.load", wraps=torch.load) as mock_load:
        detector = Detector()
        assert detector.ae is not None
        assert detector.rul is not None
        mock_load.assert_called_once()
        _, kwargs = mock_load.call_args
        assert kwargs.get("weights_only") is True


def test_client_threading_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify client() uses thread locking to create a single shared OpenAI instance."""
    monkeypatch.setattr(config, "AMD_BASE_URL", "https://mock.amd.local/v1")
    monkeypatch.setattr(config, "AMD_API_KEY", "test-api-key")
    monkeypatch.setattr(config, "AMD_MODEL", "mock-model")
    monkeypatch.setattr(llm, "_client", None)

    with patch("app.llm.OpenAI") as mock_openai:
        mock_instance = MagicMock()
        mock_openai.return_value = mock_instance

        clients: list[object] = []
        threads = [
            threading.Thread(target=lambda: clients.append(llm.client()))
            for _ in range(20)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(clients) == 20
        assert all(c is mock_instance for c in clients)
        assert mock_openai.call_count == 1


def test_circuit_breaker_trips_and_fast_fails() -> None:
    """Verify complete() trips after CIRCUIT_MAX_FAILURES consecutive errors and fast-fails."""
    llm.reset_circuit()
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = APITimeoutError(request=None)

    meta = {
        "model": "",
        "calls": 0,
        "latency_s": 0.0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
    }
    messages = [{"role": "user", "content": "ping"}]

    with patch("app.llm.client", return_value=mock_client):
        # Trigger failures up to the limit
        for _ in range(llm.CIRCUIT_MAX_FAILURES):
            with pytest.raises(RuntimeError, match="All AMD Token Factory models are busy"):
                llm.complete(messages, meta.copy(), temperature=0.0, max_tokens=10)

        # Next call should fast-fail due to circuit open
        with pytest.raises(
            RuntimeError,
            match="AMD Token Factory circuit is OPEN due to repeated failures. Cooling down.",
        ):
            llm.complete(messages, meta.copy(), temperature=0.0, max_tokens=10)

        # Verify chat.completions.create was NOT called during the fast-fail call
        total_calls_before_fast_fail = mock_client.chat.completions.create.call_count
        with pytest.raises(RuntimeError, match="circuit is OPEN"):
            llm.complete(messages, meta.copy(), temperature=0.0, max_tokens=10)
        assert mock_client.chat.completions.create.call_count == total_calls_before_fast_fail

    llm.reset_circuit()


def test_reset_circuit_restores_operation() -> None:
    """Verify reset_circuit() clears failures and cooldown, restoring normal calls."""
    llm.reset_circuit()
    llm._circuit_failures = llm.CIRCUIT_MAX_FAILURES
    llm._circuit_open_until = time.monotonic() + 60.0

    meta = {
        "model": "",
        "calls": 0,
        "latency_s": 0.0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
    }
    messages = [{"role": "user", "content": "ping"}]

    # Confirm it's open
    with pytest.raises(RuntimeError, match="circuit is OPEN"):
        llm.complete(messages, meta.copy(), temperature=0.0, max_tokens=10)

    # Reset circuit
    llm.reset_circuit()
    assert llm._circuit_failures == 0
    assert llm._circuit_open_until == 0.0

    # Successful call should work and keep failures at 0
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content="pong"))]
    mock_resp.usage = None
    mock_client.chat.completions.create.return_value = mock_resp

    with patch("app.llm.client", return_value=mock_client):
        result = llm.complete(messages, meta.copy(), temperature=0.0, max_tokens=10)
        assert result == "pong"
        assert llm._circuit_failures == 0


def test_retriever_offline_loading() -> None:
    """Verify Retriever attempts local_files_only loading first for air-gapped readiness."""
    from app.retriever import Retriever

    with patch("sentence_transformers.SentenceTransformer") as mock_st:
        mock_st.return_value = MagicMock()
        r = Retriever()
        assert r is not None
        # Check that it tried local_files_only=True
        first_call_kwargs = mock_st.call_args_list[0][1]
        assert first_call_kwargs.get("local_files_only") is True
