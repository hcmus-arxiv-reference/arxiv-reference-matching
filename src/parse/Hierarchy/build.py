"""Build extension bằng Python hiện tại: python -m src.parse.Hierarchy.build."""

import argparse
from pathlib import Path
import subprocess
import sys


def build_extension(build_dir: str | Path | None = None, jobs: int = 2) -> None:
    import pybind11

    source = Path(__file__).resolve().parent / "cpp_core"
    build_dir = Path(build_dir).resolve() if build_dir is not None else source / "_build"
    configure = [
        "cmake", "-S", str(source), "-B", str(build_dir),
        "-DBUILD_PYTHON_BINDINGS=ON", "-DBUILD_TESTING=OFF",
        "-DCMAKE_BUILD_TYPE=Release", f"-DPython3_EXECUTABLE={sys.executable}",
        f"-Dpybind11_DIR={pybind11.get_cmake_dir()}",
    ]
    # Prefer development files belonging to the selected project environment.
    if (Path(sys.prefix) / "include/openssl/evp.h").is_file():
        configure.append(f"-DOPENSSL_ROOT_DIR={sys.prefix}")
    subprocess.run(configure, check=True)
    subprocess.run(
        ["cmake", "--build", str(build_dir), "--config", "Release",
         "--target", "_hierarchy_native", "--parallel", str(jobs)],
        check=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path)
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()
    build_extension(args.build_dir, args.jobs)
