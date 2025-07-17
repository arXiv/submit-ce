"""
Compile (La)TeX source submissions at GCP.

This script provides an interface between the legacy submission
and the GCP compilation system. It makes a request to compile a submission
at GCP and then installs the resulting PDF and log in the submission
directory.
"""
import os
import sys
import json
import tarfile
import glob
import tempfile
import shutil
import argparse
import time
import logging
import stat
import requests
import httpx
import urllib.parse
from typing import List, Optional
from enum import Enum

GCP_COMPILE_URL = "https://tex-to-pdf-default-1090350072932.us-central1.run.app"

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
DEFAULT_COMPILATION_TIMEOUT = 290
DEFAULT_MAX_APPEND_FILES = 0
DEFAULT_MAX_TEX_FILES = 1


# Enum for preflight options
class PreflightOption(str, Enum):
    V1 = "v1"
    V2 = "v2"


def parse_preflight_option(option):
    if option is None:
        return None
    return PreflightOption(option)


# Create loggers
logger = logging.getLogger(__name__)

# Create formatters
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s',
                              datefmt='%Y-%m-%d %H:%M:%S')

# Configure logging
logging.basicConfig(level=logging.DEBUG)


def get_submission_dir(identifier, base_submissions_dir=None):
    """Generate the submission's home directory path."""
    base_submission_dir = os.path.join(base_submissions_dir, identifier[:4], identifier)
    return base_submission_dir


def adjust_permissions(file_path):
    """Add write permissions to file."""
    # Get the current file permissions
    current_permissions = os.stat(file_path).st_mode

    # Add group write permissions (g+w)
    new_permissions = current_permissions | stat.S_IWGRP

    # Update the file permissions
    if not current_permissions & stat.S_IWGRP:
        os.chmod(file_path, new_permissions)


def set_up_logging(identifier, submission_log_name=DEFAULT_SUBMISSION_LOG_NAME,
                   system_logs_dir=DEFAULT_SYSTEM_LOGS_DIR,
                   system_log_name=DEFAULT_SYSTEM_LOG_NAME,
                   base_submissions_dir=None,
                   log_to_console=False,
                   only_log_to_console=False):
    """Set up submission, system, and console logging."""

    # Remove all existing handlers from the logger
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    if log_to_console:

        # Create a stream handler (logs to console)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        if only_log_to_console:
            return logger

    # Make sure various directories exist
    if not base_submissions_dir or base_submissions_dir is None:
        raise TypeError("Base submission directory is required.")
    if not os.path.exists(base_submissions_dir):
        raise FileNotFoundError(f"The base submission directory "
                                f"'{base_submissions_dir}' does not exist.")
    if not os.path.exists(system_logs_dir):
        raise FileNotFoundError(f"The system log directory '{system_logs_dir}' "
                                f"does not exist.")

    # Create a log for this submission in the submission's home directory
    submission_log_dir = get_submission_dir(identifier, base_submissions_dir)
    if not os.path.exists(submission_log_dir):
        raise FileNotFoundError(f"The submission directory '{submission_log_dir}' does not exist.")

    submission_log_path = os.path.join(submission_log_dir, submission_log_name)

    # Create system log
    system_log_path = os.path.join(system_logs_dir, system_log_name)

    # Create file handlers for this submission's compilation messaged
    file_handler_submission = logging.FileHandler(submission_log_path)
    file_handler_submission.setLevel(logging.DEBUG)
    file_handler_submission.setFormatter(formatter)
    file_handler_submission.mode = 0o664
    logger.addHandler(file_handler_submission)

    # Create file handlers for system level messages
    file_handler_system = logging.FileHandler(system_log_path)
    file_handler_system.setLevel(logging.INFO)
    file_handler_system.setFormatter(formatter)
    file_handler_system.mode = 0o664
    logger.addHandler(file_handler_system)

    adjust_permissions(system_log_path)
    adjust_permissions(submission_log_path)
    return logger


def find_and_process_log_file(output_files_dir):
    """Process the log file in the out directory as a last resort.

    The 'out' directory contains a log file. We will use this
    when we are unable to extract a log from the compilation metadata (json).
    """
    log_files = glob.glob(os.path.join(output_files_dir, 'out', '*.log'))
    if log_files:
        log_file_path = log_files[0]  # Take the first log file found
        return log_file_path  # Return log file path

    return None


def process_file_lists(list_of_listfiles: List, output_files_dir: str):
    """Process the list of files involved it the compilation.

    """
    processed_files = {}
    for current_file in list_of_listfiles:
        path = os.path.join(output_files_dir, 'out', current_file)
        if os.path.exists(path):
            processed_files[current_file] = {"input": [], "output": []}
            processed_input_files = set()
            processed_output_files = set()
            with open(path, 'r') as f:
                lines = f.readlines()
                for line in lines:
                    clean_line = line.strip()
                    if 'texmf' in clean_line:
                        continue
                    if clean_line.startswith('INPUT'):
                        input_file = clean_line[len('INPUT'):].strip()
                        if input_file.startswith("./"):
                            input_file = input_file[2:]
                            input_file = os.path.normpath(input_file)
                        if input_file not in processed_input_files:
                            processed_files[current_file]["input"].append(input_file)
                            processed_input_files.add(input_file)
                    elif clean_line.startswith('OUTPUT'):
                        output_file = clean_line[len('OUTPUT'):].strip()
                        output_file = os.path.normpath(output_file)
                        if output_file.startswith("./"):
                            output_file = input_file[2:]
                        if output_file not in processed_output_files:
                            processed_files[current_file]["output"].append(output_file)
                            processed_output_files.add(output_file)

            # After we finish processing the file we need to eliminate the set
            # by serializing the data
            processed_files[current_file]["input"] = list(processed_input_files)
            processed_files[current_file]["output"] = list(processed_output_files)

    return processed_files


def add_html_class(css_class: str, content: str) -> str:
    """Return HTML markup for display."""
    return f"<span class=\"{css_class}\">{content}</span>"


def process_metadata_and_log(submission_dir, json_log_run_data, output_files_dir,
                             json_data=None, json_file_path: Optional[str] = None):
    """Create a brief summary. Provide indication of success or failure.

    Use the log data from the last compilation run in
    the compilation metadata (json). If this fails, grab the log
    file in the out directory.

    :param submission_dir: Location of submission directory.
    :param json_log_run_data: Used a log data when there is a fatal error and we don't have a log.
    :param output_files_dir: The directory where the compilation results gzipped tar is unpacked.
    :param json_data: The original compilation metadata (JSON).
    :param json_file_path: The path for the installed compilation metadata (JSON).
    """
    # Install the log file into the submission directory
    new_log_path = os.path.join(submission_dir, GCP_LOG_NAME)

    if json_data and not json_file_path:
        raise FileNotFoundError("File path is require to write out JSON compilation metadata.")

    if json_data is None:
        # Create a minimal log file for a fatal error
        with open(new_log_path, "w") as f:
            display_status = add_html_class('tex-fatal', "FAILED")
            f.write(f"Status: {display_status}\n\n")
            f.write(f"{json_log_run_data}\n\n")
        os.chmod(new_log_path, 0o664)
        logger.debug("Creating compilation log file from supplied log data.")
    elif json_data:
        status = json_data.get("status", "Status not available")
        final_pdf_file = json_data.get("pdf_file", None)
        logger.debug("Creating compilation log file from last run log in json "
                     "metadata: %s", new_log_path)

        with open(new_log_path, "w") as f:
            if status == 'success':
                display_status = add_html_class('tex-success', "[SUCCEEDED]")
                f.write(f"\nWe successfully processed your submission. Status: {display_status}\n\n")
            else:
                display_status = add_html_class('tex-fatal', "[FAILED]")
                f.write(f"\nWe failed to process your submission. Status: {display_status}\n\n")

            f.write("\nFiles that were processed as part of this submission:\n\n")
            for converter in json_data.get("converters", []):
                if isinstance(converter, dict):
                    converter_status = converter.get("status", "N/A")
                    tex_file = converter.get("tex_file", "N/A")
                    pdf_file = converter.get("pdf_file", "N/A")
                    display_status = add_html_class('tex-success', "[SUCCEEDED]")
                    if converter_status == 'fail':
                        display_status = add_html_class('tex-fatal', "[FAILED]")

                    f.write(f"    {tex_file} => {pdf_file}  {display_status}\n")
                elif isinstance(converter, str):
                    # TeX2PDF returns strings when run in preflight mode.
                    # TODO: The set of converters will be used to populate the
                    #       TeX engine selection pulldown in the submission UI
                    pass

            f.write('\n')

            if status == 'success':
                if len(json_data.get("converters", [])) > 1:
                    f.write(f"\nOur system has compiled the above LaTeX files into "
                            f"individual PDFs and merged them into a single "
                            f"PDF document: {final_pdf_file}.\n\n")
                else:
                    f.write(f"\nOur system has compiled the above LaTeX file "
                            f"into a single PDF document: {final_pdf_file}.\n\n")
            else:
                f.write(f"\nOur system failed to generate a PDF.\n\n")

            f.write("\nLogs for each file processed (last run)\n\n")

            for converter in json_data.get("converters", []):
                if isinstance(converter, dict):
                    tex_file = converter.get("tex_file", "N/A")
                    step = converter.get("step", "N/A")

                    space = ' '
                    if converter_status == 'success':
                        markup = add_html_class('tex-success', "[SUCCEEDED]")
                        f.write(f"\n{space}<b>Processing file {tex_file}</b> {markup}\n\n")
                    else:
                        markup = add_html_class('tex-fatal', "[FAILED]")
                        f.write(f"\n{space}<b>Processing file {tex_file}</b> {markup}.\n\n")
                    f.write(f"Log for {tex_file} at step '{step}':\n\n")

                    # Get last log in series
                    last_run = converter["runs"][-1]

                    log = last_run.get("log", "N/A")
                    f.write(f"--\n{log}\n--\n")

                    logger.debug("\nCompilation: status: %s step: %s PDF file: %s TeX file: %s",
                                 converter_status, step, pdf_file, tex_file)

            os.chmod(new_log_path, 0o664)

        # Collect list of files used in compilations
        item: str
        list_files = []
        for item in json_data.get("out_files", []):
            if item.endswith('.fls'):
                list_files.append(item)

        processed_files = process_file_lists(list_files, output_files_dir)

        json_data['processed_files'] = processed_files

        logger.debug(f"Writing new compilation metadata file (JSON): {json_file_path}")
        new_metadata_path = os.path.join(submission_dir, GCP_RESULTS_NAME)
        with open(new_metadata_path, "w") as f:
            f.write(json.dumps(json_data, indent=4))
            os.chmod(new_metadata_path, 0o664)
    else:
        # Use existing log file (in 'out' directory)
        log_file_path = find_and_process_log_file(output_files_dir)
        if log_file_path and os.path.exists(log_file_path):
            try:
                shutil.copy2(log_file_path, new_log_path)
                os.chmod(new_log_path, 0o664)
            except OSError as e:
                logger.error("Failed to copy log file to submission directory: %s", e)
        else:
            # No log file found
            pass


def save_response_output(response, output_file_path):
    """Save the response content from the compilation service.

    Return path when successful, otherwise return None.
    """
    if response is not None and response.content:
        # Write the content to the output file in the temp_dir
        with open(output_file_path, 'wb') as out_file:
            out_file.write(response.content)
            os.chmod(output_file_path, 0o664)

        logger.debug("Output file created: %s", output_file_path)

        # Check if the output file (tarfile) exists.
        if not os.path.exists(output_file_path) or os.path.getsize(output_file_path) == 0:
            logger.critical("Output file '%s' not found or has zero size.", output_file_path)
            return None  # Return None for both files

        return output_file_path
    return None


def extract_output_files(output_file_path, temp_dir):
    """Extract files from the gzipped tar output file."""
    with tarfile.open(output_file_path, 'r:gz') as tar:
        tar.extractall(temp_dir)


def copy_json_file_to_submission_directory(base_submissions_dir, json_file_path, identifier):
    """Install the compilation response metadata into the submission directory.

    We preserve the json just in case we need to look at it or use it after
    the temporary directory is cleaned up.
    """
    base_submission_dir = os.path.join(base_submissions_dir, identifier[:4], identifier)

    # Use identifier as the new name for the JSON file
    new_json_name = GCP_RESULTS_NAME

    # Install JSON file into base_submission_dir with the new name
    new_json_path = os.path.join(base_submission_dir, new_json_name)
    try:
        shutil.copy2(json_file_path, new_json_path)
        os.chmod(new_json_path, 0o664)
    except OSError as e:
        logger.error("Failed to copy JSON file to %s: %s", new_json_path, e)


def find_pdf_file(output_files_dir, pdf_file):
    """Use the provided pdf_file value directly."""
    if pdf_file:
        pdf_file_path = os.path.join(output_files_dir, 'out', pdf_file)
        if os.path.exists(pdf_file_path):
            return pdf_file_path
    return None

def _compile_submission(args: argparse.Namespace):
    """Compile (La)TeX source at GCP.

    Make a request to compile a submission at GCP, then install resulting
    pdf, log, and json files into the submission's home directory.

    In standard production environment we only need the identifier to determine all
    paths.
    :param identifier: The submission identifier.
    :param base_submissions_dir: Base directory to look for submissions and other related files. (Default is /data/new)
    :param: max_append_files : Limit on extra files apended to final PDF. Default is 0.
    :param: max_tex_files : Maximum number of (La)TeX source files to compile. Default is 1.
    :param output_file: Name of file to store gzipped response from tex2pdf service.
    :param preflight: Execute light-weight preflight check instead of compiling document.
    :param source_file: A gzipped tarball containing the source to be compiled.
    :param tex2pdf_url: The URL to the tex2pdf service.
    :param timeout: A user specified timeout for tex2pdf service. (Default is 290 seconds)
    :param: watermark_text : Text to use for watermark.
    """
    identifier = args.identifier
    max_append_files = args.max_append_files if args.max_append_files is not None else DEFAULT_MAX_APPEND_FILES
    max_tex_files = args.max_tex_files if args.max_tex_files is not None else DEFAULT_MAX_TEX_FILES
    output_file = args.output if args.output is not None else None
    preflight = parse_preflight_option(args.preflight)
    source_file = args.source if args.source is not None else None
    timeout = args.timeout if args.timeout is not None else DEFAULT_COMPILATION_TIMEOUT
    base_submissions_dir = args.base if args.base is not None else '/data/new'
    tex2pdf_url = args.tex2pdf_url if args.tex2pdf_url is not None else GCP_COMPILE_URL
    watermark_text = args.watermark_text if args.watermark_text is not None else None

    return _compile_submission(args)

# def compile_submission(
#         identifier: str,
#         output_file: str, #TODO is this str?
#         source_file: str,
#         base_submissions_dir: str,
#         tex2pdf_url: str = GCP_COMPILE_URL
#         max_append_files: int = DEFAULT_MAX_APPEND_FILES,
#         max_tex_files: int = DEFAULT_MAX_TEX_FILES,
#         timeout: int = DEFAULT_COMPILATION_TIMEOUT,
#         watermark_text: Optional[str] = None,
#         preflight = parse_preflight_option(args.preflight)
#     )
#     args =
#     return _compile_submission(args)
def compile_submission(
        identifier: str,

        output_file: str,
        source_file: str,
        base_submissions_dir: str = "/data/new",

        tex2pdf_url: str = GCP_COMPILE_URL,
        preflight: Optional[PreflightOption] = None,
        watermark_text: Optional[str] = None,
        max_append_files: int = DEFAULT_MAX_APPEND_FILES,
        max_tex_files: int = DEFAULT_MAX_TEX_FILES,
        timeout: int = DEFAULT_COMPILATION_TIMEOUT,
    ):
    """Compile (La)TeX source at GCP.

    Make a request to compile a submission at GCP, then install resulting
    pdf, log, and json files into the submission's home directory.

    In standard production environment we only need the identifier to determine all
    paths.
    :param identifier: The submission identifier.
    :param base_submissions_dir: Base directory to look for submissions and other related files. (Default is /data/new)
    :param: max_append_files : Limit on extra files apended to final PDF. Default is 0.
    :param: max_tex_files : Maximum number of (La)TeX source files to compile. Default is 1.
    :param output_file: Name of file to store gzipped response from tex2pdf service. If not passed
        the result will be saved in a temp directory and then unpacked to the submission directory.
    :param preflight: Execute light-weight preflight check instead of compiling document.
    :param source_file: A gzipped tarball containing the source to be compiled.
         If not passed, the submission src directory will be used.
    :param tex2pdf_url: The URL to the tex2pdf service.
    :param timeout: A user specified timeout for tex2pdf service. (Default is 290 seconds)
    :param: watermark_text : Text to use for watermark.
    :param: max_tex_files : Max number of tex files.
    :param: max_append_files : Max append files
    """
    if preflight:
        logger.info("Processing preflight request for '%s' at GCP", identifier)
    else:
        logger.info("Processing compilation request for '%s' at GCP", identifier)

    # additional parameters
    query_params = {
        'timeout': timeout,
        'max_appending_files': max_append_files,
        'max_tex_files': max_tex_files,
    }
    if watermark_text:
        query_params['watermark_text'] = watermark_text

    if preflight:
        query_params['preflight'] = preflight

    # url = f'{tex2pdf_url}/convert/?timeout={timeout}'
    url = f'{tex2pdf_url}/convert/?{urllib.parse.urlencode(query_params)}'
    logger.info("TeX2PDF request url '%s'", url)
    headers = {'accept': 'application/json'}

    # Create a unique temporary directory that only exists during the
    # execution of the script.
    #
    # Note: newer versions of Python support delete=False option to
    # preserve temporary directory for debugging purposes
    with tempfile.TemporaryDirectory(prefix=f"temp_compile_{identifier}_", suffix='_dir') as temp_dir:
        if output_file.startswith(os.path.sep):
            output_file_path = output_file  # Support this for debugging purposes
        else:
            output_file_path = os.path.join(temp_dir, output_file)
        response = None

        # We need either the latest source directory or a gzipped tar file
        # Specifying gzipped tar file will overide the default action of
        # grabbing the source.

        # Locate source
        base_submission_dir = os.path.join(base_submissions_dir,
                                           str(identifier)[:4], str(identifier))
        if not os.path.exists(base_submission_dir):
            raise FileNotFoundError(f"The base directory "
                                    f"'{base_submission_dir}' does not exist.")
        source_dir = os.path.join(base_submission_dir, "src")

        # Check if the incoming file or source directory exists
        temp_tar_path = ''

        try:
            if source_file:
                if not os.path.exists(source_file):
                    # We will consider this a fatal error
                    emsg = f"Source specified but not found: {source_file}"
                    raise FileNotFoundError(emsg)

                incoming_file = source_file
                logger.info("Using client-specified output "
                            "filename: %s", source_file)
            else:
                if not os.path.exists(source_dir):
                    emsg = "Source directory not found in submission home directory: %s"
                    logger.error(emsg, source_dir)
                    raise FileNotFoundError(emsg)

                logger.info("Using submission source directory: %s", source_dir)
                temp_tar_path = os.path.join(temp_dir, f"{identifier}.tar.gz")
                with tarfile.open(temp_tar_path, "w:gz") as tar:
                    tar.add(source_dir, arcname="")
                    os.chmod(temp_tar_path, 0o664)
                    incoming_file = temp_tar_path

        except FileNotFoundError as e:
            logger.critical("The request to compile document '%s' "
                            "at GCP failed: %s", identifier, e)
            return None, None

        files = {'incoming': (os.path.basename(incoming_file),
                              open(incoming_file, 'rb'), 'application/gzip')}

        # Use identifier as the new base name for PDF file
        new_pdf_name = f"{identifier}.pdf"
        new_pdf_path = os.path.join(base_submission_dir, new_pdf_name)
        new_log_path = os.path.join(base_submission_dir, GCP_LOG_NAME)
        new_json_path = os.path.join(base_submission_dir, GCP_RESULTS_NAME)
        new_tar_path = os.path.join(base_submission_dir, f"{identifier}.tar.gz")
        new_preflight_path = os.path.join(base_submission_dir, GCP_PREFLIGHT_NAME)

        # Remove all prior compilation output prior to making request
        # for new compilation

        # Note: When running preflight, we must determine whether we need to
        #       delete any existing compilation output files. Calling preflight in itself
        #       does not guarantee that the resulting PDF will change.
        #
        #       For now, we will delete existing compilation output files.
        try:
            if os.path.exists(new_pdf_path):
                os.remove(new_pdf_path)
            if os.path.exists(new_log_path):
                os.remove(new_log_path)
            if os.path.exists(new_json_path):
                os.remove(new_json_path)
            if os.path.exists(new_preflight_path):
                os.remove(new_preflight_path)

        except PermissionError as e:
            logger.error("You have insufficient permissions to delete file: %s.", e)
        except Exception as e:
            logger.error("There was an exception while deleting {file}: %s", e)

        json_data = None

        try:
            #  Create a temporary message and replace previous log.
            log_msg = f"The system will now compile your (La)TeX source for document " \
                      f"'{identifier}'\n\n" \
                      "This may take a few minutes. Please be patient.\n\n" \
                      "If the results are not displayed after several minutes, " \
                      "please try again or contact the arXiv editorial team."
            if preflight:
                log_msg = f"The system will now run a 'preflight' process to check " \
                          f"your (La)TeX source files for document '{identifier}'\n\n" \
                          "This check will attempt to identify potential problems " \
                          "with your submission.\n\n"

            process_metadata_and_log(base_submission_dir, log_msg, temp_dir)

            # Perform the POST request using requests library
            for retry_attempt in range(MAX_RETRIES):
                try:
                    with httpx.Client(timeout=timeout) as client:
                        response = client.post(url, headers=headers, files=files)
                        if response.status_code == 500:
                            logger.warning("Retry attempt %s/%s for identifier %s.",
                                           retry_attempt + 1, MAX_RETRIES, identifier)
                            time.sleep(RETRY_DELAY)
                        else:
                            break  # Exit the loop if the request succeeds
                except httpx.HTTPStatusError as exc:
                    # Handle HTTP status errors
                    logger.error(f"HTTPX error occurred: {exc}")
                    raise exc
                except httpx.RequestError as exc:
                    # Handle request errors (e.g., connection errors)
                    logger.error(f"Request error occurred: {exc}")

            if response.status_code == 500:
                raise requests.HTTPError(f"HTTP error {response.status_code}")

            response.raise_for_status()

            # Call the function to save the response output
            output_file_path = save_response_output(response, output_file_path)

            # Determine the type of response
            content_type = response.headers['Content-Type']

            # We expect 'application/gzip' for most convert endpoint responses (including preflight v1).
            # and 'application/json' for preflight v2.

            # Check if the content type is "application/gzip"
            if output_file_path:

                # For preflight v2 we simply save the preflight response into
                # the submission home directory.
                if preflight == 'v2':
                    if content_type == 'application/json':
                        status = 'success'
                        logger.info("Preflight check completed successfully for submission 'submit/%s'.", identifier)
                        # Copy new preflight data into submission directory
                        try:
                            shutil.copy2(output_file_path, new_preflight_path)
                            os.chmod(new_preflight_path, 0o664)
                        except OSError as e:
                            logger.critical("ERROR: copying preflight data "
                                            "from %s to %s: %s", output_file_path, new_preflight_path, e)
                        msg = f"The preflight check completed successfully for submission 'submit/{identifier}'."
                        process_metadata_and_log(base_submission_dir, msg, temp_dir)
                        return status, json.loads(response.content.decode())
                    else:
                        # We need to further investigate error cases for preflight v2 endpoint,
                        # but a non-JSON response for a preflight v2 request is
                        # an obvious error.
                        error_msg = "Our system encountered an error while executing " \
                                    "preflight check for document %s."
                        logger.error(error_msg, identifier)
                        process_metadata_and_log(base_submission_dir, error_msg, temp_dir)
                        return None, None

                # Call the function to extract files from the output
                extract_output_files(output_file_path, temp_dir)

                # Find and parse the JSON file
                json_files = glob.glob(os.path.join(temp_dir, '*.json'))
                if json_files:
                    json_file_path = json_files[0]  # Take the first JSON file found
                    with open(json_file_path, 'r') as json_file:
                        json_data = json.load(json_file)

                        if preflight:
                            logger.debug("Completed preflight check for %s", identifier)
                            status = 'success'
                        else:
                            # Fetch 'status' and 'output_files' values from the JSON
                            status = json_data.get('status')
                            output_files = json_data.get('output_files', {})
                            pdf_file = json_data.get('pdf_file', None)

                            logger.debug("Compilation Status: %s", status)
                            logger.debug("Output Files: %s", output_files)
                            logger.debug("PDF File: %s", pdf_file)

                            # Install PDF and log file into base_submission_dir

                            # Use the value of pdf_file directly
                            if pdf_file is not None:
                                pdf_file_path = find_pdf_file(temp_dir, pdf_file)
                                if pdf_file_path and os.path.exists(pdf_file_path):
                                    try:
                                        shutil.copy2(pdf_file_path, new_pdf_path)
                                        os.chmod(new_pdf_path, 0o664)
                                    except OSError as e:
                                        logger.error("There was an error copying PDF file: %s", e)

                                elif pdf_file_path:
                                    # This is acceptable when compilation fails
                                    logger.error("No 'pdf_file' found in response.")
                                else:
                                    # This is acceptable when compilation fails
                                    logger.info("No 'pdf_file' found in response.")

                    process_metadata_and_log(base_submission_dir, " ", temp_dir, json_data, json_file_path)

                    # We currently update the gzipped tar file when a compilation succeeds.
                    if not preflight and status == 'success' and not source_file and os.path.exists(temp_tar_path):
                        # Copy new gzipped tarfile into submission directory
                        try:
                            shutil.copy2(temp_tar_path, new_tar_path)
                            os.chmod(temp_tar_path, 0o664)
                        except OSError as e:
                            logger.critical("ERROR: copying gziped tar file "
                                            "from %s to %s: %s", temp_tar_path, new_tar_path, e)

                else:
                    # We should always get a json file with the response
                    logger.critical("No JSON file found.")

            else:
                logger.error("Unexpected content type '%s in response.",
                             response.headers.get('content-type'))
                return None, None

            if preflight:
                operation = 'Preflight'
            else:
                operation = 'Compilation'

            if status == 'success':
                logger.info(f"{operation} of document %s succeeded at GCP", identifier)
            else:
                logger.error(f"{operation} of document %s failed at GCP", identifier)

        except requests.exceptions.RequestException as e:
            logger.critical("The request to process document %s at GCP "
                            "failed: %s", identifier, e)
            error_msg = "There was fatal error during our attempt to process your " \
                        f"document's source files(s).\n\nERROR: {e}\n\nPlease try " \
                        "again or contact the arXiv editorial team."
            process_metadata_and_log(base_submission_dir, error_msg, temp_dir)
            return None, None
        except tarfile.TarError as e:
            error_msg = "Our system encountered an error extracting source " \
                        "files for submission %s: %s"
            logger.error(error_msg, identifier, e)
            process_metadata_and_log(base_submission_dir, error_msg, temp_dir)
            return None, None

        return status, json_data


def main(args):
    """Setup routine for command-line invocation."""
    set_up_logging(identifier=args.identifier, system_logs_dir=args.logs_dir,
                   system_log_name='compile_at_gcp.log',
                   log_to_console=args.console, base_submissions_dir=args.base)

    # Call the compile function with the provided arguments
    status, json_data = _compile_submission(args)

    # dump json to console if both verbose and debug mode are enabled
    if args.console and json_data and args.debug and args.verbose:
        set_up_logging(identifier=args.identifier, log_to_console=args.console,
                       only_log_to_console=True)
        logger.debug("JSON file content:")
        logger.debug(json.dumps(json_data, indent=2))
        logger.debug("Status: %s", status)


if __name__ == "__main__":
    # Create an argument parser
    parser = argparse.ArgumentParser(description="Process LaTeX to PDF conversion request")

    # Define command-line options
    parser.add_argument("-a", "--max-append-files", type=int, default=0,
                        help="Maximum number of extra files to append to PDF (default=0)")
    parser.add_argument("-i", "--identifier", required=True, help="Identifier for the request")
    parser.add_argument("-m", "--max-tex-files", type=int, default=1,
                        help="Maximum number of text files to process (default=1)")
    parser.add_argument("-o", "--output", required=True, help="Output gzipped tar file")
    parser.add_argument("-p", "--preflight", nargs='?', const='v1',
                        choices=list(PreflightOption),
                        help="Preflight check option: 'v1', 'v2'. Defaults to 'v1' if "
                             "no argument is provided.")
    parser.add_argument("-s", "--source", default=None, help="Source LaTeX file (gzipped tar)")
    parser.add_argument("-t", "--timeout", type=int, default=DEFAULT_COMPILATION_TIMEOUT,
                        help="Timeout for the request in seconds")
    parser.add_argument("-w", "--watermark-text", default=None, help="Text string for PDF watermark.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose mode")
    parser.add_argument("-d", "--debug", action="store_true", help="Enable debug mode (dump JSON)")
    parser.add_argument("-b", "--base", default="/data/new",
                        help="Root directory for submissions directories (default:/data/new)")
    parser.add_argument("-c", "--console", default=False, action="store_true",
                        help="Write log output to console.")
    parser.add_argument("-l", "--logs-dir", default="/users/e-prints/httpd/logs",
                        help="Directory to store system level compilation log.")
    parser.add_argument("-u", '--tex2pdf-url', default=GCP_COMPILE_URL,
                        help="URL for tex2pdf service. Defaults to production service.")

    # Parse command-line arguments
    args = parser.parse_args()

    # Call main to dispatch request to compile_submission method
    main(args)
