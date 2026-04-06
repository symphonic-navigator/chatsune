"""ONNX embedding model — download, load, and inference.

Manages the full lifecycle of the Snowflake Arctic Embed M v2.0 model:
download from HuggingFace if missing, load ONNX session, tokenise,
infer, mean-pool, and L2-normalise.
"""

import logging
from pathlib import Path

import numpy as np
import onnxruntime as ort
from huggingface_hub import snapshot_download
from transformers import AutoTokenizer

_log = logging.getLogger("chatsune.embedding.model")

_HF_REPO_ID = "Snowflake/snowflake-arctic-embed-m-v2.0"
_MODEL_SUBDIR = "snowflake-arctic-embed-m-v2.0"
_DIMENSIONS = 768
_MAX_TOKENS = 8192


class EmbeddingModel:
    """Manages ONNX model loading and inference."""

    def __init__(self) -> None:
        self._session: ort.InferenceSession | None = None
        self._tokenizer = None
        self._dimensions: int = _DIMENSIONS

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @property
    def is_loaded(self) -> bool:
        return self._session is not None

    @property
    def model_name(self) -> str:
        return _MODEL_SUBDIR

    def load(self, model_dir: str) -> None:
        """Download (if needed) and load the ONNX model. Blocking."""
        model_path = Path(model_dir) / _MODEL_SUBDIR

        if not (model_path / "onnx" / "model.onnx").exists():
            _log.info("Model not found at %s — downloading from HuggingFace", model_path)
            self._download(model_dir)
        else:
            _log.info("Model found at %s", model_path)

        onnx_path = str(model_path / "onnx" / "model.onnx")
        _log.info("Loading ONNX session from %s", onnx_path)

        sess_opts = ort.SessionOptions()
        sess_opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        sess_opts.inter_op_num_threads = 2
        sess_opts.intra_op_num_threads = 2

        self._session = ort.InferenceSession(
            onnx_path,
            sess_options=sess_opts,
            providers=["CPUExecutionProvider"],
        )

        self._tokenizer = AutoTokenizer.from_pretrained(str(model_path))
        _log.info("Model loaded — dimensions=%d, max_tokens=%d", _DIMENSIONS, _MAX_TOKENS)

    def _download(self, model_dir: str) -> None:
        """Download model from HuggingFace with per-file progress logging."""
        from huggingface_hub import HfApi, hf_hub_download

        target = Path(model_dir) / _MODEL_SUBDIR
        target.mkdir(parents=True, exist_ok=True)

        api = HfApi()
        repo_info = api.repo_info(repo_id=_HF_REPO_ID)
        siblings = repo_info.siblings or []
        files = [s.rfilename for s in siblings]
        total_size = sum(s.size for s in siblings if s.size)

        _log.info(
            "Downloading %s (%d files, %.1f MB) to %s",
            _HF_REPO_ID, len(files), total_size / (1024 * 1024), target,
        )

        downloaded_size = 0
        last_logged_pct = 0

        for sibling in siblings:
            hf_hub_download(
                repo_id=_HF_REPO_ID,
                filename=sibling.rfilename,
                local_dir=str(target),
                local_dir_use_symlinks=False,
            )
            if sibling.size:
                downloaded_size += sibling.size
            if total_size > 0:
                pct = int(downloaded_size / total_size * 100)
                if pct >= last_logged_pct + 10:
                    last_logged_pct = pct - (pct % 10)
                    _log.info("Download progress: %d%%", last_logged_pct)

        _log.info("Download complete")

    def infer(self, texts: list[str]) -> list[list[float]]:
        """Tokenise, run ONNX inference, L2-normalise.

        Uses the model's built-in sentence_embedding output (already pooled).
        Returns a list of 768-dimensional unit vectors.
        """
        encoded = self._tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=_MAX_TOKENS,
            return_tensors="np",
        )

        input_ids = encoded["input_ids"]
        attention_mask = encoded["attention_mask"]

        outputs = self._session.run(
            ["sentence_embedding"],
            {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
            },
        )

        embeddings = outputs[0]  # (batch, hidden_dim) — already pooled

        # L2 normalisation
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms = np.clip(norms, a_min=1e-9, a_max=None)
        normalised = embeddings / norms

        return normalised.tolist()
