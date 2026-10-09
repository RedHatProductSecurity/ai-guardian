"""UX contracts for the OpenShell sandbox/middleware ownership boundary."""

from unittest.mock import patch

import pytest


def test_user_experience_sandbox_creation_has_no_middleware_lifecycle_options(
    capsys,
):
    """
    USER EXPERIENCE: Sandbox creation is independent from middleware.

    Expected experience:
    - ``sandbox create`` creates only the sandbox and its normal policy.
    - Middleware deployment and activation are not hidden in sandbox setup.
    - The operator manages middleware through OpenShell's gateway/policy layer.
    """
    from ai_guardian.cli import main

    with patch("sys.argv", ["ai-guardian", "sandbox", "create", "--help"]):
        with pytest.raises(SystemExit) as error:
            main()

    assert error.value.code == 0
    help_text = capsys.readouterr().out
    assert "--middleware" not in help_text
    assert "--middleware-policy" not in help_text
