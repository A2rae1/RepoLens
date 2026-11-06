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
    for path in sorted(root.glob("case-*.json")):
        raw = path.read_bytes()
        row = json.loads(raw)
        if row.get("requires_review"):
            annotation = labels["cases"][row["id"]]
            assert isinstance(annotation["passed"], bool) and len(annotation["reason"]) >= 20
            reviews.append(
                {"id": row["id"], **annotation, "answer_artifact_sha256": hashlib.sha256(raw).hexdigest()}
            )
        elif "error" not in row:
            automatic.append(row)
    assert len(reviews) == len(labels["cases"])
    report = {
        "reviewer": labels["reviewer"],
        "rubric": labels["rubric"],
        "semantic_reviewed": len(reviews),
        "semantic_passed": sum(r["passed"] for r in reviews),
        "automatic_scored": len(automatic),
        "automatic_passed": sum(bool(r["task_success"]) for r in automatic),
        "combined_total": len(reviews) + len(automatic),
        "combined_passed": sum(r["passed"] for r in reviews)
        + sum(bool(r["task_success"]) for r in automatic),
        "reviews": reviews,
        "scope": "AI-authored single Click development dataset unless explicitly replaced. Manual inspection by Codex is AI review, not independent human annotation or a general benchmark.",
    }
    (root / "semantic-review.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in report.items() if k != "reviews"}))


if __name__ == "__main__":
    main()
