import unittest

from services.stt.devices import select_device
from services.stt.domain import (
    DeviceCapabilities,
    DeviceRequirements,
    FailureCode,
    SpeechFailure,
    safe_error,
)


class DomainContractTests(unittest.TestCase):
    def test_safe_error_mapping_has_stable_non_sensitive_fields(self):
        status, error = safe_error(
            SpeechFailure(
                FailureCode.UNSUPPORTED_MEDIA_TYPE, "unsupported audio media type"
            )
        )
        self.assertEqual(status, 415)
        self.assertEqual(
            {"code": error.code, "message": error.message},
            {
                "code": "unsupported_media_type",
                "message": "unsupported audio media type",
            },
        )
        status, error = safe_error(
            SpeechFailure(FailureCode.UNKNOWN_MODEL, "unknown model alias")
        )
        self.assertEqual(status, 404)
        self.assertEqual(error.code, "unknown_model")

    def test_safe_errors_hide_paths_credentials_audio_and_native_diagnostics(self):
        diagnostics = (
            "/private/audio/russian.m4a",
            "token=sk-local-example-12345",
            "transcript: my secret words",
            "CUDA_ERROR_OUT_OF_MEMORY at /opt/engine/libnative.so:411",
        )
        for diagnostic in diagnostics:
            with self.subTest(diagnostic=diagnostic):
                failure = SpeechFailure(FailureCode.BACKEND_FAILED, diagnostic)
                status, error = safe_error(failure)
                self.assertEqual(status, 500)
                self.assertEqual(error.code, "backend_failed")
                self.assertEqual(error.message, "inference failed")
                self.assertEqual(failure.diagnostic, diagnostic)
                self.assertNotIn(diagnostic, error.message)

    def test_device_policy_is_deterministic_and_explicit_cuda_fails_closed(self):
        cpu = DeviceCapabilities("cpu", "cpu")
        cuda = DeviceCapabilities("cuda", "visible-0", free_memory_bytes=2048)
        requirement = DeviceRequirements(
            frozenset({"cpu", "cuda"}), estimated_peak_memory_bytes=1024
        )
        self.assertEqual(
            select_device("auto", ("cuda", "cpu"), requirement, (cpu, cuda)), cuda
        )
        self.assertEqual(select_device("cpu", ("cpu",), requirement, (cuda, cpu)), cpu)
        with self.assertRaises(SpeechFailure) as caught:
            select_device("cuda", ("cuda",), requirement, (cpu,))
        self.assertEqual(caught.exception.code, FailureCode.DEVICE_UNAVAILABLE)
        insufficient = DeviceCapabilities("cuda", "visible-0", free_memory_bytes=1)
        with self.assertRaises(SpeechFailure):
            select_device("cuda", ("cuda",), requirement, (insufficient,))
        unknown = DeviceCapabilities("cuda", "visible-0", free_memory_bytes=None)
        with self.assertRaises(SpeechFailure):
            select_device("cuda", ("cuda",), requirement, (unknown,))
        enough = DeviceCapabilities("cuda", "visible-0", free_memory_bytes=1024)
        self.assertEqual(
            select_device("cuda", ("cuda",), requirement, (enough,)), enough
        )


if __name__ == "__main__":
    unittest.main()
