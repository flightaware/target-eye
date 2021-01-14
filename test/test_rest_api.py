"""
Tests for the file-based dynamic discovery service provided by Target-eye.

The tests here exercise the REST API provided by Target-eye using pytest and
hypothesis.
"""
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from fa_target_eye.target_config import TargetConfig
from fa_target_eye.rest_api import REST_APP, load_target_configs


@pytest.fixture(name="test_app_empty_folder")
def _test_app_empty_folder(tmpdir):
    """Setup for testing the REST API quart app without any target configs
    defined already"""
    REST_APP.config["file_sd_directory"] = tmpdir
    REST_APP.config["target_configs"] = load_target_configs(tmpdir)
    return REST_APP


@pytest.fixture(name="test_app_with_target_config")
async def _test_app_with_target_config(tmpdir):
    """Setup for testing the REST API quart app with a single target config for
    app/env with a single target and three additional labels, "A", "B", and "C"
    """
    target_config = TargetConfig(
        application="app",
        environment="env",
        targets=["localhost:12345"],
        labels={"A": "1", "B": "2", "C": "3"},
    )
    await target_config.write_to_file(tmpdir)

    REST_APP.config["file_sd_directory"] = tmpdir
    REST_APP.config["target_configs"] = {target_config.filename: target_config}
    REST_APP.config["target_config"] = target_config
    return REST_APP


@pytest.mark.asyncio
async def test_get_empty_config(test_app_empty_folder):
    """Test basic GET for an application and environment without any targets
    defined"""
    test_client = test_app_empty_folder.test_client()
    response = await test_client.get("/app/env")
    body = await response.get_json()

    assert response.status_code == 200
    assert body == []
    assert num_files(test_app_empty_folder.config["file_sd_directory"]) == 0


@pytest.mark.asyncio
async def test_empty_post_without_targets(test_app_empty_folder):
    """Test that a POST without any targets fails"""
    test_client = test_app_empty_folder.test_client()
    response = await test_client.post("/app/env")
    body = await response.get_json()

    assert response.status_code == 400
    assert body["message"]
    assert num_files(test_app_empty_folder.config["file_sd_directory"]) == 0


@pytest.mark.asyncio
async def test_json_post_with_targets(test_app_empty_folder):
    """Test that a JSON POST with targets succeeds"""
    test_client = test_app_empty_folder.test_client()
    targets = [f"host:12345", "host:12346"]
    response = await test_client.post("/app/env", json={"targets": targets})
    body = await response.get_json(silent=True)

    assert response.status_code == 200
    assert body == [{"targets": targets, "labels": {"job": "app", "env": "env"},}]
    assert num_files(test_app_empty_folder.config["file_sd_directory"]) == 1


@pytest.mark.asyncio
async def test_json_post_with_labels(test_app_empty_folder):
    """Test that a JSON POST with targets and labels succeeds"""
    test_client = test_app_empty_folder.test_client()

    targets = [f"host:12345", "host:12346"]
    labels = {"k1": "v1"}

    response = await test_client.post("/app/env", json={"targets": targets, "labels": labels})
    assert response.status_code == 200

    labels.update({"job": "app", "env": "env"})

    body = await response.get_json(silent=True)
    assert body == [{"targets": targets, "labels": labels}]

    assert num_files(test_app_empty_folder.config["file_sd_directory"]) == 1

    # add an additional key value pair
    new_labels = {"k2": "v2"}
    response = await test_client.post("/app/env", json={"labels": new_labels})
    assert response.status_code == 200

    labels.update(new_labels)

    body = await response.get_json(silent=True)
    assert body == [{"targets": targets, "labels": labels}]

    assert num_files(test_app_empty_folder.config["file_sd_directory"]) == 1


@pytest.mark.asyncio
async def test_non_json_post_with_labels(test_app_empty_folder):
    """Test that a non-JSON POST with targets and labels succeeds"""
    test_client = test_app_empty_folder.test_client()

    targets = ["host:1", "host:2"]
    form = {"targets": ",".join(targets)}
    labels = {"k1": "v1"}
    form.update(labels)

    response = await test_client.post("/app/env", form=form)
    assert response.status_code == 200

    expected_labels = {"job": "app", "env": "env", "k1": "v1"}

    body = await response.get_json(silent=True)
    assert body == [{"targets": targets, "labels": expected_labels}]

    assert num_files(test_app_empty_folder.config["file_sd_directory"]) == 1

    form = {"k2": "v2"}
    response = await test_client.post("/app/env", form=form)

    body = await response.get_json(silent=True)

    expected_labels.update(form)
    assert body == [{"targets": targets, "labels": expected_labels}]

    assert num_files(test_app_empty_folder.config["file_sd_directory"]) == 1


@pytest.mark.asyncio
async def test_non_json_post_with_targets(test_app_empty_folder):
    """Test that sending a non-JSON post works as intended"""
    test_client = test_app_empty_folder.test_client()

    targets = "a:12345,b:12346"

    response = await test_client.post("/app/env", form={"targets": targets})
    assert response.status_code == 200

    body = await response.get_json(silent=True)
    assert body == [{"targets": targets.split(","), "labels": {"job": "app", "env": "env"},}]

    assert num_files(test_app_empty_folder.config["file_sd_directory"]) == 1


@pytest.mark.asyncio
async def test_post_failure_does_not_modify_state(test_app_empty_folder):
    """When a POST fails, want to make sure that the app config is not affected"""
    test_client = test_app_empty_folder.test_client()

    original_targets = ["localhost:1"]
    original_labels = {"job": "some_app", "env": "some_env"}
    json_to_send = {
        "targets": original_targets,
        "labels": original_labels,
    }

    response = await test_client.post("/app/env", json=json_to_send)
    assert response.status_code == 200

    body = await response.get_json(silent=True)
    assert body == [json_to_send]

    # Sending some repeat labels with new labels should fail
    new_labels = original_labels.copy()
    new_labels.update({"k1": "v1", "k2": "v2"})
    json_to_send = {
        "targets": original_targets,
        "labels": new_labels,
    }

    response = await test_client.post("/app/env", json=json_to_send)
    assert response.status_code == 400

    target_configs = list(test_app_empty_folder.config["target_configs"].values())
    assert len(target_configs) == 1

    target_config = target_configs[0]
    assert target_config.targets == original_targets
    assert target_config.labels == original_labels

    # Try the same thing with targets
    json_to_send["targets"] = original_targets[:] + ["localhost:2"]

    response = await test_client.post("/app/env", json=json_to_send)
    assert response.status_code == 400

    assert target_config.targets == original_targets


@pytest.mark.asyncio
async def test_json_put_with_targets(test_app_empty_folder):
    """Test that a JSON PUT with targets succeeds"""
    test_client = test_app_empty_folder.test_client()

    targets = ["a:12345", "b:12346"]

    response = await test_client.put("/app/env", json={"targets": targets})
    assert response.status_code == 200

    body = await response.get_json(silent=True)
    assert body == [{"targets": targets, "labels": {"job": "app", "env": "env"},}]

    assert num_files(test_app_empty_folder.config["file_sd_directory"]) == 1


@pytest.mark.asyncio
@patch("fa_target_eye.target_config.TargetConfig.delete_file")
async def test_json_delete_for_non_existent_config(mock_delete_file, test_app_empty_folder):
    """Test that it is an error to try to delete a config that does not
    exist"""

    test_client = test_app_empty_folder.test_client()

    response = await test_client.delete("/app/env")

    assert response.status_code == 400
    assert mock_delete_file.call_count == 0

    body = await response.get_json(silent=True)
    assert body


@pytest.mark.asyncio
async def test_json_delete_after_put(test_app_empty_folder):
    """Test that DELETE does what it should for a config that exists"""

    test_client = test_app_empty_folder.test_client()
    targets = ["localhost:12345"]

    put_response = await test_client.put("/app/env", json={"targets": targets})
    assert num_files(test_app_empty_folder.config["file_sd_directory"]) == 1

    delete_response = await test_client.delete("/app/env")
    assert num_files(test_app_empty_folder.config["file_sd_directory"]) == 0

    assert put_response.status_code == 200
    assert delete_response.status_code == 200

    put_body = await put_response.get_json(silent=True)
    delete_body = await delete_response.get_json(silent=True)

    assert put_body == delete_body


@pytest.mark.asyncio
async def test_json_delete_selective_parts_of_config(test_app_with_target_config):
    """Test that DELETE works when only removing parts of the targets or
    labels"""

    test_client = test_app_with_target_config.test_client()
    target_config = test_app_with_target_config.config["target_config"]
    for label_name, label_value in target_config.labels.copy().items():
        if label_name in ("job", "env"):
            continue

        deletion_obj = {label_name: label_value}
        bad_deletion_obj = {label_name: ""}

        delete_response = await test_client.delete("/app/env", json={"labels": bad_deletion_obj})
        assert delete_response.status_code == 400

        delete_response = await test_client.delete("/app/env", json={"labels": deletion_obj})
        assert delete_response.status_code == 200

        delete_response = await test_client.delete("/app/env", json={"labels": deletion_obj})
        assert delete_response.status_code == 400


@pytest.mark.asyncio
async def test_json_delete_invalid_requests(test_app_with_target_config):
    """Test that DELETE returns an expected error code for invalid deletion
    requests"""
    test_client = test_app_with_target_config.test_client()
    target_config = test_app_with_target_config.config["target_config"]
    target_labels = {k: v for k, v in target_config.labels.items() if k not in ("job", "env")}

    delete_response = await test_client.delete("/app/env", json={"labels": target_config.labels})
    assert delete_response.status_code == 400

    delete_response = await test_client.delete("/app/env", json={"labels": {}})
    assert delete_response.status_code == 400

    delete_response = await test_client.delete("/app/env", json={"labels": {"A": ""}})
    assert delete_response.status_code == 400

    delete_response = await test_client.delete("/app/env", json={"targets": []})
    assert delete_response.status_code == 400

    delete_response = await test_client.delete("/app/env", json={"targets": [""]})
    assert delete_response.status_code == 400

    invalid_label_deletion = target_labels.copy()
    invalid_label_deletion.update({"notinlabels": ""})
    delete_response = await test_client.delete("/app/env", json={"labels": invalid_label_deletion})
    assert delete_response.status_code == 400


async def check_json_file_contents(app):
    """Given the fixture test app for a single TargetConfig object, make sure that the
    contents of the JSON file for the object match the values expected

    Not a test case itself, but a helper function for the tests that deal with
    validating file contents
    """
    # fixture created TargetConfig object
    target_configs = app.config["target_configs"]
    target_config = list(target_configs.values())[0]

    json_file_contents = await target_config.read_from_file(app.config["file_sd_directory"])

    json_file_path = os.path.join(app.config["file_sd_directory"], target_config.filename,)

    return (
        json_file_contents == target_config.json
        and target_config == TargetConfig.from_json_file(json_file_path)
    )


@pytest.mark.asyncio
async def test_target_config_file_contents_expected_case(test_app_with_target_config):
    """Make sure that the JSON file contents, which were initially written to
    disk by the fixture setup, can be used to create a TargetConfig and that
    the contents actually change after a successful REST API modification
    """
    test_client = test_app_with_target_config.test_client()

    assert await check_json_file_contents(test_app_with_target_config)

    put_response = await test_client.put("/app/env", json={"labels": {"new": "v"}})
    assert put_response.status_code == 200

    assert await check_json_file_contents(test_app_with_target_config)


@pytest.mark.asyncio
async def test_target_config_file_after_api_errors(test_app_with_target_config):
    """Make sure that the target config file holding the JSON representation of
    targets for a given application and environment does not get modified when
    a REST API request fails.
    """
    test_client = test_app_with_target_config.test_client()

    # try to do an incorrect PUT
    put_response = await test_client.put("/app/env", json={"targets": [""], "labels": {"job": ""}})
    assert put_response.status_code == 400
    assert await check_json_file_contents(test_app_with_target_config)

    # try to do an incorrect POST
    post_response = await test_client.post("/app/env", json={"targets": [], "labels": {},})
    assert post_response.status_code == 400
    assert await check_json_file_contents(test_app_with_target_config)

    # try to do an incorrect DELETE
    delete_response = await test_client.delete(
        "/app/env", json={"targets": ["madeup"], "labels": {"madeup": ""},}
    )
    assert delete_response.status_code == 400
    assert await check_json_file_contents(test_app_with_target_config)


def num_files(directory: str) -> int:
    """Given a directory count the number of files"""
    directory_path = Path(directory)
    return len(list(directory_path.iterdir()))
