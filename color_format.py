from logging import Formatter, DEBUG, INFO, WARNING, ERROR, CRITICAL, Logger
class ColorFormatter(Formatter):

    grey = "\x1b[38;20m"
    yellow = "\x1b[33;20m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"
    format = "[{asctime}] [{levelname}] {name}: {message} ({filename}:{lineno})"
    dt_fmt = '%Y-%m-%d %H:%M:%S'

    FORMATS = {
        DEBUG: grey + format + reset,
        INFO: grey + format + reset,
        WARNING: yellow + format + reset,
        ERROR: red + format + reset,
        CRITICAL: bold_red + format + reset
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = Formatter(log_fmt, self.dt_fmt, style='{')
        return formatter.format(record)