import logging


class _ColorFormatter(logging.Formatter):
    COLORS = {
        logging.DEBUG: "\033[36m",
        logging.INFO: "\033[33m",
        logging.WARNING: "\033[35m",
        logging.ERROR: "\033[31m",
        logging.CRITICAL: "\033[1;31m",
    }
    RESET = "\033[0m"

    def format(self, record):
        color = self.COLORS.get(record.levelno, self.RESET)
        record.msg = f"{color}{record.msg}{self.RESET}"
        return super().format(record)


def setup_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(_ColorFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.root.handlers = [handler]
    logging.root.setLevel(logging.INFO)
