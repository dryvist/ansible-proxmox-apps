"""Daily pull-request status playbook contracts: env gate, token masking, fail-open metrics, chat publish, message marks."""

from pathlib import Path

import jinja2
import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "playbooks/pr-status-post.yml"
TEMPLATE = ROOT / "playbooks/templates/pr-status-message.j2"

GREEN, YELLOW, RED = "\U0001f7e2", "\U0001f7e1", "\U0001f534"

TOKEN_MARKERS = (
    "pr_status_bao_token",
    "pr_status_env_token",
    "pr_status_github_minted_tokens",
    "pr_status_github_tokens",
    "pr_status_github_mint_results",
)


def _load(path=None):
    return yaml.safe_load((path or PLAYBOOK).read_text(encoding="utf-8"))


def _tasks(node):
    for task in node or []:
        yield task
        for key in ("block", "rescue", "always"):
            yield from _tasks(task.get(key))


def _fields(task):
    return str({key: value for key, value in task.items() if key not in {"block", "rescue", "always"}})


def _plays():
    return _load()


def _task_list():
    return [(play["name"], task) for play in _plays() for task in _tasks(play.get("tasks"))]


def _by_module(module, task_list=None):
    return [(play_name, task) for play_name, task in (task_list or _task_list())
            if module in task]


def test_the_run_stays_local_and_unprivileged():
    plays = _plays()
    assert len(plays) == 2
    for play in plays:
        assert play["hosts"] == "localhost"
        assert play["connection"] == "local"
        assert play["gather_facts"] is False
        assert play["become"] is False
        assert play["vars"]["ansible_become"] is False
    assert "become: true" not in PLAYBOOK.read_text(encoding="utf-8")


def test_the_gate_fails_before_any_request():
    plays = _plays()
    gate, census = plays
    assert gate["name"].startswith("Refuse to run without")
    for env_name in ("PR_CENSUS_OWNERS", "STATUS_METRICS_URL", "STATUS_CHANNEL", "PROXMOX_SUBDOMAIN"):
        assert f"lookup('env', '{env_name}')" in str(gate.get("vars", {}))
    gate_conditions = " ".join(gate["tasks"][0]["ansible.builtin.assert"]["that"])
    for var_name in ("pr_status_owners_raw", "pr_status_metrics_url", "pr_status_channel"):
        assert var_name in gate_conditions
    channel_check = _by_module("ansible.builtin.assert", [(gate["name"], t) for t in _tasks(gate["tasks"])])
    assert any("match('^[A-Za-z0-9_-]+$')" in _fields(task) for _, task in channel_check)
    assert not any("ansible.builtin.uri" in task for task in _tasks(gate["tasks"]))
    assert all("ansible.builtin.uri" in task for _, task in _by_module("ansible.builtin.uri", [(census["name"], t) for t in _tasks(census["tasks"])]))


def test_the_census_runs_one_search_pair_per_owner():
    open_search = next(task for _, task in _task_list()
                       if task.get("name", "").startswith("Search each owner for open pull requests"))
    merged_search = next(task for _, task in _task_list()
                         if task.get("name", "").startswith("Search each owner for pull requests merged"))
    for task, terms in ((open_search, "pr_status_open_terms"), (merged_search, "pr_status_merged_terms")):
        uri = task["ansible.builtin.uri"]
        assert uri["url"] == "{{ pr_status_github_api }}/search/issues?q={{ pr_status_search_terms | urlencode }}"
        assert terms in _fields(task)
        assert "org:' ~ item" in _fields(task)
        assert "pr_status_excludes | join(' ')" in _fields(task)
        assert uri["headers"]["Authorization"] == "Bearer {{ pr_status_github_tokens[item] }}"
    assert "is:pr is:open archived:false" in _plays()[1]["vars"]["pr_status_open_terms"]
    assert "is:pr is:merged" in _plays()[1]["vars"]["pr_status_merged_terms"]
    assert "pr_status_merged_since" in _plays()[1]["vars"]["pr_status_merged_terms"]
    totals = next(task for _, task in _task_list() if task.get("name", "").startswith("Sum the open and merged"))
    assert "pr_status_open_searches.results" in _fields(totals)
    assert "pr_status_merged_searches.results" in _fields(totals)
    assert "json.total_count" in _fields(totals)


def test_github_tokens_come_from_the_mint_or_the_env_fallback():
    source = next(task for _, task in _task_list()
                  if task.get("name", "").startswith("Select the GitHub token source"))
    assert "'openbao' if pr_status_github_bao_enabled" in _fields(source)
    assert "'env' if pr_status_github_env_enabled else 'missing'" in _fields(source)
    mint = next(task for _, task in _task_list()
                if task.get("name", "").startswith("Mint a GitHub read token"))
    request = mint["community.hashi_vault.vault_write"]
    assert request["path"] == "{{ pr_status_github_mint_mount }}/token"
    assert request["data"]["org_name"] == "{{ pr_status_census_org }}"
    assert request["data"]["permissions"] == {
        "contents": "read", "metadata": "read", "pull_requests": "read"}
    assert mint["failed_when"] is False
    assert mint["loop"] == "{{ pr_status_owners }}"
    require_env = next(task for _, task in _task_list()
                       if task.get("name", "").startswith("Require an available GitHub token source"))
    assert "PR_CENSUS_GITHUB_TOKEN" in _fields(require_env)


def test_every_task_holding_a_token_is_masked():
    for _, task in _task_list():
        if task.get("name", "").startswith("Require an available GitHub token source"):
            continue  # Its message carries the source decision, never a token value.
        if task.get("name", "").startswith("Require every census owner's minted token"):
            continue  # Its message names the mint path, never a token value.
        if any(marker in _fields(task) for marker in TOKEN_MARKERS):
            assert task.get("no_log") is True, task["name"]


def test_authenticated_searches_never_follow_redirects():
    requests = [task["ansible.builtin.uri"] for _, task in _task_list() if "ansible.builtin.uri" in task]
    authed = [uri for uri in requests if "Authorization" in uri.get("headers", {})]
    assert len(authed) == 2
    for uri in authed:
        assert uri["follow_redirects"] == "none"
        assert uri["unredirected_headers"] == ["Authorization"]


def test_the_jobs_query_fails_open():
    reads = [task for _, task in _task_list()
             if task.get("name", "").startswith("Read the jobs query verbatim")]
    assert len(reads) == 1
    uri = reads[0]["ansible.builtin.uri"]
    assert uri["url"].startswith("{{ pr_status_post_metrics_url }}/api/v1/query?query=")
    assert reads[0]["failed_when"] is False
    assert reads[0].get("no_log") is True
    assert "pr_status_jobs_terms | length > 0" in str(reads[0].get("when"))
    jobs = next(task for _, task in _task_list() if task.get("name", "").startswith("Resolve the jobs figure"))
    assert "unmeasured" in _fields(jobs)
    assert "pr_status_jobs_read.status" in _fields(jobs)


def test_lane_utilization_is_left_to_the_gpu_post():
    # The gpu status post reports each lane; repeating it here would post the
    # same red lane twice a day.
    playbook = PLAYBOOK.read_text(encoding="utf-8")
    text = TEMPLATE.read_text(encoding="utf-8")
    assert "busy" not in text
    assert all("accelerator" not in str(task) for _, task in _task_list())
    assert "busy" not in playbook


def test_merged_counts_cover_the_last_24_hours():
    since = next(task for _, task in _task_list()
                 if "pr_status_merged_since" in task.get("ansible.builtin.set_fact", {}))
    assert "- 86400" in since["ansible.builtin.set_fact"]["pr_status_merged_since"]


def test_the_post_reuses_the_alert_hub_publish():
    build = next(task for _, task in _task_list()
                 if task.get("name", "").startswith("Build the status message"))
    assert build["ansible.builtin.set_fact"]["pr_status_message"] == (
        "{{ lookup('ansible.builtin.template', 'templates/pr-status-message.j2') }}"
    )
    post = next(task for _, task in _task_list()
                if task.get("name", "").startswith("Post the status to the chat channel"))
    uri = post["ansible.builtin.uri"]
    assert uri["url"] == "https://ntfy.{{ pr_status_post_ingress_domain }}/{{ pr_status_post_channel }}"
    assert uri["method"] == "POST"
    assert uri["headers"]["Title"] == "Pull-request status"
    assert uri["body"] == "{{ pr_status_message }}"
    channel_fact = next(task for _, task in _task_list()
                        if task.get("name", "").startswith("Split the census owners"))
    assert channel_fact["ansible.builtin.set_fact"]["pr_status_post_channel"] == "{{ pr_status_channel }}"


def test_no_estate_specific_values_are_baked_in():
    for path in (PLAYBOOK, TEMPLATE):
        text = path.read_text(encoding="utf-8")
        hosts = set(__import__("re").findall(r"https://([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)", text))
        assert hosts <= {"api.github.com"}, path


def _render(context):
    # ansible's template lookup environment: trim_blocks on, the jinja defaults
    # for everything else this template uses.
    environment = jinja2.Environment(trim_blocks=True, loader=jinja2.FileSystemLoader(str(TEMPLATE.parent)))
    return environment.from_string(TEMPLATE.read_text(encoding="utf-8")).render(context)


def test_the_message_is_all_green_when_every_figure_is_on_target():
    text = _render({
        "pr_status_generated_utc": "2026-01-01 12:00 UTC",
        "pr_status_open_total": 12,
        "pr_status_merged_total": 3,
        "pr_status_jobs_measured": True,
        "pr_status_jobs_text": "5",
    })
    assert text == (
        "2026-01-01 12:00 UTC pull-request status\n"
        f"{GREEN} open pull requests: 12\n"
        f"{GREEN} merged in the last 24 h: 3\n"
        f"{GREEN} Hermes cron runs, last hour: 5"
    )


def test_the_message_turns_yellow_at_thirty_five_open_pull_requests():
    text = _render({
        "pr_status_generated_utc": "2026-01-01 13:00 UTC",
        "pr_status_open_total": 35,
        "pr_status_merged_total": 1,
        "pr_status_jobs_measured": True,
        "pr_status_jobs_text": "7",
    })
    assert text == (
        "2026-01-01 13:00 UTC pull-request status\n"
        f"{YELLOW} open pull requests: 35\n"
        f"{GREEN} merged in the last 24 h: 1\n"
        f"{GREEN} Hermes cron runs, last hour: 7"
    )


def test_the_message_reports_unmeasured_when_the_jobs_query_fails():
    text = _render({
        "pr_status_generated_utc": "2026-01-01 14:00 UTC",
        "pr_status_open_total": 12,
        "pr_status_merged_total": 0,
        "pr_status_jobs_measured": False,
        "pr_status_jobs_text": "unmeasured",
    })
    assert text == (
        "2026-01-01 14:00 UTC pull-request status\n"
        f"{GREEN} open pull requests: 12\n"
        f"{GREEN} merged in the last 24 h: 0\n"
        f"{RED} Hermes cron runs, last hour: unmeasured"
    )


def test_open_pull_requests_are_green_at_30_and_yellow_from_31():
    def mark(total):
        text = _render({"pr_status_generated_utc": "t", "pr_status_open_total": total, "pr_status_merged_total": 0,
                        "pr_status_jobs_measured": False})
        return next(line for line in text.splitlines() if "open pull requests:" in line)[0]

    assert [mark(total) for total in (30, 31, 40, 41)] == [GREEN, YELLOW, YELLOW, RED]
