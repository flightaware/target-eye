"""
Contains tests utilizing the JSON schema defined by Target-eye that matches the
exact format expect by Prometheus inside file-based service discovery files.
"""
from contextlib import contextmanager
from string import ascii_letters

from hypothesis import given
import hypothesis.strategies as st
from jsonschema import validate, ValidationError
from prometheus_client.metrics_core import METRIC_LABEL_NAME_RE
import pytest

from fa_target_eye.target_config_schema import (
    TARGET_CONFIG_FILE_SCHEMA,
    TARGET_CONFIG_OBJECT_SCHEMA,
)

UNICODE_VALUES = st.text(min_size=1)
LETTERS = st.text(alphabet=ascii_letters, min_size=1)
LABELS = st.dictionaries(st.from_regex(METRIC_LABEL_NAME_RE), UNICODE_VALUES)


@contextmanager
def not_raises(exception):
    """Context manager to ensures that a particular exception was not raised

    Taken from:

    https://stackoverflow.com/questions/20274987/how-to-use-pytest-to-check-that-error-is-not-raised
    """
    try:
        yield
    except exception:
        pytest.fail(f"DID RAISE {exception}")


@given(UNICODE_VALUES, UNICODE_VALUES, LETTERS, LABELS)
def test_known_valid_schemas(app, env, host, labels):
    """Assert true for a number of known valid examples"""
    labels.update({"job": app, "env": env})
    target_config_object = {
        "targets": [f"{host}", f"{host}:1"],
        "labels": labels,
    }

    with not_raises(ValidationError):
        validate(target_config_object, TARGET_CONFIG_OBJECT_SCHEMA)
        validate([target_config_object], TARGET_CONFIG_FILE_SCHEMA)


def test_invalid_schemas_empty_values():
    """Should throw an error for invalid schemas with empty values"""
    with pytest.raises(ValidationError):
        validate({}, TARGET_CONFIG_OBJECT_SCHEMA)

    with pytest.raises(ValidationError):
        validate([], TARGET_CONFIG_FILE_SCHEMA)

    with pytest.raises(ValidationError):
        validate([{}], TARGET_CONFIG_FILE_SCHEMA)


@given(UNICODE_VALUES, UNICODE_VALUES, LABELS)
def test_invalid_schemas_no_targets(app, env, labels):
    """Should throw an error for invalid schemas with no targets"""
    no_targets = {
        "labels": {"job": app, "env": env},
    }
    no_targets.update(labels)

    with pytest.raises(ValidationError):
        validate(no_targets, TARGET_CONFIG_OBJECT_SCHEMA)

    with pytest.raises(ValidationError):
        validate(no_targets, TARGET_CONFIG_OBJECT_SCHEMA)

    with pytest.raises(ValidationError):
        validate([no_targets] * 2, TARGET_CONFIG_OBJECT_SCHEMA)


@given(LETTERS)
def test_invalid_schemas_no_labels(host):
    """Should throw an error for invalid schemas with no labels"""
    no_labels = {
        "targets": [f"{host}", f"{host}:1"],
    }
    with pytest.raises(ValidationError):
        validate(no_labels, TARGET_CONFIG_OBJECT_SCHEMA)

    with pytest.raises(ValidationError):
        validate([no_labels], TARGET_CONFIG_FILE_SCHEMA)

    with pytest.raises(ValidationError):
        validate([no_labels] * 2, TARGET_CONFIG_OBJECT_SCHEMA)


@given(UNICODE_VALUES, UNICODE_VALUES, LETTERS, LABELS)
def test_invalid_schemas_multiple_inner_objects(app, env, host, labels):
    """Throw an error when more than one valid object is included in the file
    schema"""
    labels.update({"job": app, "env": env})
    valid_schema = {
        "targets": [f"{host}", f"{host}:1"],
        "labels": labels,
    }

    with not_raises(ValidationError):
        validate(valid_schema, TARGET_CONFIG_OBJECT_SCHEMA)
        validate([valid_schema], TARGET_CONFIG_FILE_SCHEMA)

    with pytest.raises(ValidationError):
        validate([valid_schema] * 2, TARGET_CONFIG_FILE_SCHEMA)
