"""Tests for auth module."""

import os
from unittest.mock import patch

import pytest

from src import auth
from src.auth import get_api_key
from src.exceptions import AuthenticationError


def _engine(root, platform, metadata):
    pkg = root / f"engine-{platform}" / f"engine_{platform}"
    pkg.mkdir(parents=True)
    (pkg / "metadata.py").write_text(metadata)


@pytest.fixture
def engines(tmp_path, monkeypatch):
    """Discover only the fake engines under tmp_path; returns the loader."""
    root = tmp_path / "ENGINES"
    monkeypatch.setattr(auth, "find_generator_engines_dir", lambda: root)
    monkeypatch.setattr(auth, "SUPPORTED_PLATFORMS", [])
    monkeypatch.setattr(auth, "_ENGINE_KEYS", {})

    def load(**metadata):
        for platform, text in metadata.items():
            _engine(root, platform, text)
        auth.load_platforms(tmp_path)

    return load


class TestGetApiKey:
    def test_engine_with_odd_key_name_is_picked_up(self, engines, tmp_path):
        project = tmp_path / ".00_TOOLS" / "GENERATORS" / "ENGINES"
        _engine(project, "newco", 'API_KEY_ENV_VAR = "NEWCO_SECRET"')
        engines(
            newco='API_KEY_ENV_VAR = "SHADOWED"',
            plain="",
            broken="raise RuntimeError",
        )
        assert auth.SUPPORTED_PLATFORMS == ["newco", "plain"]
        with patch.dict(os.environ, {"NEWCO_SECRET": "nc", "PLAIN_API_KEY": "pl"}):
            assert get_api_key("newco") == "nc"
            assert get_api_key("plain") == "pl"

    def test_from_environment(self, engines):
        engines(replicate='API_KEY_ENV_VAR = "REPLICATE_API_TOKEN"')
        with patch.dict(os.environ, {"REPLICATE_API_TOKEN": "r8_test123"}):
            key = get_api_key("replicate")
            assert key == "r8_test123"

    def test_from_environment_fal(self, engines):
        engines(fal='API_KEY_ENV_VAR = "FAL_KEY"')
        with patch.dict(os.environ, {"FAL_KEY": "fal_test456"}):
            key = get_api_key("fal")
            assert key == "fal_test456"

    def test_missing_key_raises(self):
        with patch.dict(os.environ, {}, clear=True), patch(
            "src.auth._try_pass", return_value=None
        ), patch("src.auth.env.get_api_token_from_env", return_value=None):
            with pytest.raises(AuthenticationError, match="No API key found"):
                get_api_key("replicate")

    def test_unknown_platform_uses_convention(self):
        key_name = "CUSTOM_API_KEY"
        with patch.dict(os.environ, {key_name: "val"}):
            key = get_api_key("custom")
            assert key == "val"

    def test_env_file_fallback(self):
        with patch.dict(os.environ, {}, clear=True), patch(
            "src.auth._try_pass", return_value=None
        ), patch("src.auth.env.get_api_token_from_env", return_value="r8_from_env"):
            key = get_api_key("replicate")
            assert key == "r8_from_env"
