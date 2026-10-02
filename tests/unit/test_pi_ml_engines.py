"""Tests for ML prompt injection engine validation in the web console."""

import pytest

pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")

from ai_guardian.web.pages.pi_ml_engines import (  # noqa: E402
    _validate_ml_engines_json,
    VALID_ML_ENGINE_TYPES,
)


class TestValidateMLEnginesJSON:
    """Test the web validation function."""

    def test_empty_string(self):
        result, err = _validate_ml_engines_json("")
        assert result == []
        assert err is None

    def test_empty_array(self):
        result, err = _validate_ml_engines_json("[]")
        assert result == []
        assert err is None

    def test_valid_single_engine(self):
        result, err = _validate_ml_engines_json(
            '[{"type": "llm-guard", "model": "protectai/deberta-v3-base-prompt-injection-v2"}]'
        )
        assert err is None
        assert len(result) == 1
        assert result[0]["type"] == "llm-guard"

    def test_valid_engine_with_threshold(self):
        result, err = _validate_ml_engines_json(
            '[{"type": "llm-guard", "model": "test-model", "threshold": 0.9}]'
        )
        assert err is None
        assert result[0]["threshold"] == 0.9

    def test_valid_multiple_engines(self):
        result, err = _validate_ml_engines_json(
            '[{"type": "llm-guard", "model": "model-a"}, '
            '{"type": "llm-guard", "model": "model-b", "threshold": 0.7}]'
        )
        assert err is None
        assert len(result) == 2

    def test_invalid_json(self):
        result, err = _validate_ml_engines_json("{bad json")
        assert result is None
        assert "Invalid JSON" in err

    def test_not_array(self):
        result, err = _validate_ml_engines_json('{"type": "llm-guard"}')
        assert result is None
        assert "JSON array" in err

    def test_engine_not_object(self):
        result, err = _validate_ml_engines_json('["llm-guard"]')
        assert result is None
        assert "must be an object" in err

    def test_missing_type(self):
        result, err = _validate_ml_engines_json('[{"model": "test"}]')
        assert result is None
        assert "missing 'type'" in err

    def test_unknown_type(self):
        result, err = _validate_ml_engines_json(
            '[{"type": "unknown-engine", "model": "test"}]'
        )
        assert result is None
        assert "unknown type" in err

    def test_missing_model(self):
        result, err = _validate_ml_engines_json('[{"type": "llm-guard"}]')
        assert result is None
        assert "missing 'model'" in err

    def test_threshold_not_number(self):
        result, err = _validate_ml_engines_json(
            '[{"type": "llm-guard", "model": "test", "threshold": "high"}]'
        )
        assert result is None
        assert "threshold must be a number" in err

    def test_threshold_out_of_range_high(self):
        result, err = _validate_ml_engines_json(
            '[{"type": "llm-guard", "model": "test", "threshold": 1.5}]'
        )
        assert result is None
        assert "0.0-1.0" in err

    def test_threshold_out_of_range_low(self):
        result, err = _validate_ml_engines_json(
            '[{"type": "llm-guard", "model": "test", "threshold": -0.1}]'
        )
        assert result is None
        assert "0.0-1.0" in err

    def test_threshold_boundary_zero(self):
        result, err = _validate_ml_engines_json(
            '[{"type": "llm-guard", "model": "test", "threshold": 0.0}]'
        )
        assert err is None
        assert result[0]["threshold"] == 0.0

    def test_threshold_boundary_one(self):
        result, err = _validate_ml_engines_json(
            '[{"type": "llm-guard", "model": "test", "threshold": 1.0}]'
        )
        assert err is None
        assert result[0]["threshold"] == 1.0

    def test_valid_engine_types_constant(self):
        assert "llm-guard" in VALID_ML_ENGINE_TYPES
