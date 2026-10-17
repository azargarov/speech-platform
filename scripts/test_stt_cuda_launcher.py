from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.stt_cuda_launcher import (
    DiagnosticLauncher,
    ProcessOutcome,
    SubprocessRunner,
    classify_output,
)


IMAGE = "sha256:" + "a" * 64


class FakeRunner:
    def __init__(
        self,
        *,
        started=True,
        exit_code=0,
        timed_out=False,
        exit_confirmed=True,
        harness=False,
        output=b"",
        fail=False,
    ):
        self.started = started
        self.exit_code = exit_code
        self.timed_out = timed_out
        self.exit_confirmed = exit_confirmed
        self.harness = harness
        self.output = output
        self.fail = fail
        self.command = None

    def run(self, command, *, timeout_seconds, grace_seconds, stdout_path, stderr_path):
        self.command = command
        if self.fail:
            raise RuntimeError("sensitive /local/path and token=secret-value")
        if self.started and "--cidfile" in command:
            Path(command[command.index("--cidfile") + 1]).write_text("c" * 64)
        for path in (stdout_path, stderr_path):
            path.write_text(json.dumps(classify_output(self.output, False)) + "\n")
            os.chmod(path, 0o600)
        if self.harness:
            Path(command[command.index("--harness-output") + 1]).write_text(
                '{"outcome":"pass"}\n'
            )
        return ProcessOutcome(
            self.started,
            self.exit_code,
            self.timed_out,
            self.timed_out,
            self.timed_out,
            self.exit_confirmed,
            "FileNotFoundError" if not self.started else None,
            "2026-10-17T00:00:00Z",
            "2026-10-17T00:00:01Z",
            classify_output(self.output, False),
            classify_output(self.output, False),
        )


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "attempts"

    def launch(self, runner):
        return DiagnosticLauncher(self.root, runner).run(
            "attempt-001",
            [
                "docker",
                "run",
                "--network",
                "none",
                "--user",
                "65532:65532",
                "--name",
                "attempt-001",
                "--cidfile",
                "{attempt_dir}/container.id",
                "--harness-output",
                "{harness_dir}/harness-report.json",
            ],
            image_id=IMAGE,
            container_name="attempt-001",
            platform="linux/amd64",
            lock_sha256="b" * 64,
            timeout_seconds=180,
            grace_seconds=5,
        )

    def test_success_missing_and_present_harness_report(self):
        missing = self.launch(FakeRunner())
        self.assertEqual(missing["outcome"], "harness_report_missing")
        # A separate attempt demonstrates the harness report is kept by the launcher.
        report = DiagnosticLauncher(self.root, FakeRunner(harness=True)).run(
            "attempt-002",
            [
                "docker",
                "run",
                "--network=none",
                "--user=65532:65532",
                "--harness-output",
                "{harness_dir}/harness-report.json",
            ],
            image_id=IMAGE,
            container_name="attempt-002",
            platform="linux/amd64",
            timeout_seconds=180,
            grace_seconds=5,
        )
        self.assertEqual(report["outcome"], "completed")
        self.assertTrue(
            (self.root / "attempt-002" / "harness" / "harness-report.json").exists()
        )

    def test_nonzero_exit_and_launch_failure_are_persisted(self):
        report = self.launch(FakeRunner(exit_code=1))
        self.assertEqual(report["outcome"], "container_start_or_process_failed")
        self.assertEqual(report["failure_layer"], "container_start_or_process")
        self.assertEqual(report["process"]["exit_code"], 1)
        self.assertEqual(
            (self.root / "attempt-001" / "launcher-report.json").stat().st_mode & 0o777,
            0o600,
        )
        self.root = Path(self.tmp.name) / "launch-failure"
        failed = self.launch(FakeRunner(started=False))
        self.assertEqual(failed["outcome"], "launch_failed")

    def test_runner_exception_still_writes_launch_report_and_safe_capture_files(self):
        with self.assertRaises(RuntimeError):
            self.launch(FakeRunner(fail=True))
        directory = self.root / "attempt-001"
        data = (directory / "launcher-report.json").read_text()
        self.assertNotIn("/local/path", data)
        self.assertNotIn("secret-value", data)
        self.assertEqual(json.loads(data)["outcome"], "launcher_failed")
        self.assertTrue((directory / "stdout.json").exists())
        self.assertTrue((directory / "stderr.json").exists())

    def test_timeout_forced_termination_and_unconfirmed_exit(self):
        report = self.launch(
            FakeRunner(exit_code=None, timed_out=True, exit_confirmed=False)
        )
        self.assertEqual(report["outcome"], "cleanup_unconfirmed")
        self.assertTrue(report["process"]["termination_requested"])
        self.assertTrue(report["process"]["kill_requested"])
        self.assertFalse(report["process"]["exit_confirmed"])

    def test_docker_exit_codes_have_conservative_failure_layers(self):
        for exit_code, expected in (
            (125, "docker_cli_or_daemon"),
            (126, "container_exec"),
            (127, "container_exec"),
            (1, "container_start_or_process"),
        ):
            with self.subTest(exit_code=exit_code):
                root = Path(self.tmp.name) / f"exit-{exit_code}"
                report = DiagnosticLauncher(root, FakeRunner(exit_code=exit_code)).run(
                    "attempt",
                    [
                        "docker",
                        "run",
                        "--network",
                        "none",
                        "--user",
                        "65532:65532",
                        "--cidfile",
                        "{attempt_dir}/container.id",
                    ],
                    image_id=IMAGE,
                    container_name="attempt",
                    platform="linux/amd64",
                    timeout_seconds=180,
                    grace_seconds=5,
                )
                self.assertEqual(report["failure_layer"], expected)

    def test_output_capture_is_classified_redacted_and_bounded(self):
        long_private = b"transcript " + b"x" * 100
        result = classify_output(long_private, True)
        self.assertNotIn("transcript", json.dumps(result))
        self.assertTrue(result["truncated"])
        self.assertEqual(result["classifications"], ["unclassified_output_redacted"])
        self.assertEqual(
            classify_output(b"permission denied /private/file", False)[
                "classifications"
            ],
            ["permission_denied"],
        )
        self.assertEqual(
            classify_output(
                b'exec: "python3": executable file not found in $PATH', False
            )["classifications"],
            ["executable_unavailable"],
        )
        self.assertEqual(
            classify_output(b"ModuleNotFoundError: No module named 'yaml'", False)[
                "classifications"
            ],
            ["python_import_failure"],
        )
        self.assertEqual(
            classify_output(b"invalid mount config for type bind", False)[
                "classifications"
            ],
            ["mount_setup_failure"],
        )
        report = self.launch(FakeRunner(output=long_private))
        directory = self.root / "attempt-001"
        for filename in ("stdout.json", "stderr.json"):
            content = (directory / filename).read_text()
            self.assertNotIn("transcript", content)
            self.assertNotIn("x" * 40, content)
            self.assertEqual(stat.S_IMODE((directory / filename).stat().st_mode), 0o600)
        self.assertEqual(report["outcome"], "harness_report_missing")

    def test_atomic_launcher_report_and_evidence_survives_cleanup(self):
        self.launch(FakeRunner(exit_code=2, output=b"daemon unavailable"))
        attempt = self.root / "attempt-001"
        self.assertEqual(
            stat.S_IMODE((attempt / "launcher-report.json").stat().st_mode), 0o600
        )
        self.assertEqual(list(attempt.glob(".*.tmp")), [])
        # Container cleanup is intentionally independent of the attempt directory.
        self.assertFalse((attempt / "container").exists())
        self.assertTrue((attempt / "launcher-report.json").exists())
        self.assertTrue((attempt / "stderr.json").exists())

    def test_retention_limit_refuses_unbounded_attempt_creation(self):
        launcher = DiagnosticLauncher(self.root, FakeRunner(), max_attempts=1)
        command = ["docker", "run", "--network", "none", "--user", "65532:65532"]
        launcher.run(
            "first",
            command,
            image_id=IMAGE,
            container_name="first",
            platform="linux/amd64",
            timeout_seconds=180,
            grace_seconds=5,
        )
        with self.assertRaisesRegex(RuntimeError, "retention limit"):
            launcher.run(
                "second",
                command,
                image_id=IMAGE,
                container_name="second",
                platform="linux/amd64",
                timeout_seconds=180,
                grace_seconds=5,
            )

    def test_shared_group_is_limited_to_harness_mount_subdirectory(self):
        runner = FakeRunner()
        launcher = DiagnosticLauncher(self.root, runner, shared_gid=os.getgid())
        launcher.run(
            "group-attempt",
            ["docker", "run", "--network", "none", "--user", "65532:65532"],
            image_id=IMAGE,
            container_name="group-attempt",
            platform="linux/amd64",
            timeout_seconds=180,
            grace_seconds=5,
        )
        attempt = self.root / "group-attempt"
        self.assertEqual(stat.S_IMODE(attempt.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((attempt / "harness").stat().st_mode), 0o2770)
        self.assertEqual(
            stat.S_IMODE((attempt / "launcher-report.json").stat().st_mode), 0o600
        )

    def test_static_report_mount_failure_is_persisted_without_running_docker(self):
        runner = FakeRunner()
        group = os.getgid()
        report = DiagnosticLauncher(self.root, runner, shared_gid=group).run(
            "static-failure",
            [
                "docker",
                "run",
                "--network",
                "none",
                "--read-only",
                "--user",
                "65532:65532",
                "--group-add",
                str(group + 1),
                "--mount",
                "type=bind,src={harness_dir},dst=/results",
            ],
            image_id=IMAGE,
            container_name="static-failure",
            platform="linux/amd64",
            timeout_seconds=180,
            grace_seconds=5,
        )
        self.assertEqual(report["outcome"], "preflight_failed")
        self.assertEqual(
            report["diagnostic_code"], "report_mount_supplementary_group_mismatch"
        )
        self.assertIsNone(runner.command)
        self.assertTrue(
            (self.root / "static-failure" / "launcher-report.json").is_file()
        )

    def test_container_report_mount_failure_has_fixed_safe_classification(self):
        result = classify_output(
            b'{"diagnostic_code": "report_mount_write_failed", '
            b'"failed_stage": "report_mount_validation"}',
            False,
        )
        self.assertEqual(result["classifications"], ["report_mount_unwritable"])

    def test_docker_boundary_rejects_network_ports_and_root(self):
        base = ["docker", "run", "--network", "none", "--user", "65532:65532"]
        for index, extra in enumerate(
            (
                ["--publish", "8080:8080"],
                ["--user", "0:0"],
            )
        ):
            with self.subTest(extra=extra):
                with self.assertRaises(ValueError):
                    DiagnosticLauncher(
                        Path(self.tmp.name) / ("reject-" + str(index)),
                        FakeRunner(),
                    ).run(
                        "attempt",
                        base + extra,
                        image_id=IMAGE,
                        container_name="attempt",
                        platform="linux/amd64",
                        timeout_seconds=180,
                        grace_seconds=5,
                    )

    def test_readonly_parent_bind_requires_existing_nested_target(self):
        from scripts.stt_cuda_launcher import validate_docker_invocation

        source = Path(self.tmp.name) / "input"
        source.mkdir()
        audio = Path(self.tmp.name) / "audio.m4a"
        audio.write_bytes(b"fixture")
        command = [
            "docker",
            "run",
            "--network",
            "none",
            "--user",
            "65532:65532",
            "--mount",
            f"type=bind,src={source},dst=/input,readonly",
            "--mount",
            f"type=bind,src={audio},dst=/input/smoke-audio,readonly",
        ]
        with self.assertRaisesRegex(ValueError, "nested bind target must exist"):
            validate_docker_invocation(command)

        (source / "smoke-audio").touch()
        validate_docker_invocation(command)

    def test_cuda_http_invocation_requires_explicit_configured_limits(self):
        from scripts.stt_cuda_launcher import validate_docker_invocation

        sources = Path(self.tmp.name)
        for name in ("input", "models", "configs", "scripts", "services", "results"):
            (sources / name).mkdir(exist_ok=True)
        image = IMAGE
        command = [
            "docker",
            "run",
            "--network",
            "none",
            "--platform",
            "linux/amd64",
            "--pull",
            "never",
            "--read-only",
            "--user",
            "65532:65532",
            "--group-add",
            "1000",
            "--entrypoint",
            "python",
            "--gpus",
            "device=0",
            "--memory",
            str(8 * 1024**3),
            "--cpus",
            "4",
            "--pids-limit",
            "128",
        ]
        for name, destination in (
            ("input", "/input"),
            ("models", "/models"),
            ("configs", "/opt/validation/configs"),
            ("scripts", "/opt/validation/scripts"),
            ("services", "/opt/validation/services"),
        ):
            command.extend(
                [
                    "--mount",
                    f"type=bind,src={sources / name},dst={destination},readonly",
                ]
            )
        command.extend(
            [
                "--mount",
                f"type=bind,src={sources / 'results'},dst=/results",
                image,
                "scripts/stt_cuda_http_smoke.py",
            ]
        )
        profile = validate_docker_invocation(
            command,
            cuda_http_profile=True,
            expected_gpu_index=0,
            expected_image_id=image,
            expected_platform="linux/amd64",
            expected_shared_gid=1000,
        )
        self.assertEqual(profile["gpu_device_index"], 0)
        self.assertEqual(profile["memory_limit_bytes"], 8 * 1024**3)
        self.assertEqual(profile["cpu_limit"], 4)
        self.assertEqual(profile["pids_limit"], 128)

    def test_cuda_http_invocation_rejects_gpu_override_and_missing_resource_limit(self):
        from scripts.stt_cuda_launcher import validate_docker_invocation

        # The complete valid argument vector is built by the preceding test; these
        # focused cases prove an operator override cannot silently change GPU policy.
        command = [
            "docker",
            "run",
            "--network=none",
            "--platform=linux/amd64",
            "--pull=never",
            "--read-only",
            "--user=65532:65532",
            "--group-add=1000",
            "--entrypoint=python",
            "--gpus=device=1",
            f"--memory={8 * 1024**3}",
            "--cpus=4",
            "--pids-limit=128",
            IMAGE,
        ]
        with self.assertRaisesRegex(ValueError, "GPU selection"):
            validate_docker_invocation(
                command,
                cuda_http_profile=True,
                expected_gpu_index=0,
                expected_image_id=IMAGE,
                expected_platform="linux/amd64",
                expected_shared_gid=1000,
            )
        command[command.index("--gpus=device=1")] = "--gpus=device=0"
        command.remove(f"--memory={8 * 1024**3}")
        with self.assertRaisesRegex(ValueError, "memory limit"):
            validate_docker_invocation(
                command,
                cuda_http_profile=True,
                expected_gpu_index=0,
                expected_image_id=IMAGE,
                expected_platform="linux/amd64",
                expected_shared_gid=1000,
            )

    def test_real_runner_without_docker_captures_only_sanitized_bounded_output(self):
        out = Path(self.tmp.name) / "out.json"
        err = Path(self.tmp.name) / "err.json"
        result = SubprocessRunner().run(
            [
                sys.executable,
                "-c",
                "import sys; print('secret transcript words'); print('permission denied', file=sys.stderr)",
            ],
            timeout_seconds=2,
            grace_seconds=0.2,
            stdout_path=out,
            stderr_path=err,
        )
        self.assertEqual(result.exit_code, 0)
        self.assertNotIn("secret transcript", out.read_text())
        self.assertEqual(
            json.loads(err.read_text())["classifications"], ["permission_denied"]
        )

    def test_real_runner_timeout_terminates_and_reaps_fake_process(self):
        out = Path(self.tmp.name) / "out.json"
        err = Path(self.tmp.name) / "err.json"
        code = "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(10)"
        result = SubprocessRunner().run(
            [sys.executable, "-c", code],
            timeout_seconds=0.15,
            grace_seconds=0.1,
            stdout_path=out,
            stderr_path=err,
        )
        self.assertTrue(result.timed_out)
        self.assertTrue(result.termination_requested)
        self.assertTrue(result.kill_requested)
        self.assertTrue(result.exit_confirmed)
        self.assertIsNotNone(result.exit_code)

    def test_real_runner_launch_error_is_recorded_without_message(self):
        out = Path(self.tmp.name) / "out.json"
        err = Path(self.tmp.name) / "err.json"
        result = SubprocessRunner().run(
            [str(Path(self.tmp.name) / "missing-executable")],
            timeout_seconds=1,
            grace_seconds=0.1,
            stdout_path=out,
            stderr_path=err,
        )
        self.assertFalse(result.started)
        self.assertEqual(result.start_error_class, "FileNotFoundError")
        self.assertNotIn(self.tmp.name, json.dumps(result.__dict__))


if __name__ == "__main__":
    unittest.main()
