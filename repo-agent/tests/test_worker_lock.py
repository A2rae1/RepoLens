import asyncio
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from repo_agent.lifecycle import invoke_checkpointed
from repo_agent.worker_lock import job_lock


def test_lock_is_shared_across_processes_and_released_after_worker_death(tmp_path):
    script = tmp_path / "holder.py"
    marker = tmp_path / "ready"
    script.write_text(
        "import sys,time\nfrom pathlib import Path\nfrom repo_agent.worker_lock import job_lock\n"
        "with job_lock(Path(sys.argv[1]),'job') as acquired:\n"
        " assert acquired\n Path(sys.argv[2]).write_text('ready')\n time.sleep(30)\n"
    )
    env = os.environ | {"PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    # Windows venv python.exe is a redirector: kill the actual interpreter,
    # not a launcher that could leave its child holding the test lock.
    interpreter = getattr(sys, "_base_executable", sys.executable)
    worker = subprocess.Popen([interpreter, str(script), str(tmp_path), str(marker)], env=env)
    try:
        deadline = time.monotonic() + 5
        while not marker.exists() and worker.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert marker.exists()
        with job_lock(tmp_path, "job") as acquired:
            assert not acquired
        with job_lock(tmp_path, "other-job") as acquired:
            assert acquired
    finally:
        worker.kill()
        worker.wait(timeout=5)
    with job_lock(tmp_path, "job") as acquired:
        assert acquired


async def test_cancelled_graph_finishes_cleanup_before_job_can_be_reclaimed(tmp_path):
    started, releasing, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def ainvoke(*args):
        started.set()
        try:
            await asyncio.Future()
        finally:
            await releasing.wait()
            finished.set()

    async def run():
        with job_lock(tmp_path, "job") as acquired:
            assert acquired
            await invoke_checkpointed(SimpleNamespace(ainvoke=ainvoke), None, {})

    worker = asyncio.create_task(run())
    await started.wait()
    worker.cancel()
    await asyncio.sleep(0)
    assert not worker.done()
    with job_lock(tmp_path, "job") as acquired:
        assert not acquired
    releasing.set()
    await asyncio.gather(worker, return_exceptions=True)
    assert finished.is_set()
    with job_lock(tmp_path, "job") as acquired:
        assert acquired


async def test_windows_checkpoint_adapter_drains_issued_thread_on_cancellation():
    from concurrent.futures import ThreadPoolExecutor

    from repo_agent.checkpoints import ThreadedPostgresSaver

    started, release = threading.Event(), threading.Event()
    fake = SimpleNamespace(_slots=asyncio.Semaphore(1), _pool=ThreadPoolExecutor(max_workers=1))

    def database_write():
        started.set()
        release.wait(timeout=3)

    task = asyncio.create_task(ThreadedPostgresSaver.dispatch(fake, database_write))
    try:
        assert await asyncio.to_thread(started.wait, 2)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        assert task.cancelled()
    finally:
        release.set()
        fake._pool.shutdown(wait=True)
