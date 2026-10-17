"""STT composition root for the selected, strictly validated runtime profile."""

from services.stt.backends.faster_whisper import (
    FasterWhisperBackend,
    FasterWhisperOptions,
)
from services.stt.config import ApplicationConfig, DeploymentConfig
from services.stt.device_adapters import SystemDeviceProbe


class FasterWhisperFactory:
    def __init__(self, options):
        self._options = options

    def __call__(self):
        return FasterWhisperBackend(self._options)


def create_runtime(config: ApplicationConfig, deployment: DeploymentConfig):
    if config.backend_id != "faster-whisper" or config.audio_limits is None:
        raise ValueError("M02-B requires version 3 faster-whisper application config")
    if (
        config.device_mode == "cuda"
        and deployment.minimum_free_gpu_bytes_before_load is None
    ):
        raise ValueError("explicit CUDA requires a configured free-memory preflight")
    options = dict(config.backend_options)
    settings = FasterWhisperOptions(
        cpu_threads=options["cpu_threads"],
        compute_type_cpu=options["compute_type_cpu"],
        compute_type_cuda=options["compute_type_cuda"],
        beam_size=options["beam_size"],
        sample_rate_hz=config.audio_limits.sample_rate_hz,
        max_duration_seconds=config.audio_limits.max_duration_seconds,
        max_decoded_audio_bytes=config.audio_limits.max_decoded_audio_bytes,
        max_result_bytes=config.admission.max_result_bytes,
        cuda_device_index=deployment.cuda_device_index,
        minimum_free_gpu_bytes_before_load=deployment.minimum_free_gpu_bytes_before_load,
    )
    probe = SystemDeviceProbe(
        cuda_enabled=config.device_mode in {"cuda", "auto"},
        cuda_device_index=deployment.cuda_device_index,
    )
    return FasterWhisperFactory(settings), probe
