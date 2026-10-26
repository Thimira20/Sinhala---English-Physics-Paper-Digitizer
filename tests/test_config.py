"""
Tests for core.config_manager: merge defaults, atomic save, key masking, and masked key preservation.
"""
import json
import pytest
from pathlib import Path
from core.config_manager import ConfigManager, deep_merge
from core.models import Settings

def test_deep_merge():
    base = {"a": 1, "nested": {"k1": "v1", "k2": "v2"}}
    override = {"b": 2, "nested": {"k2": "override_v2", "k3": "v3"}}
    merged = deep_merge(base, override)
    assert merged["a"] == 1
    assert merged["b"] == 2
    assert merged["nested"]["k1"] == "v1"
    assert merged["nested"]["k2"] == "override_v2"
    assert merged["nested"]["k3"] == "v3"

def test_config_load_and_mask(tmp_path: Path):
    default_cfg = tmp_path / "config.default.json"
    user_cfg = tmp_path / "config.json"
    
    default_cfg.write_text(json.dumps({
        "gemini_api_key": "",
        "gemini_model": "gemini-2.5-pro",
        "requests_per_minute": 60
    }), encoding="utf-8")
    
    user_cfg.write_text(json.dumps({
        "gemini_api_key": "AIzaSySecretKey123456789",
        "requests_per_minute": 30
    }), encoding="utf-8")
    
    mgr = ConfigManager(config_path=user_cfg, default_path=default_cfg)
    settings = mgr.load_settings()
    
    # Internal loaded settings has full key
    assert settings.gemini_api_key == "AIzaSySecretKey123456789"
    assert settings.requests_per_minute == 30
    assert settings.gemini_model == "gemini-2.5-pro"
    
    # Masked copy masks key
    masked = settings.masked_copy()
    assert masked.gemini_api_key == "AIza...6789"
    assert masked.requests_per_minute == 30

def test_atomic_save_and_preserve_masked_key(tmp_path: Path):
    default_cfg = tmp_path / "config.default.json"
    user_cfg = tmp_path / "config.json"
    
    default_cfg.write_text(json.dumps({
        "gemini_api_key": "",
        "gemini_model": "gemini-2.5-pro"
    }), encoding="utf-8")
    
    user_cfg.write_text(json.dumps({
        "gemini_api_key": "AIzaSyRealSecretKey123456"
    }), encoding="utf-8")
    
    mgr = ConfigManager(config_path=user_cfg, default_path=default_cfg)
    mgr.load_settings()
    
    # User sends updated settings with masked key back
    update_data = mgr.load_settings().masked_copy().model_dump()
    update_data["server_port"] = 8080
    
    saved = mgr.save_settings(update_data)
    assert saved.server_port == 8080
    assert saved.gemini_api_key == "AIzaSyRealSecretKey123456" # Original preserved
    
    # Verify file on disk
    on_disk = json.loads(user_cfg.read_text(encoding="utf-8"))
    assert on_disk["gemini_api_key"] == "AIzaSyRealSecretKey123456"
    assert on_disk["server_port"] == 8080
