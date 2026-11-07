import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from conftest import archive

from repo_agent.executor import Executor
from repo_agent.settings import Settings
from repo_agent.tools import Tools


async def test_java_candidates_never_become_exact_definitions(evidence, tmp_path):
    store, repo, _ = evidence
    text = '''// class Ghost {}
public class Actual {
 String example = "class Fake {}";
 String block = """\nclass Imaginary {}\n""";
 /* interface Invisible {} */
 record Nested(int value) {}
}
'''
    snapshot = repo.ingest(
        "alice", "workspace", "https://github.com/example/sample", "c" * 40, archive({"Actual.java": text})
    )
    context = {"job": "job", "owner": "alice", "workspace": "workspace", "snapshot": snapshot["id"]}
    tools = Tools(store, repo, Executor(Settings(_env_file=None, data_dir=tmp_path), store))
    found = await tools.call(context, "find_symbol", '{"name":"Actual"}')
    assert found["evidence"] and found["exact_definitions"] == []
    assert found["declaration_candidates"][0]["start_line"] == 2
    assert found["declaration_candidates"][0]["end_line"] == 2
    assert repo.symbol_locations("alice", "workspace", snapshot["id"], "Nested")
    for fake in ["Ghost", "Fake", "Imaginary", "Invisible"]:
        assert repo.symbol_locations("alice", "workspace", snapshot["id"], fake) == []


def test_old_java_symbol_index_is_rebuilt(evidence):
    store, repo, snapshot = evidence
    with store.connect() as db:
        db.execute("INSERT INTO symbols VALUES(?, 'Fake.java','Ghost','class',1,80)", (snapshot["id"],))
        db.execute("INSERT INTO symbol_index_versions VALUES(?,1)", (snapshot["id"],))
    assert repo.symbol_locations("alice", "workspace", snapshot["id"], "Ghost") == []
    python = repo.symbol_locations("alice", "workspace", snapshot["id"], "add")
    assert python[0]["precision"] == "exact_ast" and python[0]["end_line"] == 2


def test_metrics_include_errors_and_preserve_pending_and_historical_summary(tmp_path, monkeypatch):
    evaluation = Path(__file__).resolve().parents[1] / "evaluation"
    monkeypatch.syspath_prepend(str(evaluation))
    spec = importlib.util.spec_from_file_location("metrics_under_test", evaluation / "run.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rows = [
        {"task_success": True, "requires_review": False},
        {"task_success": False, "error": "TimeoutError", "requires_review": False},
    ]
    for index, row in enumerate(rows):
        (tmp_path / f"case-{index}.json").write_text(json.dumps(row))
    old = tmp_path / "summary.json"
    old.write_text('{"historical":true}')
    result = module.summarize(tmp_path)
    assert result["task_success_rate"] == 0.5
    assert result["task_success_denominator"] == result["task_success_scored_cases"] == 2
    assert result["execution_errors"] == 1
    assert old.read_text() == '{"historical":true}'
    (tmp_path / "case-pending.json").write_text(json.dumps({"task_success": None, "requires_review": True}))
    pending = module.summarize(tmp_path)
    assert pending["task_success_rate"] is None
    assert pending["semantic_review_pending"] == pending["unscored_cases"] == 1
    assert pending["task_success_lower_bound"] == 1 / 3
    assert pending["task_success_upper_bound"] == 2 / 3


def test_review_combination_also_counts_failed_execution_and_keeps_original(tmp_path):
    for index, row in enumerate(
        [
            {"id": "ok", "task_success": True, "requires_review": False},
            {"id": "offline", "task_success": False, "requires_review": False, "error": "ConnectError"},
        ]
    ):
        (tmp_path / f"case-{index}.json").write_text(json.dumps(row))
    labels = tmp_path / "annotations.json"
    labels.write_text(json.dumps({"reviewer": "test fixture", "rubric": "fixture", "cases": {}}))
    original = tmp_path / "semantic-review.json"
    original.write_text('{"historical":true}')
    script = Path(__file__).resolve().parents[1] / "evaluation/record_reviews.py"
    subprocess.run(
        [sys.executable, str(script), "--root", str(tmp_path), "--annotations", str(labels)],
        check=True,
        capture_output=True,
        timeout=10,
    )
    result = json.loads((tmp_path / "semantic-review-v2.json").read_text())
    assert result["automatic_scored"] == result["combined_total"] == 2
    assert result["combined_passed"] == 1 and result["execution_errors"] == 1
    assert original.read_text() == '{"historical":true}'
