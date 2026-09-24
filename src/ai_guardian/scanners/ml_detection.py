"""
ML-based prompt injection detection using ONNX Runtime.

Provides multi-engine ML detection that runs inside the daemon process.
Models are loaded once and kept in memory for fast inference (~10-50ms).
Hook-mode invocations query the daemon via socket/REST.

Requires onnxruntime and tokenizers (main dependencies).
"""

import hashlib
import json
import logging
import os
import re
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

MODEL_REGISTRY = {
    "protectai/deberta-v3-base-prompt-injection-v2": {
        "hf_repo": "protectai/deberta-v3-base-prompt-injection-v2",
        "files": {
            "model.onnx": {
                "hf_filename": "onnx/model.onnx",
            },
            "tokenizer.json": {
                "hf_filename": "tokenizer.json",
            },
        },
        "max_length": 512,
        "labels": {0: "SAFE", 1: "INJECTION"},
        "description": "DeBERTa v3 base fine-tuned for prompt injection detection",
    },
}

DEFAULT_MODEL = "protectai/deberta-v3-base-prompt-injection-v2"

_HF_BASE_URL = "https://huggingface.co"


def is_ml_available():
    """Check if ML dependencies (onnxruntime) are available.

    tokenizers and onnxruntime are installed as main dependencies.
    """
    try:
        import onnxruntime  # noqa: F401
        import tokenizers  # noqa: F401

        return True
    except ImportError:
        return False


def get_models_dir():
    """Return cache directory for ML models.

    Uses get_cache_dir() / 'models'. Creates directory if needed.
    """
    from ai_guardian.config.utils import get_cache_dir

    models_dir = get_cache_dir() / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    return models_dir


def _model_slug(model_name):
    """Convert model name to filesystem-safe slug."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", model_name)


def _model_dir(model_name):
    """Get directory for a specific model."""
    return get_models_dir() / _model_slug(model_name)


def list_registered_models():
    """List all models in the registry with download status."""
    results = []
    for name, info in MODEL_REGISTRY.items():
        model_path = _model_dir(name)
        downloaded = model_path.exists() and all(
            (model_path / fname).exists() for fname in info["files"]
        )
        results.append(
            {
                "name": name,
                "description": info.get("description", ""),
                "downloaded": downloaded,
                "path": str(model_path) if downloaded else None,
            }
        )
    return results


def download_model(model_name=DEFAULT_MODEL, force=False):
    """Download ONNX model and tokenizer from HuggingFace Hub.

    Args:
        model_name: Name from MODEL_REGISTRY
        force: Re-download even if already present

    Returns:
        Path to model directory

    Raises:
        ValueError: If model not in registry
        RuntimeError: If download fails
    """
    if model_name not in MODEL_REGISTRY:
        raise ValueError(
            f"Unknown model '{model_name}'. "
            f"Available: {', '.join(MODEL_REGISTRY.keys())}"
        )

    info = MODEL_REGISTRY[model_name]
    dest = _model_dir(model_name)
    dest.mkdir(parents=True, exist_ok=True)

    hf_repo = info["hf_repo"]

    for local_name, file_info in info["files"].items():
        dest_file = dest / local_name
        if dest_file.exists() and not force:
            logger.info(f"Already downloaded: {local_name}")
            continue

        hf_filename = file_info["hf_filename"]
        url = f"{_HF_BASE_URL}/{hf_repo}/resolve/main/{hf_filename}"

        logger.info(f"Downloading {local_name} from {url}")
        try:
            _download_file(url, dest_file)
        except Exception as e:
            if dest_file.exists():
                dest_file.unlink()
            raise RuntimeError(f"Failed to download {local_name}: {e}") from e

    manifest = {
        "model_name": model_name,
        "files": {},
    }
    for local_name in info["files"]:
        fpath = dest / local_name
        if fpath.exists():
            manifest["files"][local_name] = {
                "sha256": _file_sha256(fpath),
                "size": fpath.stat().st_size,
            }
    (dest / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    logger.info(f"Model downloaded to {dest}")
    return dest


def _download_file(url, dest_path):
    """Download a file with progress reporting."""
    req = urllib.request.Request(url, headers={"User-Agent": "ai-guardian"})
    with urllib.request.urlopen(req, timeout=300) as response:
        total = int(response.headers.get("Content-Length", 0))
        downloaded = 0
        chunk_size = 1024 * 1024

        with open(dest_path, "wb") as f:
            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    pct = downloaded * 100 // total
                    mb = downloaded / (1024 * 1024)
                    total_mb = total / (1024 * 1024)
                    logger.info(f"  {mb:.1f}/{total_mb:.1f} MB ({pct}%)")


def _file_sha256(path):
    """Compute SHA256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def verify_model(model_name=DEFAULT_MODEL):
    """Verify model files exist and manifest checksums match.

    Returns:
        (is_valid, message)
    """
    if model_name not in MODEL_REGISTRY:
        return False, f"Unknown model: {model_name}"

    info = MODEL_REGISTRY[model_name]
    dest = _model_dir(model_name)

    if not dest.exists():
        return False, "Model not downloaded. Run: ai-guardian ml download"

    for local_name in info["files"]:
        fpath = dest / local_name
        if not fpath.exists():
            return (
                False,
                f"Missing file: {local_name}. Run: ai-guardian ml download --force",
            )

    manifest_path = dest / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for local_name, file_info in manifest.get("files", {}).items():
                expected_hash = file_info.get("sha256")
                if expected_hash:
                    actual_hash = _file_sha256(dest / local_name)
                    if actual_hash != expected_hash:
                        return False, (
                            f"Checksum mismatch for {local_name}. "
                            f"Run: ai-guardian ml download --force"
                        )
        except (json.JSONDecodeError, OSError) as e:
            return False, f"Cannot read manifest: {e}"

    return True, f"Model verified: {model_name}"


def ensure_model_downloaded(model_name=DEFAULT_MODEL, force=False):
    """Download model if not already present. Safe for daemon auto-download.

    Args:
        model_name: Model name from registry
        force: Re-download even if present

    Returns:
        (downloaded, message) — downloaded is True if a download occurred
    """
    if model_name not in MODEL_REGISTRY:
        return False, f"Unknown model: {model_name}"

    is_valid, _ = verify_model(model_name)
    if is_valid and not force:
        return False, f"Model already downloaded and verified: {model_name}"

    try:
        download_model(model_name, force=force)
        is_valid, msg = verify_model(model_name)
        if is_valid:
            return True, f"Model downloaded and verified: {model_name}"
        return False, f"Download completed but verification failed: {msg}"
    except Exception as e:
        return False, f"Download failed: {e}"


def setup_ml(
    detector="hybrid",
    model=DEFAULT_MODEL,
    threshold=0.85,
    force=False,
):
    """One-command ML detection setup: check deps, download model, update config.

    Args:
        detector: Detection mode — "hybrid" (heuristic+ML) or "ml" (ML only)
        model: Model name from registry
        threshold: Confidence threshold (0.0-1.0)
        force: Re-download model and overwrite existing config

    Returns:
        dict with keys: success, steps (list of (step_name, ok, message))
    """
    steps = []

    if not is_ml_available():
        steps.append(
            (
                "dependencies",
                False,
                "onnxruntime not available. Install with: pip install onnxruntime",
            )
        )
        return {"success": False, "steps": steps}
    steps.append(("dependencies", True, "onnxruntime and tokenizers available"))

    downloaded, dl_msg = ensure_model_downloaded(model, force=force)
    is_valid, verify_msg = verify_model(model)
    if not is_valid:
        steps.append(("download", False, dl_msg))
        steps.append(("verify", False, verify_msg))
        return {"success": False, "steps": steps}
    steps.append(("download", True, dl_msg))
    steps.append(("verify", True, verify_msg))

    from ai_guardian.config.writer import write_scoped_config

    ok, msg = write_scoped_config("global", "prompt_injection", "detector", detector)
    steps.append(("config_detector", ok, msg))

    from ai_guardian.config.loaders import _load_config_file

    current_config, _ = _load_config_file()
    current_config = current_config or {}
    current_engines = current_config.get("prompt_injection", {}).get("ml_engines", [])

    if current_engines and not force:
        steps.append(
            (
                "config_engines",
                True,
                f"ml_engines already configured ({len(current_engines)} engine(s)), skipping (use --force to overwrite)",
            )
        )
    else:
        engines = [{"type": "llm-guard", "model": model, "threshold": threshold}]
        ok, msg = write_scoped_config(
            "global", "prompt_injection", "ml_engines", engines
        )
        steps.append(("config_engines", ok, msg))

    ok, msg = write_scoped_config(
        "global", "prompt_injection", "ml_strategy", "any-match"
    )
    steps.append(("config_strategy", ok, msg))

    all_ok = all(s[1] for s in steps)
    return {"success": all_ok, "steps": steps}


class MLEngine:
    """Single ONNX model engine for prompt injection detection.

    Thread-safe — ONNX inference session handles concurrent calls.
    """

    def __init__(self, engine_config):
        """Load ONNX model and tokenizer.

        Args:
            engine_config: Dict with keys:
                - type: Engine type (e.g., "llm-guard")
                - model: Model name from registry or path
                - threshold: Confidence threshold (default 0.85)
                - max_length: Max token length (default from registry)

        Raises:
            ImportError: If onnxruntime is not installed
            FileNotFoundError: If model files not downloaded
        """
        import onnxruntime
        import tokenizers

        self.engine_type = engine_config.get("type", "llm-guard")
        self.model_name = engine_config["model"]
        self.threshold = engine_config.get("threshold", 0.85)

        registry_info = MODEL_REGISTRY.get(self.model_name, {})
        self.max_length = engine_config.get(
            "max_length", registry_info.get("max_length", 512)
        )
        self.labels = registry_info.get("labels", {0: "SAFE", 1: "INJECTION"})

        model_path = _model_dir(self.model_name)
        onnx_path = model_path / "model.onnx"
        tokenizer_path = model_path / "tokenizer.json"

        if not onnx_path.exists():
            raise FileNotFoundError(
                f"Model not found at {onnx_path}. " f"Run: ai-guardian ml download"
            )
        if not tokenizer_path.exists():
            raise FileNotFoundError(
                f"Tokenizer not found at {tokenizer_path}. "
                f"Run: ai-guardian ml download"
            )

        sess_options = onnxruntime.SessionOptions()
        sess_options.graph_optimization_level = (
            onnxruntime.GraphOptimizationLevel.ORT_ENABLE_ALL
        )
        sess_options.intra_op_num_threads = min(os.cpu_count() or 1, 4)

        self._session = onnxruntime.InferenceSession(
            str(onnx_path), sess_options=sess_options
        )
        self._tokenizer = tokenizers.Tokenizer.from_file(str(tokenizer_path))
        self._tokenizer.enable_truncation(max_length=self.max_length)
        self._tokenizer.enable_padding(length=self.max_length)

        logger.info(
            f"ML engine loaded: {self.engine_type}/{self.model_name} "
            f"(threshold={self.threshold})"
        )

    def predict(self, text):
        """Run inference on text.

        Args:
            text: Content to classify

        Returns:
            dict: {
                "is_injection": bool,
                "confidence": float,
                "label": str,
                "model": str,
                "engine_type": str,
                "threshold": float,
            }
        """
        import numpy as np

        encoding = self._tokenizer.encode(text)
        input_ids = np.array([encoding.ids], dtype=np.int64)
        attention_mask = np.array([encoding.attention_mask], dtype=np.int64)

        feed = {"input_ids": input_ids, "attention_mask": attention_mask}
        input_names = {inp.name for inp in self._session.get_inputs()}
        if "token_type_ids" in input_names:
            feed["token_type_ids"] = np.zeros_like(input_ids)

        outputs = self._session.run(None, feed)
        logits = outputs[0][0]

        exp_logits = np.exp(logits - np.max(logits))
        probs = exp_logits / exp_logits.sum()

        injection_idx = 1
        safe_idx = 0
        injection_prob = float(probs[injection_idx])
        safe_prob = float(probs[safe_idx])

        is_injection = injection_prob >= self.threshold
        label = self.labels.get(
            injection_idx if is_injection else safe_idx,
            "INJECTION" if is_injection else "SAFE",
        )

        return {
            "is_injection": is_injection,
            "confidence": injection_prob,
            "label": label,
            "model": self.model_name,
            "engine_type": self.engine_type,
            "threshold": self.threshold,
        }


class MLEngineManager:
    """Manages 1-N ML engines with execution strategy.

    Mirrors the multi-engine pattern from secret scanning
    (first-match, any-match, consensus).
    """

    def __init__(self, engines_config, strategy="any-match", consensus_threshold=2):
        """Initialize engine manager.

        Args:
            engines_config: List of engine config dicts
            strategy: "first-match", "any-match", or "consensus"
            consensus_threshold: Min engines that must agree for consensus
        """
        self.strategy = strategy
        self.consensus_threshold = consensus_threshold
        self.engines = []
        self.load_errors = []

        for cfg in engines_config:
            try:
                engine = MLEngine(cfg)
                self.engines.append(engine)
            except Exception as e:
                error_msg = (
                    f"Failed to load engine {cfg.get('type', '?')}/"
                    f"{cfg.get('model', '?')}: {e}"
                )
                logger.warning(error_msg)
                self.load_errors.append(error_msg)

        if not self.engines:
            logger.warning("No ML engines loaded successfully")

    @property
    def available(self):
        """Whether any engines are loaded and ready."""
        return len(self.engines) > 0

    def detect(self, text):
        """Run detection across engines, apply strategy.

        Args:
            text: Content to classify

        Returns:
            dict: {
                "available": bool,
                "is_injection": bool,
                "confidence": float,
                "strategy": str,
                "results": list[dict],
                "engines_total": int,
                "engines_loaded": int,
            }
        """
        if not self.engines:
            return {
                "available": False,
                "is_injection": False,
                "confidence": 0.0,
                "strategy": self.strategy,
                "results": [],
                "engines_total": 0,
                "engines_loaded": 0,
                "error": "No ML engines available",
            }

        results = []
        for engine in self.engines:
            try:
                result = engine.predict(text)
                results.append(result)
            except Exception as e:
                logger.warning(
                    f"Engine {engine.engine_type}/{engine.model_name} "
                    f"prediction failed: {e}"
                )
                results.append(
                    {
                        "is_injection": False,
                        "confidence": 0.0,
                        "label": "ERROR",
                        "model": engine.model_name,
                        "engine_type": engine.engine_type,
                        "error": str(e),
                    }
                )

        is_injection, confidence = self._apply_strategy(results)

        return {
            "available": True,
            "is_injection": is_injection,
            "confidence": confidence,
            "strategy": self.strategy,
            "results": results,
            "engines_total": len(self.engines) + len(self.load_errors),
            "engines_loaded": len(self.engines),
        }

    def _apply_strategy(self, results):
        """Apply execution strategy across engine results.

        Args:
            results: List of per-engine prediction dicts

        Returns:
            (is_injection, confidence)
        """
        valid_results = [r for r in results if r.get("label") != "ERROR"]
        if not valid_results:
            return False, 0.0

        if self.strategy == "first-match":
            for r in valid_results:
                if r["is_injection"]:
                    return True, r["confidence"]
            return False, max(r["confidence"] for r in valid_results)

        elif self.strategy == "any-match":
            injections = [r for r in valid_results if r["is_injection"]]
            if injections:
                max_conf = max(r["confidence"] for r in injections)
                return True, max_conf
            return False, max(r["confidence"] for r in valid_results)

        elif self.strategy == "consensus":
            injection_count = sum(1 for r in valid_results if r["is_injection"])
            threshold = min(self.consensus_threshold, len(valid_results))
            is_injection = injection_count >= threshold
            if is_injection:
                conf_vals = [
                    r["confidence"] for r in valid_results if r["is_injection"]
                ]
                return True, sum(conf_vals) / len(conf_vals)
            return False, max(r["confidence"] for r in valid_results)

        return False, 0.0

    def get_status(self):
        """Get engine manager status for reporting."""
        return {
            "ml_engines_loaded": len(self.engines),
            "ml_engines_total": len(self.engines) + len(self.load_errors),
            "ml_strategy": self.strategy,
            "ml_load_errors": self.load_errors,
            "ml_engines": [
                {
                    "type": e.engine_type,
                    "model": e.model_name,
                    "threshold": e.threshold,
                }
                for e in self.engines
            ],
        }
