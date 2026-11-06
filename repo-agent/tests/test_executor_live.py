import json
import os
import uuid
from pathlib import Path

import pytest
from conftest import archive

from repo_agent.execution_recovery import docker_capture
from repo_agent.executor import Executor
from repo_agent.repository import Repository
from repo_agent.settings import Settings
from repo_agent.store import Store

pytestmark = pytest.mark.skipif(
    os.environ.get("EXECUTOR_IT") != "true", reason="Requires pinned local runner image and Docker"
)


def prepare(tmp_path, files):
    cfg = Settings(
        data_dir=tmp_path, executor_enabled=True, docker_executable=os.environ["DOCKER_EXECUTABLE"]
    )
    manifest = json.loads(Path(".local/runner-image.json").read_text(encoding="utf-8-sig"))
    (tmp_path / "runner-image.json").write_text(json.dumps(manifest), encoding="utf-8")
    store = Store(tmp_path)
    snapshot = Repository(store).ingest(
        "fixture-owner", "fixture-workspace", "https://github.com/example/fixture", "c" * 40, archive(files)
    )
    return cfg, store, snapshot


async def test_real_container_needs_approval_then_reuses_verified_result(tmp_path):
    cfg, store, snapshot = prepare(
        tmp_path,
        {
            "sample.py": "def add(a,b):\n    return a+b\n",
            "tests/test_sample.py": "import unittest\nfrom sample import add\nclass T(unittest.TestCase):\n    def test_add(self): self.assertEqual(add(1,2),3)\n",
            "tests/__init__.py": "",
        },
    )
    executor = Executor(cfg, store)
    job = "fixture-" + uuid.uuid4().hex
    plan = executor.plan(job, snapshot["id"], "python_unittest")
    key = store.propose(job, plan)
    with pytest.raises(PermissionError):
        await executor.run("fixture-owner", "fixture-workspace", job, key)
    store.decide(job, key, True)  # Synthetic test-harness approval, not a real-user production approval.
    result = await executor.run("fixture-owner", "fixture-workspace", job, key)
    assert result["verified"] and "TESTS_RUN 1" in result["output"]
    assert (await executor.run("fixture-owner", "fixture-workspace", job, key))["reused"]


async def test_zero_discovered_tests_are_not_reported_successful(tmp_path):
    cfg, store, snapshot = prepare(tmp_path, {"sample.py": "value=1\n", "tests/__init__.py": ""})
    executor = Executor(cfg, store)
    job = "empty-" + uuid.uuid4().hex
    key = store.propose(job, executor.plan(job, snapshot["id"], "python_unittest"))
    store.decide(job, key, True)
    result = await executor.run("fixture-owner", "fixture-workspace", job, key)
    assert not result["verified"] and result["exit_code"] == 5


async def test_container_result_is_recovered_after_worker_metadata_crash(tmp_path):
    cfg, store, snapshot = prepare(tmp_path, {"sample.py": "value=1\n"})
    executor = Executor(cfg, store)
    job = "recover-" + uuid.uuid4().hex
    key = store.propose(job, executor.plan(job, snapshot["id"], "python_ast"))
    store.decide(job, key, True)
    name = "repo-verify-" + uuid.uuid4().hex[:16]
    code, _, _ = await docker_capture(
        cfg.docker_executable,
        "run",
        "-d",
        "--name",
        name,
        "--network",
        "none",
        "--memory",
        "128m",
        "--label",
        "repolens.job=" + job,
        "--label",
        "repolens.plan=" + key,
        executor.image_id,
        "python",
        "-c",
        "print('RECOVERED_FIXTURE')",
    )
    assert code == 0
    await docker_capture(cfg.docker_executable, "wait", name)
    with store.connect() as db:
        db.execute(
            "INSERT INTO executions VALUES(?,?,'RUNNING',?)",
            (job, key, json.dumps({"container_name": name, "recipe": "python_ast"})),
        )
    result = await Executor(cfg, Store(tmp_path)).run("fixture-owner", "fixture-workspace", job, key)
    assert result["recovered"] and result["verified"] and "RECOVERED_FIXTURE" in result["output"]


async def test_real_runner_blocks_network_host_writes_secrets_and_privileges(tmp_path):
    payload = """import unittest,os,socket
from pathlib import Path
class Boundary(unittest.TestCase):
 def test_boundaries(self):
  self.assertNotEqual(os.geteuid(),0)
  with self.assertRaises(OSError): socket.create_connection(('1.1.1.1',80),timeout=.3)
  with self.assertRaises(OSError): Path('/work/source-write-denied').write_text('no')
  self.assertFalse(Path('/var/run/docker.sock').exists())
  self.assertFalse(Path('/app/.env').exists())
  for key in ('DEEPSEEK_API_KEY','AGENT_INTERNAL_SECRET','AWS_SECRET_ACCESS_KEY','MCP_AUTH_TOKEN'):
   self.assertNotIn(key,os.environ)
  status=Path('/proc/self/status').read_text()
  self.assertIn('NoNewPrivs:\\t1',status)
  self.assertLessEqual(int(Path('/sys/fs/cgroup/pids.max').read_text()),64)
  self.assertLessEqual(int(Path('/sys/fs/cgroup/memory.max').read_text()),256*1024*1024)
"""
    cfg, store, snapshot = prepare(tmp_path, {"tests/__init__.py": "", "tests/test_boundary.py": payload})
    executor = Executor(cfg, store)
    job = "boundary-" + uuid.uuid4().hex
    key = store.propose(job, executor.plan(job, snapshot["id"], "python_unittest"))
    store.decide(job, key, True)
    result = await executor.run("fixture-owner", "fixture-workspace", job, key)
    assert result["verified"] and "TESTS_RUN 1" in result["output"]


async def test_real_runner_large_output_is_bounded_and_not_verified(tmp_path):
    payload = "import unittest\nclass Flood(unittest.TestCase):\n def test_flood(self): print('x'*120000)\n"
    cfg, store, snapshot = prepare(tmp_path, {"tests/__init__.py": "", "tests/test_flood.py": payload})
    executor = Executor(cfg, store)
    job = "output-" + uuid.uuid4().hex
    key = store.propose(job, executor.plan(job, snapshot["id"], "python_unittest"))
    store.decide(job, key, True)
    result = await executor.run("fixture-owner", "fixture-workspace", job, key)
    assert (
        not result["verified"]
        and result.get("error") == "RuntimeError"
        and len(result["output"].encode()) <= 100000
    )
    code, out, _ = await docker_capture(
        cfg.docker_executable, "ps", "-aq", "--filter", "label=repolens.job=" + job
    )
    assert code == 0 and not out.strip()


async def test_real_runner_wall_timeout_cleans_only_own_container(tmp_path):
    payload = "import unittest,time\nclass Slow(unittest.TestCase):\n def test_slow(self): time.sleep(40)\n"
    cfg, store, snapshot = prepare(tmp_path, {"tests/__init__.py": "", "tests/test_slow.py": payload})
    executor = Executor(cfg, store)
    job = "timeout-" + uuid.uuid4().hex
    key = store.propose(job, executor.plan(job, snapshot["id"], "python_unittest"))
    store.decide(job, key, True)
    result = await executor.run("fixture-owner", "fixture-workspace", job, key)
    assert not result["verified"] and result["exit_code"] in (None, 124, 137)
    code, out, _ = await docker_capture(
        cfg.docker_executable, "ps", "-aq", "--filter", "label=repolens.job=" + job
    )
    assert code == 0 and not out.strip()
