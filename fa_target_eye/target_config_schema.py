"""
Contains JSON schema for TargetConfig objects.

This is used primarily to validate REST API requests and to ensure that we only
write JSON to disk that Prometheus can understand.
"""

NON_EMPTY_STRING = {"type": "string", "minLength": 1}

TARGETS_LIST_SCHEMA = {
    "description": "[<host/IPv4/domain>:<port>, ...] to scrape for metrics",
    "type": "array",
    "minItems": 1,
    "properties": {"items": NON_EMPTY_STRING},
}

LABELS_DICT_SCHEMA = {
    "description": "Format of the labels object",
    "type": "object",
    "minProperties": 2,
    "properties": {"job": NON_EMPTY_STRING, "env": NON_EMPTY_STRING},
    "required": ["job", "env"],
}

TARGET_CONFIG_OBJECT_SCHEMA = {
    "description": "Format of the elements of the TARGET_CONFIG_FILE_SCHEMA array",
    "type": "object",
    "minProperties": 2,
    "maxProperties": 2,
    "properties": {"targets": TARGETS_LIST_SCHEMA, "labels": LABELS_DICT_SCHEMA,},
    "required": ["targets", "labels"],
}

TARGET_CONFIG_FILE_SCHEMA = {
    "description": "Format of the contents of a target config file",
    "type": "array",
    "maxItems": 1,
    "minItems": 1,
    "items": TARGET_CONFIG_OBJECT_SCHEMA,
}
