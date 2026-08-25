import argparse
import csv
import json
import subprocess
import logging
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
import re
import sys
import time

MEM_CONTAINER1_MB = 2000  # ansiblenewclass:latest
MEM_CONTAINER2_MB = 300   # ansiblenewclassstudent:latest
DEFAULT_CONFIG_FILE = 'workshop_config.json'
DEFAULT_MEMORY_RESERVE_PERCENT = 10
DEFAULT_MEMORY_RESERVE_MIN_MB = 512


def load_project_config(project_dir: Path) -> dict:
    """Load workshop config from project folder, falling back to defaults."""
    config_path = project_dir / DEFAULT_CONFIG_FILE

    default_config = {
        'users_csv': 'users.csv',
        'credentials_path': '/Users/jesper/.azure/credentials',
        'azure_environment': 'AzureCloud',
        'memory_reserve_percent': DEFAULT_MEMORY_RESERVE_PERCENT,
        'memory_reserve_min_mb': DEFAULT_MEMORY_RESERVE_MIN_MB,
        'containers': [
            {
                'name': 'instructor',
                'image': 'ansiblenewclass:latest',
                'memory_mb': MEM_CONTAINER1_MB,
                'timeout_seconds': 1200
            },
            {
                'name': 'student',
                'image': 'ansiblenewclassstudent:latest',
                'memory_mb': MEM_CONTAINER2_MB,
                'timeout_seconds': 1200
            }
        ]
    }

    if not config_path.exists():
        logging.warning(
            "Config file not found at %s. Using defaults.",
            config_path
        )
        return default_config

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        containers = config.get('containers', [])
        if not containers:
            raise ValueError("Config must define at least one container in 'containers'.")

        for index, container in enumerate(containers, start=1):
            if 'image' not in container or not container['image']:
                raise ValueError(f"Container #{index} is missing required field: image")
            container.setdefault('name', f'container_{index}')
            container.setdefault('memory_mb', 512)
            container.setdefault('timeout_seconds', 1200)

            dockerfile = container.get('dockerfile')
            if dockerfile:
                container.setdefault('build_context', '.')

        config.setdefault('users_csv', default_config['users_csv'])
        config.setdefault('credentials_path', default_config['credentials_path'])
        config.setdefault('azure_environment', default_config['azure_environment'])
        config.setdefault('memory_reserve_percent', DEFAULT_MEMORY_RESERVE_PERCENT)
        config.setdefault('memory_reserve_min_mb', DEFAULT_MEMORY_RESERVE_MIN_MB)

        reserve_percent = int(config['memory_reserve_percent'])
        reserve_min_mb = int(config['memory_reserve_min_mb'])
        if not 0 <= reserve_percent < 100:
            raise ValueError("memory_reserve_percent must be between 0 and 99")
        if reserve_min_mb < 0:
            raise ValueError("memory_reserve_min_mb cannot be negative")
        return config

    except (json.JSONDecodeError, OSError, ValueError) as e:
        logging.error("Failed to load config file %s: %s", config_path, str(e))
        sys.exit(1)


def resolve_path(path_value: str, project_dir: Path) -> Path:
    """Resolve absolute and relative paths. Relative paths are resolved from project dir first."""
    candidate = Path(path_value)
    if candidate.is_absolute():
        return candidate

    from_project_dir = (project_dir / candidate).resolve()
    if from_project_dir.exists():
        return from_project_dir

    return (Path.cwd() / candidate).resolve()

def detect_docker_total_memory() -> int:
    """Return the Docker VM's total memory in MB."""
    result = subprocess.run(
        ['docker', 'info', '--format', '{{json .MemTotal}}'],
        capture_output=True, text=True, check=False
    )
    if result.returncode == 0:
        try:
            total_mb = int(result.stdout.strip()) // (1024 * 1024)
            if total_mb > 0:
                return total_mb
        except ValueError:
            pass
    raise RuntimeError(f"Could not detect Docker total memory: {result.stderr.strip()}")


def detect_docker_available_memory(probe_image: str) -> int:
    """Return the Docker VM's current MemAvailable value in MB."""
    result = subprocess.run(
        [
            'docker', 'run', '--rm', '--entrypoint', 'cat',
            probe_image, '/proc/meminfo'
        ],
        capture_output=True, text=True, check=False
    )
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            if line.startswith('MemAvailable:'):
                try:
                    available_kb = int(line.split()[1])
                    if available_kb > 0:
                        return available_kb // 1024
                except (IndexError, ValueError):
                    break
    raise RuntimeError(f"Could not detect Docker available memory: {result.stderr.strip()}")


def container_memory_mb(container: dict) -> int:
    """Return a validated scheduling reservation for a container."""
    memory_mb = int(container.get('memory_mb', 512))
    return memory_mb if memory_mb > 0 else 512


def calculate_memory_reserve(total_mb: int, percent: int, minimum_mb: int) -> int:
    """Calculate memory kept free for Docker and its Linux VM."""
    return max(minimum_mb, total_mb * percent // 100)


def setup_logging(log_to_file: bool = False, verbose: bool = False) -> None:
    """Configure console logging and optional file logging."""
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_to_file:
        handlers.append(logging.FileHandler('container_deployment.log'))

    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=handlers
    )


def build_container_images(containers: list[dict], project_dir: Path, azure_environment: str) -> None:
    """Build container images for config entries that define dockerfile."""
    for container in containers:
        dockerfile = container.get('dockerfile')
        if not dockerfile:
            logging.info(
                "Skipping build for container '%s' (no dockerfile configured).",
                container['name']
            )
            continue

        image = container['image']
        dockerfile_path = resolve_path(dockerfile, project_dir)
        build_context_path = resolve_path(container.get('build_context', '.'), project_dir)

        if not dockerfile_path.exists():
            raise FileNotFoundError(f"Dockerfile not found for image {image}: {dockerfile_path}")
        if not build_context_path.exists() or not build_context_path.is_dir():
            raise FileNotFoundError(f"Build context not found for image {image}: {build_context_path}")

        logging.info(
            "Building container '%s' image %s using Dockerfile %s and context %s",
            container['name'],
            image,
            dockerfile_path,
            build_context_path
        )

        build_result = subprocess.run(
            [
                'docker', 'build',
                '-f', str(dockerfile_path),
                '--build-arg', f'AZURE_PROFILE={azure_environment}',
                '-t', image,
                str(build_context_path)
            ],
            text=True,
            capture_output=True,
            check=False
        )

        if build_result.returncode != 0:
            logging.error(
                "Failed building image %s. Docker output: %s",
                image,
                build_result.stderr
            )
            raise RuntimeError(f"Image build failed for {image}")

        logging.info("Image build complete: %s", image)

def wait_for_container(container_id: str, timeout: int = 1200, container_label: str = '') -> bool:
    """
    Wait for a container to complete execution
    Returns True if container completed successfully, False otherwise
    """
    try:
        start_time = time.time()
        last_progress_log = 0
        label = container_label or container_id

        logging.info("Waiting for container %s to complete (timeout=%ss)", label, timeout)

        while True:
            elapsed = int(time.time() - start_time)
            if elapsed > timeout:
                logging.error(f"Container {container_id} timed out after {timeout} seconds")
                return False

            result = subprocess.run(
                ['docker', 'inspect', '--format', '{{.State.Status}}', container_id],
                capture_output=True,
                text=True,
                check=False
            )

            if result.returncode != 0:
                logging.error(f"Error checking container status: {result.stderr}")
                return False

            status = result.stdout.strip()
            if elapsed - last_progress_log >= 30:
                logging.info("Container %s status=%s elapsed=%ss", label, status, elapsed)
                last_progress_log = elapsed

            if status == 'exited':
                # Check exit code
                exit_code_result = subprocess.run(
                    ['docker', 'inspect', '--format', '{{.State.ExitCode}}', container_id],
                    capture_output=True,
                    text=True,
                    check=False
                )
                exit_code = exit_code_result.stdout.strip()
                success = exit_code == '0'
                logging.info(
                    "Container %s finished with exit code %s (%s)",
                    label,
                    exit_code,
                    'success' if success else 'failure'
                )
                return success
            
            time.sleep(5)  # Wait before checking again
            
    except subprocess.SubprocessError as e:
        logging.error(f"Error monitoring container {container_id}: {str(e)}")
        return False


def save_container_logs(container_id: str, username: str, container_name: str,
                        log_dir: Path = Path('failed_container_logs')) -> Path | None:
    """Save combined Docker output for a failed container before cleanup."""
    safe_username = re.sub(r'[^A-Za-z0-9_.-]+', '_', username)
    safe_container_name = re.sub(r'[^A-Za-z0-9_.-]+', '_', container_name)
    log_path = log_dir / f'{safe_username}_{safe_container_name}_{container_id[:12]}.log'

    try:
        logs_result = subprocess.run(
            ['docker', 'logs', '--timestamps', container_id],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False
        )
        if logs_result.returncode != 0:
            logging.warning(
                "Could not read logs for container %s: %s",
                container_id, logs_result.stdout.strip()
            )
            return None

        log_dir.mkdir(parents=True, exist_ok=True)
        log_path.write_text(logs_result.stdout, encoding='utf-8')
        logging.error("Saved failed container logs to %s", log_path.resolve())
        return log_path
    except (OSError, subprocess.SubprocessError) as error:
        logging.warning("Could not save logs for container %s: %s", container_id, error)
        return None

def run_container_job(username: str, password: str, container: dict,
                      credentials_path: Path, azure_environment: str) -> bool:
    """Launch, monitor, and clean up one workshop container."""
    container_id = ''
    try:
        if not username or not password:
            raise ValueError("Username and password cannot be empty")

        if not credentials_path.exists():
            raise FileNotFoundError(f"Credentials file not found at {credentials_path}")

        name = container['name']
        image = container['image']
        timeout = int(container.get('timeout_seconds', 1200))
        result = subprocess.run(
            [
                'docker', 'run', '-d',
                '--mount', f'type=bind,source={credentials_path},target=/root/.azure/credentials',
                '-e', f'username={username}',
                '-e', f'password={password}',
                '-e', f'AZURE_ENVIRONMENT={azure_environment}',
                '-e', f'ARM_ENVIRONMENT={azure_environment}',
                image
            ],
            text=True, capture_output=True, check=False
        )
        if result.returncode != 0:
            logging.error(
                "Container '%s' launch failed for user %s. Error: %s",
                name, username, result.stderr
            )
            return False

        container_id = result.stdout.strip()
        logging.info(
            "Launched container '%s' for user %s. Container ID: %s",
            name, username, container_id
        )
        success = wait_for_container(
            container_id,
            timeout=timeout,
            container_label=f"{username}:{name}"
        )
        if not success:
            logging.error("Container '%s' failed or timed out for user %s", name, username)
            save_container_logs(container_id, username, name)
        return success

    except (subprocess.SubprocessError, ValueError, FileNotFoundError) as e:
        logging.error("Error running container for user %s: %s", username, str(e))
        return False
    finally:
        if container_id:
            cleanup_result = subprocess.run(
                ['docker', 'rm', '-f', container_id],
                text=True, capture_output=True, check=False
            )
            if cleanup_result.returncode != 0:
                logging.warning(
                    "Could not remove container %s: %s",
                    container_id, cleanup_result.stderr.strip()
                )


def select_ready_jobs(ready_jobs: list[dict], headroom_mb: int) -> tuple[list[dict], int]:
    """Select jobs by stage and CSV order while their reservations fit."""
    selected: list[dict] = []
    remaining_mb = headroom_mb
    for job in sorted(ready_jobs, key=lambda item: (item['stage'], item['order'])):
        memory_mb = container_memory_mb(job['container'])
        if memory_mb <= remaining_mb:
            selected.append(job)
            remaining_mb -= memory_mb
    return selected, remaining_mb


def schedule_container_jobs(rows: list[dict], containers: list[dict],
                            credentials_path: Path, azure_environment: str,
                            total_memory_mb: int, reserve_mb: int,
                            available_memory_probe, job_runner=run_container_job) -> tuple[int, int]:
    """Run per-user container stages with dynamic, memory-aware scheduling."""
    usable_capacity_mb = total_memory_mb - reserve_mb
    if usable_capacity_mb < max(container_memory_mb(container) for container in containers):
        raise RuntimeError("Usable Docker memory cannot fit the largest configured container")

    ready_jobs = [
        {
            'username': row['Username'],
            'password': row['Password'],
            'stage': 0,
            'order': order,
            'container': containers[0]
        }
        for order, row in enumerate(rows)
    ]
    active_jobs = {}
    active_reserved_mb = 0
    completed_users: set[str] = set()
    failed_users: set[str] = set()
    last_available_mb = available_memory_probe()

    with ThreadPoolExecutor(max_workers=len(rows)) as executor:
        while ready_jobs or active_jobs:
            reservation_headroom = usable_capacity_mb - active_reserved_mb
            live_headroom = max(0, last_available_mb - reserve_mb)
            selected_jobs, _ = select_ready_jobs(
                ready_jobs, min(reservation_headroom, live_headroom)
            )

            for job in selected_jobs:
                ready_jobs.remove(job)
                memory_mb = container_memory_mb(job['container'])
                active_reserved_mb += memory_mb
                logging.info(
                    "Scheduling stage %s '%s' for %s: estimate=%s MB, "
                    "available=%s MB, active reservations=%s MB",
                    job['stage'] + 1, job['container']['name'], job['username'],
                    memory_mb, last_available_mb, active_reserved_mb
                )
                future = executor.submit(
                    job_runner,
                    job['username'], job['password'], job['container'],
                    credentials_path, azure_environment
                )
                active_jobs[future] = job

            if not active_jobs:
                raise RuntimeError(
                    "No ready container fits current Docker memory availability "
                    f"({last_available_mb} MB available, {reserve_mb} MB reserved)"
                )

            completed_futures, _ = wait(active_jobs, return_when=FIRST_COMPLETED)
            for future in completed_futures:
                job = active_jobs.pop(future)
                active_reserved_mb -= container_memory_mb(job['container'])
                try:
                    succeeded = bool(future.result())
                except Exception:
                    logging.exception(
                        "Container '%s' raised an unexpected error for user %s",
                        job['container']['name'], job['username']
                    )
                    succeeded = False

                next_stage = job['stage'] + 1
                if succeeded and next_stage < len(containers):
                    ready_jobs.append({
                        **job,
                        'stage': next_stage,
                        'container': containers[next_stage]
                    })
                elif succeeded:
                    completed_users.add(job['username'])
                else:
                    failed_users.add(job['username'])

            try:
                last_available_mb = available_memory_probe()
            except RuntimeError as error:
                logging.warning(
                    "Memory probe failed after completion; retaining last reading of %s MB: %s",
                    last_available_mb, error
                )

    return len(completed_users), len(failed_users)

def read_csv(filepath: Path, config: dict, project_dir: Path) -> None:
    """Read user credentials from CSV and launch containers in parallel."""
    try:
        if not filepath.exists():
            raise FileNotFoundError(f"CSV file not found: {filepath}")

        with open(filepath, mode='r', newline='') as file:
            reader = csv.DictReader(file)

            # Validate CSV structure
            required_fields = {'Username', 'Password'}
            if not required_fields.issubset(reader.fieldnames):
                raise ValueError(f"CSV must contain fields: {required_fields}")

            rows = list(reader)

        if not rows:
            logging.warning("No users found in CSV file: %s", filepath)
            return

        containers = config['containers']
        logging.info("Loaded %s user(s) from %s", len(rows), filepath)
        logging.info("Configured container run order: %s", ', '.join(c['name'] for c in containers))

        credentials_path = resolve_path(config['credentials_path'], project_dir)
        azure_environment = str(config.get('azure_environment', 'AzureCloud'))
        logging.info("Using Azure environment: %s", azure_environment)

        total_memory_mb = detect_docker_total_memory()
        reserve_mb = calculate_memory_reserve(
            total_memory_mb,
            int(config['memory_reserve_percent']),
            int(config['memory_reserve_min_mb'])
        )
        logging.info(
            "Docker memory: total=%s MB, reserve=%s MB, scheduler capacity=%s MB",
            total_memory_mb, reserve_mb, total_memory_mb - reserve_mb
        )
        probe_image = containers[0]['image']
        successful_launches, failed_launches = schedule_container_jobs(
            rows,
            containers,
            credentials_path,
            azure_environment,
            total_memory_mb,
            reserve_mb,
            lambda: detect_docker_available_memory(probe_image)
        )

        logging.info(f"Deployment complete. Successful: {successful_launches}, Failed: {failed_launches}")

    except (csv.Error, FileNotFoundError, ValueError, RuntimeError) as e:
        logging.error(f"Error processing CSV file: {str(e)}")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description='Deploy lab containers')
    parser.add_argument('project_folder', help='Project folder that contains workshop_config.json')
    parser.add_argument('--log', action='store_true', help='Enable logging to stdout and file')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose debug output')
    args = parser.parse_args()

    setup_logging(log_to_file=args.log, verbose=args.verbose)

    project_dir = Path(args.project_folder).resolve()
    if not project_dir.exists() or not project_dir.is_dir():
        logging.error("Project folder does not exist or is not a directory: %s", project_dir)
        sys.exit(1)

    config = load_project_config(project_dir)
    csv_path = resolve_path(config['users_csv'], project_dir)
    azure_environment = str(config.get('azure_environment', 'AzureCloud'))

    logging.info("Starting deployment for project folder: %s", project_dir)
    build_container_images(config['containers'], project_dir, azure_environment)
    read_csv(csv_path, config, project_dir)

if __name__ == "__main__":
    main()