import asyncio

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .objects import PART_SIZE


def uploads_router(app, control, auth):
    router = APIRouter()

    def objects():
        backend = getattr(app.state, "objects", None)
        if backend is None:
            raise HTTPException(503, "对象存储未启用")
        return backend

    async def call(function, *args):
        try:
            return await asyncio.to_thread(function, *args)
        except PermissionError:
            raise HTTPException(403, "无此资料访问权限") from None
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        except (BotoCoreError, ClientError):
            raise HTTPException(503, "对象存储暂不可用；上传进度会保留") from None

    class Begin(BaseModel):
        workspace: str = Field(min_length=1, max_length=36)
        sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
        size: int = Field(ge=1, le=12_000_000)

    @router.post("/uploads")
    async def begin(body: Begin, principal=Depends(auth)):
        workspaces = await control.user(principal[1], "/api/agent/workspaces")
        if body.workspace not in {w["id"] for w in workspaces}:
            raise HTTPException(403, "无此工作区访问权限")
        return await call(objects().begin, principal[0], body.workspace, body.sha256, body.size)

    @router.get("/uploads/{upload}")
    async def status(upload: str, principal=Depends(auth)):
        return await call(objects().status, principal[0], upload)

    @router.put("/uploads/{upload}/parts/{number}")
    async def part(
        upload: str, number: int, request: Request, x_content_sha256: str = Header(), principal=Depends(auth)
    ):
        data = bytearray()
        async for block in request.stream():
            data.extend(block)
            if len(data) > PART_SIZE:
                raise HTTPException(413, "分片过大")
        return await call(objects().part, principal[0], upload, number, bytes(data), x_content_sha256)

    @router.post("/uploads/{upload}/complete")
    async def complete(upload: str, principal=Depends(auth)):
        return await call(objects().complete, principal[0], upload)

    @router.get("/uploads/{upload}/download")
    async def download(upload: str, principal=Depends(auth)):
        data = await call(objects().download, principal[0], upload)
        return Response(
            data,
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="verified-archive.zip"'},
        )

    @router.get("/uploads/{upload}/content")
    async def content(upload: str, principal=Depends(auth)):
        # A bounded JSON transport for in-app clients; binary download remains available.
        # Both paths use exactly the same owner/checksum enforcement.
        import base64
        import hashlib

        data = await call(objects().download, principal[0], upload)
        return {
            "encoding": "base64",
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "content": base64.b64encode(data).decode("ascii"),
        }

    return router
