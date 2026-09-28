import logging
import os
import sys
from typing import Optional
from hytils import darkgrey, green, yellow, red

from rich.console import Console
from rich.filesize import decimal
from rich.progress import (
    BarColumn,
    Progress,
    ProgressColumn,
    TaskID,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)
from rich.text import Text


STATUS_LEVEL = 24
logging.addLevelName(STATUS_LEVEL, "STATUS")

PROGRESS_LEVEL = 25  # Between INFO (20) and WARNING (30)
logging.addLevelName(PROGRESS_LEVEL, "PROGRESS")


class ColorFormatter(logging.Formatter):
    COLORS = {
        logging.DEBUG: darkgrey,
        logging.INFO: green,
        STATUS_LEVEL: lambda x: x,
        PROGRESS_LEVEL: lambda x: x,
        logging.WARNING: yellow,
        logging.ERROR: red,
        logging.CRITICAL: red,
    }

    LEVEL_PREFIX = {
        logging.DEBUG: "[D]",
        5: "[V]",
        logging.INFO: "[I]",
        STATUS_LEVEL: "",
        PROGRESS_LEVEL: "",
        logging.WARNING: "[W]",
        logging.ERROR: "[E]",
        logging.CRITICAL: "[C]",
    }

    def format(self, record: logging.LogRecord) -> str:
        level_no: int = record.levelno
        if level_no == STATUS_LEVEL:
            return record.getMessage()

        # PROGRESS level should not be formatted (handled by handlers)
        if level_no == PROGRESS_LEVEL:
            return record.getMessage()

        color_fn = self.COLORS.get(level_no, lambda x: x)
        prefix: str = self.LEVEL_PREFIX.get(level_no, f"{level_no}")
        if level_no < logging.INFO:
            # Use relative path for readability
            try:
                rel_path = os.path.relpath(record.pathname)
            except ValueError:
                rel_path = os.path.basename(record.pathname)
            link = f"{rel_path}:{record.lineno}"
            formatted = color_fn(f"{prefix}") + f" {record.getMessage()}  ({link})"

        else:
            formatted = color_fn(f"{prefix}") + f" {record.getMessage()}"

        return formatted



class HInstallLogger(logging.Logger):
    def status(self, msg, *args, **kwargs):
        if self.isEnabledFor(STATUS_LEVEL):
            self._log(STATUS_LEVEL, msg, args, **kwargs)

    def progress(self, progress_data, *args, **kwargs):
        """Log a progress update at PROGRESS level"""
        if self.isEnabledFor(PROGRESS_LEVEL):
            # Create a log record with the progress data attached
            record = self.makeRecord(
                self.name, PROGRESS_LEVEL, "(progress)", 0,
                f"Progress: {getattr(progress_data, 'package_name', 'unknown')}",
                args, None, **kwargs
            )
            # Attach the progress data for handlers to use
            record.progress_data = progress_data
            self.handle(record)


logging.setLoggerClass(HInstallLogger)


class UnitsOrBytesColumn(ProgressColumn):
    """Renders completed / total formatted as bytes or units."""
    def render(self, task) -> Text:
        unit = task.fields.get("unit", "")
        completed = task.completed
        total = task.total
        if unit in ("B", "bytes"):
            comp_str = decimal(int(completed))
            if total is not None and total > 0:
                tot_str = decimal(int(total))
                return Text(f"{comp_str}/{tot_str}", style="progress.download")
            return Text(f"{comp_str}", style="progress.download")
        elif unit:
            if total is not None and total > 0:
                return Text(f"{int(completed)}/{int(total)} {unit}", style="progress.download")
            return Text(f"{int(completed)} {unit}", style="progress.download")
        else:
            if total is not None and total > 0:
                return Text(f"{int(completed)}/{int(total)}", style="progress.download")
            return Text(f"{int(completed)}", style="progress.download")


class TransferSpeedColumn(ProgressColumn):
    """Renders human readable transfer speed if unit is bytes."""
    def render(self, task) -> Text:
        unit = task.fields.get("unit", "")
        if unit in ("B", "bytes") and task.speed is not None:
            return Text(f"{decimal(int(task.speed))}/s", style="progress.data.speed")
        return Text("")


class RichConsoleStream:
    """Stream wrapper that routes stdout through Rich Console to play nice with Progress."""
    def __init__(self, console: Console):
        self.console = console

    def write(self, text: str):
        if text:
            self.console.print(text, end="", markup=False, highlight=False)

    def flush(self):
        pass


class RichProgressHandler(logging.Handler):
    """Logging handler that listens to PROGRESS_LEVEL records and updates a Rich Progress display."""
    def __init__(self, console: Optional[Console] = None):
        super().__init__(level=PROGRESS_LEVEL)
        self.console = console or Console(file=sys.stdout)
        self.progress = Progress(
            TextColumn("[bold cyan]{task.fields[package]}", justify="left"),
            TextColumn("{task.description}"),
            BarColumn(bar_width=30),
            TaskProgressColumn(),
            UnitsOrBytesColumn(),
            TransferSpeedColumn(),
            TimeRemainingColumn(),
            console=self.console,
            transient=False,
        )
        self.tasks: dict[str, TaskID] = {}
        self.finished_tasks: set[str] = set()
        self._started = False

    def _get_action(self, status: str, description: str, package_name: str) -> str:
        desc_l = description.lower()
        status_l = status.lower()

        if any(w in desc_l or w in status_l for w in ('download', 'copy')):
            return 'download'
        elif any(w in desc_l or w in status_l for w in ('install', 'extract', 'untar', 'unzip')):
            return 'install'
        else:
            if f"{package_name}:install" in self.tasks and f"{package_name}:install" not in self.finished_tasks:
                return 'install'
            elif f"{package_name}:download" in self.tasks and f"{package_name}:download" not in self.finished_tasks:
                return 'download'
            return 'general'

    def emit(self, record: logging.LogRecord):
        if record.levelno != PROGRESS_LEVEL:
            return

        progress_data = getattr(record, 'progress_data', None)
        if not progress_data:
            return

        package_name = getattr(progress_data, 'package_name', '')
        status = getattr(progress_data, 'status', '')
        pct = getattr(progress_data, 'progress', 0.0)
        total = getattr(progress_data, 'total', 0)
        completed = getattr(progress_data, 'completed', 0)
        unit = getattr(progress_data, 'unit', '')
        description = getattr(progress_data, 'description', '')

        action = self._get_action(status, description, package_name)
        task_key = f"{package_name}:{action}"

        is_finished = status in ('success', 'failed', 'done', 'error')

        # If this exact task has already finished, ignore subsequent messages
        if task_key in self.finished_tasks:
            return

        if task_key not in self.tasks:
            if is_finished:
                # Don't create a task just to finish it if it didn't exist
                return

            if not self._started:
                self.progress.start()
                self._started = True

            task_id = self.progress.add_task(
                description=description or f"{action.capitalize()}ing...",
                total=float(total) if total > 0 else 100.0,
                completed=float(completed),
                package=package_name,
                unit=unit,
            )
            self.tasks[task_key] = task_id
        else:
            task_id = self.tasks[task_key]

        current_task = self.progress._tasks.get(task_id)

        update_kwargs = {}
        if description:
            update_kwargs['description'] = description

        if total > 0:
            update_kwargs['total'] = float(total)
        elif current_task and current_task.total and current_task.total > 0:
            pass  # preserve existing total
        elif is_finished:
            update_kwargs['total'] = 100.0

        if completed > 0:
            update_kwargs['completed'] = float(completed)
        elif is_finished:
            task_total = update_kwargs.get('total') or (current_task.total if current_task else 100.0) or 100.0
            update_kwargs['completed'] = float(task_total)
        elif pct > 0:
            update_kwargs['completed'] = float(pct)
            update_kwargs['total'] = 100.0

        if unit:
            update_kwargs['unit'] = unit

        self.progress.update(task_id, **update_kwargs)

        if is_finished:
            self.finished_tasks.add(task_key)
            if status == 'success':
                final_desc = f"[green]✓ {description or 'Done'}[/green]"
            elif status in ('failed', 'error'):
                final_desc = f"[red]✗ {description or 'Failed'}[/red]"
            else:
                final_desc = f"[green]✓ {description or 'Done'}[/green]"

            self.progress.update(task_id, description=final_desc)
            self.progress.refresh()

            # When all known tasks have finished, stop cleanly
            if self.tasks and all(k in self.finished_tasks for k in self.tasks):
                if action == 'install' or 'failed' in status or 'error' in status:
                    self.stop()

    def stop(self):
        """Stop progress display and reset task list."""
        if self._started:
            self.progress.stop()
            self._started = False
            for tid in list(self.progress.task_ids):
                self.progress.remove_task(tid)
            self.tasks.clear()
            self.finished_tasks.clear()

    def close(self):
        self.stop()
        super().close()



def setup_alog(
    log_file: Optional[str] = None,
    to_stdout: bool = True,
    to_gui: Optional[logging.Handler] = None,
    stdout_formatter: Optional[logging.Formatter] = None,
    gui_formatter: Optional[logging.Formatter] = None,
    file_formatter: Optional[logging.Formatter] = None,
    to_rich: bool = True,
):
    """Reconfigure the global logger."""
    logger = logging.getLogger("hinstall")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    # Console handler
    if to_stdout:
        console = Console(file=sys.stdout)
        stream_target = RichConsoleStream(console) if to_rich else sys.stdout
        stream_handler = logging.StreamHandler(stream_target)
        stream_handler.setFormatter(stdout_formatter or ColorFormatter())
        stream_handler.addFilter(lambda r: r.levelno not in (STATUS_LEVEL, PROGRESS_LEVEL))
        logger.addHandler(stream_handler)

        if to_rich:
            rich_handler = RichProgressHandler(console=console)
            logger.addHandler(rich_handler)
            import atexit
            atexit.register(rich_handler.stop)

    # # File handler
    # if log_file:
    #     file_handler = logging.FileHandler(log_file, mode="w", encoding="utf-8")
    #     file_handler.setFormatter(file_formatter or SimpleFormatter())
    #     logger.addHandler(file_handler)

    # GUI handler
    if to_gui:
        to_gui.setFormatter(gui_formatter or logging.Formatter('%(message)s'))
        to_gui.addFilter(lambda r: r.levelno != STATUS_LEVEL)
        logger.addHandler(to_gui)

    return logger


# Default initialization (basic mode)
ilog: HInstallLogger = setup_alog(to_stdout=True)




