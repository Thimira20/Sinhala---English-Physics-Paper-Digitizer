"""
Configuration manager: handles loading, deep-merging defaults, atomic writes,
and API key masking.
"""
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict
from core.models import Settings

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DEFAULT_PATH = PROJECT_ROOT / "config.default.json"
CONFIG_PATH = PROJECT_ROOT / "config.json"

def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = base.copy()
    for k, v in override.items():
        if k in merged and isinstance(merged[k], dict) and isinstance(v, dict):
            merged[k] = deep_merge(merged[k], v)
        else:
            merged[k] = v
    return merged

class ConfigManager:
    def __init__(self, config_path: Path = CONFIG_PATH, default_path: Path = CONFIG_DEFAULT_PATH):
        self.config_path = config_path
        self.default_path = default_path
        self._cached_settings: Settings | None = None

    def load_settings(self, force_reload: bool = False) -> Settings:
        if self._cached_settings is not None and not force_reload:
            return self._cached_settings

        defaults = {}
        if self.default_path.exists():
            try:
                defaults = json.loads(self.default_path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.error(f"Error reading defaults from {self.default_path}: {e}")

        user_cfg = {}
        if self.config_path.exists():
            try:
                user_cfg = json.loads(self.config_path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.error(f"Error reading user config from {self.config_path}: {e}")

        merged = deep_merge(defaults, user_cfg)
        settings = Settings.model_validate(merged)
        self._cached_settings = settings
        return settings

    def save_settings(self, new_settings: Settings | dict) -> Settings:
        current = self.load_settings()

        if isinstance(new_settings, dict):
            req_key = new_settings.get("gemini_api_key")
            if req_key is None or "..." in req_key or req_key == "********":
                new_settings["gemini_api_key"] = current.gemini_api_key
            merged = deep_merge(current.model_dump(), new_settings)
            validated = Settings.model_validate(merged)
        else:
            req_key = new_settings.gemini_api_key
            if not req_key or "..." in req_key or req_key == "********":
                new_settings.gemini_api_key = current.gemini_api_key
            validated = new_settings

        data = validated.model_dump()
        tmp_file = self.config_path.with_suffix(".tmp")
        try:
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp_file, self.config_path)
            self._cached_settings = validated
            logger.info("Configuration saved atomically.")
            return validated
        except Exception as e:
            if tmp_file.exists():
                tmp_file.unlink()
            logger.error(f"Failed to write config file: {e}")
            raise

_config_manager = ConfigManager()

def get_settings() -> Settings:
    return _config_manager.load_settings()

def get_config_manager() -> ConfigManager:
    return _config_manager
