from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from scripts.project_lock import LockError, ProjectLock
from scripts.stt_deployment import UncertainSubprocessError, _run


class ProjectLockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "locks"
        self.root.mkdir(mode=0o700)

    def tearDown(self):
        self.temp.cleanup()

    def _child(self, project: str, root: Path, *, hold: bool = False):
        code = (
            "import sys,time; from scripts.project_lock import ProjectLock; "
            "lock=ProjectLock(sys.argv[1],sys.argv[2]).acquire(); "
            "print('LOCKED',flush=True); "
            "time.sleep(60) if sys.argv[3]=='hold' else lock.release()"
        )
        return subprocess.Popen(
            [
                sys.executable,
                "-c",
                code,
                project,
                str(root),
                "hold" if hold else "once",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def test_same_project_contention_across_processes_and_different_project_progress(
        self,
    ):
        holder = self._child("voice-one", self.root, hold=True)
        try:
            self.assertEqual(holder.stdout.readline().strip(), "LOCKED")
            with self.assertRaisesRegex(LockError, "already active"):
                ProjectLock("voice-one", self.root).acquire()
            with ProjectLock("voice-two", self.root):
                pass
        finally:
            holder.terminate()
            holder.wait(timeout=5)
            holder.stdout.close()
            holder.stderr.close()
        with ProjectLock("voice-one", self.root):
            pass

    def test_stale_pid_information_does_not_grant_ownership(self):
        with ProjectLock("voice", self.root) as lock:
            os.write(lock.fd, b"owner_pid=99999999\n")
        with ProjectLock("voice", self.root):
            pass

    def test_symlink_and_unsafe_lock_file_permissions_are_rejected(self):
        target = self.root / "target"
        target.write_text("")
        (self.root / "voice.lock").symlink_to(target)
        with self.assertRaisesRegex(LockError, "could not safely acquire"):
            ProjectLock("voice", self.root).acquire()
        (self.root / "voice.lock").unlink()
        path = self.root / "voice.lock"
        path.touch(mode=0o600)
        path.chmod(0o644)
        with self.assertRaisesRegex(LockError, "permissions"):
            ProjectLock("voice", self.root).acquire()

    def test_symlink_root_and_unsafe_root_permissions_are_rejected(self):
        linked_root = Path(self.temp.name) / "linked-locks"
        linked_root.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(LockError, "filesystem validation"):
            ProjectLock("voice", linked_root).acquire()
        self.root.chmod(0o750)
        with self.assertRaisesRegex(LockError, "permissions"):
            ProjectLock("voice", self.root).acquire()
        self.root.chmod(0o700)

    def test_replacement_is_detected_and_lock_file_is_never_unlinked(self):
        lock = ProjectLock("voice", self.root).acquire()
        path = lock.path
        inode = path.stat().st_ino
        path.rename(self.root / "displaced")
        path.touch(mode=0o600)
        with self.assertRaisesRegex(LockError, "unexpectedly replaced"):
            lock.mark_mutation_started()
        lock.release()
        self.assertTrue(path.exists())
        self.assertNotEqual(inode, path.stat().st_ino)

    def test_process_exit_and_holder_termination_release_flock(self):
        child = self._child("voice", self.root)
        self.assertEqual(child.stdout.readline().strip(), "LOCKED")
        self.assertEqual(child.wait(timeout=5), 0)
        child.stdout.close()
        child.stderr.close()
        with ProjectLock("voice", self.root):
            pass

        holder = self._child("voice", self.root, hold=True)
        self.assertEqual(holder.stdout.readline().strip(), "LOCKED")
        holder.send_signal(signal.SIGTERM)
        holder.wait(timeout=5)
        holder.stdout.close()
        holder.stderr.close()
        with ProjectLock("voice", self.root):
            pass

    def test_timeout_kills_and_reaps_long_running_compose_process_group(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            _run([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.1)

    def test_locked_timeout_reports_uncertain_outcome_and_leaves_gate(self):
        with ProjectLock("voice", self.root) as lock:
            lock.mark_mutation_started()
            with self.assertRaisesRegex(
                UncertainSubprocessError, "outcome is uncertain"
            ):
                _run(
                    [sys.executable, "-c", "import time; time.sleep(30)"],
                    timeout=0.1,
                    lock_fd=lock.fd,
                )
        with self.assertRaisesRegex(LockError, "operator review"):
            ProjectLock("voice", self.root).acquire()

    def test_signal_interrupt_kills_child_before_coordinator_returns(self):
        child_code = (
            "import os,signal,sys,time; from scripts.stt_deployment import _run; "
            "open(sys.argv[1],'w').write(str(os.getpid())); "
            "_run([sys.executable,'-c','import time; time.sleep(60)'])"
        )
        child = subprocess.Popen(
            [sys.executable, "-c", child_code, str(self.root / "coordinator.pid")],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        pid_path = self.root / "coordinator.pid"
        deadline = time.monotonic() + 5
        while not pid_path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(pid_path.exists())
        child.send_signal(signal.SIGINT)
        child.wait(timeout=5)
        child.stderr.close()
        self.assertNotEqual(child.returncode, 0)

    def test_compose_child_keeps_lock_after_coordinator_is_killed(self):
        coordinator_pid_file = self.root / "coordinator.pid"
        child_pid_file = self.root / "compose.pid"
        coordinator_code = (
            "import os,sys; from scripts.project_lock import ProjectLock; "
            "from scripts.stt_deployment import _run; "
            "lock=ProjectLock('voice',sys.argv[1]).acquire(); "
            "lock.mark_mutation_started(); "
            "open(sys.argv[2],'w').write(str(os.getpid())); "
            "_run([sys.executable,'-c',"
            "'import os,sys,time; open(sys.argv[1],\\\"w\\\").write(str(os.getpid())); time.sleep(60)',"
            "sys.argv[3]],lock_fd=lock.fd,timeout=120)"
        )
        coordinator = subprocess.Popen(
            [
                sys.executable,
                "-c",
                coordinator_code,
                str(self.root),
                str(coordinator_pid_file),
                str(child_pid_file),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 5
        while not child_pid_file.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(child_pid_file.exists())
        child_pid = int(child_pid_file.read_text())
        coordinator.kill()
        coordinator.wait(timeout=5)
        with self.assertRaisesRegex(LockError, "already active"):
            ProjectLock("voice", self.root).acquire()
        os.kill(child_pid, signal.SIGKILL)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.kill(child_pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.02)
        with self.assertRaisesRegex(LockError, "operator review"):
            ProjectLock("voice", self.root).acquire()

    def test_descendant_retaining_inherited_lock_blocks_until_exit(self):
        lock = ProjectLock("voice", self.root).acquire()
        lock.mark_mutation_started()
        code = (
            "import subprocess,sys,time; fd=int(sys.argv[1]); "
            "subprocess.Popen([sys.executable,'-c','import time; time.sleep(1.2)'],"
            "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,"
            "pass_fds=(fd,)); time.sleep(.1)"
        )
        child = subprocess.Popen(
            [sys.executable, "-c", code, str(lock.fd)],
            pass_fds=(lock.fd,),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.assertEqual(child.wait(timeout=5), 0)
        lock.release()
        with self.assertRaisesRegex(LockError, "already active"):
            ProjectLock("voice", self.root).acquire()
        time.sleep(1.4)
        with self.assertRaisesRegex(LockError, "operator review"):
            ProjectLock("voice", self.root).acquire()

    def test_runner_flags_and_terminates_descendants_after_normal_child_exit(self):
        with ProjectLock("voice", self.root) as lock:
            lock.mark_mutation_started()
            code = (
                "import subprocess,sys,time; fd=int(sys.argv[1]); "
                "subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],"
                "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,"
                "pass_fds=(fd,)); time.sleep(.1)"
            )
            with self.assertRaisesRegex(UncertainSubprocessError, "descendants"):
                _run([sys.executable, "-c", code, str(lock.fd)], lock_fd=lock.fd)
        with self.assertRaisesRegex(LockError, "operator review"):
            ProjectLock("voice", self.root).acquire()

    def test_interrupted_mutation_blocks_future_coordinators(self):
        lock = ProjectLock("voice", self.root).acquire()
        lock.mark_mutation_started()
        lock.release()
        with self.assertRaisesRegex(LockError, "operator review"):
            ProjectLock("voice", self.root).acquire()

    def test_recovery_requires_exclusive_lock_and_records_explicit_resolution(self):
        lock = ProjectLock("voice", self.root).acquire()
        lock.mark_mutation_started()
        lock.release()
        recovery = ProjectLock("voice", self.root).acquire(recovery=True)
        try:
            with self.assertRaisesRegex(LockError, "already active"):
                ProjectLock("voice", self.root).acquire(recovery=True)
            recovery.resolve_uncertainty(
                approval_reference="change-123",
                determination="runtime and artifacts inspected; mutation complete",
            )
        finally:
            recovery.release()
        audits = list(self.root.glob("voice.resolved.*"))
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0].stat().st_mode & 0o777, 0o600)
        with ProjectLock("voice", self.root):
            pass


if __name__ == "__main__":
    unittest.main()
