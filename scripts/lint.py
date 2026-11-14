"""Lint all first-party tracked Python and workspace frontend sources."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    subprocess.run(args, cwd=ROOT, check=True)


def main():
    fix = "--fix" in sys.argv[1:]
    files = (
        subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=ROOT,
        )
        .decode("utf-8")
        .split("\0")
    )
    python_files = sorted({name for name in files if name.endswith(".py")})
    if "--hook" in sys.argv[1:]:
        # The checked worktree must match the staged code. Never accept an
        # unformatted index just because an unstaged correction passes lint.
        changed = (
            subprocess.check_output(["git", "diff", "--name-only", "-z"], cwd=ROOT)
            .decode("utf-8")
            .split("\0")
        )
        relevant = [
            name
            for name in changed
            if name.endswith(".py")
            or name.startswith("src/pia/frontend/")
            or name in {"pyproject.toml", "scripts/pre-commit"}
        ]
        if relevant:
            sys.exit(
                "Stage code/configuration before committing: " + ", ".join(relevant)
            )
    run(
        sys.executable,
        "-m",
        "ruff",
        "format",
        *([] if fix else ["--check"]),
        *python_files,
    )
    run(
        sys.executable,
        "-m",
        "ruff",
        "check",
        *(["--fix"] if fix else []),
        *python_files,
    )
    npm = "npm.cmd" if sys.platform == "win32" else "npm"
    if fix:
        run(npm, "--prefix", "src/pia/frontend", "run", "format")
    run(npm, "--prefix", "src/pia/frontend", "run", "lint")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)
