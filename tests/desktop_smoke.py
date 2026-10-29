"""Compatibility entrypoint for the React/Mantine desktop integration checks."""
from pathlib import Path
import runpy
runpy.run_path(str(Path(__file__).with_name("react_desktop_smoke.py")),run_name="__main__")
