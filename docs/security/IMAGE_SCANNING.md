# Image Scanning (OCR)

OCR-based secret and PII detection in images. Extracts text from image files using optical character recognition, then scans the extracted text through existing secret, PII, prompt injection, and SSRF scanners.

**NEW in v1.10.0** (Issue #720)

## How It Works

When an AI agent reads an image file (PNG, JPEG, GIF, BMP, TIFF, WebP), AI Guardian:

1. Detects the file is an image (by extension and magic bytes)
2. Extracts text using RapidOCR (`rapidocr` with `onnxruntime`)
3. Scans the extracted text through existing scanners (secrets, PII, prompt injection, SSRF)
4. Blocks/warns/logs based on the configured action

This catches secrets embedded in screenshots, scanned documents, terminal captures, and other image content before it reaches the AI model.

## Supported Hook Events

| Hook | Image Scanning | Status |
|------|---------------|--------|
| **PreToolUse** (file reads) | **Yes** | OCR runs on image files before AI sees them |
| **PostToolUse** | **No** | AI already extracted text; existing text scanners handle it |
| **UserPromptSubmit** | **Partial** | Only inline base64 images; pasted attachments not available in hook data |

## IDE Compatibility

### PreToolUse — Image File Reads

All IDEs that support PreToolUse hooks provide the `file_path`, which AI Guardian uses to detect image files and run OCR before the AI sees them.

| IDE | PreToolUse Hook | File Path Available | Image Content in Hook | Notes |
|-----|----------------|--------------------|-----------------------|-------|
| Claude Code | **No for images** | N/A | N/A | PreToolUse does not fire for image file reads ([#62639](https://github.com/anthropics/claude-code/issues/62639)); only PostToolUse fires with empty output. Image sent directly to model as vision content. |
| Cursor | Yes (`preToolUse` + `beforeReadFile`) | Yes | `beforeReadFile` includes `content` as string | [Bug: not invoked if file is open](https://forum.cursor.com/t/beforefileread-hook-not-invoked-if-file-is-open/161031) |
| GitHub Copilot | Yes | Yes (`toolArgs.path`) | No | [Bug: hooks don't fire with Anthropic BYOM](https://github.com/github/copilot-sdk/issues/893) |
| Cline | Yes | Yes | No | macOS/Linux only |
| Windsurf | Yes (`pre_read_code`) | Yes (`tool_info.file_path`) | No | |
| Gemini CLI | Yes | Yes | No | [Bug: GIF files crash CLI](https://github.com/google-gemini/gemini-cli/issues/18057) |
| Kiro | Yes | Yes (`tool_input.operations[].path`) | No | [Bug: IDE sends empty toolArgs](https://github.com/kirodotdev/Kiro/issues/7375); [IDE can't read images](https://github.com/kirodotdev/Kiro/issues/7224) |
| Augment | Yes | Yes | No | `updatedInput` not yet implemented |
| JetBrains Junie | **No hook system** | N/A | N/A | [Feature request: JUNIE-1961](https://youtrack.jetbrains.com/projects/JUNIE/issues/JUNIE-1961) |
| Aider | **No hook system** | N/A | N/A | AiderDesk has SDK-level hooks |

### UserPromptSubmit — Pasted Image Attachments

**No IDE currently exposes pasted image attachment data in prompt hook payloads.** When a user pastes or attaches an image directly into a chat message, the image data is not included in the hook's JSON input. Only the text portion of the prompt is available.

This is a limitation of the IDE hook APIs, not AI Guardian:

- Claude Code: [anthropics/claude-code#16592](https://github.com/anthropics/claude-code/issues/16592) — feature request to expose image data in hooks

AI Guardian checks for inline base64-encoded images (`data:image/...;base64,...`) in the prompt text, but IDE-attached images are not available through this mechanism.

## Known Limitations

### 1. Pasted image attachments not hookable

See [UserPromptSubmit](#userpromptsubmit--pasted-image-attachments) above. No IDE exposes image attachment data in prompt hooks.

**Workaround**: Save the image to a file and ask the agent to read the file. The PreToolUse hook intercepts the file read and runs OCR scanning.

### 2. IDE-specific bugs

Several IDEs have bugs in their hook systems that may affect image scanning reliability. See the compatibility table above for details and tracking issues.

### 3. Other limitations

- **SVG files** are excluded from OCR scanning because SVG is text-based XML. Existing text scanners handle SVG content directly.
- **Animated GIFs** — only the first frame is scanned.
- **Very large images** (>10MB by default) are skipped to stay within the performance budget. Configurable via `max_image_size_mb`.
- **Low-quality or handwritten text** may not be extracted reliably. OCR confidence threshold (`min_confidence`) controls this.

### Other limitations

- **SVG files** are excluded from OCR scanning because SVG is text-based XML. Existing text scanners handle SVG content directly.
- **Animated GIFs** — only the first frame is scanned.
- **Very large images** (>10MB by default) are skipped to stay within the performance budget. Configurable via `max_image_size_mb`.
- **Low-quality or handwritten text** may not be extracted reliably. OCR confidence threshold (`min_confidence`) controls this.

## Configuration

Image scanning is configured in `ai-guardian.json` under the `image_scanning` section:

```json
{
  "image_scanning": {
    "enabled": true,
    "action": "block",
    "scan_types": ["secrets", "pii"],
    "max_processing_ms": 1500,
    "min_confidence": 0.5,
    "redaction_method": "blur",
    "qr_scanning": false,
    "face_detection": false,
    "ignore_files": [],
    "ignore_tools": [],
    "max_image_size_mb": 10
  }
}
```

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `enabled` | `true` | Enable/disable image scanning. Supports time-based toggling. |
| `action` | `"block"` | Action on detection: `block`, `warn`, or `log-only` |
| `scan_types` | `["secrets", "pii"]` | Threat types to scan for: `secrets`, `pii`, `ssrf`, `prompt_injection` |
| `max_processing_ms` | `1500` | Max OCR time per image (milliseconds) |
| `min_confidence` | `0.5` | Minimum OCR confidence threshold (0-1). Lower values catch more but risk false positives. |
| `redaction_method` | `"blur"` | How to redact sensitive regions: `blur`, `blackout`, or `pixelate` |
| `qr_scanning` | `false` | Scan QR codes for embedded secrets. Requires `pyzbar`. |
| `face_detection` | `false` | Detect faces (biometric PII). Requires `opencv-python-headless`. |
| `ignore_files` | `[]` | File patterns to skip (e.g., `["*.ico", "favicon.*"]`) |
| `ignore_tools` | `[]` | Tool names to skip |
| `max_image_size_mb` | `10` | Max file size in MB. Larger images are skipped. |

## Performance

| Step | Time | When |
|------|------|------|
| Image detection (extension + magic bytes) | <1ms | Always |
| OCR text extraction | 200ms–1s | Only on image files |
| Pattern scan on extracted text | <10ms | Only if OCR produced text |
| Total typical | ~300ms | Terminal screenshot |
| Total worst case | ~1.5s | Large high-resolution photo |

## Dependencies

- **rapidocr** and **onnxruntime** (required) — included as regular dependencies
- **pyzbar** (optional) — for QR code scanning (`qr_scanning: true`)
- **opencv-python-headless** (optional) — for face detection (`face_detection: true`)

AI Guardian pins RapidOCR to `3.9.2`. ONNX Runtime is pinned per Python and
platform so supported interpreters use available wheels:

- `1.19.2` on Python 3.9 and older supported interpreters
- `1.23.2` on Python 3.10, and on Python 3.11-3.13 for macOS 13+ Intel or
  ARM64
- `1.29.0` on Python 3.11 and newer for Linux/Windows and macOS 14+ ARM64

Python 3.14 on Intel macOS or macOS versions before 14 on ARM64 has no
compatible published ONNX Runtime wheel and therefore does not select the
dependency. Image OCR is unavailable on those targets unless a compatible
runtime is installed by the user.

## Image Redaction

When a violation is found, AI Guardian can redact the sensitive regions in the image using bounding box coordinates from the OCR engine:

| Method | Description |
|--------|-------------|
| `blur` | Gaussian blur over the region (default) |
| `blackout` | Solid black rectangle |
| `pixelate` | Downscale then upscale the region |

## Supported Image Formats

PNG, JPEG, GIF, BMP, TIFF, WebP, ICO

Detection uses both file extension and magic byte signatures for reliability.

## Doctor Check

Run `ai-guardian doctor` to verify OCR availability:

```
image_scanning .... PASS  rapidocr and onnxruntime available for image OCR scanning
```

If the OCR engine is not installed:

```
image_scanning .... FAIL  rapidocr/onnxruntime not available (required for image scanning)
  Fix: pip install rapidocr onnxruntime
```
