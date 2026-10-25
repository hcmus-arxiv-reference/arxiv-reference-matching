"""The public crawler command must retain the verified cache/Range contract."""
import subprocess
import sys


def test_crawler_help_preserves_resume_options_without_optional_standalone_dependencies():
    result = subprocess.run([sys.executable, "-m", "src.milestone1_crawler", "--help"],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    for flag in ("--data-dir", "--max-passes", "--retry-delay", "--discover-batch"):
        assert flag in result.stdout


def test_public_pipeline_api_still_imports():
    result = subprocess.run([sys.executable, "-c",
                             "from src.milestone1_crawler import BatchedDiscovery, LieuPipeline"],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
