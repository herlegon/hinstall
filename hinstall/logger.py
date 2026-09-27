import logging
import os
import sys
from typing import Optional
from hytils import darkgrey, green, yellow, red


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
            formatted = color_fn(f"{prefix}") + f"{record.getMessage()}  ({link})"

        else:
            formatted = color_fn(f"{prefix}") + f"{record.getMessage()}"

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


def setup_alog(
    log_file: Optional[str] = None,
    to_stdout: bool = True,
    to_gui: Optional[logging.Handler] = None,
    stdout_formatter: Optional[logging.Formatter] = None,
    gui_formatter: Optional[logging.Formatter] = None,
    file_formatter: Optional[logging.Formatter] = None,
):
    """Reconfigure the global logger."""
    logger = logging.getLogger("hinstall")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    # Console handler
    if to_stdout:
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(stdout_formatter or ColorFormatter())
        stream_handler.addFilter(lambda r: r.levelno != STATUS_LEVEL)
        logger.addHandler(stream_handler)

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



