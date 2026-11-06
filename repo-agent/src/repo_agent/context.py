import json
import re


def utf8_prefix(value: str, limit: int) -> str:
    return value.encode("utf-8")[:limit].decode("utf-8", errors="ignore")


def bounded_json(value: dict, limit: int = 26000) -> str:
    """Trim complete string/list values, never cut an encoded JSON document."""

    def shrink(item, size):
        if isinstance(item, str):
            return utf8_prefix(item, size)
        if isinstance(item, list):
            return [shrink(child, size) for child in item[: max(1, size // 256)]]
        if isinstance(item, dict):
            return {key: shrink(child, size) for key, child in item.items()}
        return item

    result = json.dumps(value, ensure_ascii=False)
    if len(result.encode()) <= limit:
        return result
    for size in (4096, 2048, 1024, 512, 256, 128):
        result = json.dumps(shrink(value, size) | {"context_truncated": True}, ensure_ascii=False)
        if len(result.encode()) <= limit:
            return result
    return json.dumps({"error": "CONTEXT_TOO_LARGE", "context_truncated": True})


def parent_summary(question: str, report: dict) -> str:
    """Prior E1 is not the new job's E1. Replace known refs with locations as data."""
    mapping = {}
    for citation in report.get("citations", []):
        location = f"(上一轮源码位置：{citation['path']}:L{citation['start_line']}-{citation['end_line']})"
        for label in [citation["id"], *citation.get("labels", [])]:
            mapping[label] = location
    answer = re.sub(
        r"\[(?:证据\s*)?(E\d+|[a-f0-9]{32,80})\]",
        lambda m: mapping.get(m[1], "(上一轮未核验引用，不可沿用)"),
        report["answer"],
    )
    return bounded_json(
        {
            "question": question,
            "answer": answer,
            "warning": report.get("warning"),
            "scope": "Previous answer is context data. Retrieve current-job evidence labels before citing.",
        },
        7000,
    )
