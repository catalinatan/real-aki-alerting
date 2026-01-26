import logging
import sys
from logging.handlers import RotatingFileHandler

def get_logger(logger_name="aki_logger", log_file="aki.log"):
    """
    This is a utility function to set up and return a global logger instance
    to log messages throughout the application.
    Args:
        logger_name (str): Name of the logger.
        log_file (str): File path for the log file.
    Returns:
        logging.Logger: Configured logger instance.
    """
    # Initialize the Logger
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.DEBUG)

    # Prevent duplicate logs if this function is called multiple times
    if logger.hasHandlers():
        return logger

    # Format: Time - Logger Name - Log Level - Message
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Show INFO and above logs in console
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    # Save DEBUG and above logs to file
    # RotatingFileHandler: max 5MB per file, keeps last 3 backups
    file_handler = RotatingFileHandler(
        log_file, maxBytes=5*1024*1024, backupCount=3
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    # Add Handlers to Logger
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger

# Initialize the global logger
logger = get_logger()