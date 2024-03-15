import logging


class LogColors:
    DIM = "\033[2m"
    CYAN = "\033[36m"
    RESET = "\033[0m"


def setup_logger(name, level=logging.INFO, color_code=LogColors.RESET):
    # Create a new logger
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Clear existing handlers to ensure a fresh setup
    logger.handlers.clear()

    # Set up a new handler with the specified formatter
    formatter = logging.Formatter(f"{color_code}%(message)s{LogColors.RESET}")
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    logger.addHandler(stream_handler)

    # Prevent the logger from propagating messages to the root logger
    logger.propagate = False

    return logger
