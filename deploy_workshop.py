import argparse
import csv
import json
import subprocess
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import sys
import time

MEM_CONTAINER1_MB = 2000  # ansiblenewclass:latest
MEM_CONTAINER2_MB = 300   # ansiblenewclassstudent:latest
DEFAULT_CONFIG_FILE = 'workshop_config.json'


def load_project_config(project_dir: Path) -> dict:
    """Load workshop config from project folder, falling back to defaults."""
    config_path = project_dir / DEFAULT_CONFIG_FILE

    default_config = {
        'users_csv': 'users.csv',
        'credentials_path': '/Users/jesper/.azure/credentials',
        'azure_environment': 'AzureCloud',
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

def detect_vm_memory() -> int:
    """Detect total VM memory available to Docker, returns MB"""
    result = subprocess.run(
        ['docker', 'info', '--format', '{{json .MemTotal}}'],
        capture_output=True, text=True, check=False
    )
    if result.returncode == 0:
        try:
            return int(result.stdout.strip()) // (1024 * 1024)
        except ValueError:
            pass
    logging.warning("Could not detect VM memory, defaulting to 4096 MB")
    return 4096


def calculate_semaphore_limits(available_mb: int, containers: list[dict]) -> dict[str, int]:
    """Calculate max concurrent runs per container type based on available memory."""
    limits: dict[str, int] = {}

    for container in containers:
        name = container['name']
        memory_mb = int(container.get('memory_mb', 512))
        if memory_mb <= 0:
            memory_mb = 512
        limits[name] = max(1, available_mb // memory_mb)

    limits_message = ', '.join(
        f"{name}={count}" for name, count in limits.items()
    )
    logging.info("VM memory: %s MB -> max concurrent per container type: %s", available_mb, limits_message)
    return limits


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

def launch_container(username: str, password: str, containers: list[dict],
                     semaphores: dict[str, threading.Semaphore], credentials_path: Path,
                     azure_environment: str) -> bool:
    """
    Launch workshop containers sequentially with provided credentials.
    Semaphores gate each container type to enforce memory limits independently.
    Returns True if all containers succeed, False otherwise.
    """
    try:
        # Validate inputs
        if not username or not password:
            raise ValueError("Username and password cannot be empty")

        if not credentials_path.exists():
            raise FileNotFoundError(f"Credentials file not found at {credentials_path}")

        for container in containers:
            name = container['name']
            image = container['image']
            timeout = int(container.get('timeout_seconds', 1200))

            with semaphores[name]:
                logging.info(
                    "Starting container '%s' for user %s using image %s",
                    name,
                    username,
                    image
                )

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

                if not wait_for_container(
                    container_id,
                    timeout=timeout,
                    container_label=f"{username}:{name}"
                ):
                    logging.error("Container '%s' failed or timed out for user %s", name, username)
                    return False

        return True

    except (subprocess.SubprocessError, ValueError, FileNotFoundError) as e:
        logging.error(f"Error launching containers for user {username}: {str(e)}")
        return False

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

        available_mb = detect_vm_memory()
        semaphore_limits = calculate_semaphore_limits(available_mb, containers)
        semaphores = {
            name: threading.Semaphore(limit)
            for name, limit in semaphore_limits.items()
        }

        successful_launches = 0
        failed_launches = 0

        with ThreadPoolExecutor(max_workers=len(rows)) as executor:
            futures = {
                executor.submit(
                    launch_container,
                    row['Username'],
                    row['Password'],
                    containers,
                    semaphores,
                    credentials_path,
                    azure_environment
                ): row['Username']
                for row in rows
            }
            for future in as_completed(futures):
                if future.result():
                    successful_launches += 1
                else:
                    failed_launches += 1

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