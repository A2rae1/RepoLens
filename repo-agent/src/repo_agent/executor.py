import asyncio
import hashlib
import io
import json
import time
import uuid
import zipfile
from pathlib import PurePosixPath

from .execution_recovery import docker_capture, recover_execution
from .repository import safe_archive
from .settings import Settings
from .store import Store

RECIPES = {
    "python_ast": [
        "python",
        "-I",
        "-c",
        "import ast,pathlib;fs=list(pathlib.Path('/work').rglob('*.py'));[ast.parse(p.read_text(encoding='utf-8'),filename=str(p)) for p in fs];print('AST_OK',len(fs))",
    ],
    "python_unittest": [
        "python",
        "-I",
        "-c",
        "import sys,unittest;sys.path[:0]=['/work/src','/work'];r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover('/work/tests',top_level_dir='/work'));print('TESTS_RUN',r.testsRun);sys.exit(0 if r.testsRun>0 and r.wasSuccessful() else 5)",
    ],
    "python_pytest": [
        "python",
        "-I",
        "-c",
        "import sys,pytest;sys.path[:0]=['/work/src','/work'];sys.exit(pytest.main(['/work/tests','-q','-p','no:cacheprovider','--basetemp=/tmp/pytest']))",
    ],
}


class Executor:
    def __init__(self, settings: Settings, store: Store):
        self.settings, self.store = settings, store
        manifest = settings.data_dir / "runner-image.json"
        self.image_id = ""
        if manifest.exists():
            image = json.loads(manifest.read_text(encoding="utf-8-sig"))
            if image.get("tag") == settings.executor_image:
                self.image_id = image["id"]

    def plan(self, job: str, snapshot: str, recipe: str) -> dict:
        if recipe not in RECIPES:
            raise ValueError("Recipe is not in the execution allowlist")
        return {
            "job": job,
            "snapshot": snapshot,
            "recipe": recipe,
            "recipe_digest": hashlib.sha256(json.dumps(RECIPES[recipe]).encode()).hexdigest(),
            "python_path": "/work/src:/work",
            "mount_mode": "volume-subpath" if self.settings.executor_volume else "native-bind",
            "image": self.settings.executor_image,
            "image_id": self.image_id,
            "network": "none",
            "timeout_seconds": 30,
            "memory_mb": 256,
            "read_only_source": True,
            "warning": "Docker resource restrictions reduce risk; not a strong sandbox for hostile code.",
        }

    async def run(self, owner: str, workspace: str, job: str, plan_hash: str) -> dict:
        approval = self.store.approval(job, plan_hash)
        if approval["decision"] != "APPROVED" or approval["expires"] <= time.time():
            raise PermissionError("Execution has not received an unexpired user approval")
        plan = json.loads(approval["plan"])
        if plan["job"] != job or plan != self.plan(job, plan["snapshot"], plan["recipe"]):
            raise PermissionError("Execution plan changed after approval")
        self.store.snapshot(plan["snapshot"], owner, workspace)
        if not self.settings.executor_enabled:
            return {"status": "NOT_RUN", "reason": "EXECUTOR_DISABLED"}
        if not self.image_id:
            return {"status": "NOT_RUN", "reason": "RUNNER_IMAGE_DIGEST_NOT_CONFIGURED"}
        with self.store.connect() as db:
            old = db.execute(
                "SELECT * FROM executions WHERE job=? AND plan_hash=?", (job, plan_hash)
            ).fetchone()
            if old:
                if old["status"] in {"COMPLETED", "CANCELLED"}:
                    return json.loads(old["result"]) | {"reused": True}
                # Crash after dispatch is ambiguous: don't silently run the same untrusted code twice.
                return await recover_execution(self.settings, self.store, job, plan_hash, old["result"])
            source = db.execute(
                "SELECT * FROM snapshot_archives WHERE snapshot=?", (plan["snapshot"],)
            ).fetchone()
            if not source:
                raise RuntimeError("COMPLETE_SOURCE_ARCHIVE_REQUIRED_REFETCH_FIXED_COMMIT")
        if not job or any(
            c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in job
        ):
            raise ValueError("Invalid execution job identifier")
        work_root = self.settings.executor_work_dir or self.settings.data_dir / "executions"
        sandbox = work_root / job / plan_hash
        sandbox.mkdir(parents=True, exist_ok=True)
        # The archive digest is portable across Windows/native and Linux/container runs.
        archive = (self.settings.data_dir / "archives" / (source["digest"] + ".zip")).read_bytes()
        if hashlib.sha256(archive).hexdigest() != source["digest"]:
            raise ValueError("SOURCE_ARCHIVE_CHECKSUM_MISMATCH")
        safe_archive(archive)
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
            for item in zipped.infolist():
                if item.is_dir():
                    continue
                relative = PurePosixPath(*PurePosixPath(item.filename).parts[1:])
                target = (sandbox / str(relative)).resolve()
                if not target.is_relative_to(sandbox.resolve()):
                    raise ValueError("Unsafe source path")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zipped.read(item))
        name = "repo-verify-" + uuid.uuid4().hex[:16]
        with self.store.connect() as db:
            db.execute(
                "INSERT INTO executions VALUES(?,?,'RUNNING',?)",
                (job, plan_hash, json.dumps({"container_name": name, "recipe": plan["recipe"]})),
            )
        mount = (
            f"type=volume,source={self.settings.executor_volume},target=/work,readonly,volume-subpath={job}/{plan_hash}"
            if self.settings.executor_volume
            else f"type=bind,source={sandbox.resolve()},target=/work,readonly"
        )
        args = [
            self.settings.docker_executable,
            "run",
            "--name",
            name,
            "--init",
            "--label",
            "repolens.job=" + job,
            "--label",
            "repolens.plan=" + plan_hash,
            "--log-driver",
            "json-file",
            "--log-opt",
            "max-size=128k",
            "--log-opt",
            "max-file=1",
            "--network",
            "none",
            "--memory",
            "256m",
            "--cpus",
            "0.5",
            "--pids-limit",
            "64",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--user",
            "65534:65534",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=32m",
            "--mount",
            mount,
            "--workdir",
            "/work",
            "--env",
            "PYTHONPATH=/work/src:/work",
            self.image_id,
            "timeout",
            "--kill-after=2s",
            "30s",
            *RECIPES[plan["recipe"]],
        ]
        process = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        output = bytearray()

        async def collect():
            while data := await process.stdout.read(4096):
                if len(output) + len(data) > 100_000:
                    raise RuntimeError("OUTPUT_LIMIT_EXCEEDED")
                output.extend(data)
            return await process.wait()

        try:
            code = await asyncio.wait_for(collect(), timeout=30)
            result = {
                "status": "COMPLETED",
                "exit_code": code,
                "output": output.decode(errors="replace"),
                "plan_hash": plan_hash,
                "recipe": plan["recipe"],
                "verified": code == 0,
            }
        except (Exception, asyncio.CancelledError) as exc:
            # This name belongs exclusively to this execution. Never kill other containers/processes.
            cleanup = await asyncio.create_subprocess_exec(
                self.settings.docker_executable,
                "rm",
                "-f",
                name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await cleanup.wait()
            if process.returncode is None:
                process.kill()
                await process.wait()
            result = {
                "status": "COMPLETED",
                "exit_code": None,
                "output": output[:100_000].decode(errors="replace"),
                "plan_hash": plan_hash,
                "recipe": plan["recipe"],
                "verified": False,
                "error": "CANCELLED" if isinstance(exc, asyncio.CancelledError) else type(exc).__name__,
            }
            if isinstance(exc, asyncio.CancelledError):
                with self.store.connect() as db:
                    db.execute(
                        "UPDATE executions SET status='CANCELLED',result=? WHERE job=? AND plan_hash=?",
                        (json.dumps(result), job, plan_hash),
                    )
                raise
        with self.store.connect() as db:
            db.execute(
                "UPDATE executions SET status='COMPLETED',result=? WHERE job=? AND plan_hash=?",
                (json.dumps(result), job, plan_hash),
            )
        await docker_capture(self.settings.docker_executable, "rm", name, timeout=5)
        return result
