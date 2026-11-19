"""Core settings facade."""

from src.settings_store import (
    SystemVault,
    document,
    get_store,
    save_document,
    schema,
    sensitive,
    values,
)

__all__ = [
    "SystemVault",
    "document",
    "get_store",
    "save_document",
    "schema",
    "sensitive",
    "values",
]
