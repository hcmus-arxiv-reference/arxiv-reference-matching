"""The new default is standalone; the existing cache requires an explicit engine."""
import subprocess
import sys


def test_integrated_help_preserves_resume_options():
    result = subprocess.run([sys.executable, "-m", "src.milestone1_crawler", "--engine", "integrated", "--help"],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    for flag in ("--data-dir", "--max-passes", "--retry-delay", "--discover-batch"):
        assert flag in result.stdout


def test_default_help_uses_standalone_options():
    result = subprocess.run([sys.executable, "-m", "src.milestone1_crawler", "--help"],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert "--default-encoding" in result.stdout
    assert "--data-dir" in result.stdout
    assert "--max-passes" not in result.stdout


def test_public_pipeline_api_still_imports():
    result = subprocess.run([sys.executable, "-c",
                             "from src.milestone1_crawler import BatchedDiscovery, LieuPipeline"],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
