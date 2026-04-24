import logging
import sys
from pathlib import Path

LOG_FORMAT = "[%(asctime)s] %(levelname)s %(name)s: %(message)s"

def configure(level: str | int = "INFO", logger_name="animal_translator") -> logging.Logger:
    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    return logging.getLogger(logger_name)


animal_translate_logger = configure()
re_run_logger = configure("re_run_logger")
transform_logger = configure("transform_logger")
