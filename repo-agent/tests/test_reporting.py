from repo_agent.context import parent_summary
from repo_agent.reporting import make_report


def test_citation_format_variants_and_unknown_ids(evidence):
    store, repo, snapshot = evidence
    chunk = repo.search("alice", "workspace", snapshot["id"], "Python")[0]
    base = {
        "owner": "alice",
        "workspace": "workspace",
        "snapshot": snapshot["id"],
        "evidence": {chunk["id"]: chunk},
        "steps": 1,
        "skill": "environment",
    }
    for text in [
        f"声明支持Python3.12 [{chunk['id']}]",
        f"声明支持Python3.12 [证据 {chunk['id']}]",
        f"声明支持Python3.12 [证据{chunk['id']}]",
    ]:
        report = make_report(base | {"answer": text}, store)
        assert len(report["citations"]) == 1
    report = make_report(base | {"answer": "[" + "0" * 64 + "]"}, store)
    assert not report["citations"] and report["unknown_citation_ids"]


def test_alias_resolution_is_exact_job_local_and_rejects_guessed_or_malformed_ids(evidence):
    store, repo, snapshot = evidence
    chunk = repo.search("alice", "workspace", snapshot["id"], "Python")[0]
    state = {
        "owner": "alice",
        "workspace": "workspace",
        "snapshot": snapshot["id"],
        "evidence": {chunk["id"]: chunk},
        "steps": 1,
        "skill": "environment",
        "citation_aliases": {"E1": chunk["id"], "E2": "0" * 64},
        "answer": "支持声明[E1]，伪造[E2]，猜测[E999]，错误长度[" + chunk["id"][:-1] + "]。",
    }
    report = make_report(state, store)
    assert [c["id"] for c in report["citations"]] == [chunk["id"]]
    assert report["citations"][0]["labels"] == ["E1"]
    assert set(report["unknown_citation_ids"]) == {"E2", "E999", chunk["id"][:-1]}


def test_parent_labels_are_not_misinterpreted_as_child_labels():
    previous = {
        "answer": "已读取[E9]，未知[E1]。",
        "citations": [
            {"id": "a" * 64, "labels": ["E9"], "path": "README.md", "start_line": 2, "end_line": 5}
        ],
    }
    summary = parent_summary("原问题", previous)
    assert "[E9]" not in summary and "[E1]" not in summary
    assert "README.md:L2-5" in summary and "不可沿用" in summary


def test_large_multibyte_tool_context_and_parent_summary_remain_valid_json():
    import json

    from repo_agent.context import bounded_json

    result = {
        "evidence": [{"id": f"E{i}", "path": "中文.py", "content": '中\\"\n' * 20000} for i in range(12)]
    }
    packed = bounded_json(result)
    assert len(packed.encode()) <= 26000
    decoded = json.loads(packed)
    assert decoded["context_truncated"] and decoded["evidence"][0]["id"] == "E0"
    summary = parent_summary("长问题" * 2000, {"answer": "很长的回答" * 10000})
    assert len(summary.encode()) <= 7000
    assert json.loads(summary)["scope"].startswith("Previous answer")
