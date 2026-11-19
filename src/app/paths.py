"""Unified paths facade (config, user, cache)."""

from src.cache_paths import cache_path
from src.config_paths import BASE_DIR, CONFIG_DIR
from src.user_paths import user_path

__all__ = ["BASE_DIR", "CONFIG_DIR", "cache_path", "user_path"]
