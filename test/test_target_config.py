"""
pytest test cases for fa_target_eye.target_config which contains the object
representation of a Prometheus file-based service discovery file.
"""
import json
from string import ascii_letters, digits, whitespace, punctuation

from hypothesis import given
import hypothesis.strategies as st
from prometheus_client.metrics_core import METRIC_LABEL_NAME_RE
import pytest

from fa_target_eye.target_config import TargetConfig

ALLOWED_PORTS = st.integers(min_value=1, max_value=2 ** 16 - 1)

LETTERS = st.text(alphabet=ascii_letters, min_size=1)

TARGET_TUPLE_LIST = st.lists(
    st.tuples(LETTERS, ALLOWED_PORTS), min_size=1, max_size=2 ** 5, unique=True,
)

UNICODE_VALUES = st.text(min_size=1)

LABELS_DICT = st.dictionaries(LETTERS, UNICODE_VALUES, min_size=1, max_size=2 ** 10,)


@given(st.floats(allow_nan=True, allow_infinity=True))
def test_invalid_float_port_numbers(port):
    """Make sure float port numbers get rejected"""
    with pytest.raises(ValueError):
        TargetConfig(application="app", environment="env", targets=[f"localhost:{port}"])


@given(st.floats(min_value=1, max_value=2 ** 16 - 1))
def test_invalid_float_port_numbers_within_valid_integer_range(port):
    """Make sure floats within the valid port range get rejected"""
    with pytest.raises(ValueError):
        TargetConfig(application="app", environment="env", targets=[f"localhost:{port}"])


@given(st.one_of(st.integers(min_value=-100, max_value=-1), st.integers(min_value=2 ** 16)))
def test_invalid_integer_port_numbers(port):
    """Make sure invalid integers get rejected"""
    with pytest.raises(ValueError):
        TargetConfig(application="app", environment="env", targets=[f"localhost:{port}"])


@given(st.text(alphabet=whitespace))
def test_invalid_whitespace_label_names(label_name):
    """Make sure invalid label names of just whitespace get rejected"""
    with pytest.raises(ValueError):
        labels = {label_name: "value"}
        TargetConfig(application="app", environment="env", labels=labels)


@given(st.text(alphabet=digits))
def test_invalid_digits_label_names(label_name):
    """Make sure invalid label names of just digits get rejected"""
    with pytest.raises(ValueError):
        labels = {label_name: "value"}
        TargetConfig(application="app", environment="env", labels=labels)


def invalid_label_punctuation() -> str:
    """Return invalid label name punctuation symbols"""
    return "".join(char for char in punctuation if char != "_")


@given(st.text(alphabet=invalid_label_punctuation()))
def test_invalid_punctuation_label_names(label_name):
    """Make sure invalid label names of non-underscore punctuation get rejected"""
    with pytest.raises(ValueError):
        labels = {label_name: "value"}
        TargetConfig(application="app", environment="env", labels=labels)


@given(st.from_regex(METRIC_LABEL_NAME_RE))
def test_valid_label_names(label_name):
    """Make sure valid label names end up creating TargetConfig objects without
    throwing an exception"""
    target_config = TargetConfig(
        application="app", environment="env", targets=[], labels={label_name: "value",}
    )
    assert (
        len(target_config.labels) == 3 and {"job", "env", label_name} == target_config.labels.keys()
    )


@given(UNICODE_VALUES, UNICODE_VALUES)
def test_default_labels_added_when_no_labels_in_constructor(app, env):
    """Make sure the constructor includes the default job and env labels"""
    target_config = TargetConfig(application=app, environment=env)
    assert target_config.labels == {"job": app, "env": env}


@given(st.ip_addresses(v=4), ALLOWED_PORTS)
def test_ip_address_hosts_are_allowed(ip_address, port):
    """Make sure IP addresses can be used for hostnames"""
    targets = [f"{ip_address!s}:{port}"]
    target_config = TargetConfig(application="app", environment="env", targets=targets,)
    assert target_config.targets == targets


@given(UNICODE_VALUES, UNICODE_VALUES)
def test_json_property_gets_created_properly(app, env):
    """Make sure the JSON version of the object looks correct"""
    target_config = TargetConfig(application=app, environment=env)
    expected_json = [{"targets": [], "labels": {"job": app, "env": env}}]

    assert json.loads(target_config.json) == expected_json


@given(
    UNICODE_VALUES, UNICODE_VALUES, TARGET_TUPLE_LIST,
)
def test_targets_list_updates(app, env, target_tuples):
    """Make sure updates to the targets list work as expected

    In particular, an update should only work if all the updates provided
    aren't already in the list
    """
    starting_targets = ["localhost:1", "graceful:2"]
    target_config = TargetConfig(application=app, environment=env, targets=starting_targets)

    assert target_config.targets == starting_targets
    assert target_config.labels == {"job": app, "env": env}

    new_targets = [f"{host}:{port}" for host, port in target_tuples]
    all_targets = starting_targets + new_targets

    assert not target_config.update_with_new_targets(starting_targets)
    assert not target_config.update_with_new_targets(all_targets)
    assert not target_config.update_with_new_targets(new_targets * 2)

    assert target_config.update_with_new_targets(new_targets)
    assert sorted(target_config.targets) == sorted(all_targets)


@given(
    UNICODE_VALUES, UNICODE_VALUES, LABELS_DICT,
)
def test_labels_updates(app, env, label_updates):
    """Make sure updates to the labels work as expected

    In particular, an update should only work if all the updates provided
    actually change a key in the labels dict
    """
    starting_targets = ["localhost:1"]
    starting_labels = {"job": "myjob", "env": "myenv"}
    target_config = TargetConfig(
        application=app, environment=env, targets=starting_targets, labels=starting_labels
    )

    assert target_config.targets == starting_targets
    assert target_config.labels == starting_labels

    # all updates must replace the value of an existing field
    # or be a new field
    assert not target_config.update_with_new_labels(
        {"job": "someotherjob", "env": starting_labels["env"],}
    )
    assert not target_config.update_with_new_labels(
        {"newlabel": "newvalue", "env": starting_labels["env"],}
    )

    new_labels = starting_labels.copy()
    new_labels.update(label_updates)
    assert target_config.update_with_new_labels(label_updates)

    assert target_config.labels == new_labels

    assert not target_config.update_with_new_labels(label_updates)


@given(
    UNICODE_VALUES, UNICODE_VALUES, TARGET_TUPLE_LIST,
)
def test_delete_from_targets(app, env, target_tuples):
    """Test that deleting some of the targets but not all of them works"""
    # need one dummy target because we can't delete all the targets
    # through the delete_from_targets method
    target_config = TargetConfig(application=app, environment=env, targets=["dummy"],)

    orig_targets = target_config.targets[:]
    new_targets = [f"{host}:{port}" for host, port in target_tuples]
    not_in_targets = "NOTIN:1"

    for new_target in new_targets:
        # try to delete a target before it exists
        assert not target_config.delete_from_targets([new_target])
        assert target_config.targets == orig_targets

        # add a new target
        assert target_config.update_with_new_targets([new_target])

        # try to delete the new target along with a target that isn't in the
        # object
        assert not target_config.delete_from_targets([new_target, not_in_targets])
        assert sorted(target_config.targets) == sorted(orig_targets + [new_target])

        # delete the newly added target
        assert target_config.delete_from_targets([new_target])
        assert target_config.targets == orig_targets

    # add all the targets back
    assert target_config.update_with_new_targets(new_targets)

    # delete all the targets again
    assert target_config.delete_from_targets(new_targets)

    # try to re-delete
    assert not target_config.delete_from_targets(new_targets)


@given(
    UNICODE_VALUES, UNICODE_VALUES, LABELS_DICT,
)
def test_delete_from_labels(app, env, labels):
    """Test deleting labels works as expected"""
    target_config = TargetConfig(application=app, environment=env, labels=labels.copy())

    assert not target_config.delete_from_labels(target_config.labels)
    assert target_config.delete_from_labels(labels)
    assert not target_config.delete_from_labels(labels)

    assert not target_config.delete_from_labels({"job": target_config.labels["job"]})
    assert not target_config.delete_from_labels({"job": ""})

    assert not target_config.delete_from_labels({"env": target_config.labels["env"]})
    assert not target_config.delete_from_labels({"env": ""})

    assert not target_config.delete_from_labels(
        {"job": target_config.labels["job"], "env": target_config.labels["env"]}
    )
    assert not target_config.delete_from_labels({"job": "", "env": ""})
