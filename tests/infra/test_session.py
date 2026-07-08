import pytest

from nano_claude.infra.session import Session, estimate_tokens, message_tokens


def test_estimate_tokens():
    assert estimate_tokens("hello") == 1
    assert estimate_tokens("a" * 100) == 25


def test_session_create():
    s = Session(system_prompt="You are a helpful assistant.")
    assert len(s.messages) == 1
    assert s.messages[0].content == "You are a helpful assistant."


@pytest.mark.asyncio
async def test_session_add_messages():
    s = Session()
    await s.add_user_message("hello")
    assert len(s.messages) == 1
    assert s.messages[0].content == "hello"


@pytest.mark.asyncio
async def test_session_total_tokens():
    s = Session()
    await s.add_user_message("hello world!")
    assert s.total_tokens() > 0


@pytest.mark.asyncio
async def test_session_compact():
    s = Session(max_tokens=100)
    await s.add_user_message("first message that takes some tokens " * 5)
    await s.add_user_message("second message also taking tokens " * 5)
    assert len(s.messages) == 2

    s.max_tokens = 1
    await s._compact()
    assert len(s.messages) == 1


@pytest.mark.asyncio
async def test_session_save_load(tmp_path):
    s = Session(system_prompt="test")
    await s.add_user_message("hello")
    p = str(tmp_path / "session.json")
    s.save(p)

    s2 = Session.load(p)
    assert len(s2.messages) == 2
    assert s2.messages[0].content == "test"
    assert s2.messages[1].content == "hello"


def test_session_title_from_first_message():
    s = Session()
    assert s.title == ""
    coro = s.add_user_message("write a python script for sorting")
    import asyncio
    asyncio.run(coro)
    assert s.title == "write a python script for sorting"


def test_session_title_truncated():
    s = Session()
    long_msg = "a" * 100
    coro = s.add_user_message(long_msg)
    import asyncio
    asyncio.run(coro)
    assert s.title == "a" * 37 + "..."
    assert len(s.title) == 40


def test_session_title_only_first_message():
    s = Session()
    coro1 = s.add_user_message("first task")
    import asyncio
    asyncio.run(coro1)
    assert s.title == "first task"
    coro2 = s.add_user_message("second task")
    asyncio.run(coro2)
    assert s.title == "first task"  # title unchanged


def test_session_title_from_multiline():
    s = Session()
    coro = s.add_user_message("\n\n  second line  \nthird line")
    import asyncio
    asyncio.run(coro)
    assert s.title == "second line"



