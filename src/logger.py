import logging
import sys
import os
from logging.handlers import TimedRotatingFileHandler

# Default logging configuration
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_LOG_FILE = "app.log"
DEFAULT_BACKUP_COUNT = 30 # Keep logs for 30 days, subject to change by hospital policy
DEFAULT_FORMAT = '%(asctime)s - [%(levelname)s] - %(name)s - %(message)s'

def get_logger(logger_name : str = "aki_logger") -> logging.Logger:
    """
    Creates a global logger instance that rotates files daily at midnight.

    Args:
        logger_name (str): Name of the logger.

    Returns:
        logging.Logger: Configured logger instance.
    """
    # Fetch config from environment (if available)
    log_level_str = os.getenv("LOG_LEVEL", DEFAULT_LOG_LEVEL).upper()
    log_level = getattr(logging, log_level_str, logging.INFO)
    
    log_file = os.getenv("LOG_FILE", DEFAULT_LOG_FILE)

    try:
        backup_count = int(os.getenv("LOG_BACKUP_COUNT", DEFAULT_BACKUP_COUNT))
    except ValueError:
        # Fallback if env vars are not valid integers
        backup_count = DEFAULT_BACKUP_COUNT
    
    # Initialize the Logger
    logger = logging.getLogger(logger_name)
    logger.setLevel(log_level)

    # Prevent duplicate logs if this function is called multiple times
    if logger.hasHandlers():
        return logger

    # Format: Time - Logger Name - Log Level - Message
    formatter = logging.Formatter(DEFAULT_FORMAT)

    # Configure handler for logging output to console
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Configure handler for logging output to file with daily rotation
    if log_file:
        try:
            file_handler = TimedRotatingFileHandler(
                log_file, 
                when="midnight", 
                interval=1, 
                backupCount=backup_count,
                encoding="utf-8"
            )
            # Appends date to filename (e.g., app.log.2023-10-27)
            file_handler.suffix = "%Y-%m-%d" 
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except (IOError, PermissionError):
            print(f"WARNING: No write access to {log_file}. Console logging only.", file=sys.stderr)

    # Prevent propagation to root logger (avoid double logging)
    logger.propagate = False

    return logger

# Initialize the global logger
logger = get_logger()