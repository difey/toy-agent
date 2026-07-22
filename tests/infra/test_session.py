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


# ── _collapse_mode_switches tests ─────────────────────────────────


_MODE_PLAN = "[Mode changed to Plan mode. You can now only discuss requirements and write/edit .md files. Do NOT write any source code or run shell commands.]"
_MODE_BUILD = "[Mode changed to Build mode. All tools are now available. You can implement code, run commands, and make changes.]"


def _plan_msg():
    from nano_claude.core.message import UserMessage
    return UserMessage(content=_MODE_PLAN)


def _build_msg():
    from nano_claude.core.message import UserMessage
    return UserMessage(content=_MODE_BUILD)


def _user_msg(text: str = "hello"):
    from nano_claude.core.message import UserMessage
    return UserMessage(content=text)


def test_collapse_mode_switches_noop():
    """无连续模式切换时不移除任何消息."""
    s = Session()
    s.messages.append(_user_msg())
    s.messages.append(_plan_msg())
    s.messages.append(_user_msg("how are you"))
    result = s._collapse_mode_switches()
    assert result == 0
    assert len(s.messages) == 3


def test_collapse_mode_switches_single():
    """只有 1 条模式切换时不操作."""
    s = Session()
    s.messages.append(_user_msg())
    s.messages.append(_plan_msg())
    result = s._collapse_mode_switches()
    assert result == 0
    assert len(s.messages) == 2


def test_collapse_mode_switches_basic():
    """连续 3 条模式切换只保留最后 1 条."""
    s = Session()
    s.messages.append(_user_msg())
    s.messages.append(_plan_msg())      # 第 1 次切换
    s.messages.append(_build_msg())     # 第 2 次切换
    s.messages.append(_plan_msg())      # 第 3 次切换（应保留）
    result = s._collapse_mode_switches()
    assert result == 2
    assert len(s.messages) == 2  # user_msg + 最后一条 plan
    assert s.messages[1].content == _MODE_PLAN


def test_collapse_mode_switches_alternating():
    """plan→build→plan→build 交替切换，保留最后一条 build."""
    s = Session()
    s.messages.append(_user_msg())
    s.messages.append(_plan_msg())      # 第 1 次切换
    s.messages.append(_build_msg())     # 第 2 次切换
    s.messages.append(_plan_msg())      # 第 3 次切换
    s.messages.append(_build_msg())     # 第 4 次切换（应保留）
    result = s._collapse_mode_switches()
    assert result == 3
    assert len(s.messages) == 2  # user_msg + 最后一条 build
    assert s.messages[1].content == _MODE_BUILD


def test_collapse_mode_switches_with_normal_messages():
    """模式切换消息之间有正常消息时不折叠."""
    s = Session()
    s.messages.append(_user_msg())
    s.messages.append(_plan_msg())      # 模式切换
    s.messages.append(_user_msg("normal message"))  # 正常消息
    s.messages.append(_build_msg())     # 模式切换
    result = s._collapse_mode_switches()
    assert result == 0  # 两条模式切换不连续，不移除
    assert len(s.messages) == 4


def test_collapse_mode_switches_all_mode_switches():
    """所有消息都是模式切换时只保留最后一条."""
    s = Session()
    s.messages.append(_plan_msg())
    s.messages.append(_build_msg())
    s.messages.append(_plan_msg())
    s.messages.append(_build_msg())
    result = s._collapse_mode_switches()
    assert result == 3
    assert len(s.messages) == 1
    assert s.messages[0].content == _MODE_BUILD


@pytest.mark.asyncio
async def test_collapse_mode_switches_add_user_message():
    """add_user_message 添加模式切换消息时自动折叠."""
    s = Session()
    await s.add_user_message("hello")
    # 直接 append 模式切换消息模拟历史累积
    s.messages.append(_plan_msg())
    s.messages.append(_build_msg())
    assert len(s.messages) == 3
    # 通过 add_user_message 添加另一条模式切换消息，触发自动折叠
    removed = await s.add_user_message(_MODE_PLAN)
    assert removed == 2  # 前 2 条模式切换被折叠
    assert len(s.messages) == 2  # 原来的 user_msg + 最后一条 plan
    assert s.messages[1].content == _MODE_PLAN


@pytest.mark.asyncio
async def test_collapse_mode_switches_add_message():
    """add_message 添加模式切换消息时自动折叠."""
    s = Session()
    await s.add_user_message("hello")
    # 直接 append 模式切换消息模拟历史累积
    s.messages.append(_plan_msg())
    s.messages.append(_build_msg())
    assert len(s.messages) == 3
    # 通过 add_message 添加另一条模式切换消息，触发自动折叠
    removed = await s.add_message(_plan_msg())
    assert removed == 2  # 前 2 条模式切换被折叠
    assert len(s.messages) == 2  # user_msg + 最后一条 plan



