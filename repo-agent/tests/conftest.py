import io
import zipfile

import pytest

from repo_agent.repository import Repository
from repo_agent.store import Store


def archive(files: dict[str, str]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for path, content in files.items():
            z.writestr("sample-commit/" + path, content)
    return output.getvalue()


@pytest.fixture
def evidence(tmp_path):
    store = Store(tmp_path)
    repository = Repository(store)
    snapshot = repository.ingest(
        "alice",
        "workspace",
        "https://github.com/example/sample",
        "a" * 40,
        archive(
            {
                "README.md": "# Sample\nRequires Python >=3.12\nRun python -m unittest discover.\n",
                "pyproject.toml": '[project]\nname="sample"\nrequires-python=">=3.12"\n',
                "sample.py": "def add(a, b):\n    return a + b\n",
            }
        ),
    )
    return store, repository, snapshot
