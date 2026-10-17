"""Validate direct pins, hash completeness and CPU/CUDA dependency separation."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIRECT = {
    "requirements-stt-cpu.in": {"pyyaml", "aiohttp", "faster-whisper"},
    "requirements-stt-cuda.in": {
        "pyyaml",
        "aiohttp",
        "faster-whisper",
        "ctranslate2",
        "nvidia-ml-py",
        "nvidia-cublas-cu12",
        "nvidia-cudnn-cu12",
    },
}
CUDA_RUNTIME_POLICY = {
    "ctranslate2": "4.8.3",
    "nvidia-cublas-cu12": "12.9.2.10",
    "nvidia-cuda-nvrtc-cu12": "12.9.86",
    "nvidia-cudnn-cu12": "9.27.0.42",
}


def _requirements(path):
    pins = {}
    for line in path.read_text().splitlines():
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+)", line.strip())
        if match:
            pins[match.group(1).lower().replace("_", "-")] = match.group(2)
    return pins


def _locked_packages(path):
    text = path.read_text()
    packages = {}
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        match = re.match(r"^([A-Za-z0-9_.-]+)==([^ ]+)(?: \\)?$", lines[index])
        if match:
            name = match.group(1).lower().replace("_", "-")
            hashes = []
            index += 1
            while index < len(lines) and lines[index].startswith("    --hash=sha256:"):
                hashes.append(lines[index])
                index += 1
            if not hashes:
                raise ValueError(f"locked package has no hashes: {name}")
            packages[name] = match.group(2)
        else:
            index += 1
    return packages


def validate(root=ROOT):
    for input_name, direct_names in DIRECT.items():
        source = _requirements(root / "services" / input_name)
        lock = _locked_packages(root / "services" / input_name.replace(".in", ".lock"))
        if set(source) != direct_names:
            raise ValueError(f"unexpected direct dependencies in {input_name}")
        if not set(source).issubset(lock):
            raise ValueError(f"lock omits a direct dependency from {input_name}")
        for name, version in source.items():
            if lock[name] != version:
                raise ValueError(f"direct dependency version differs from lock: {name}")
        if input_name.endswith("cpu.in") and any(
            name.startswith("nvidia-") for name in lock
        ):
            raise ValueError("CPU lock must not include NVIDIA packages")
        if input_name.endswith("cuda.in"):
            for name, version in CUDA_RUNTIME_POLICY.items():
                if lock.get(name) != version:
                    raise ValueError(
                        f"unsupported CUDA runtime combination: {name} must be {version}"
                    )
            if "nvidia-cuda-runtime-cu12" in lock:
                raise ValueError(
                    "CUDA lock must not add nvidia-cuda-runtime-cu12; "
                    "CTranslate2 4.8.3 statically links CUDA Runtime"
                )
        if (
            "faster-whisper" not in lock
            or "ctranslate2" not in lock
            or "av" not in lock
        ):
            raise ValueError("inference lock is incomplete")
    print("PASS: STT lock pins, hashes and CPU/CUDA compatibility policy")


if __name__ == "__main__":
    validate()
