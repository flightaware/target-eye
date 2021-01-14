"""
REST API for Target-eye provides the ability to:

    - Add
    - Update
    - Delete

Prometheus scrape targets.

Targets consist of the following information:

    - Hostname / IP address
    - Port
    - Application / Service
    - Environment, e.g., prod-hou, staging-dal, test-hou
    - Labels (optional)
        By default, each target's metrics will also include a job label with
        the Application / Service as its value and the env label with
        Environment as its value

        The values of job and env can be overridden by the client but not
        excluded, i.e., job and env will always be included with the metrics
        scraped by targets defined for the given application and environment

The REST API provides a single URL:

    /<application>/<environment>

Targets and labels are included in the request body.


Only a single list of targets and labels can be applied to a given application
and environment.  This limitation is imposed for operational simplicity.
"""

import asyncio
from copy import deepcopy
from getpass import getuser
import logging
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
from typing import Any, Awaitable, Dict, List, MutableMapping, Optional


import attr
from hypercorn.asyncio import serve
from hypercorn.config import Config
import jsonschema
import toml
import quart
import yaml

from .target_config import TargetConfig
from .target_config_schema import TARGETS_LIST_SCHEMA

REST_APP = quart.Quart(__name__)
LOGGER = logging.getLogger(__name__)
SHUTDOWN_EVENT = asyncio.Event()


def run_rest_api(config_file: str) -> None:
    """Setup and run the quart web-app that provides the REST API based on the
    config file passed in.

    If config_file is not a valid file-path it is expected that all the
    arguments will come from environment variables.
    """

    def get_file_sd_directory() -> str:
        """Use environment variables or the config dict to find the directory
        for file-based service discovery"""
        file_sd_dir = os.getenv("FILE_SD_DIRECTORY")
        if file_sd_dir is None:
            file_sd_dir = config_dict["target-eye"].get("file_sd_directory")
            if not file_sd_dir:
                LOGGER.error("No file_sd_directory defined in config or env")
                sys.exit(1)

        return file_sd_dir

    def tls_configured() -> bool:
        """Whether enough config attributes have been set for TLS"""
        return all((hypercorn_config.certfile, hypercorn_config.keyfile))

    config_dict: MutableMapping[str, Any] = {"hypercorn": {}, "target-eye": {}}
    if os.path.isfile(config_file):
        LOGGER.info(f"Loading config from {config_file}")
        config_dict = toml.load(config_file)

    if config_dict["hypercorn"]:
        hypercorn_config = Config.from_mapping(config_dict["hypercorn"])
    else:
        LOGGER.info("Loading configuration from environment variables")
        hypercorn_config = hypercorn_config_from_env()

    setup_logging(hypercorn_config.loglevel)

    file_sd_dir = get_file_sd_directory()
    setup_file_sd_directory(file_sd_dir)
    REST_APP.config["file_sd_directory"] = file_sd_dir

    target_configs = load_target_configs(file_sd_dir)
    REST_APP.config["target_configs"] = target_configs
    LOGGER.info(f"Loaded {len(target_configs)} target configs from {file_sd_dir}")

    if tls_configured():
        LOGGER.info(f"Exposing HTTPS REST API with TLS on {hypercorn_config.bind}")
    else:
        LOGGER.info(f"Exposing HTTP REST API without TLS on {hypercorn_config.bind}")

    # If an exception occurs during serving requests, we log it and exit
    # rather than moving on to further processing, so it's not bad in this
    # case to catch all exceptions broadly: it's what we want
    # pylint: disable=broad-except
    try:
        loop = asyncio.get_event_loop()

        loop.add_signal_handler(signal.SIGTERM, _signal_handler)
        loop.add_signal_handler(signal.SIGINT, _signal_handler)

        loop.run_until_complete(
            serve(REST_APP, hypercorn_config, shutdown_trigger=_shutdown_trigger)
        )
    except Exception as err:
        LOGGER.error(f"When trying to serve Target-eye: {err}")
        sys.exit(1)


def _shutdown_trigger(*_: Any) -> Awaitable[None]:
    """Called to allow for a graceful shutdown"""
    return asyncio.create_task(SHUTDOWN_EVENT.wait())


def _signal_handler(*_: Any) -> None:
    """Shutdown the app ASAP"""
    LOGGER.info("Shutting down Target-eye")
    SHUTDOWN_EVENT.set()


def hypercorn_config_from_env() -> Config:
    """Fill in a hypercorn Config object with environment variables"""

    # this grabs all the attributes of the Config class used for configuration
    # skipping over methods and other unusable attributes
    config_attrs = [
        config_attr
        for config_attr in dir(Config)
        if not config_attr.startswith("_") and not callable(getattr(Config, config_attr))
    ]

    hypercorn_config = Config()
    for config_attr in config_attrs:
        if (config_value := os.getenv(config_attr.upper())) is not None:
            setattr(hypercorn_config, config_attr, config_value)

    return hypercorn_config


def setup_logging(log_level: str) -> None:
    """Setup logging format and level"""
    logging.basicConfig(
        level=log_level.upper(),
        format="%(asctime)s %(levelname)8s: (%(funcName)s) %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    LOGGER.setLevel(getattr(logging, log_level.upper()))


def setup_file_sd_directory(file_sd_dir: str) -> None:
    """Create the file service-discovery directory

    Will create all parent directories.

    Also tries to create a temporary file in that directory to check the
    ability of Target-eye to write new files to that directory.

    No error is thrown if the directory already exists.
    """
    try:
        Path(file_sd_dir).mkdir(
            parents=True, exist_ok=True,
        )
        LOGGER.info(f"Service discovery directory: {file_sd_dir}")
    except PermissionError as perr:
        LOGGER.error("Could not create service discovery directory")
        LOGGER.error(f"{perr}")
        sys.exit(1)

    try:
        with tempfile.TemporaryFile() as _:
            LOGGER.info(f"Service discovery directory is writable by current user {getuser()}")
    except PermissionError as perr:
        LOGGER.error("Could not create file in service discovery directory")
        LOGGER.error(f"{perr}")
        sys.exit(1)


def load_target_configs(directory: str) -> Dict[str, TargetConfig]:
    """Load all target configs in the given directory

    Returns a dictionary mapping relative filenames to TargetConfig objects.

    The returned dictionary is meant to be stored in the REST API
    """
    try:
        target_configs = {}
        file_sd_dir = Path(directory)

        for target_config_file_path in file_sd_dir.glob("*.json"):
            base_name = os.path.basename(target_config_file_path)
            target_configs[base_name] = TargetConfig.from_json_file(str(target_config_file_path))
    except Exception as err:
        LOGGER.error("Failed to load target config file")
        LOGGER.error(f"{err}")
        raise err
    else:
        return target_configs


def rest_api_methods() -> List[str]:
    """HTTP methods supported by the REST API"""
    return ["GET", "POST", "PUT", "DELETE"]


def json_mimetype() -> str:
    """Returns the mimetype for a JSON response"""
    return "application/json"


def file_sd_directory() -> str:
    """Returns the REST API file-based service discovery directory"""
    return REST_APP.config["file_sd_directory"]


def save_in_app_config(target_config: TargetConfig) -> None:
    """Save the given target config into the REST API's config"""
    REST_APP.config["target_configs"][target_config.filename] = target_config


def delete_from_app_config(target_config: TargetConfig) -> None:
    """Delete the given target config from the REST API's config"""
    del REST_APP.config["target_configs"][target_config.filename]


@REST_APP.route("/<application>/<environment>", methods=rest_api_methods())
async def targets_management(application: str, environment: str) -> quart.Response:
    """Manage the targets for an application and environment

    Always returns a JSON response
    """
    request_handler = globals()[f"{quart.request.method.lower()}"]
    try:
        return await request_handler(application, environment)
    except (ValueError, TypeError, jsonschema.ValidationError) as err:
        raise InvalidUsage(f"{err}")


async def post(application: str, environment: str) -> quart.Response:
    """A POST handles modifications to an existing application and
    environment's targets and / or labels.

    If the application and environment do not currently have a file on disk, it
    will be created, i.e., it is not an error.

    On success, which means that the changes were persisted to disk, a JSON
    response with the updated target information will be returned
    """
    target_config = maybe_find_target_config(
        application, environment, REST_APP.config["target_configs"]
    )
    request_targets = await targets_in_request(quart.request)
    request_labels = await labels_in_request(quart.request)

    if target_config is not None:
        if not (request_targets or request_labels):
            raise InvalidUsage("Must provide either targets or labels")

        if request_targets is not None and not request_targets:
            raise InvalidUsage("Cannot provide empty list of targets")

        if request_labels is not None and not request_labels:
            raise InvalidUsage("Cannot provide empty list of labels")

        if request_targets and not target_config.update_with_new_targets(request_targets):
            raise InvalidUsage("Some of the targets specified already exist")

        if request_labels and not target_config.update_with_new_labels(request_labels):
            raise InvalidUsage("Some of the labels specified already exist")
    elif not request_targets:
        raise InvalidUsage("Must provide at least one target")
    else:
        target_config = TargetConfig(
            application=application,
            environment=environment,
            targets=request_targets or [],
            labels=request_labels or {},
        )

    await target_config.write_to_file(file_sd_directory())
    save_in_app_config(target_config)

    return quart.Response(target_config.json, status=200, mimetype=json_mimetype())


async def put(application: str, environment: str) -> quart.Response:
    """A PUT handles replacing the data for a given application and environment
    entirely with whatever is contained in the request.

    This makes it, unlike the POST handler, idempotent.

    On success, which means that the changes were persisted to disk, a JSON
    response with the updated target information will be returned
    """

    request_targets = await targets_in_request(quart.request)
    request_labels = await labels_in_request(quart.request)

    if request_targets and request_labels:
        target_config = TargetConfig(
            application=application,
            environment=environment,
            targets=request_targets,
            labels=request_labels,
        )
    else:
        target_config = find_or_create_target_config(
            application, environment, REST_APP.config["target_configs"]
        )

        if request_targets:
            for request_target in request_targets:
                target_config.validate_target(request_target)

            target_config.targets = request_targets

        if request_labels:
            replace_labels_for_put(target_config, request_labels)

    await target_config.write_to_file(file_sd_directory())
    save_in_app_config(target_config)

    return quart.Response(target_config.json, status=200, mimetype=json_mimetype())


def replace_labels_for_put(target_config: TargetConfig, new_labels: Dict[str, str]) -> None:
    """During a PUT we want to replace the labels if any were provided but
    still preserving the job and env labels with their current values"""
    if "job" not in new_labels:
        new_labels["job"] = target_config.labels["job"]

    if "env" not in new_labels:
        new_labels["env"] = target_config.labels["env"]

    for label_name, label_value in new_labels.items():
        target_config.validate_label(label_name, label_value)

    target_config.labels = new_labels


async def delete(application: str, environment: str) -> quart.Response:
    """A DELETE handles getting rid of the target config, either whole or
    in-part, for an application and environment

    A request without any targets or labels will delete the entire config file

    A request with targets will delete any of the targets provided as long as
    at least one target would be left and all the provided targets are
    currently in the list of targets

    A request with labels will delete any of the label names provided (label
    keys are ignored)
    """
    target_config = maybe_find_target_config(
        application, environment, REST_APP.config["target_configs"]
    )

    if target_config is None:
        raise InvalidUsage(f"No targets defined for {application}/{environment}")

    request_targets = await targets_in_request(quart.request)
    request_labels = await labels_in_request(quart.request)

    if request_targets is not None and not request_targets:
        raise InvalidUsage("Cannot provide empty targets list")

    if request_labels is not None and not request_labels:
        raise InvalidUsage("Cannot provide empty labels dict")

    if request_targets and not target_config.delete_from_targets(request_targets):
        raise InvalidUsage("Cannot delete all targets")

    if request_labels and not target_config.delete_from_labels(request_labels):
        raise InvalidUsage("Cannot delete job or env labels")

    if not (request_targets or request_labels):
        await target_config.delete_file(file_sd_directory())
        delete_from_app_config(target_config)
    else:
        await target_config.write_to_file(file_sd_directory())
        save_in_app_config(target_config)

    return quart.Response(target_config.json, status=200, mimetype=json_mimetype())


async def get(application: str, environment: str) -> quart.Response:
    """GET requests return the contents of the current file for the given
    application and environment

    It is not an error to request an application and environment without any
    defined labels
    """
    target_config = maybe_find_target_config(
        application, environment, REST_APP.config["target_configs"]
    )

    if target_config is not None:
        response = target_config.json
    else:
        response = json.dumps([])

    return quart.Response(response, status=200, mimetype=json_mimetype())


# this is the formatting that black did, which runs without an exception
# pylint: disable=bad-continuation
def maybe_find_target_config(
    application: str, environment: str, target_configs: Dict[str, TargetConfig]
) -> Optional[TargetConfig]:
    """Given an application and environment, find the associated TargetConfig object
    in the dictionary of TargetConfig objects mapped by filename

    If one cannot be found, return None
    """
    looking_for = TargetConfig(application=application, environment=environment)

    if (current_target := target_configs.get(looking_for.filename)) is not None:
        return deepcopy(current_target)

    return None


# this is the formatting that black did, which runs without an exception
# pylint: disable=bad-continuation
def find_or_create_target_config(
    application: str, environment: str, target_configs: Dict[str, TargetConfig]
) -> TargetConfig:
    """Given an application and environment, find the associated TargetConfig object
    in the dictionary of TargetConfig objects mapped by filename

    If one cannot be found, one is created so that its attributes can be set
    accordingly

    If one is found, a copy of it with the same file lock is returned
    """
    looking_for = TargetConfig(application=application, environment=environment)
    found_target = target_configs.get(looking_for.filename)

    if found_target is not None:
        return deepcopy(found_target)

    return looking_for


def yaml_request(request: quart.local.LocalProxy) -> bool:
    """Given a request, return True if it contains a YAML request body"""
    return request.content_type in (
        "text/vnd.yaml",
        "text/yaml",
        "text/x-yaml",
        "application/vnd.yaml",
        "application/x-yaml",
        "application/yaml",
    )


def json_request(request: quart.local.LocalProxy) -> bool:
    """Given a request, return True if it contains a JSON request body"""
    return request.content_type == "application/json"


async def targets_in_request(request: quart.local.LocalProxy) -> Optional[List[str]]:
    """Given a REST API request, return all targets contained in quart.request

    If no targets were provided returns None

    This only makes sense in a non-GET request
    """
    if yaml_request(request) or json_request(request):
        if yaml_request(request):
            request_body = await request.get_data(raw=True)
            request_json = yaml.safe_load(request_body)
        else:
            request_json = await request.get_json(silent=True)

        if isinstance(request_json, dict):
            request_targets = request_json.get("targets")
        else:
            request_targets = None

    else:
        request_form = await request.form
        request_targets = request_form.get("targets")

        if isinstance(request_targets, str):
            request_targets = request_targets.split(",")

    if request_targets is not None:
        jsonschema.validate(request_targets, TARGETS_LIST_SCHEMA)

    return request_targets


async def labels_in_request(request: quart.local.LocalProxy) -> Optional[Dict[str, str]]:
    """Given a REST API request, return all labels provided

    If no labels were provided returns None

    This only makes sense in a non-GET request
    """
    if yaml_request(request) or json_request(request):
        if yaml_request(request):
            request_body = await request.get_data(raw=True)
            request_json = yaml.safe_load(request_body)
        else:
            request_json = await request.get_json(silent=True)

        if isinstance(request_json, dict):
            request_labels = request_json.get("labels")
        else:
            request_labels = None
    else:
        request_body = await request.form
        request_labels = {k: v for k, v in request_body.items() if k != "targets"}
        if not request_labels:
            request_labels = None

    if request_labels is not None:
        for label_name, label_value in request_labels.items():
            TargetConfig.validate_label(label_name, label_value)

    return request_labels


@attr.s
class InvalidUsage(Exception):
    """General exception for the REST API to use when a request does not match
    expectations

    It always returns a JSON response and can optionally be provided a dict of
    information as the payload keyword argument
    """

    message: str = attr.ib()
    status_code: int = attr.ib(default=400)
    payload: Optional[dict] = attr.ib(default=None)

    def to_dict(self):
        """Convert into a dict suitable for sending as JSON"""
        result = dict(self.payload or ())
        result["message"] = self.message
        return result


@REST_APP.errorhandler(InvalidUsage)
def invalid_usage_response(error: InvalidUsage) -> quart.Response:
    """Format an InvalidUsage error as a JSON response"""
    response = quart.jsonify(error.to_dict())
    response.status_code = error.status_code
    return response
