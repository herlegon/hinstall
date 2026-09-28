from dataclasses import dataclass
from typing import Literal


# Extracted from hwss
#   used to send message to the websocket client


InstallTaskId = Literal[
    'stop',
    'parse',
    'install',
]


@dataclass(slots=True)
class ParseTask:
    task_id: InstallTaskId = 'parse'
    app_name: str = ""
    cfg: str = ""
    cache: bool = True
    local_backend: bool = False
    reinstall: bool = False
    use_local_rehost: bool = False
    local_rehost: str = ""
    ffmpeg_selection: Literal['lgpl', 'gpl', 'user'] = 'lgpl'
    ffmpeg_user_dir: str = ""


@dataclass(slots=True)
class InstallTask:
    task_id: InstallTaskId = 'install'
    stage: int = -1


@dataclass(slots=True)
class InstallTaskResult:
    task_id: InstallTaskId = 'install'
    stage: int = -1
    status: Literal['parsed', 'installed', 'failed', 'error'] = ''
    restart: bool = False


@dataclass(slots=True)
class InstallProgress:
    task_id: InstallTaskId = 'install'
    package_name: str = ""
    status: str = ""
    type: Literal['progress', 'indet'] = 'progress'
    progress: float = 0.
    total: int = 0
    completed: int = 0
    speed: float = 0.0
    unit: str = ""
    description: str = ""

