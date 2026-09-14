import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]


def test_make_check_venv_fails_clearly_when_project_python_is_absent() -> None:
    result = subprocess.run(
        ["make", "check-venv", "PYTHON=.missing-venv/bin/python"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode != 0
    assert "Run 'make install' with Python 3.12" in result.stdout + result.stderr


def test_make_venv_rejects_existing_incompatible_project_interpreter() -> None:
    result = subprocess.run(
        ["make", "venv", "PYTHON=/bin/sh"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode != 0
    assert "Project environment must use Python 3.12" in result.stdout + result.stderr
