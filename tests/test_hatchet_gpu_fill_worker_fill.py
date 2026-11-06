"""Contracts for the grounded Q&A fill workload: corpus, prompt and JSON, JSONL output, and config."""

import ast
import json
import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKER_PACKAGE = ROOT / "roles/hatchet_docker/files/gpu_fill_worker"
FIXTURES = ROOT / "tests/hatchet_gpu_fill_worker"
for path in (WORKER_PACKAGE, FIXTURES):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
sys.dont_write_bytecode = True

from adapter import LatencyGuardError  # noqa: E402
from config import load_config  # noqa: E402
from fill import corpus, qa  # noqa: E402
from fill import tasks as fill_tasks  # noqa: E402
from fill_fixtures import GOOD, PLATFORM, WHEN, chat_reply  # noqa: E402


def test_sections_start_at_each_heading():
    assert list(corpus._sections("# A\nalpha\n## B\nbeta\n")) == ["# A\nalpha\n", "## B\nbeta\n"]


def test_load_chunks_skips_symlinks_that_point_outside_the_corpus(tmp_path):
    secret = tmp_path / "outside-secret.txt"
    secret.write_text("TOKEN-VALUE", encoding="utf-8")
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    (corpus_dir / "real.md").write_text("# Real\nalpha\n", encoding="utf-8")
    (corpus_dir / "leak.md").symlink_to(secret)

    chunks = corpus.load_chunks(corpus_dir)

    assert [chunk.chunk_id for chunk in chunks] == ["real.md#0"]
    assert all("TOKEN-VALUE" not in chunk.text for chunk in chunks)


def test_chunks_stay_within_the_limit_and_are_never_blank():
    body = "\n".join(f"## Section {i}\n" + ("word " * 400) + "\n" for i in range(6))
    chunks = corpus.chunk_text(body, limit=2000)
    assert chunks
    assert all(0 < len(chunk) <= 2000 for chunk in chunks)
    assert all(chunk.strip() for chunk in chunks)


def test_load_chunks_uses_relative_path_and_index_and_skips_hidden_dirs(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text("# Guide\nalpha\n", encoding="utf-8")
    (tmp_path / "root.md").write_text("# Root\nbeta\n", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "hidden.md").write_text("# Hidden\n", encoding="utf-8")

    ids = [chunk.chunk_id for chunk in corpus.load_chunks(tmp_path)]

    assert ids == ["docs/guide.md#0", "root.md#0"]
    assert ids == [chunk.chunk_id for chunk in corpus.load_chunks(tmp_path)]


def test_round_robin_cycles_chunks_in_order():
    picker = corpus.ChunkPicker([corpus.Chunk("a.md#0", "A"), corpus.Chunk("b.md#0", "B")])
    assert [picker.next().chunk_id for _ in range(5)] == [
        "a.md#0",
        "b.md#0",
        "a.md#0",
        "b.md#0",
        "a.md#0",
    ]


def test_seeded_random_selection_is_reproducible():
    chunks = [corpus.Chunk(f"f{i}.md#0", "x") for i in range(10)]
    first = corpus.ChunkPicker(chunks, mode="random", seed=7)
    second = corpus.ChunkPicker(chunks, mode="random", seed=7)
    assert [first.next().chunk_id for _ in range(20)] == [second.next().chunk_id for _ in range(20)]


def test_picker_rejects_empty_corpus_and_unknown_mode():
    with pytest.raises(ValueError):
        corpus.ChunkPicker([])
    with pytest.raises(ValueError):
        corpus.ChunkPicker([corpus.Chunk("a.md#0", "A")], mode="shuffle")


def test_corpus_module_has_no_network_imports():
    tree = ast.parse((WORKER_PACKAGE / "fill/corpus.py").read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    assert not modules & {"socket", "ssl", "http", "urllib", "requests"}


def test_prompt_embeds_chunk_text_and_the_five_pair_shape():
    prompt = qa.build_prompt("Alpha fact.")
    assert "Alpha fact." in prompt
    assert "exactly 5" in prompt
    assert '"pairs"' in prompt


def test_parse_accepts_a_good_reply():
    valid, invalid = qa.parse_pairs(GOOD)
    assert len(valid) == 5
    assert invalid == 0


def test_parse_keeps_valid_pairs_and_counts_partial_invalid_ones():
    reply = json.dumps(
        {
            "pairs": [
                {"question": "q", "answer": "a"},
                {"question": "", "answer": "a"},
                {"question": "q", "answer": "a", "extra": 1},
                "text",
            ]
        }
    )
    valid, invalid = qa.parse_pairs(reply)
    assert valid == [{"question": "q", "answer": "a"}]
    assert invalid == 3


@pytest.mark.parametrize(
    "reply",
    [
        "not json",
        "```json\n" + GOOD + "\n```",
        json.dumps([1, 2]),
        json.dumps({"pairs": "text"}),
        json.dumps({"pairs": []}),
        GOOD[:-20],
    ],
)
def test_parse_rejects_malformed_and_truncated_replies(reply):
    with pytest.raises(qa.MalformedOutput):
        qa.parse_pairs(reply)


def test_completion_text_requires_message_content():
    assert qa.completion_text(chat_reply("hi")) == "hi"
    with pytest.raises(qa.MalformedOutput):
        qa.completion_text({"choices": []})


def test_run_fill_appends_valid_records_to_the_dated_role_file(tmp_path):
    calls = []

    def fake_chat(platform_cfg, payload, latency_guard=None):
        calls.append((platform_cfg, payload, latency_guard))
        return chat_reply(GOOD)

    chunk = corpus.Chunk("docs/guide.md#2", "Alpha fact.")
    result = qa.run_fill(
        chunk,
        role="medium",
        platform_cfg=PLATFORM,
        chat=fake_chat,
        latency_guard=None,
        writer=qa.JsonlWriter(tmp_path),
        when=WHEN,
    )

    assert result == {"status": "written", "chunk_id": "docs/guide.md#2", "written": 5, "invalid": 0}
    records = [
        json.loads(line)
        for line in (tmp_path / "medium" / "2026-11-05.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(records) == 5
    assert records[0] == {
        "chunk_id": "docs/guide.md#2",
        "role": "medium",
        "model": "pro6000-direct",
        "question": "q0",
        "answer": "a0",
        "timestamp": WHEN.isoformat(),
    }
    payload = calls[0][1]["payload"]
    assert payload["max_tokens"] == 512
    assert "Alpha fact." in payload["prompt"]


def test_partial_reply_writes_only_valid_pairs(tmp_path):
    reply = json.dumps({"pairs": [{"question": "q", "answer": "a"}, {"question": "", "answer": "a"}]})
    result = qa.run_fill(
        corpus.Chunk("a.md#0", "A"),
        role="medium",
        platform_cfg=PLATFORM,
        chat=lambda *_args, **_kwargs: chat_reply(reply),
        latency_guard=None,
        writer=qa.JsonlWriter(tmp_path),
        when=WHEN,
    )
    assert result["written"] == 1
    assert result["invalid"] == 1
    assert result["status"] == "partial"


def test_reply_without_exactly_five_valid_pairs_is_partial_not_written_in_full(tmp_path):
    four = json.dumps({"pairs": [{"question": f"q{i}", "answer": f"a{i}"} for i in range(4)]})
    result = qa.run_fill(
        corpus.Chunk("a.md#0", "A"),
        role="medium",
        platform_cfg=PLATFORM,
        chat=lambda *_args, **_kwargs: chat_reply(four),
        latency_guard=None,
        writer=qa.JsonlWriter(tmp_path),
        when=WHEN,
    )
    assert result == {"status": "partial", "chunk_id": "a.md#0", "written": 4, "invalid": 0}


def test_malformed_reply_is_counted_logged_and_not_written(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="gpu_fill.qa"):
        result = qa.run_fill(
            corpus.Chunk("a.md#0", "A"),
            role="medium",
            platform_cfg=PLATFORM,
            chat=lambda *_args, **_kwargs: chat_reply("oops"),
            latency_guard=None,
            writer=qa.JsonlWriter(tmp_path),
            when=WHEN,
        )
    assert result["status"] == "malformed"
    assert not (tmp_path / "medium").exists()
    assert "malformed fill output" in caplog.text


def test_latency_guard_refusal_propagates_from_chat(tmp_path):
    def refuse(*_args, **_kwargs):
        raise LatencyGuardError("blocked")

    with pytest.raises(LatencyGuardError):
        qa.run_fill(
            corpus.Chunk("a.md#0", "A"),
            role="medium",
            platform_cfg=PLATFORM,
            chat=refuse,
            latency_guard={"prometheus_url": "http://192.0.2.10:9090", "query": "q", "max_ratio": 1.2},
            writer=qa.JsonlWriter(tmp_path),
            when=WHEN,
        )


@pytest.mark.parametrize("max_runs", [1, 2, 6])
def test_top_up_count_never_lets_in_flight_runs_exceed_max_runs(max_runs):
    for in_flight in range(0, max_runs + 3):
        count = fill_tasks.top_up_count(max_runs, in_flight)
        assert count >= 0
        if in_flight < max_runs:
            assert in_flight + count == max_runs
        else:
            assert count == 0


def test_top_up_count_rejects_non_positive_max_runs():
    with pytest.raises(ValueError):
        fill_tasks.top_up_count(0, 0)


def write_config(tmp_path, config):
    path = tmp_path / "worker.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def test_config_accepts_a_fill_block_and_rejects_bad_mappings(tmp_path):
    config = {
        "roles": {"medium": {"max_runs": 2}},
        "platforms": {"pro6000-direct": dict(PLATFORM)},
        "fill": {
            "cron": "7,37 * * * *",
            "corpus_dir": "/corpus",
            "output_dir": "/output",
            "roles": {"medium": "pro6000-direct"},
        },
    }
    assert load_config(write_config(tmp_path, config))["fill"]["roles"] == {"medium": "pro6000-direct"}

    unknown_role = json.loads(json.dumps(config))
    unknown_role["fill"]["roles"] = {"large": "pro6000-direct"}
    with pytest.raises(ValueError, match="not a configured LLM role"):
        load_config(write_config(tmp_path, unknown_role))

    not_chat = json.loads(json.dumps(config))
    not_chat["platforms"] = {"pro6000-direct": {"run_url": None, "auth_env": None, "timeout_s": 30}}
    with pytest.raises(ValueError, match="active chat platform"):
        load_config(write_config(tmp_path, not_chat))

    relative = json.loads(json.dumps(config))
    relative["fill"]["corpus_dir"] = "corpus"
    with pytest.raises(ValueError, match="absolute path"):
        load_config(write_config(tmp_path, relative))
