import ast
import hashlib
import io
import re
import stat
import time
import zipfile
from pathlib import PurePosixPath

import httpx

from .network import tls_context
from .store import Store
from .telemetry import operation

REPO = re.compile(r"https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)\Z")
SHA = re.compile(r"[a-fA-F0-9]{40}\Z")
TEXT_SUFFIXES = {
    ".md",
    ".rst",
    ".txt",
    ".py",
    ".java",
    ".xml",
    ".toml",
    ".json",
    ".yml",
    ".yaml",
    ".gradle",
    ".properties",
}


def canonical(repo: str, commit: str) -> tuple[str, str]:
    if not REPO.fullmatch(repo) or not SHA.fullmatch(commit):
        raise ValueError("Only public github.com repositories and full commit SHAs are supported")
    if any(part in {".", ".."} for part in repo.split("/")[-2:]):
        raise ValueError("Invalid repository")
    return repo, commit.lower()


def safe_archive(data: bytes) -> dict[str, str]:
    """Never extract untrusted archives into the host filesystem."""
    if len(data) > 12_000_000:
        raise ValueError("Archive exceeds compressed size limit")
    files, total = {}, 0
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if len(entries) > 6000:
            raise ValueError("Archive contains too many entries")
        root = None
        seen = set()
        for item in entries:
            path = PurePosixPath(item.filename)
            if path.is_absolute() or ".." in path.parts or "\\" in item.filename or ":" in item.filename:
                raise ValueError("Unsafe archive path")
            reserved = {
                "CON",
                "PRN",
                "AUX",
                "NUL",
                *(f"COM{i}" for i in range(1, 10)),
                *(f"LPT{i}" for i in range(1, 10)),
            }
            if any(
                part.rstrip(". ") != part
                or part.split(".")[0].upper() in reserved
                or any(ord(c) < 32 for c in part)
                for part in path.parts
            ):
                raise ValueError("Unsafe Windows archive component")
            canonical_path = str(path).casefold()
            if canonical_path in seen:
                raise ValueError("Duplicate or case-colliding archive path")
            seen.add(canonical_path)
            if not path.parts:
                continue
            if root is None:
                root = path.parts[0]
            if path.parts[0] != root:
                raise ValueError("Repository archive must have one root")
            mode = (item.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise ValueError("Symlinks are not accepted")
            total += item.file_size
            if total > 40_000_000 or item.file_size > 2_000_000:
                raise ValueError("Archive exceeds expanded size limit")
            if item.file_size > max(1, item.compress_size) * 150:
                raise ValueError("Archive compression ratio is unsafe")
            relative = str(PurePosixPath(*path.parts[1:]))
            if item.is_dir() or len(path.parts) < 2:
                continue
            if any(p.startswith(".") and p not in {".github"} for p in path.parts[1:]):
                continue
            if PurePosixPath(relative).suffix.lower() not in TEXT_SUFFIXES and PurePosixPath(
                relative
            ).name not in {"LICENSE", "Dockerfile", "Makefile"}:
                continue
            raw = archive.read(item)
            try:
                content = raw.decode("utf-8")
            except UnicodeDecodeError:
                continue
            if "\x00" not in content:
                files[relative] = content
    if not files:
        raise ValueError("No supported text files in archive")
    return files


def chunks(path: str, text: str):
    lines = text.splitlines()
    start = 0
    while start < len(lines):
        end = min(start + 45, len(lines))
        # Prefer a section/symbol boundary without losing any source lines.
        for candidate in range(end - 1, start + 15, -1):
            if lines[candidate].startswith(("# ", "## ", "def ", "class ", "public class ")):
                end = candidate
                break
        content = "\n".join(lines[start:end])[:7000]
        if content.strip():
            yield start + 1, end, content
        start = end  # Disjoint chunks keep citations simple; boundary ablation can compare overlap later.


class Repository:
    def __init__(self, store: Store):
        self.store = store

    def index_symbols(self, snapshot: str):
        with self.store.connect() as db:
            if db.execute(
                "SELECT 1 FROM symbol_index_versions WHERE snapshot=? AND version=1", (snapshot,)
            ).fetchone():
                return
            files = db.execute(
                "SELECT path,content FROM source_files WHERE snapshot=?", (snapshot,)
            ).fetchall()
            for file in files:
                if file["path"].endswith(".py"):
                    try:
                        nodes = ast.walk(ast.parse(file["content"]))
                        symbols = [
                            (
                                snapshot,
                                file["path"],
                                n.name,
                                type(n).__name__,
                                n.lineno,
                                n.end_lineno or n.lineno,
                            )
                            for n in nodes
                            if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                        ]
                    except SyntaxError:
                        continue
                elif file["path"].endswith(".java"):
                    symbols = [
                        (
                            snapshot,
                            file["path"],
                            m.group(2),
                            m.group(1),
                            file["content"][: m.start()].count("\n") + 1,
                            file["content"][: m.start()].count("\n") + 80,
                        )
                        for m in re.finditer(r"\b(class|interface|record|enum)\s+(\w+)", file["content"])
                    ]
                else:
                    continue
                db.executemany("INSERT OR IGNORE INTO symbols VALUES(?,?,?,?,?,?)", symbols)
            db.execute(
                "INSERT INTO symbol_index_versions VALUES(?,1) ON CONFLICT(snapshot) DO UPDATE SET version=1",
                (snapshot,),
            )

    def find_symbol(self, owner: str, workspace: str, snapshot: str, name: str) -> list[dict]:
        found = self.symbol_locations(owner, workspace, snapshot, name)
        evidence = []
        for symbol in found:
            evidence.extend(
                self.read(
                    owner,
                    workspace,
                    snapshot,
                    symbol["path"],
                    symbol["start_line"],
                    min(symbol["end_line"], symbol["start_line"] + 75),
                )
            )
        return list({item["id"]: item for item in evidence}.values())[:10]

    def symbol_locations(self, owner: str, workspace: str, snapshot: str, name: str) -> list[dict]:
        self.store.snapshot(snapshot, owner, workspace)
        self.index_symbols(snapshot)
        with self.store.connect() as db:
            found = db.execute(
                "SELECT * FROM symbols WHERE snapshot=? AND name=? ORDER BY path,start_line LIMIT 5",
                (snapshot, name),
            ).fetchall()
        return [dict(row) for row in found]

    async def fetch(self, owner: str, workspace: str, repo: str, commit: str) -> dict:
        with operation("repo.fetch", **{"repo.url": repo, "repo.commit": commit}):
            return await self._fetch(owner, workspace, repo, commit)

    async def _fetch(self, owner: str, workspace: str, repo: str, commit: str) -> dict:
        repo, commit = canonical(repo, commit)
        match = REPO.fullmatch(repo)
        url = f"https://codeload.github.com/{match[1]}/{match[2]}/zip/{commit}"
        async with httpx.AsyncClient(timeout=40, follow_redirects=False, verify=tls_context()) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                data = bytearray()
                async for block in response.aiter_bytes():
                    data.extend(block)
                    if len(data) > 12_000_000:
                        raise ValueError("Repository archive exceeds download limit")
        return self.ingest(owner, workspace, repo, commit, bytes(data))

    def ingest(self, owner: str, workspace: str, repo: str, commit: str, archive: bytes) -> dict:
        repo, commit = canonical(repo, commit)
        files = safe_archive(archive)
        snapshot_id = hashlib.sha256(f"{owner}\n{workspace}\n{repo}\n{commit}".encode()).hexdigest()
        archive_digest = hashlib.sha256(archive).hexdigest()
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
            tree = [
                (
                    str(PurePosixPath(*PurePosixPath(item.filename).parts[1:])),
                    hashlib.sha256(zipped.read(item)).hexdigest(),
                )
                for item in zipped.infolist()
                if not item.is_dir()
            ]
        tree_digest = hashlib.sha256(repr(sorted(tree)).encode()).hexdigest()
        archive_dir = self.store.root / "archives"
        archive_dir.mkdir(exist_ok=True)
        archive_path = archive_dir / (archive_digest + ".zip")
        with self.store.connect() as db:
            old = db.execute(
                "SELECT tree_digest FROM snapshot_archives WHERE snapshot=?", (snapshot_id,)
            ).fetchone()
            if old and old["tree_digest"] != tree_digest:
                raise ValueError("SNAPSHOT_CONTENT_CHANGED_FOR_FIXED_COMMIT")
            if not archive_path.exists():
                archive_path.write_bytes(archive)
            db.execute(
                "INSERT OR IGNORE INTO snapshot_archives VALUES(?,?,?,?)",
                (snapshot_id, archive_digest, str(archive_path.resolve()), tree_digest),
            )
            previous = db.execute("SELECT * FROM snapshots WHERE id=?", (snapshot_id,)).fetchone()
            if previous:
                return dict(previous) | {"reused": True}
            # One transaction publishes all chunks and the visible snapshot, never half an index.
            db.execute(
                "INSERT INTO snapshots VALUES(?,?,?,?,?,?)",
                (snapshot_id, owner, workspace, repo, commit, time.time()),
            )
            for path, text in files.items():
                db.execute(
                    "INSERT INTO source_files VALUES(?,?,?,?)",
                    (snapshot_id, path, text, hashlib.sha256(text.encode()).hexdigest()),
                )
                for start, end, content in chunks(path, text):
                    digest = hashlib.sha256(content.encode()).hexdigest()
                    cid = hashlib.sha256(f"{snapshot_id}:{path}:{start}:{digest}".encode()).hexdigest()
                    db.execute(
                        "INSERT INTO chunks VALUES(?,?,?,?,?,?,?)",
                        (cid, snapshot_id, path, start, end, content, digest),
                    )
                    db.execute("INSERT INTO evidence_fts VALUES(?,?,?,?)", (cid, snapshot_id, path, content))
        return self.store.snapshot(snapshot_id, owner, workspace) | {"files": len(files), "reused": False}

    def read(self, owner: str, workspace: str, snapshot: str, path: str, start: int, end: int) -> list[dict]:
        self.store.snapshot(snapshot, owner, workspace)
        if start < 1 or end < start or end - start > 180:
            raise ValueError("Read range must be within 180 source lines")
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT * FROM chunks WHERE snapshot=? AND path=? AND end_line>=? AND start_line<=? ORDER BY start_line",
                (snapshot, path, start, end),
            ).fetchall()
        return [dict(row) for row in rows]

    def search(self, owner: str, workspace: str, snapshot: str, query: str, k: int = 5) -> list[dict]:
        self.store.snapshot(snapshot, owner, workspace)
        words = re.findall(r"[\w]+", query, re.UNICODE)[:20]
        if not words:
            return []
        expression = " OR ".join('"' + word.replace('"', "") + '"' for word in words)
        with self.store.connect() as db:
            rows = db.execute(
                """SELECT c.*,bm25(evidence_fts) AS score
                FROM evidence_fts JOIN chunks c ON c.id=evidence_fts.chunk_id
                WHERE evidence_fts MATCH ? AND c.snapshot=? ORDER BY score LIMIT ?""",
                (expression, snapshot, max(1, min(k, 10))),
            ).fetchall()
        return [dict(row) | {"retrieval": "sqlite_fts_bm25"} for row in rows]
