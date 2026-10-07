"""UX contracts for first-class external middleware sandbox creation (#2507)."""

from types import SimpleNamespace

from ai_guardian.sandbox import create_sandbox


def test_user_experience_rejects_unsupported_image_before_runtime_access():
    """
    USER EXPERIENCE: External middleware is requested for a non-AI-Guardian
    OpenShell image.

    Expected experience:
    - Sandbox creation stops before invoking OpenShell.
    - The user sees the image compatibility requirement and an example image.
    - No provider, gateway, or middleware state is touched.
    """
    args = SimpleNamespace(
        runtime="openshell",
        image="quay.io/nvidia/openshell-community:latest",
        middleware=True,
        cli="codex",
    )
    output = []

    assert create_sandbox(args, interactive=False, output=output) == 2
    assert output == [
        "Error: external OpenShell middleware requires an AI Guardian OpenShell "
        "image (for example localhost/ai-guardian-openshell:dev); received "
        "'quay.io/nvidia/openshell-community:latest'\n"
    ]
