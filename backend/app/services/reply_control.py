"""Account-scoped controls for a live reply; no prompts or keys are stored here."""
import asyncio
import threading

from fastapi import HTTPException
from starlette.concurrency import iterate_in_threadpool


class ReplyControl:
    def __init__(self, owner, conversation):
        self.owner = owner
        self.conversation = conversation
        self.ready = asyncio.Event()
        self.ready.set()
        self.cancelled = False

    def apply(self, action):
        if action == "pause":
            self.ready.clear()
        elif action == "resume":
            self.ready.set()
        else:
            self.cancelled = True
            self.ready.set()

    async def wait(self):
        try:
            await asyncio.wait_for(self.ready.wait(), timeout=1800)
        except TimeoutError:
            self.apply("cancel")
        return not self.cancelled


_controls = {}
_lock = threading.Lock()


def register_reply(stream_id, owner, conversation):
    control = ReplyControl(owner, conversation)
    with _lock:
        if stream_id in _controls:
            raise HTTPException(409, "回复标识正在使用")
        _controls[stream_id] = control
    return control


def control_reply(stream_id, owner, conversation, action):
    with _lock:
        control = _controls.get(stream_id)
    if not control or (control.owner, control.conversation) != (owner, conversation):
        raise HTTPException(404, "当前回复已结束或不存在")
    control.apply(action)


async def controlled_reply(generator, stream_id, control):
    iterator = iterate_in_threadpool(generator)
    try:
        while await control.wait():
            try:
                line = await iterator.__anext__()
            except StopAsyncIteration:
                break
            if not await control.wait():
                break
            yield line
    finally:
        control.apply("cancel")
        # A synchronous provider call already in flight finishes before its next
        # checkpoint. Closing here also closes the upstream SSE iterator.
        try:
            generator.close()
        except ValueError:
            # The disconnected client's worker is still in a blocking call.
            pass
        with _lock:
            if _controls.get(stream_id) is control:
                del _controls[stream_id]
