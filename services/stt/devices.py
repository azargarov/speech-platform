"""Device policy selection without hardware-specific imports."""

from services.stt.domain import (
    DeviceCapabilities,
    DeviceRequirements,
    SpeechFailure,
    FailureCode,
)


def select_device(
    mode: str,
    preference: tuple[str, ...],
    requirements: DeviceRequirements,
    available: tuple[DeviceCapabilities, ...],
) -> DeviceCapabilities:
    permitted = (mode,) if mode != "auto" else preference
    for kind in permitted:
        if kind not in requirements.allowed_kinds:
            continue
        kind_features = dict(requirements.required_features_by_kind).get(
            kind, frozenset()
        )
        for device in available:
            required = requirements.required_features | kind_features
            if device.kind != kind or not required.issubset(device.features):
                continue
            estimate = requirements.estimated_peak_memory_bytes
            if kind == "cuda" and estimate is not None:
                if device.free_memory_bytes is None:
                    continue
                if device.free_memory_bytes < estimate:
                    continue
            return device
    raise SpeechFailure(
        FailureCode.DEVICE_UNAVAILABLE,
        "no compatible device satisfies the configured policy",
    )
