"""CPU and optional CUDA discovery at the infrastructure edge."""

from __future__ import annotations

from services.stt.domain import DeviceCapabilities, OperationContext


class SystemDeviceProbe:
    def __init__(self, *, cuda_enabled: bool, cuda_device_index: int = 0):
        self._cuda_enabled = cuda_enabled
        self._cuda_device_index = cuda_device_index

    def discover(self, context: OperationContext):
        context.check()
        cpu_features = {"audio-f32-mono"}
        try:
            import ctranslate2

            cpu_features.update(
                f"compute_type:{kind}"
                for kind in ctranslate2.get_supported_compute_types("cpu")
            )
        except (ImportError, RuntimeError, OSError):
            pass
        devices = [DeviceCapabilities("cpu", "0", frozenset(cpu_features))]
        if not self._cuda_enabled:
            return tuple(devices)
        try:
            import ctranslate2

            count = ctranslate2.get_cuda_device_count()
        except (ImportError, RuntimeError, OSError):
            return tuple(devices)
        if self._cuda_device_index >= count:
            return tuple(devices)
        free_bytes = None
        total_bytes = None
        try:
            import pynvml

            pynvml.nvmlInit()
            try:
                handle = pynvml.nvmlDeviceGetHandleByIndex(self._cuda_device_index)
                memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
                free_bytes = int(memory.free)
                total_bytes = int(memory.total)
            finally:
                pynvml.nvmlShutdown()
        except Exception:
            # Unknown memory remains unknown; device policy fails closed when a
            # required preflight estimate is configured.
            pass
        try:
            compute_features = {
                f"compute_type:{kind}"
                for kind in ctranslate2.get_supported_compute_types(
                    "cuda", self._cuda_device_index
                )
            }
        except Exception:
            compute_features = set()
        devices.append(
            DeviceCapabilities(
                "cuda",
                str(self._cuda_device_index),
                frozenset({"audio-f32-mono"} | compute_features),
                total_bytes,
                free_bytes,
            )
        )
        return tuple(devices)
