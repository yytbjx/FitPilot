"""LangGraph 全状态检查点：Postgres 持久化 + 每步提交。"""



from __future__ import annotations



import random

from collections.abc import AsyncIterator, Iterator, Sequence

from typing import Any



from langgraph.checkpoint.base import (

    WRITES_IDX_MAP,

    BaseCheckpointSaver,

    Checkpoint,

    CheckpointMetadata,

    CheckpointTuple,

    get_checkpoint_id,

    get_checkpoint_metadata,

)

from sqlalchemy import delete, select

from sqlalchemy.dialects.postgresql import insert as pg_insert

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker



from app.models.langgraph_checkpoint import LGChannelBlob, LGCheckpoint, LGCheckpointWrite





class PostgresCheckpointSaver(BaseCheckpointSaver):

    """完整 LangGraph 检查点协议：channel blobs + pending writes + 父链。"""



    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:

        super().__init__()

        self._factory = session_factory



    async def _load_blobs(

        self,

        db: AsyncSession,

        thread_id: str,

        checkpoint_ns: str,

        versions: dict[str, str],

    ) -> dict[str, Any]:

        channel_values: dict[str, Any] = {}

        for channel, version in versions.items():

            row = await db.scalar(

                select(LGChannelBlob).where(

                    LGChannelBlob.thread_id == thread_id,

                    LGChannelBlob.checkpoint_ns == checkpoint_ns,

                    LGChannelBlob.channel == channel,

                    LGChannelBlob.version == version,

                )

            )

            if row:

                channel_values[channel] = self.serde.loads_typed((row.blob_type, row.blob_data))

        return channel_values



    async def _load_writes(

        self,

        db: AsyncSession,

        thread_id: str,

        checkpoint_ns: str,

        checkpoint_id: str,

    ) -> list[tuple[str, str, Any]]:

        rows = (

            await db.scalars(

                select(LGCheckpointWrite)

                .where(

                    LGCheckpointWrite.thread_id == thread_id,

                    LGCheckpointWrite.checkpoint_ns == checkpoint_ns,

                    LGCheckpointWrite.checkpoint_id == checkpoint_id,

                )

                .order_by(LGCheckpointWrite.write_idx)

            )

        ).all()

        return [

            (r.task_id, r.channel, self.serde.loads_typed((r.blob_type, r.blob_data)))

            for r in rows

        ]



    async def _get_saved(

        self,

        db: AsyncSession,

        thread_id: str,

        checkpoint_ns: str,

        checkpoint_id: str,

    ) -> LGCheckpoint | None:

        return await db.scalar(

            select(LGCheckpoint).where(

                LGCheckpoint.thread_id == thread_id,

                LGCheckpoint.checkpoint_ns == checkpoint_ns,

                LGCheckpoint.checkpoint_id == checkpoint_id,

            )

        )



    async def _build_tuple(

        self,

        db: AsyncSession,

        *,

        config: dict[str, Any],

        row: LGCheckpoint,

    ) -> CheckpointTuple:

        thread_id = row.thread_id

        checkpoint_ns = row.checkpoint_ns

        checkpoint_id = row.checkpoint_id

        checkpoint_: Checkpoint = self.serde.loads_typed(

            (row.checkpoint_type, row.checkpoint_data)

        )

        metadata = self.serde.loads_typed((row.metadata_type, row.metadata_data))

        writes = await self._load_writes(db, thread_id, checkpoint_ns, checkpoint_id)

        return CheckpointTuple(

            config={

                "configurable": {

                    "thread_id": thread_id,

                    "checkpoint_ns": checkpoint_ns,

                    "checkpoint_id": checkpoint_id,

                }

            },

            checkpoint={

                **checkpoint_,

                "channel_values": await self._load_blobs(

                    db, thread_id, checkpoint_ns, checkpoint_["channel_versions"]

                ),

            },

            metadata=metadata,

            pending_writes=writes,

            parent_config=(

                {

                    "configurable": {

                        "thread_id": thread_id,

                        "checkpoint_ns": checkpoint_ns,

                        "checkpoint_id": row.parent_checkpoint_id,

                    }

                }

                if row.parent_checkpoint_id

                else None

            ),

        )



    async def aget_tuple(self, config: dict[str, Any]) -> CheckpointTuple | None:

        thread_id = config.get("configurable", {}).get("thread_id")

        if not thread_id:

            return None

        checkpoint_ns = config.get("configurable", {}).get("checkpoint_ns", "")

        async with self._factory() as db:

            if checkpoint_id := get_checkpoint_id(config):

                row = await self._get_saved(db, thread_id, checkpoint_ns, checkpoint_id)

                if not row:

                    return None

                return await self._build_tuple(db, config=config, row=row)



            row = await db.scalar(

                select(LGCheckpoint)

                .where(

                    LGCheckpoint.thread_id == thread_id,

                    LGCheckpoint.checkpoint_ns == checkpoint_ns,

                )

                .order_by(LGCheckpoint.checkpoint_id.desc())

                .limit(1)

            )

            if not row:

                return None

            return await self._build_tuple(db, config=config, row=row)



    async def alist(

        self,

        config: dict[str, Any] | None,

        *,

        filter: dict[str, Any] | None = None,

        before: dict[str, Any] | None = None,

        limit: int | None = None,

    ) -> AsyncIterator[CheckpointTuple]:

        thread_id = (config or {}).get("configurable", {}).get("thread_id")

        if not thread_id:

            return

        checkpoint_ns = (config or {}).get("configurable", {}).get("checkpoint_ns", "")

        before_id = get_checkpoint_id(before) if before else None

        async with self._factory() as db:

            stmt = (

                select(LGCheckpoint)

                .where(

                    LGCheckpoint.thread_id == thread_id,

                    LGCheckpoint.checkpoint_ns == checkpoint_ns,

                )

                .order_by(LGCheckpoint.checkpoint_id.desc())

            )

            if before_id:

                stmt = stmt.where(LGCheckpoint.checkpoint_id < before_id)

            if limit:

                stmt = stmt.limit(limit)

            rows = list((await db.scalars(stmt)).all())

            for row in rows:

                metadata = self.serde.loads_typed((row.metadata_type, row.metadata_data))

                if filter and not all(

                    metadata.get(k) == v for k, v in filter.items()

                ):

                    continue

                yield await self._build_tuple(db, config=config or {}, row=row)



    async def aput(

        self,

        config: dict[str, Any],

        checkpoint: Checkpoint,

        metadata: CheckpointMetadata,

        new_versions: dict[str, Any],

    ) -> dict[str, Any]:

        thread_id = config["configurable"]["thread_id"]

        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")

        c = checkpoint.copy()

        values: dict[str, Any] = c.pop("channel_values")  # type: ignore[misc]

        parent_checkpoint_id = config["configurable"].get("checkpoint_id")

        ckpt_type, ckpt_data = self.serde.dumps_typed(c)

        meta_type, meta_data = self.serde.dumps_typed(

            get_checkpoint_metadata(config, metadata)

        )



        async with self._factory() as db:

            for channel, version in new_versions.items():

                blob_type, blob_data = (

                    self.serde.dumps_typed(values[channel])

                    if channel in values

                    else ("empty", b"")

                )

                stmt = pg_insert(LGChannelBlob).values(

                    thread_id=thread_id,

                    checkpoint_ns=checkpoint_ns,

                    channel=channel,

                    version=version,

                    blob_type=blob_type,

                    blob_data=blob_data,

                )

                stmt = stmt.on_conflict_do_update(

                    index_elements=["thread_id", "checkpoint_ns", "channel", "version"],

                    set_={"blob_type": blob_type, "blob_data": blob_data},

                )

                await db.execute(stmt)



            db.add(

                LGCheckpoint(

                    thread_id=thread_id,

                    checkpoint_ns=checkpoint_ns,

                    checkpoint_id=checkpoint["id"],

                    parent_checkpoint_id=parent_checkpoint_id,

                    checkpoint_type=ckpt_type,

                    checkpoint_data=ckpt_data,

                    metadata_type=meta_type,

                    metadata_data=meta_data,

                )

            )

            await db.commit()



        return {

            "configurable": {

                "thread_id": thread_id,

                "checkpoint_ns": checkpoint_ns,

                "checkpoint_id": checkpoint["id"],

            }

        }



    async def aput_writes(

        self,

        config: dict[str, Any],

        writes: Sequence[tuple[str, Any]],

        task_id: str,

        task_path: str = "",

    ) -> None:

        thread_id = config["configurable"]["thread_id"]

        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")

        checkpoint_id = config["configurable"]["checkpoint_id"]

        if not checkpoint_id:

            return



        async with self._factory() as db:

            existing = {

                (r.task_id, r.write_idx)

                for r in (

                    await db.scalars(

                        select(LGCheckpointWrite).where(

                            LGCheckpointWrite.thread_id == thread_id,

                            LGCheckpointWrite.checkpoint_ns == checkpoint_ns,

                            LGCheckpointWrite.checkpoint_id == checkpoint_id,

                        )

                    )

                ).all()

            }

            for idx, (channel, value) in enumerate(writes):

                inner_idx = WRITES_IDX_MAP.get(channel, idx)

                if inner_idx >= 0 and (task_id, inner_idx) in existing:

                    continue

                blob_type, blob_data = self.serde.dumps_typed(value)

                db.add(

                    LGCheckpointWrite(

                        thread_id=thread_id,

                        checkpoint_ns=checkpoint_ns,

                        checkpoint_id=checkpoint_id,

                        task_id=task_id,

                        write_idx=inner_idx,

                        channel=channel,

                        blob_type=blob_type,

                        blob_data=blob_data,

                        task_path=task_path or "",

                    )

                )

            await db.commit()



    async def adelete_thread(self, thread_id: str) -> None:

        async with self._factory() as db:

            await db.execute(delete(LGCheckpointWrite).where(LGCheckpointWrite.thread_id == thread_id))

            await db.execute(delete(LGChannelBlob).where(LGChannelBlob.thread_id == thread_id))

            await db.execute(delete(LGCheckpoint).where(LGCheckpoint.thread_id == thread_id))

            await db.commit()



    def get_tuple(self, config: dict[str, Any]) -> CheckpointTuple | None:

        raise NotImplementedError("use async")



    def list(

        self,

        config: dict[str, Any] | None,

        *,

        filter: dict[str, Any] | None = None,

        before: dict[str, Any] | None = None,

        limit: int | None = None,

    ) -> Iterator[CheckpointTuple]:

        raise NotImplementedError("use async")



    def put(

        self,

        config: dict[str, Any],

        checkpoint: Checkpoint,

        metadata: CheckpointMetadata,

        new_versions: dict[str, Any],

    ) -> dict[str, Any]:

        raise NotImplementedError("use async")



    def get_next_version(self, current: str | None, channel: None) -> str:

        if current is None:

            current_v = 0

        elif isinstance(current, int):

            current_v = current

        else:

            current_v = int(str(current).split(".")[0])

        return f"{current_v + 1:032}.{random.random():016}"





async def get_latest_checkpoint_info(

    session_factory: async_sessionmaker[AsyncSession],

    task_id: str,

) -> dict[str, Any] | None:

    """查询 thread 最新 LangGraph 检查点元信息（供 resume API）。"""

    async with session_factory() as db:

        row = await db.scalar(

            select(LGCheckpoint)

            .where(LGCheckpoint.thread_id == task_id)

            .order_by(LGCheckpoint.checkpoint_id.desc())

            .limit(1)

        )

        if not row:

            return None

        metadata = PostgresCheckpointSaver(session_factory).serde.loads_typed(

            (row.metadata_type, row.metadata_data)

        )

        return {

            "thread_id": row.thread_id,

            "checkpoint_id": row.checkpoint_id,

            "checkpoint_ns": row.checkpoint_ns,

            "parent_checkpoint_id": row.parent_checkpoint_id,

            "created_at": row.created_at.isoformat() if row.created_at else None,

            "metadata": metadata,

        }





async def load_latest_checkpoint_state(

    session_factory: async_sessionmaker[AsyncSession],

    task_id: str,

) -> dict[str, Any] | None:

    """从最新检查点提取 channel_values（兼容旧调用方）。"""

    saver = PostgresCheckpointSaver(session_factory)

    tup = await saver.aget_tuple({"configurable": {"thread_id": task_id}})

    if not tup:

        return None

    return dict(tup.checkpoint.get("channel_values") or {})


