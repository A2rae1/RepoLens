import io
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pytest
from conftest import archive

from repo_agent.repository import canonical, safe_archive


def test_versioned_search_citations_and_owner_filter(evidence):
    store, repo, snapshot = evidence
    found = repo.search("alice", "workspace", snapshot["id"], "Python", 5)
    assert found and found[0]["path"] == "README.md"
    assert found[0]["start_line"] == 1
    assert "3.12" in found[0]["content"]
    with pytest.raises(PermissionError):
        repo.search("bob", "workspace", snapshot["id"], "Python")
    with pytest.raises(PermissionError):
        repo.read("alice", "other-workspace", snapshot["id"], "README.md", 1, 10)
    with pytest.raises(ValueError):
        repo.read("alice", "workspace", snapshot["id"], "README.md", 1, 1000)


@pytest.mark.parametrize(
    "repo,sha",
    [
        ("http://127.0.0.1/secrets", "a" * 40),
        ("https://github.com/a/b@localhost", "a" * 40),
        ("https://github.com/a/b", "main"),
        ("https://github.com/../b", "a" * 40),
    ],
)
def test_url_allowlist_blocks_ssrf_and_unpinned_version(repo, sha):
    with pytest.raises(ValueError):
        canonical(repo, sha)


def test_zip_path_traversal_and_expansion_guard():
    with pytest.raises(ValueError):
        safe_archive(archive({"../escape.py": "print(1)"}))
    with pytest.raises(ValueError):
        safe_archive(archive({"bomb.txt": "0" * 1_000_000}))
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as z:
        link = zipfile.ZipInfo("root/link.py")
        link.external_attr = 0o120777 << 16
        z.writestr(link, "../../outside")
    with pytest.raises(ValueError):
        safe_archive(output.getvalue())


def test_snapshot_dedupe_and_version_change_do_not_mix(evidence):
    store, repo, original = evidence
    with pytest.raises(ValueError, match="SNAPSHOT_CONTENT_CHANGED"):
        repo.ingest("alice", "workspace", original["repo"], "a" * 40, archive({"README.md": "different"}))
    newer = repo.ingest(
        "alice", "workspace", original["repo"], "b" * 40, archive({"README.md": "Requires Python 3.13"})
    )
    old = repo.search("alice", "workspace", original["id"], "Python")[0]
    new = repo.search("alice", "workspace", newer["id"], "Python")[0]
    assert "3.12" in old["content"] and "3.13" in new["content"]


def test_budget_reservation_is_atomic_and_keeps_unknown_calls(evidence):
    store, _, _ = evidence

    def attempt(_):
        try:
            store.reserve_call("job", "fixture", 1, 7)
            return 1
        except RuntimeError:
            return 0

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(attempt, range(30))) == 7
    with store.connect() as db:
        assert db.execute("SELECT SUM(reserved_cny) FROM model_calls").fetchone()[0] == 7


def test_approval_and_memory_cannot_be_granted_by_model(evidence):
    store, _, _ = evidence
    key = store.propose("job", {"recipe": "python_ast"})
    assert store.approval("job", key)["decision"] is None
    store.decide("job", key, True)
    store.decide("job", key, True)  # The same durable decision is idempotent.
    with pytest.raises(ValueError):
        store.decide("job", key, False)  # A model/client cannot reverse that decision.
    with pytest.raises(PermissionError):
        store.preference("alice", "python", "3.12", confirmed=False)
    store.preference("alice", "python", "3.12", confirmed=True)
    assert store.preferences("bob") == {}
    store.preference("alice", "python", None, confirmed=True)
    assert store.preferences("alice") == {}
