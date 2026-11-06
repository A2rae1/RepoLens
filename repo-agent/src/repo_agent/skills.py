"""A skill selects scoped instructions AND an allowed tool set; it cannot grant execution permission."""

SKILLS = {
    "environment": {
        "terms": ("环境", "安装", "依赖", "python", "java", "install", "version"),
        "instructions": "优先检查manifest及README，区分声明版本、推断兼容和实际验证。",
        "tools": {"inspect_manifest", "search_evidence", "read_file_region", "propose_validation"},
    },
    "diagnose": {
        "terms": ("错误", "失败", "报错", "error", "fail", "debug"),
        "instructions": "先定位错误符号和路径，再提出证据支持的原因；不编造复现成功。",
        "tools": {"search_evidence", "read_file_region", "inspect_manifest", "propose_validation"},
    },
    "research": {
        "terms": (),
        "instructions": "先检索功能与限制的证据，结论带路径、行号和commit，无证据明确回答未知。",
        "tools": {"search_evidence", "read_file_region", "inspect_manifest"},
    },
}


def select_skill(question: str) -> tuple[str, dict]:
    lower = question.lower()
    # An explicit failure intent outranks a language/environment keyword.
    for name in ("diagnose", "environment"):
        skill = SKILLS[name]
        if any(term in lower for term in skill["terms"]):
            return name, skill | {"tools": skill["tools"] | {"find_symbol"}}
    return "research", SKILLS["research"] | {"tools": SKILLS["research"]["tools"] | {"find_symbol"}}
