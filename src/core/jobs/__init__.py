"""Core jobs, notifications, and logs facade."""

from src.log_reader import log_path, read_log
from src.notifications import NotificationCenter
from src.plugin_logs import write as write_plugin_log

__all__ = ["NotificationCenter", "log_path", "read_log", "write_plugin_log"]
