"""Compact binary session logging with a separate writer process."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import multiprocessing
from multiprocessing.context import BaseContext
from pathlib import Path
import os
from queue import Empty, Full
import struct
import time
from typing import BinaryIO, Iterator


MAGIC = b"MTBTLOG\0"
FORMAT_VERSION = 1
HEADER_STRUCT = struct.Struct("<8sHHHHqdIdddddd")
RECORD_STRUCT = struct.Struct("<qii")


class BinaryLogError(RuntimeError):
    """Base error for binary telemetry logging."""


class BinaryLogQueueFull(BinaryLogError):
    """Raised instead of silently dropping samples when the writer queue is full."""


@dataclass(frozen=True)
class BinaryLogHeader:
    """Metadata required to interpret and calibrate one binary session."""

    session_start_utc_ns: int
    target_hz: float
    block_records: int
    shock_v_zero: float
    shock_v_full: float
    fork_v_zero: float
    fork_v_full: float
    shock_travel_mm_max: float
    fork_travel_mm_max: float
    flags: int = 0

    @classmethod
    def from_session(
        cls,
        session_start_utc: datetime,
        target_hz: float,
        block_records: int,
        shock_v_zero: float,
        shock_v_full: float,
        fork_v_zero: float,
        fork_v_full: float,
        shock_travel_mm_max: float,
        fork_travel_mm_max: float,
    ) -> "BinaryLogHeader":
        if session_start_utc.tzinfo is None:
            session_start_utc = session_start_utc.replace(tzinfo=timezone.utc)
        session_start_utc = session_start_utc.astimezone(timezone.utc)
        return cls(
            session_start_utc_ns=int(session_start_utc.timestamp() * 1_000_000_000),
            target_hz=target_hz,
            block_records=block_records,
            shock_v_zero=shock_v_zero,
            shock_v_full=shock_v_full,
            fork_v_zero=fork_v_zero,
            fork_v_full=fork_v_full,
            shock_travel_mm_max=shock_travel_mm_max,
            fork_travel_mm_max=fork_travel_mm_max,
        )

    @property
    def session_start_utc(self) -> datetime:
        return datetime.fromtimestamp(self.session_start_utc_ns / 1_000_000_000, tz=timezone.utc)

    def pack(self) -> bytes:
        if self.block_records < 1:
            raise ValueError("block_records must be at least 1")
        return HEADER_STRUCT.pack(
            MAGIC,
            FORMAT_VERSION,
            HEADER_STRUCT.size,
            RECORD_STRUCT.size,
            self.flags,
            self.session_start_utc_ns,
            self.target_hz,
            self.block_records,
            self.shock_v_zero,
            self.shock_v_full,
            self.fork_v_zero,
            self.fork_v_full,
            self.shock_travel_mm_max,
            self.fork_travel_mm_max,
        )

    @classmethod
    def unpack(cls, data: bytes) -> "BinaryLogHeader":
        if len(data) != HEADER_STRUCT.size:
            raise ValueError(f"Invalid binary log header size: {len(data)}")
        (
            magic,
            version,
            header_size,
            record_size,
            flags,
            session_start_utc_ns,
            target_hz,
            block_records,
            shock_v_zero,
            shock_v_full,
            fork_v_zero,
            fork_v_full,
            shock_travel_mm_max,
            fork_travel_mm_max,
        ) = HEADER_STRUCT.unpack(data)
        if magic != MAGIC:
            raise ValueError("Input is not an MTB telemetry binary log")
        if version != FORMAT_VERSION:
            raise ValueError(f"Unsupported binary log version: {version}")
        if header_size != HEADER_STRUCT.size or record_size != RECORD_STRUCT.size:
            raise ValueError("Binary log uses incompatible header or record sizes")
        return cls(
            session_start_utc_ns=session_start_utc_ns,
            target_hz=target_hz,
            block_records=block_records,
            shock_v_zero=shock_v_zero,
            shock_v_full=shock_v_full,
            fork_v_zero=fork_v_zero,
            fork_v_full=fork_v_full,
            shock_travel_mm_max=shock_travel_mm_max,
            fork_travel_mm_max=fork_travel_mm_max,
            flags=flags,
        )


@dataclass(frozen=True)
class BinaryLogRecord:
    """One synchronized shock/fork sample."""

    offset_ns: int
    shock_raw: int
    fork_raw: int


def read_header(handle: BinaryIO) -> BinaryLogHeader:
    """Read and validate a binary telemetry header."""
    data = handle.read(HEADER_STRUCT.size)
    if len(data) != HEADER_STRUCT.size:
        raise ValueError("Binary log is truncated before the complete header")
    return BinaryLogHeader.unpack(data)


def iter_records(handle: BinaryIO) -> Iterator[BinaryLogRecord]:
    """Yield complete records, ignoring a trailing partial record after power loss."""
    while True:
        data = handle.read(RECORD_STRUCT.size)
        if not data:
            return
        if len(data) != RECORD_STRUCT.size:
            return
        yield BinaryLogRecord(*RECORD_STRUCT.unpack(data))


def read_binary_log(path: Path) -> tuple[BinaryLogHeader, list[BinaryLogRecord]]:
    """Read one complete binary session into memory."""
    with path.open("rb") as handle:
        header = read_header(handle)
        return header, list(iter_records(handle))


def _writer_process(
    path: str,
    packed_header: bytes,
    data_queue: multiprocessing.Queue,
    result_queue: multiprocessing.Queue,
    fsync_interval_s: float,
    writer_cpu: int | None,
) -> None:
    blocks_written = 0
    bytes_written = 0
    fsync_count = 0
    writer_cpu_applied: int | None = None
    try:
        if writer_cpu is not None and hasattr(os, "sched_setaffinity"):
            os.sched_setaffinity(0, {writer_cpu})
            writer_cpu_applied = writer_cpu
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("wb", buffering=1024 * 1024) as handle:
            handle.write(packed_header)
            bytes_written += len(packed_header)
            last_sync = time.monotonic()
            while True:
                block = data_queue.get()
                if block is None:
                    break
                handle.write(block)
                blocks_written += 1
                bytes_written += len(block)
                if fsync_interval_s > 0 and (time.monotonic() - last_sync) >= fsync_interval_s:
                    handle.flush()
                    os.fsync(handle.fileno())
                    fsync_count += 1
                    last_sync = time.monotonic()
            handle.flush()
            os.fsync(handle.fileno())
            fsync_count += 1
        result_queue.put(
            {
                "ok": True,
                "blocks_written": blocks_written,
                "bytes_written": bytes_written,
                "fsync_count": fsync_count,
                "writer_cpu": writer_cpu_applied,
            }
        )
    except BaseException as exc:
        result_queue.put(
            {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "blocks_written": blocks_written,
                "bytes_written": bytes_written,
                "fsync_count": fsync_count,
                "writer_cpu": writer_cpu_applied,
            }
        )


class BinarySessionWriter:
    """Block records in the producer and persist them in a spawned process."""

    def __init__(
        self,
        path: Path,
        header: BinaryLogHeader,
        queue_blocks: int = 16,
        enqueue_timeout_s: float = 0.25,
        fsync_interval_s: float = 2.0,
        ack_timeout_s: float = 10.0,
        writer_cpu: int | None = None,
        context: BaseContext | None = None,
    ) -> None:
        if queue_blocks < 1:
            raise ValueError("queue_blocks must be at least 1")
        if enqueue_timeout_s <= 0:
            raise ValueError("enqueue_timeout_s must be > 0")
        self.path = path
        self.header = header
        self.enqueue_timeout_s = enqueue_timeout_s
        self.ack_timeout_s = ack_timeout_s
        if context is None:
            start_method = "fork" if "fork" in multiprocessing.get_all_start_methods() else "spawn"
            context = multiprocessing.get_context(start_method)
        self._context = context
        self._data_queue = self._context.Queue(maxsize=queue_blocks)
        self._result_queue = self._context.Queue(maxsize=1)
        self._block = bytearray(RECORD_STRUCT.size * header.block_records)
        self._block_count = 0
        self._closed = False
        self.blocks_enqueued = 0
        self.records_enqueued = 0
        self.enqueue_blocked_count = 0
        self.enqueue_timeout_count = 0
        self.queue_max_blocks_seen = 0
        self._process = self._context.Process(
            target=_writer_process,
            args=(
                str(path),
                header.pack(),
                self._data_queue,
                self._result_queue,
                fsync_interval_s,
                writer_cpu,
            ),
            name="mtb-binary-writer",
        )
        self._process.start()

    def append(self, offset_ns: int, shock_raw: int, fork_raw: int) -> None:
        if self._closed:
            raise BinaryLogError("Cannot append to a closed binary session")
        RECORD_STRUCT.pack_into(
            self._block,
            self._block_count * RECORD_STRUCT.size,
            offset_ns,
            shock_raw,
            fork_raw,
        )
        self._block_count += 1
        if self._block_count == self.header.block_records:
            self._enqueue_current_block()

    def _enqueue_current_block(self, timeout_s: float | None = None) -> None:
        if self._block_count == 0:
            return
        payload = bytes(self._block[: self._block_count * RECORD_STRUCT.size])
        started = time.monotonic()
        try:
            self._data_queue.put(
                payload,
                timeout=self.enqueue_timeout_s if timeout_s is None else timeout_s,
            )
        except Full as exc:
            self.enqueue_timeout_count += 1
            raise BinaryLogQueueFull(
                "Binary writer queue stayed full; session stopped without silent sample loss"
            ) from exc
        if (time.monotonic() - started) > 0.001:
            self.enqueue_blocked_count += 1
        self.blocks_enqueued += 1
        self.records_enqueued += self._block_count
        try:
            self.queue_max_blocks_seen = max(self.queue_max_blocks_seen, self._data_queue.qsize())
        except (NotImplementedError, OSError):
            pass
        self._block_count = 0

    def close(self) -> dict[str, object]:
        """Drain all records, fsync the file, and return writer metrics."""
        if self._closed:
            raise BinaryLogError("Binary session writer is already closed")
        self._closed = True
        close_started = time.monotonic()
        try:
            self._enqueue_current_block(timeout_s=self.ack_timeout_s)
            try:
                self._data_queue.put(None, timeout=self.ack_timeout_s)
            except Full as exc:
                raise BinaryLogError("Timed out sending stop command to binary writer") from exc
            try:
                result = self._result_queue.get(timeout=self.ack_timeout_s)
            except Empty as exc:
                raise BinaryLogError("Timed out waiting for binary writer acknowledgement") from exc
            self._process.join(timeout=self.ack_timeout_s)
            if self._process.is_alive():
                self._process.terminate()
                self._process.join(timeout=1.0)
                raise BinaryLogError("Binary writer did not exit after acknowledgement")
            if not result.get("ok"):
                raise BinaryLogError(f"Binary writer failed: {result.get('error', 'unknown error')}")
            return {
                **result,
                "records_enqueued": self.records_enqueued,
                "blocks_enqueued": self.blocks_enqueued,
                "queue_max_blocks_seen": self.queue_max_blocks_seen,
                "enqueue_blocked_count": self.enqueue_blocked_count,
                "enqueue_timeout_count": self.enqueue_timeout_count,
                "writer_ack_latency_ms": round((time.monotonic() - close_started) * 1000.0, 3),
            }
        finally:
            if self._process.is_alive():
                self._process.terminate()
                self._process.join(timeout=1.0)
            self._data_queue.close()
            self._result_queue.close()

    def snapshot_stats(self) -> dict[str, int]:
        """Return lightweight runtime counters for UI/status reporting."""
        queue_blocks = 0
        try:
            queue_blocks = int(self._data_queue.qsize())
        except (NotImplementedError, OSError):
            queue_blocks = 0
        return {
            "queue_blocks": queue_blocks,
            "queue_max_blocks_seen": int(self.queue_max_blocks_seen),
            "enqueue_blocked_count": int(self.enqueue_blocked_count),
            "enqueue_timeout_count": int(self.enqueue_timeout_count),
        }
