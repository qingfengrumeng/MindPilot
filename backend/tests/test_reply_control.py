import asyncio

import pytest
from fastapi import HTTPException

from app.services.reply_control import register_reply, control_reply, controlled_reply


def test_pause_resume_keeps_same_iterator_and_closes_it():
    async def check():
        consumed = []
        closed = []
        def source():
            try:
                for text in ('first', 'second', 'done'):
                    consumed.append(text)
                    yield text
            finally:
                closed.append(True)
        control = register_reply('pause-test', 'alice', 'conversation')
        output = controlled_reply(source(), 'pause-test', control)
        assert await anext(output) == 'first'
        control_reply('pause-test', 'alice', 'conversation', 'pause')
        pending = asyncio.create_task(anext(output))
        await asyncio.sleep(.03)
        assert not pending.done()
        assert consumed == ['first']
        control_reply('pause-test', 'alice', 'conversation', 'resume')
        assert await pending == 'second'
        assert await anext(output) == 'done'
        with pytest.raises(StopAsyncIteration):
            await anext(output)
        assert closed == [True]
        with pytest.raises(HTTPException) as error:
            control_reply('pause-test', 'alice', 'conversation', 'resume')
        assert error.value.status_code == 404
    asyncio.run(check())


def test_cancel_during_pause_and_owner_isolation():
    async def check():
        control = register_reply('cancel-test', 'alice', 'conversation')
        output = controlled_reply(iter_source(), 'cancel-test', control)
        assert await anext(output) == 'first'
        for owner, conversation in [('bob', 'conversation'), ('alice', 'other')]:
            with pytest.raises(HTTPException) as error:
                control_reply('cancel-test', owner, conversation, 'cancel')
            assert error.value.status_code == 404
        control_reply('cancel-test', 'alice', 'conversation', 'pause')
        pending = asyncio.create_task(anext(output))
        await asyncio.sleep(.02)
        control_reply('cancel-test', 'alice', 'conversation', 'cancel')
        with pytest.raises(StopAsyncIteration):
            await pending
    asyncio.run(check())


def iter_source():
    yield 'first'
    yield 'second'
