# Multi-Engine ML Support for Prompt Injection Detection

**GitHub Issue**: [#185](https://github.com/RedHatProductSecurity/ai-guardian/issues/185)  
**Status**: v1.11.0  
**Priority**: High

## Summary

AI Guardian supports ML-based prompt injection detection using ONNX models that run inside the daemon process. Multiple ML engines can be configured simultaneously with execution strategies (first-match, any-match, consensus), mirroring the [multi-engine pattern for secret scanning](MULTI_ENGINE_SUPPORT.md).

## Background

### Why ML Detection?

Heuristic (regex) detection is fast (<1ms) and catches common attack patterns, but has limitations:

- **Novel attacks**: New prompt injection techniques may not match existing patterns
- **Obfuscation**: Attackers can rephrase instructions to evade regex
- **Context understanding**: Regex cannot understand intent, only surface patterns
- **False positives**: Legitimate content may match broad patterns

ML models trained on prompt injection datasets understand semantic meaning and catch attacks that evade pattern matching.

### Why Multi-Engine?

Different models have different strengths:

- **General detection**: Broad prompt injection coverage
- **Jailbreak-specific**: Focused on role-play and identity manipulation attacks
- **Custom models**: Organization-specific attack patterns

Running multiple engines with execution strategies provides defense-in-depth.

## Architecture

```
Hook invocation (hook mode, <20ms target)
  → PromptInjectionDetector.detect()
    → if detector == "heuristic": local regex (unchanged, <1ms)
    → if detector == "ml": query daemon → all ml_engines → apply strategy
    → if detector == "hybrid": heuristic first, uncertain → query daemon
    → fallback_on_error if daemon/model unavailable

Daemon process (persistent, models loaded once)
  → DaemonState.get_ml_engine_manager()
    → MLEngineManager (1-N MLEngine instances)
    → Each MLEngine: ONNX model + tokenizer in memory
  → Socket IPC: "ml_detect" message type
  → REST API: POST /api/ml-detect, GET /api/ml-status
```

Models run exclusively in the daemon process to avoid the startup cost on every hook invocation. The hook queries the daemon via Unix socket (or TCP on Windows) with a 2-second timeout.

## Setup

### Prerequisites

```bash
# tokenizers is included as a main dependency
# onnxruntime is included via rapidocr-onnxruntime on Python < 3.13
# On Python 3.13+, install onnxruntime separately:
# pip install onnxruntime

# Download the default model (~370 MB)
ai-guardian ml download

# Verify installation
ai-guardian ml status
```

### Configuration

Add to `ai-guardian.json`:

```json
{
  "prompt_injection": {
    "enabled": true,
    "detector": "hybrid",
    "ml_engines": [
      {
        "type": "llm-guard",
        "model": "protectai/deberta-v3-base-prompt-injection-v2",
        "threshold": 0.85
      }
    ],
    "ml_strategy": "any-match",
    "fallback_on_error": "heuristic"
  }
}
```

### Start the Daemon

```bash
ai-guardian daemon start
```

The daemon loads ML models on the first detection request (lazy loading).

## Configuration Reference

### `detector`

| Value | Description | Daemon Required |
|-------|-------------|-----------------|
| `heuristic` | Regex patterns only (default, <1ms) | No |
| `ml` | ML engines only, via daemon | Yes |
| `hybrid` | Heuristic first, ML for uncertain cases | Yes (graceful fallback) |

### `ml_engines`

Array of engine configurations. Each engine loads one ONNX model:

```json
{
  "type": "llm-guard",
  "model": "protectai/deberta-v3-base-prompt-injection-v2",
  "threshold": 0.85
}
```

| Field | Type | Description |
|-------|------|-------------|
| `type` | string | Engine type. Currently: `llm-guard` |
| `model` | string | Model name from registry |
| `threshold` | float | Confidence threshold (0.0-1.0, default 0.85) |

### `ml_strategy`

Execution strategy when multiple engines are configured:

| Strategy | Behavior | Use Case |
|----------|----------|----------|
| `first-match` | Use first engine that detects injection | Performance-optimized |
| `any-match` | Flag if ANY engine detects (default) | Defense-in-depth |
| `consensus` | Flag only if N engines agree | Reduce false positives |

### `consensus_threshold`

Minimum number of engines that must agree for the `consensus` strategy. Default: 2.

### `fallback_on_error`

Action when ML detection is unavailable (daemon not running, model not loaded):

| Value | Behavior |
|-------|----------|
| `heuristic` | Fall back to regex detection (default) |
| `block` | Fail closed — block the operation |
| `allow` | Fail open — allow the operation |

## Available Models

| Model | Size | Description |
|-------|------|-------------|
| `protectai/deberta-v3-base-prompt-injection-v2` | ~370 MB | DeBERTa v3 base fine-tuned for prompt injection detection. Same model used by LLM Guard. |

## CLI Commands

```bash
# Download a model
ai-guardian ml download [MODEL_NAME] [--force]

# List available and downloaded models
ai-guardian ml list

# Show ML detection status
ai-guardian ml status

# Verify model integrity
ai-guardian ml verify [MODEL_NAME]
```

## API Endpoints

### Socket Protocol

Send `ml_detect` message type:

```json
{"version": 1, "type": "ml_detect", "data": {"content": "text to check"}}
```

Response:

```json
{
  "available": true,
  "is_injection": true,
  "confidence": 0.95,
  "strategy": "any-match",
  "results": [
    {
      "is_injection": true,
      "confidence": 0.95,
      "label": "INJECTION",
      "model": "protectai/deberta-v3-base-prompt-injection-v2",
      "engine_type": "llm-guard"
    }
  ]
}
```

### REST API

- `POST /api/ml-detect` — Run ML detection (body: `{"content": "text"}`)
- `GET /api/ml-status` — Get engine status (loaded count, errors)

## Performance

| Metric | Heuristic | ML (ONNX) | Hybrid |
|--------|-----------|-----------|--------|
| Latency | <1ms | 10-50ms | <1ms (most), +10-50ms (uncertain) |
| Memory | ~5 MB | ~400-600 MB per model | Same as ML |
| Dependencies | None | onnxruntime (bundled), tokenizers (bundled) | Same as ML |
| Startup | Instant | 1-3s (first load) | Same as ML |

The hybrid mode provides the best balance: most requests are handled by the fast heuristic, with ML consulted only for uncertain cases (confidence between 0.3 and 0.85).

## Troubleshooting

### "ML dependencies not available"

```bash
# onnxruntime is bundled via rapidocr-onnxruntime on Python < 3.13
# On Python 3.13+, install separately:
pip install onnxruntime
```

### "Model not downloaded"

```bash
ai-guardian ml download
```

### "ML model not available" in daemon

Check daemon logs:

```bash
ai-guardian daemon status
ai-guardian ml status
```

The daemon loads models lazily on first request. If loading fails, check:
- Model files exist: `ai-guardian ml verify`
- Sufficient memory (~400-600 MB per model)
- ONNX Runtime compatible with your platform

### Daemon not running

ML detection requires the daemon. Start it:

```bash
ai-guardian daemon start
```

With `fallback_on_error: "heuristic"` (default), detection falls back to regex patterns when the daemon is unavailable.
