"""Recovery contracts shared by HTTP approval and the background reconciler."""

import asyncio

import httpx


async def drain_issued(future):
    """Do not release an execution lock while issued database/graph work is still running."""
    while not future.done():
        try:
            await asyncio.shield(future)
        except asyncio.CancelledError:
            continue
        except Exception:
            break
    if not future.cancelled():
        future.exception()  # Observe a failed cleanup without masking the original cancellation.


async def invoke_checkpointed(graph, graph_input, config):
    async def invoke():
        try:
            return await graph.ainvoke(graph_input, config)
        except asyncio.CancelledError as error:
            # LangGraph may attach its asynchronous exit/flush task to cancellation.
            for item in error.args:
                if isinstance(item, asyncio.Future):
                    await drain_issued(item)
            raise

    task = asyncio.create_task(invoke())
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        task.cancel()
        await drain_issued(task)
        raise


def graph_config(job: dict) -> dict:
    generation = job.get("generation", 0)
    # Preserve existing generation-zero checkpoints after an application upgrade.
    thread = job["id"] if generation == 0 else f"{job['id']}:generation:{generation}"
    return {"configurable": {"thread_id": thread}, "recursion_limit": 80}


class ApprovalRecovery:
    def __init__(self, store, control):
        self.store, self.control = store, control

    async def deliver(self, job: str, plan_hash: str, nonce: str = "") -> bool:
        try:
            owned = await self.control.internal("/" + job)
            if (
                owned["status"] == "CANCELLED"
                or (owned.get("approvalHash") and owned["approvalHash"] != plan_hash)
                or (owned["status"] != "AWAITING_APPROVAL" and not owned.get("approvalHash"))
            ):
                self.store.approvals.delivered(job, plan_hash, nonce, "SUPERSEDED")
                return False
            await self.control.internal(f"/{job}/resume", {"planHash": plan_hash})
        except (httpx.HTTPError, RuntimeError):
            return False  # Retain the durable delivery; never undo a possibly delivered decision.
        self.store.approvals.delivered(job, plan_hash, nonce)
        return True

    async def reconcile(self):
        for item in self.store.approvals.pending():
            await self.deliver(item["job"], item["plan_hash"], item["nonce"])
