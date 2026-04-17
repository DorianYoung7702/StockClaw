"""Tests for commonsense / locale policy augmentation (no live LLM)."""

from __future__ import annotations


def test_augment_appends_commonsense_boundary():
    from app.prompts.response_policy import augment_system_prompt

    out = augment_system_prompt("BASE_INSTRUCTION")
    assert "BASE_INSTRUCTION" in out
    assert "常识性" in out
    assert "具体情景" in out


def test_augment_zh_mode_adds_simplified_chinese_rule(monkeypatch):
    import app.config as cfg_mod
    from app.prompts.response_policy import augment_system_prompt

    monkeypatch.setenv("ATLAS_FORCE_RESPONSE_LOCALE", "zh")
    cfg_mod._settings = None
    out = augment_system_prompt("HELLO")
    assert "HELLO" in out
    assert "简体中文" in out


def test_structured_addendum_zh_note(monkeypatch):
    import app.config as cfg_mod
    from app.agents.synthesis import _structured_addendum

    monkeypatch.setenv("ATLAS_FORCE_RESPONSE_LOCALE", "zh")
    cfg_mod._settings = None
    body = _structured_addendum()
    assert "Simplified Chinese" in body

    monkeypatch.setenv("ATLAS_FORCE_RESPONSE_LOCALE", "auto")
    cfg_mod._settings = None
    body_auto = _structured_addendum()
    assert "Simplified Chinese" not in body_auto
