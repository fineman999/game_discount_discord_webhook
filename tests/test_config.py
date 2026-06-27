"""config 로드/검증 테스트 (임시 파일 기반)."""

from __future__ import annotations

import pytest

from dealbot.config import ConfigError, load_config


def _write(tmp_path, mode):
    p = tmp_path / "config.yaml"
    p.write_text(f"country: KR\nmode: {mode}\nwatchlist:\n  - title: X\n", encoding="utf-8")
    return p


def test_mode_both_accepted(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ITAD_API_KEY", "k")
    cfg = load_config(_write(tmp_path, "both"), require_webhook=False)
    assert cfg.mode == "both"


@pytest.mark.parametrize("mode", ["watchlist", "deals", "both"])
def test_valid_modes(tmp_path, monkeypatch, mode):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ITAD_API_KEY", "k")
    assert load_config(_write(tmp_path, mode), require_webhook=False).mode == mode


def test_invalid_mode_raises(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ITAD_API_KEY", "k")
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, "bogus"), require_webhook=False)
