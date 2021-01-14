"""
Target-eye writes target config files containing JSON into a Prometheus
file-based service discovery mechanism.  Those JSON files are named using the
application / service and environment.

The format inside each JSON file is quite simple:

[
  {
    "targets": [ "<host>", ... ],
    "labels": {
      "<labelname>": "<labelvalue>", ...
    }
  },
  ...
]

Target-eye only allows a single object in the list per-file.

By default, Target-eye includes the following labels:

    - job: contains the application / service specified in a REST API call
    - env: contains the environment for the job label

Both of these can be overridden by specifying the labels in the REST API
request but they cannot be removed.

In order to manage these files, Target-eye converts each of them into a Python
object that can be easily converted into JSON and vice versa.  The Python
objects are responsible for writing the contents out to disk so that Prometheus
will pick this up and modify its scrape targets accordingly.
"""
import asyncio
from hashlib import md5
import json
import os
import re
from typing import Dict, List, Optional

import aiofiles
import aiofiles.os
import attr
import jsonschema
from prometheus_client.metrics_core import METRIC_LABEL_NAME_RE
import validators

from .target_config_schema import TARGET_CONFIG_FILE_SCHEMA


@attr.s(slots=True, kw_only=True, eq=False)
class TargetConfig:
    """Given an application and an environment, TargetConfig provides a
    container for the contents of the target config file.

    On disk a target config file contains JSON and is in a file with a .json
    extension whose name consists of the has of the application and environment
    information.
    """

    application: str = attr.ib()
    environment: str = attr.ib()
    targets: List[str] = attr.ib(factory=list)
    labels: Dict[str, str] = attr.ib(factory=dict)
    _filename: Optional[str] = attr.ib(init=False, default=None)
    _file_lock: asyncio.Lock = attr.ib(factory=asyncio.Lock)

    def __attrs_post_init__(self) -> None:
        """Properly set the labels attribute"""
        if not self.labels:
            self.labels = {
                "job": self.application,
                "env": self.environment,
            }

        if "job" not in self.labels:
            self.labels["job"] = self.application

        if "env" not in self.labels:
            self.labels["env"] = self.environment

    def __eq__(self, other):
        """Whether two TargetConfig objects are equal which is based on all the
        attributes except for _file_lock
        """
        return (
            self.application == other.application
            and self.environment == other.environment
            and sorted(self.targets) == sorted(other.targets)
            and self.labels == other.labels
        )

    def __ne__(self, other):
        """Counterpart to the eq dunder"""
        return not self.__eq__(other)

    HOSTNAME_RE = re.compile(r"(?!-)[a-z0-9-]{1,63}(?<!-)$", re.IGNORECASE)

    # self is required for the attr validation to work
    # pylint: disable=no-self-use
    @targets.validator
    def validate_targets(self, _: attr.Attribute, targets: List[str]) -> bool:
        """Whether the list of targets only contains valid targets

        Each target must consist of a hostname or IP followed by an optional port number
        """
        return all(self.validate_target(target) for target in targets)

    @staticmethod
    def validate_target(target: str):
        """Whether a given target is a valid hostname / IP and port"""

        def valid_host(host: str) -> bool:
            """Valid hostname or IPv4 address with localhost allowed"""
            if valid_hostname(host):
                return True

            if validators.domain(host):
                return True

            if validators.ipv4(host):
                return True

            raise ValueError(f"Invalid host {host}")

        def valid_port(port: str) -> bool:
            """Valid port number excluding the 0 port"""
            if not port.isdigit():
                raise ValueError(f"Port must be integer {port}")

            if int(port) not in range(1, 2 ** 16):
                raise ValueError(f"Invalid port number {port}")
            return True

        host, *rest = target.split(":", maxsplit=1)

        if not host.strip():
            raise ValueError("Empty hostname")

        if not rest:
            # Prometheus' default
            # https://prometheus.io/docs/prometheus/latest/configuration/configuration/
            port = "80"
        else:
            port = rest[0]

        return valid_host(host) and valid_port(port)

    # self is required for the attr validation to work
    # pylint: disable=no-self-use
    @labels.validator
    def validate_labels(self, _: Optional[attr.Attribute], labels: Dict[str, str]) -> bool:
        """Whether the dict of labels conforms to Prometheus standards

        In particular this concerns label names since label values can be any
        sequence of UTF-8 characters

        For label values we make sure that we can encode them using UTF-8 without an
        exception
        """
        return all(
            self.validate_label(label_name, label_value)
            for label_name, label_value in labels.items()
        )

    @staticmethod
    def validate_label(label_name: str, label_value: str) -> bool:
        """Whether a label name and key are valid"""
        try:
            label_value.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError(f"For label {label_name}, invalid label value {label_value}")

        if not METRIC_LABEL_NAME_RE.match(label_name):
            raise ValueError(f"Invalid label {label_name}")

        return True

    def __deepcopy__(self, _):
        """Does a deepcopy except for the _file_lock which we keep the same for
        all copies so that any attempts to write to disk must be serialized"""
        return attr.evolve(self, file_lock=self._file_lock)

    @property
    def filename(self) -> str:
        """Returns the relative filename for this object

        In order to avoid non-ASCII characters in file paths we use a hash of
        the UTF-8 encoded bytes object of the application and the environment
        """

        def bytes_to_hash() -> bytes:
            """Return the bytes to hash for the TargetConfig's filename"""
            contents = f"{self.application}{self.environment}"
            return contents.encode("utf-8")

        def hash_value() -> str:
            """Return the hashed filename value"""
            return md5(bytes_to_hash()).hexdigest()

        if self._filename is None:
            self._filename = hash_value()

        return f"{self._filename}.json"

    @property
    def json(self) -> str:
        """Converts the object into a JSON representation suitable for
        Prometheus' file-based service discovery
        """
        return json.dumps([{"targets": self.targets, "labels": self.labels,}])

    @classmethod
    def from_json_file(cls, target_config_file_path: str):
        """Create an instance of the class from a target config file"""
        with open(target_config_file_path) as file_obj:
            target_config_list = json.load(file_obj)
            target_config_dict = target_config_list[0]

            return cls(
                application=target_config_dict["labels"]["job"],
                environment=target_config_dict["labels"]["env"],
                targets=target_config_dict["targets"],
                labels=target_config_dict["labels"],
            )

    async def write_to_file(self, directory: str) -> None:
        """Use aiofiles to write the JSON contents to disk

        If the JSON version of the target does not fit the schema raises a
        TypeError

        If the directory does not exist raises a FileNotFoundError
        """
        if not self.valid_prometheus_json():
            raise TypeError(f"Invalid JSON for target config: {self}")

        if not os.path.isdir(directory):
            raise FileNotFoundError

        async with self._file_lock:
            file_path = os.path.join(directory, self.filename)
            async with aiofiles.open(file_path, mode="w") as target_file:
                await target_file.write(self.json)

    async def read_from_file(self, directory: str) -> str:
        """Use aiofiles to read the JSON contents from disk based on this
        object's filename property

        If the directory or file does not exist, raises a FileNotFoundError

        Returns the contents of the file back as a string
        """
        if not os.path.isdir(directory):
            raise FileNotFoundError

        json_file = os.path.join(directory, self.filename)

        if not os.path.isfile(json_file):
            raise FileNotFoundError

        async with aiofiles.open(json_file, encoding="utf-8") as file_obj:
            return await file_obj.read()

    async def delete_file(self, directory: str) -> None:
        """Use aiofiles to delete this object's file from the given directory

        If the filename does not exist raises a FileNotFoundError

        If the directory does not exist raises a FileNotFoundError
        """
        if not os.path.isdir(directory):
            raise FileNotFoundError

        abs_file_path = os.path.join(directory, self.filename)
        if not os.path.isfile(abs_file_path):
            raise FileNotFoundError

        await aiofiles.os.remove(abs_file_path)

    def valid_prometheus_json(self) -> bool:
        """Whether the object's JSON matches the schema that Prometheus
        expects"""
        try:
            jsonschema.validate(json.loads(self.json), TARGET_CONFIG_FILE_SCHEMA)
        except jsonschema.ValidationError:
            return False
        else:
            return True

    def update_with_new_targets(self, targets: List[str]) -> bool:
        """Given a list of additional targets, add them to the list of targets
        in the object.

        If only new targets were provided and the targets list does not contain
        duplicates, return True
        If False is returned no update is made to the target config

        Raises a ValueError if any of the targets is in an invalid form
        """
        if not targets:
            return False

        if sorted(set(targets)) != sorted(targets):
            return False

        for target in targets:
            if target in self.targets:
                return False

            self.validate_target(target)

        self.targets.extend(targets)
        return True

    def update_with_new_labels(self, labels: Dict[str, str]) -> bool:
        """Given a dict of potential label updates, add them to the list of
        labels in the object if the label name does not exist.

        If the label name does exist, its value will be modified.

        If every key-value pair in labels causes an update, return True

        Raises a ValueError if any of the labels is in an invalid form
        """
        if not labels:
            return False

        for name, value in labels.items():
            if name not in self.labels:
                continue

            if not value.strip():
                return False

            if self.labels[name] == value:
                return False

            self.validate_label(name, value)

        self.labels.update(labels)
        return True

    def delete_from_targets(self, targets: List[str]) -> bool:
        """Given a list of targets, delete those from the object's current list
        of targets

        If all targets would be deleted, return False

        If not all targets provided are in the current targets list return
        False

        Otherwise return True

        Object is only modified if this method returns True
        """
        if not targets:
            return False

        if not all(target in self.targets for target in targets):
            return False

        if sorted(set(targets)) != sorted(targets):
            return False

        if len(targets) == len(self.targets):
            return False

        self.targets = list(set(self.targets) - set(targets))
        return True

    def delete_from_labels(self, labels: Dict[str, str]) -> bool:
        """Given an iterable of labels, delete those from the object's current dict
        of labels

        If the job or env label would be deleted, return False

        If not all label names provided are in the current labels, return
        False

        Otherwise return True

        Object is only modified if this method returns True
        """
        if not labels:
            return False

        if "job" in labels or "env" in labels:
            return False

        for label_name, label_value in labels.items():
            if label_name not in self.labels:
                return False

            if label_value != self.labels[label_name]:
                return False

        for label in labels:
            del self.labels[label]
        return True


@validators.validator
def valid_hostname(hostname: str) -> bool:
    """Validator for hostname

    Taken from https://stackoverflow.com/questions/2532053/validate-a-hostname-string
    """
    if not hostname.strip():
        return False

    if hostname[-1] == ".":
        # strip exactly one dot from the right, if present
        hostname = hostname[:-1]

    if len(hostname) > 253:
        return False

    labels = hostname.split(".")

    # the TLD must be not all-numeric
    if re.match(r"[0-9]+$", labels[-1]):
        return False

    return all(TargetConfig.HOSTNAME_RE.match(label) for label in labels)
