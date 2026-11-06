"""Official Postgres storage with Windows-safe async dispatch.

Psycopg async rejects Windows Proactor, while Selector cannot spawn Docker.
Keep the app's loop unchanged: run official synchronous saver operations in a
bounded dedicated pool. On Linux use the official AsyncPostgresSaver directly.
No custom SQL schema or serialization is implemented here.
"""

import asyncio
import functools
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver


class ThreadedPostgresSaver(PostgresSaver):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="checkpoint-db")
        self._slots = asyncio.Semaphore(8)

    async def dispatch(self, function, *args, **kwargs):
        async with self._slots:
            return await asyncio.get_running_loop().run_in_executor(
                self._pool, functools.partial(function, *args, **kwargs)
            )

    async def aget_tuple(self, config):
        return await self.dispatch(self.get_tuple, config)

    async def alist(self, config, *, filter=None, before=None, limit=None):
        rows = await self.dispatch(
            lambda: list(self.list(config, filter=filter, before=before, limit=min(limit or 100, 100)))
        )
        for row in rows:
            yield row

    async def aput(self, config, checkpoint, metadata, new_versions):
        return await self.dispatch(self.put, config, checkpoint, metadata, new_versions)

    async def aput_writes(self, config, writes, task_id, task_path=""):
        await self.dispatch(self.put_writes, config, writes, task_id, task_path)

    async def adelete_thread(self, thread_id):
        await self.dispatch(self.delete_thread, thread_id)

    async def aget_delta_channel_history(self, config, *, channels):
        return await self.dispatch(self.get_delta_channel_history, config, channels=channels)


@asynccontextmanager
async def postgres_saver(url):
    if sys.platform != "win32":
        async with AsyncPostgresSaver.from_conn_string(url) as saver:
            await saver.setup()
            yield saver
        return
    manager = ThreadedPostgresSaver.from_conn_string(url)
    saver = await asyncio.to_thread(manager.__enter__)
    try:
        await saver.dispatch(saver.setup)
        yield saver
    finally:
        # Finish issued database work before closing its connection on shutdown.
        await asyncio.to_thread(saver._pool.shutdown, wait=True)
        await asyncio.to_thread(manager.__exit__, None, None, None)
