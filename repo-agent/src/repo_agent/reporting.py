import re
from urllib.parse import quote

from .store import Store


def make_report(state: dict, store: Store) -> dict:
    answer = state.get("answer", "未生成答案")
    mentioned = re.findall(r"\[(?:证据\s*)?(E\d+|[a-f0-9]{32,80})\]", answer)
    aliases = state.get("citation_aliases", {})
    resolved = {label: aliases.get(label, label) for label in mentioned}
    cited = list(dict.fromkeys(key for key in resolved.values() if key in state["evidence"]))
    unknown = sorted(label for label, key in resolved.items() if key not in state["evidence"])
    snapshot = store.snapshot(state["snapshot"], state["owner"], state["workspace"])
    citations = [
        {
            "id": key,
            "labels": [label for label in dict.fromkeys(mentioned) if resolved[label] == key],
            "path": state["evidence"][key]["path"],
            "start_line": state["evidence"][key]["start_line"],
            "end_line": state["evidence"][key]["end_line"],
            "commit": snapshot["commit_sha"],
            "url": f"{snapshot['repo']}/blob/{snapshot['commit_sha']}/{quote(state['evidence'][key]['path'], safe='/')}#L{state['evidence'][key]['start_line']}",
        }
        for key in cited
    ]
    warning = (
        "模型引用了未取到的证据；这些引用已拒绝。"
        if unknown
        else ("无引用的结论未经证据支持；执行状态以validation_result事件为准。" if not citations else None)
    )
    validations, cursor = [], 0
    while True:
        events = store.events(state.get("job", ""), cursor)
        validations.extend(e["data"] for e in events if e["kind"] == "validation_result")
        if len(events) < 100:
            break
        cursor = events[-1]["seq"]
    return {
        "completion_reason": state.get("outcome", "ANSWER"),
        "answer": answer,
        "citations": citations,
        "unknown_citation_ids": unknown,
        "evidence_count": len(state["evidence"]),
        "snapshot": snapshot,
        "steps": state["steps"],
        "skill": state["skill"],
        "warning": warning,
        "verification": {
            "source_configuration_is_not_a_run": True,
            "upstream_ci_run": "UNKNOWN_NO_RUN_LOG_INGESTED",
            "local_executions": [
                {key: value for key, value in result.items() if key != "output"} for result in validations
            ],
            "scope": "Only the listed recipe and environment were attempted; AST parsing is not a test-suite pass.",
        },
    }
