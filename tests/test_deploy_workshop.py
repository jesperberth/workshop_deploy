import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import deploy_workshop


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.credentials_path = Path(self.temp_dir.name) / "credentials"
        self.credentials_path.write_text("[default]\n", encoding="utf-8")
        self.containers = [
            {"name": "azure", "image": "azure:latest", "memory_mb": 1500},
            {"name": "devbox", "image": "devbox:latest", "memory_mb": 300},
            {"name": "gpunode", "image": "gpunode:latest", "memory_mb": 300},
        ]

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_selection_prioritizes_first_stage_and_backfills_smaller_job(self):
        ready_jobs = [
            {"stage": 1, "order": 0, "container": self.containers[1]},
            {"stage": 0, "order": 1, "container": self.containers[0]},
            {"stage": 1, "order": 2, "container": self.containers[1]},
        ]

        selected, remaining_mb = deploy_workshop.select_ready_jobs(ready_jobs, 1800)

        self.assertEqual([job["stage"] for job in selected], [0, 1])
        self.assertEqual([job["order"] for job in selected], [1, 0])
        self.assertEqual(remaining_mb, 0)

    def test_scheduler_runs_each_users_stages_in_order(self):
        launches = []

        def runner(username, password, container, credentials_path, azure_environment):
            launches.append((username, container["name"]))
            return True

        successful, failed = deploy_workshop.schedule_container_jobs(
            [{"Username": "work1", "Password": "secret"}],
            self.containers,
            self.credentials_path,
            "AzureCloud",
            total_memory_mb=4096,
            reserve_mb=512,
            available_memory_probe=lambda: 4096,
            job_runner=runner,
        )

        self.assertEqual(launches, [
            ("work1", "azure"),
            ("work1", "devbox"),
            ("work1", "gpunode"),
        ])
        self.assertEqual((successful, failed), (1, 0))

    def test_failed_stage_suppresses_dependent_stages(self):
        launches = []

        def runner(username, password, container, credentials_path, azure_environment):
            launches.append(container["name"])
            return False

        successful, failed = deploy_workshop.schedule_container_jobs(
            [{"Username": "work1", "Password": "secret"}],
            self.containers,
            self.credentials_path,
            "AzureCloud",
            total_memory_mb=4096,
            reserve_mb=512,
            available_memory_probe=lambda: 4096,
            job_runner=runner,
        )

        self.assertEqual(launches, ["azure"])
        self.assertEqual((successful, failed), (0, 1))

    def test_initial_launch_fills_first_stage_capacity(self):
        rows = [
            {"Username": f"work{index}", "Password": "secret"}
            for index in range(1, 4)
        ]
        launches = []
        launch_lock = threading.Lock()
        initial_batch_started = threading.Event()
        release_initial_batch = threading.Event()
        scheduler_result = []

        def runner(username, password, container, credentials_path, azure_environment):
            with launch_lock:
                launches.append((username, container["name"]))
                first_stage_count = sum(name == "azure" for _, name in launches)
                if first_stage_count == 2:
                    initial_batch_started.set()
            if container["name"] == "azure" and not release_initial_batch.is_set():
                release_initial_batch.wait(timeout=2)
            return True

        def run_scheduler():
            scheduler_result.append(deploy_workshop.schedule_container_jobs(
                rows,
                self.containers,
                self.credentials_path,
                "AzureCloud",
                total_memory_mb=4096,
                reserve_mb=512,
                available_memory_probe=lambda: 4096,
                job_runner=runner,
            ))

        scheduler_thread = threading.Thread(target=run_scheduler)
        scheduler_thread.start()
        try:
            self.assertTrue(initial_batch_started.wait(timeout=2))
            with launch_lock:
                self.assertEqual(len(launches), 2)
                self.assertTrue(all(name == "azure" for _, name in launches))
        finally:
            release_initial_batch.set()
            scheduler_thread.join(timeout=5)

        self.assertFalse(scheduler_thread.is_alive())
        self.assertEqual(scheduler_result, [(3, 0)])

    def test_initial_memory_probe_failure_aborts_scheduling(self):
        def failing_probe():
            raise RuntimeError("probe failed")

        with self.assertRaisesRegex(RuntimeError, "probe failed"):
            deploy_workshop.schedule_container_jobs(
                [{"Username": "work1", "Password": "secret"}],
                self.containers,
                self.credentials_path,
                "AzureCloud",
                total_memory_mb=4096,
                reserve_mb=512,
                available_memory_probe=failing_probe,
            )

    def test_live_memory_pressure_blocks_a_new_launch(self):
        probe_count = 0
        launches = []
        first_job_started = threading.Event()
        release_first_job = threading.Event()
        scheduler_result = []

        def memory_probe():
            nonlocal probe_count
            probe_count += 1
            return 2100 if probe_count == 1 else 4096

        def runner(username, password, container, credentials_path, azure_environment):
            launches.append((username, container["name"]))
            if len(launches) == 1:
                first_job_started.set()
                release_first_job.wait(timeout=2)
            return True

        def run_scheduler():
            scheduler_result.append(deploy_workshop.schedule_container_jobs(
                [
                    {"Username": "work1", "Password": "secret"},
                    {"Username": "work2", "Password": "secret"},
                ],
                self.containers,
                self.credentials_path,
                "AzureCloud",
                total_memory_mb=4096,
                reserve_mb=512,
                available_memory_probe=memory_probe,
                job_runner=runner,
            ))

        scheduler_thread = threading.Thread(target=run_scheduler)
        scheduler_thread.start()
        try:
            self.assertTrue(first_job_started.wait(timeout=2))
            self.assertEqual(launches, [("work1", "azure")])
        finally:
            release_first_job.set()
            scheduler_thread.join(timeout=5)

        self.assertFalse(scheduler_thread.is_alive())
        self.assertEqual(scheduler_result, [(2, 0)])


class ContainerJobTests(unittest.TestCase):
    def test_container_is_removed_after_completion(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            credentials_path = Path(temp_dir) / "credentials"
            credentials_path.write_text("[default]\n", encoding="utf-8")
            completed = subprocess.CompletedProcess([], 0, stdout="container-id\n", stderr="")
            removed = subprocess.CompletedProcess([], 0, stdout="container-id\n", stderr="")

            with patch("deploy_workshop.subprocess.run", side_effect=[completed, removed]) as run_mock, \
                    patch("deploy_workshop.wait_for_container", return_value=True):
                result = deploy_workshop.run_container_job(
                    "work1",
                    "secret",
                    {"name": "azure", "image": "azure:latest", "timeout_seconds": 10},
                    credentials_path,
                    "AzureCloud",
                )

        self.assertTrue(result)
        self.assertEqual(run_mock.call_args_list[-1].args[0], ["docker", "rm", "-f", "container-id"])

    def test_failed_container_logs_are_saved_before_removal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            credentials_path = Path(temp_dir) / "credentials"
            credentials_path.write_text("[default]\n", encoding="utf-8")
            launched = subprocess.CompletedProcess([], 0, stdout="container-id\n", stderr="")
            removed = subprocess.CompletedProcess([], 0, stdout="container-id\n", stderr="")

            with patch("deploy_workshop.subprocess.run", side_effect=[launched, removed]) as run_mock, \
                    patch("deploy_workshop.wait_for_container", return_value=False), \
                    patch("deploy_workshop.save_container_logs") as save_logs_mock:
                result = deploy_workshop.run_container_job(
                    "work1",
                    "secret",
                    {"name": "azure", "image": "azure:latest", "timeout_seconds": 10},
                    credentials_path,
                    "AzureCloud",
                )

        self.assertFalse(result)
        save_logs_mock.assert_called_once_with("container-id", "work1", "azure")
        self.assertEqual(run_mock.call_args_list[-1].args[0], ["docker", "rm", "-f", "container-id"])

    def test_save_container_logs_writes_combined_output(self):
        completed = subprocess.CompletedProcess([], 0, stdout="2026-08-20T12:00:00Z failed\n")

        with tempfile.TemporaryDirectory() as temp_dir, \
                patch("deploy_workshop.subprocess.run", return_value=completed) as run_mock:
            log_path = deploy_workshop.save_container_logs(
                "abcdef1234567890", "work/1", "azure node", Path(temp_dir)
            )

            self.assertEqual(
                log_path,
                Path(temp_dir) / "work_1_azure_node_abcdef123456.log"
            )
            self.assertEqual(log_path.read_text(encoding="utf-8"), completed.stdout)

        self.assertEqual(
            run_mock.call_args.args[0],
            ["docker", "logs", "--timestamps", "abcdef1234567890"]
        )


class MemoryProbeTests(unittest.TestCase):
    def test_available_memory_is_read_from_proc_meminfo(self):
        output = "MemTotal:       4194304 kB\nMemAvailable:   3145728 kB\n"
        completed = subprocess.CompletedProcess([], 0, stdout=output, stderr="")

        with patch("deploy_workshop.subprocess.run", return_value=completed):
            available_mb = deploy_workshop.detect_docker_available_memory("probe:latest")

        self.assertEqual(available_mb, 3072)


if __name__ == "__main__":
    unittest.main()
