"""Write-result assertions that cannot run in Ansible check mode."""

import pytest
import yaml

from health_probes_check_mode_support import REPO, _tasks_in

WRITE_RESULT_ASSERTIONS = (
    (
        "roles/cribl_stream/tasks/rotate_admin_password.yml",
        "Fail loudly when neither the declared nor the default credential authenticates",
        "Verify login with the rotated password once the restart lands",
        "cribl_stream_rotated_login",
        "ansible.builtin.uri",
        "POST",
        (),
    ),
    (
        "roles/homarr/tasks/integrations.yml",
        "Surface a converger failure with its reason",
        "Converge the API key, every integration, and the board tiles",
        "homarr_api_result",
        "ansible.builtin.command",
        None,
        ("homarr_api_result.rc != 0",),
    ),
    (
        "roles/object_storage/tasks/iam_provision_bucket_role.yml",
        "Fail if writing the policy did not succeed",
        "Write the bucket-scoped policy (write-if-changed)",
        "object_storage_iam_policy_put",
        "ansible.builtin.command",
        None,
        ("object_storage_iam_policy_differs",),
    ),
    (
        "roles/object_storage/tasks/iam_provision_bucket_role.yml",
        "Fail if creating the user did not succeed",
        "Create or update the RustFS user for this bucket/role",
        "object_storage_iam_user_put",
        "ansible.builtin.command",
        None,
        (),
    ),
    (
        "roles/object_storage/tasks/iam_provision_bucket_role.yml",
        "Fail if attaching the policy did not succeed",
        "Attach the policy to the user",
        "object_storage_iam_attach",
        "ansible.builtin.command",
        None,
        (),
    ),
    (
        "roles/nautobot/tasks/application_bringup.yml",
        "Assert the export schedule was reconciled",
        "Schedule the export Job via celery beat",
        "nautobot_schedule",
        "ansible.builtin.shell",
        None,
        (),
    ),
)


@pytest.mark.parametrize(
    (
        "relative_path",
        "assertion_name",
        "writer_name",
        "register_name",
        "module_name",
        "method",
        "preserved_conditions",
    ),
    WRITE_RESULT_ASSERTIONS,
)
def test_write_result_assertions_skip_check_mode(
    relative_path,
    assertion_name,
    writer_name,
    register_name,
    module_name,
    method,
    preserved_conditions,
):
    tasks = yaml.safe_load((REPO / relative_path).read_text(encoding="utf-8"))
    task_by_name = {task.get("name"): task for task in _tasks_in(tasks)}

    assertion = task_by_name[assertion_name]
    when = assertion.get("when", "")
    conditions = when if isinstance(when, list) else [when]

    assert "not ansible_check_mode" in conditions
    assert all(condition in conditions for condition in preserved_conditions)
    assert "ansible.builtin.assert" in assertion or "ansible.builtin.fail" in assertion

    writer = task_by_name[writer_name]
    assert writer.get("register") == register_name
    assert module_name in writer
    assert writer.get("check_mode") is not False
    if method:
        assert writer[module_name].get("method") == method
