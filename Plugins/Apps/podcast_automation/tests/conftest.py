"""Podcast tests share the same isolated settings fixture as the core suite."""
import importlib.util
from pathlib import Path
file=Path(__file__).resolve().parents[4]/'tests/conftest.py'
spec=importlib.util.spec_from_file_location('pia_profile_test_fixtures',file)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
isolated_profile=module.isolated_profile
