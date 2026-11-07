"""Persist explicit case-by-case AI/human annotations without altering raw answers or auto-gates."""

import argparse
import hashlib
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True)
    p.add_argument("--annotations", required=True)
    args = p.parse_args()
    root = Path(args.root)
    labels = json.loads(Path(args.annotations).read_text(encoding="utf-8"))
    reviews = []
    automatic = []
    raw_hashes = {}
    execution_errors = 0
    for path in sorted(root.glob("case-*.json")):
        raw = path.read_bytes()
        row = json.loads(raw)
        raw_hashes[path.name] = hashlib.sha256(raw).hexdigest()
        execution_errors += "error" in row
        if row.get("requires_review"):
            annotation = labels["cases"][row["id"]]
            assert isinstance(annotation["passed"], bool) and len(annotation["reason"]) >= 20
            reviews.append(
                {
                    "id": row["id"],
                    **annotation,
                    "passed": annotation["passed"] and "error" not in row,
                    "answer_artifact_sha256": hashlib.sha256(raw).hexdigest(),
                }
            )
        else:
            automatic.append(row)
    assert len(reviews) == len(labels["cases"])
    report = {
        "metric_version": 2,
        "metric_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "annotations_sha256": hashlib.sha256(Path(args.annotations).read_bytes()).hexdigest(),
        "raw_case_sha256": raw_hashes,
        "execution_errors": execution_errors,
        "reviewer": labels["reviewer"],
        "rubric": labels["rubric"],
        "semantic_reviewed": len(reviews),
        "semantic_passed": sum(r["passed"] for r in reviews),
        "automatic_scored": len(automatic),
        "automatic_passed": sum(r.get("task_success") is True and "error" not in r for r in automatic),
        "combined_total": len(reviews) + len(automatic),
        "combined_passed": sum(r["passed"] for r in reviews)
        + sum(r.get("task_success") is True and "error" not in r for r in automatic),
        "reviews": reviews,
        "scope": "AI-authored single Click development dataset unless explicitly replaced. Manual inspection by Codex is AI review, not independent human annotation or a general benchmark.",
    }
    (root / "semantic-review-v2.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in report.items() if k != "reviews"}))


if __name__ == "__main__":
    main()
