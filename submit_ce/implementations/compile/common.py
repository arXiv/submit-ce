"""Common values and functions.

TODO modify compile_at_gcp.py to use these. Currently only compile_announced_at_gcp.py uses these.
"""

import logging
import os
import stat
import sys


# The output of (La)TeX compilation
GCP_LOG_NAME = "gcp_compile.log"
# The genpdf response metadata
GCP_RESULTS_NAME = "gcp_compile.json"
# The preflight v2 JSON response
GCP_PREFLIGHT_NAME = "gcp_preflight.json"

DEFAULT_SUBMISSION_LOG_NAME = 'gcp_request.log'
DEFAULT_SYSTEM_LOGS_DIR = '/users/e-prints/httpd/logs'
DEFAULT_SYSTEM_LOG_NAME = 'compile_at_gcp.log'

# Retry compilation request settings
MAX_RETRIES = 3
RETRY_DELAY = 5

# Timeout for GCP compilation request
# The tex2pdf/genpdf GCP deployment timeout is set to 900sec
# (see arxiv-converter/gcp/genpdf/appliance.yaml for tex2pdf used here,
# and .../cloudbuild.yaml for genpdf)
DEFAULT_COMPILATION_TIMEOUT = 840
DEFAULT_MAX_APPEND_FILES = 0
DEFAULT_MAX_TEX_FILES = 1

# Create formatters
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s',
                              datefmt='%Y-%m-%d %H:%M:%S')


def adjust_permissions(file_path):
    """Add write permissions to file."""
    # Get the current file permissions
    current_permissions = os.stat(file_path).st_mode

    # Add group write permissions (g+w)
    new_permissions = current_permissions | stat.S_IWGRP

    # Update the file permissions
    if not current_permissions & stat.S_IWGRP:
        os.chmod(file_path, new_permissions)


def setup_logging(identifier,
                  logger,
                  submission_log_name=DEFAULT_SUBMISSION_LOG_NAME,
                  system_logs_dir=DEFAULT_SYSTEM_LOGS_DIR,
                  system_log_name=DEFAULT_SYSTEM_LOG_NAME,
                  temp_dir=None,
                  log_to_console=False,
                  only_log_to_console=False,
                  log_level=logging.DEBUG):
    """Set up submission, system, and console logging."""

    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    logger.setLevel(log_level)

    if log_to_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(log_level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        if only_log_to_console:
            return logger

    # Make sure various directories exist
    if not temp_dir or temp_dir is None:
        raise TypeError("Base submission directory is required.")
    if not os.path.exists(temp_dir):
        raise FileNotFoundError(f"The base submission directory "
                                f"'{temp_dir}' does not exist.")
    if not os.path.exists(system_logs_dir):
        raise FileNotFoundError(f"The system log directory '{system_logs_dir}' "
                                f"does not exist.")

    # Create a log for this submission in the submission's home directory
    paper_log_dir = temp_dir + os.pathsep + str(identifier) + ".log"
    if not os.path.exists(paper_log_dir):
        raise FileNotFoundError(f"The submission directory '{paper_log_dir}' does not exist.")

    submission_log_path = os.path.join(paper_log_dir, submission_log_name)

    # Create system log
    system_log_path = os.path.join(system_logs_dir, system_log_name)

    # Create file handlers for this submission's compilation messaged
    file_handler_submission = logging.FileHandler(str(submission_log_path))
    file_handler_submission.setLevel(logging.DEBUG)
    file_handler_submission.setFormatter(formatter)
    file_handler_submission.mode = 0o664
    logger.addHandler(file_handler_submission)

    # Create file handlers for system level messages
    file_handler_system = logging.FileHandler(str(system_log_path))
    file_handler_system.setLevel(logging.INFO)
    file_handler_system.setFormatter(formatter)
    file_handler_system.mode = 0o664
    logger.addHandler(file_handler_system)

    adjust_permissions(system_log_path)
    adjust_permissions(submission_log_path)
    return logger
