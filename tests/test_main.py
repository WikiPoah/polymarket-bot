# File-Version: 1.1.0
"""Tests for the application command-line entry point."""

import subprocess
import sys


def test_main_help_loads_without_circular_import():
    result = subprocess.run(
        [sys.executable, "-m", "src.main", "--help"],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0
    assert "Run paper-trading evaluation" in result.stdout
    assert "--log-level" in result.stdout
    assert result.stderr == ""
