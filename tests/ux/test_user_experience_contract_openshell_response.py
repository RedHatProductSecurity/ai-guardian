"""Response-delivery UX contracts; Rust unit tests execute the protocol decisions."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RESPONSE_SOURCE = (
    (REPO_ROOT / "rust" / "openshell-middleware" / "src" / "response.rs")
    .read_text(encoding="utf-8")
    .split("#[cfg(test)]", 1)[0]
)


def test_streaming_only_response_is_denied_before_upstream_body_delivery():
    """
    USER EXPERIENCE: No safe whole-body inspection -> explicit response denial.

    Manual verification:
    1. Apply the shipped middleware policy to a disposable OpenShell sandbox.
    2. Request an eligible response whose known size exceeds the payload limit.
    3. OpenShell offers STREAM_BYTES and HEADERS_ONLY, but not WHOLE_BODY_BYTES.

    Expected User Experience:
    - The sandbox sees OpenShell's canonical middleware-denial response with
      reason_code "response_inspection_unavailable", not any upstream body.
    - There is no partial delivery of a split finding or UTF-8 decoding failure
      from decoding an isolated streaming unit.
    - The free-form service diagnostic contains no provider response content.
    """
    assert "HttpResponseBodyMode::StreamBytes" not in RESPONSE_SOURCE
    assert (
        'reason_code: "response_inspection_unavailable".to_string()' in RESPONSE_SOURCE
    )
    assert (
        'reason: "AI Guardian requires whole-body response inspection".to_string()'
        in RESPONSE_SOURCE
    )


def test_bodyless_responses_do_not_fail_closed_just_for_lacking_a_body():
    """
    USER EXPERIENCE: HEAD/204/304 response -> normal successful delivery.

    Manual verification:
    1. Use the same middleware-protected sandbox with a healthy daemon.
    2. Send HEAD, or receive a 204 or 304 final response.

    Expected User Experience:
    - The permitted HEADERS_ONLY mode is accepted; no body scanner runs.
    - A daemon/control-plane outage still denies delivery, rather than silently
      bypassing the middleware's fail-closed behavior.
    """
    assert "HttpResponseBodyMode::HeadersOnly" in RESPONSE_SOURCE
    assert 'method == "HEAD"' in RESPONSE_SOURCE
    assert "matches!(preflight.status_code, 204 | 304)" in RESPONSE_SOURCE
    assert (
        'reason_code: "middleware_control_plane_unavailable".to_string()'
        in RESPONSE_SOURCE
    )
