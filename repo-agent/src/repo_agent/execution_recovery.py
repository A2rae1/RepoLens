import asyncio
import json


async def docker_capture(executable: str, *args, timeout=35):
    process = await asyncio.create_subprocess_exec(
        executable, *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        out, err = await asyncio.wait_for(process.communicate(), timeout)
    except BaseException:
        if process.returncode is None:
            process.kill()
            await process.wait()
        raise
    return process.returncode, out[:140_000], err[:140_000]


async def recover_execution(cfg, store, job: str, plan_hash: str, record: str):
    metadata = json.loads(record or "{}")
    name = metadata.get("container_name")
    if not name or not name.startswith("repo-verify-"):
        raise RuntimeError("EXECUTION_OUTCOME_UNKNOWN_MANUAL_REVIEW_REQUIRED")
    code, out, _ = await docker_capture(cfg.docker_executable, "inspect", name, timeout=5)
    if code != 0:
        raise RuntimeError("EXECUTION_CONTAINER_MISSING_MANUAL_REVIEW_REQUIRED")
    info = json.loads(out)[0]
    labels = info["Config"].get("Labels", {})
    if labels.get("repolens.job") != job or labels.get("repolens.plan") != plan_hash:
        raise PermissionError("Execution container identity mismatch")
    if info["State"]["Running"]:
        try:
            await docker_capture(cfg.docker_executable, "wait", name, timeout=35)
        except TimeoutError:
            await docker_capture(cfg.docker_executable, "kill", name, timeout=5)
        code, out, _ = await docker_capture(cfg.docker_executable, "inspect", name, timeout=5)
        if code != 0:
            raise RuntimeError("Execution state unavailable")
        info = json.loads(out)[0]
    _, logs, stderr = await docker_capture(cfg.docker_executable, "logs", name, timeout=5)
    logs = logs + stderr
    result = {
        "status": "COMPLETED",
        "exit_code": info["State"]["ExitCode"],
        "output": logs[:100_000].decode(errors="replace"),
        "output_truncated": len(logs) > 100_000,
        "verified": info["State"]["ExitCode"] == 0,
        "recipe": metadata["recipe"],
        "plan_hash": plan_hash,
        "recovered": True,
    }
    with store.connect() as db:
        db.execute(
            "UPDATE executions SET status='COMPLETED',result=? WHERE job=? AND plan_hash=?",
            (json.dumps(result), job, plan_hash),
        )
    await docker_capture(cfg.docker_executable, "rm", name, timeout=5)
    return result
