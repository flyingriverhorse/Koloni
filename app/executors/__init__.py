from pathlib import Path

from app.db.models import Project
from app.executors.base import Executor, StartError
from app.executors.docker import DockerExecutor
from app.executors.host import HostExecutor


def executor_for(location: str, project: Project, runtime_root: Path) -> Executor:
    """The executor for a command's recorded location; `runtime_root`: the app's."""
    if location == "host":
        return HostExecutor(project.pass_env)
    if location == "docker":
        if not project.docker_image:
            raise StartError("no Docker image is set for this project")
        # (A container is given none of this machine's variables: only its files are hidden.)
        empty = runtime_root / "empty" if project.hide_secrets else None
        return DockerExecutor(
            Path(project.root_path), project.docker_image, project.docker_network, empty
        )
    raise StartError(f"unknown execution location: {location}")
