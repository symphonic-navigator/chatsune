"""Tests for embedding model manager.

These tests use a tiny mock to avoid downloading the real 600MB model.
They verify the inference pipeline (tokenise → run → pool → normalise)
works correctly when an ONNX session is available.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from backend.modules.embedding._model import EmbeddingModel


@pytest.fixture
def mock_session():
    """Create a mock ONNX session that returns fake hidden states."""
    session = MagicMock()
    def mock_run(output_names, input_feed):
        batch_size = input_feed["input_ids"].shape[0]
        seq_len = input_feed["input_ids"].shape[1]
        hidden = np.random.randn(batch_size, seq_len, 768).astype(np.float32)
        return [hidden]
    session.run = mock_run
    return session


@pytest.fixture
def mock_tokenizer():
    """Create a mock tokenizer that returns numpy arrays."""
    tokenizer = MagicMock()
    def mock_call(texts, padding, truncation, max_length, return_tensors):
        batch_size = len(texts)
        seq_len = 16
        return {
            "input_ids": np.ones((batch_size, seq_len), dtype=np.int64),
            "attention_mask": np.ones((batch_size, seq_len), dtype=np.int64),
        }
    tokenizer.side_effect = mock_call
    tokenizer.return_value = mock_call(["test"], True, True, 8192, "np")
    tokenizer.__call__ = mock_call
    return tokenizer


def test_infer_returns_correct_shape(mock_session, mock_tokenizer):
    model = EmbeddingModel.__new__(EmbeddingModel)
    model._session = mock_session
    model._tokenizer = mock_tokenizer
    model._dimensions = 768

    vectors = model.infer(["hello", "world"])

    assert len(vectors) == 2
    assert len(vectors[0]) == 768
    assert len(vectors[1]) == 768


def test_infer_vectors_are_l2_normalised(mock_session, mock_tokenizer):
    model = EmbeddingModel.__new__(EmbeddingModel)
    model._session = mock_session
    model._tokenizer = mock_tokenizer
    model._dimensions = 768

    vectors = model.infer(["test sentence"])

    vec = np.array(vectors[0])
    norm = np.linalg.norm(vec)
    assert abs(norm - 1.0) < 1e-5, f"Expected unit norm, got {norm}"


def test_infer_single_text(mock_session, mock_tokenizer):
    model = EmbeddingModel.__new__(EmbeddingModel)
    model._session = mock_session
    model._tokenizer = mock_tokenizer
    model._dimensions = 768

    vectors = model.infer(["single"])

    assert len(vectors) == 1
    assert len(vectors[0]) == 768
