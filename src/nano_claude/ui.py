import asyncio
import os
import subprocess
import traceback

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition, has_focus
from prompt_toolkit.formatted_text import HTML, FormattedText
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.layout import Layout, HSplit, Window, FormattedTextControl, Float, FloatContainer
from prompt_toolkit.layout.controls import BufferControl
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.styles import Style

from nano_claude.agent import Agent
from nano_claude.message import ToolCall
from nano_claude.session import Session, list_sessions, save_current, session_info, session_path

_STYLE = Style.from_dict({
    "status": "bg:#222222 #ffffff",
    "input": "bg:#000000 #ffffff",
    "output": "bg:#000000 #cccccc",
    "prompt": "bold",
})

_COMMANDS = [
    "/help",
    "/clear",
    "/tokens",
    "/vscode",
    "/sessions",
    "/exit",
]


class SlashCompleter(Completer):
    def __init__(self, cwd: str):
        self.cwd = cwd

    def get_completions(self, document, complete_event):
        word = document.text_before_cursor
        for cmd in _COMMANDS:
            if cmd.startswith(word):
                yield Completion(cmd, start_position=-len(word))
        if word.startswith("/sessions "):
            yield Completion("/sessions new", start_position=-len(word))
            yield Completion("/sessions delete ", start_position=-len(word))
            for i, _ in enumerate(list_sessions(self.cwd), 1):
                yield Completion(f"/sessions {i}", start_position=-len(word))
        if word.startswith("/sessions delete "):
            yield Completion("/sessions delete all", start_position=-len(word))
            for i, _ in enumerate(list_sessions(self.cwd), 1):
                yield Completion(f"/sessions delete {i}", start_position=-len(word))


class InteractiveUI:
    """Persistent TUI for interactive mode with always-visible bottom toolbar."""

    def __init__(self, agent: Agent, cwd: str, session: Session, session_file_ref: list):
        self.agent = agent
        self.cwd = cwd
        self.session = session
        self.session_file_ref = session_file_ref

        self.output_buffer = Buffer(read_only=True)
        self.input_buffer = Buffer(
            completer=SlashCompleter(cwd),
            complete_while_typing=True,
            on_text_changed=self._on_input_changed,
        )

        self._permission_future: asyncio.Future | None = None
        self._question_future: asyncio.Future | None = None
        self._question_multiple: bool = False
        self._question_options: list[dict] = []
        self._question_option_map: dict[str, str] = {}
        self._question_custom_idx: int = 0

        # Session list overlay state
        self._session_files: list[str] = []
        self._session_infos: list[dict] = []
        self._session_selection: int = 0
        self._show_session_list: bool = False

        self._state = "INPUT"
        self._turn_count = 0

        self._build_ui()

    def _format_status(self) -> FormattedText:
        title = self.session.title or "new session"
        cwd_display = self.cwd
        if len(cwd_display) > 50:
            cwd_display = "..." + cwd_display[-47:]

        state_indicators = {
            "INPUT": "",
            "RUNNING": "  [🔄 AI running...]",
            "AWAITING_PERMISSION": "  [❓ Confirm (y/n)]",
            "AWAITING_QUESTION": "  [❓ Answer above]",
        }
        if self._show_session_list:
            state_text = "  [📋 Session list]"
        else:
            state_text = state_indicators.get(self._state, "")

        return HTML(
            f'<b> Session:</b> {title} '
            f'<b> CWD:</b> {cwd_display}'
            f' <style fg="ansiyellow">{state_text}</style>'
        )

    def _build_ui(self):
        kb = KeyBindings()

        @kb.add("c-c")
        def _exit(event: KeyPressEvent):
            event.app.exit()

        @kb.add("enter", filter=Condition(self._is_input_state))
        def _submit(event: KeyPressEvent):
            text = self.input_buffer.text.strip()
            if not text:
                return
            self.input_buffer.reset()
            event.app.invalidate()
            asyncio.ensure_future(self._handle_submit(text))

        @kb.add("enter", filter=Condition(self._is_question_state))
        def _submit_question(event: KeyPressEvent):
            text = self.input_buffer.text.strip()
            if not text:
                return
            self.input_buffer.reset()
            event.app.invalidate()
            asyncio.ensure_future(self._handle_question_answer(text))

        @kb.add("y", filter=Condition(self._is_permission_state))
        def _permission_yes(event: KeyPressEvent):
            if self._permission_future and not self._permission_future.done():
                self._permission_future.set_result("allow")
                self._state = "RUNNING"

        @kb.add("n", filter=Condition(self._is_permission_state))
        def _permission_no(event: KeyPressEvent):
            if self._permission_future and not self._permission_future.done():
                self._permission_future.set_result("deny")
                self._state = "RUNNING"

        @kb.add("a", filter=Condition(self._is_permission_state))
        def _permission_always(event: KeyPressEvent):
            if self._permission_future and not self._permission_future.done():
                self._permission_future.set_result("allow_always")
                self._state = "RUNNING"

        # --- Session list key bindings ---
        @kb.add("up", filter=Condition(self._is_session_list_state))
        def _session_up(event: KeyPressEvent):
            if self._session_selection > 0:
                self._session_selection -= 1
                event.app.invalidate()

        @kb.add("down", filter=Condition(self._is_session_list_state))
        def _session_down(event: KeyPressEvent):
            if self._session_selection < len(self._session_files) - 1:
                self._session_selection += 1
                event.app.invalidate()

        @kb.add("right", filter=Condition(self._is_session_list_state))
        def _session_switch(event: KeyPressEvent):
            """Switch to the selected session."""
            index = self._session_selection
            files = self._session_files
            if index < 0 or index >= len(files):
                return
            target = files[index]
            if os.path.abspath(target) == os.path.abspath(self.session_file_ref[0]):
                return
            asyncio.ensure_future(self._do_switch_session(index))

        @kb.add("left", filter=Condition(self._is_session_list_state))
        def _session_delete(event: KeyPressEvent):
            """Delete the selected session."""
            index = self._session_selection
            files = self._session_files
            if index < 0 or index >= len(files):
                return
            target = files[index]
            if os.path.abspath(target) == os.path.abspath(self.session_file_ref[0]):
                return
            asyncio.ensure_future(self._do_delete_session(index))

        @kb.add("enter", filter=Condition(self._is_session_list_state))
        def _session_enter(event: KeyPressEvent):
            """Switch to the selected session on Enter."""
            index = self._session_selection
            files = self._session_files
            if index < 0 or index >= len(files):
                return
            target = files[index]
            if os.path.abspath(target) == os.path.abspath(self.session_file_ref[0]):
                return
            asyncio.ensure_future(self._do_switch_session(index))

        @kb.add("escape", filter=Condition(self._is_session_list_state))
        def _session_close(event: KeyPressEvent):
            """Close the session list overlay."""
            self._show_session_list = False
            self._state = "INPUT"
            event.app.invalidate()

        output_win = Window(
            BufferControl(buffer=self.output_buffer, focusable=False),
            wrap_lines=True,
        )
        input_win = Window(
            BufferControl(buffer=self.input_buffer),
            height=1,
            style="class:input",
        )
        status_win = Window(
            FormattedTextControl(self._format_status),
            height=1,
            style="class:status",
        )

        self._session_list_control = FormattedTextControl(self._format_session_list)

        body = FloatContainer(
            HSplit([output_win, input_win, status_win]),
            [
                Float(
                    xcursor=True,
                    ycursor=True,
                    transparent=True,
                    content=CompletionsMenu(
                        max_height=16,
                        scroll_offset=1,
                        extra_filter=has_focus(self.input_buffer),
                    ),
                ),
                Float(
                    top=2,
                    right=4,
                    transparent=True,
                    width=70,
                    height=24,
                    content=Window(
                        self._session_list_control,
                        wrap_lines=False,
                    ),
                ),
            ],
        )

        self.application = Application(
            layout=Layout(body),
            key_bindings=kb,
            style=_STYLE,
            mouse_support=True,
            full_screen=True,
        )

    def _is_input_state(self):
        return self._state == "INPUT" and not self._show_session_list

    def _is_running_state(self):
        return self._state == "RUNNING"

    def _is_permission_state(self):
        return self._state == "AWAITING_PERMISSION"

    def _is_question_state(self):
        return self._state == "AWAITING_QUESTION"

    def _is_session_list_state(self):
        return self._show_session_list

    def _format_session_list(self) -> FormattedText:
        """Build formatted text for the session list overlay."""
        if not self._show_session_list:
            return FormattedText([("", "")])
        if not self._session_files:
            return FormattedText([("", "No saved sessions.")])

        bg = "bg:#1a1a2e #e0e0e0"
        result: list[tuple[str, str]] = []
        # Title
        result.append((f"{bg} bold", "╔══════════════════════════════════════════════════╗\n"))
        result.append((f"{bg} bold", "║  Sessions                                        ║\n"))
        result.append((f"{bg} bold", "╠══════════════════════════════════════════════════╣\n"))

        current_path = os.path.abspath(self.session_file_ref[0])
        max_items = 18
        files = self._session_files
        infos = self._session_infos

        for i in range(len(files)):
            if i >= max_items:
                result.append((f"{bg} dim", f"║  ... and {len(files) - max_items} more               ║\n"))
                break

            info = infos[i] if i < len(infos) else session_info(files[i])
            title = info["title"]
            msgs = info["messages"]
            is_current = os.path.abspath(files[i]) == current_path
            is_selected = i == self._session_selection

            # Truncate title
            if len(title) > 32:
                display_title = title[:29] + "..."
            else:
                display_title = title

            marker = "▸" if is_selected else " "
            current_tag = " ◀ current" if is_current else ""
            line = f"║ {marker} {i+1:2d}. {display_title:<32s} {msgs:2d} msgs{current_tag:<11s}║\n"

            if is_selected:
                result.append((f"{bg} bold reverse", line))
            elif is_current:
                result.append((f"{bg} bold", line))
            else:
                result.append((f"{bg}", line))

        result.append((f"{bg} bold", "╠══════════════════════════════════════════════════╣\n"))
        result.append((f"{bg} dim",   "║  ← Delete  →/Enter Switch  ↑↓ Navigate  Esc Close║\n"))
        result.append((f"{bg} bold", "╚══════════════════════════════════════════════════╝"))

        return FormattedText(result)

    def _refresh_session_list(self) -> None:
        """Refresh the session file list and info cache."""
        self._session_files = list_sessions(self.cwd)
        self._session_infos = [session_info(f) for f in self._session_files]
        if self._session_selection >= len(self._session_files):
            self._session_selection = max(0, len(self._session_files) - 1)

    def _on_input_changed(self, buffer: Buffer):
        pass

    def _append_output(self, text: str):
        text = self.output_buffer.text + text
        self.output_buffer.set_document(
            Document(text, len(text)), bypass_readonly=True
        )

    async def _handle_submit(self, text: str):
        if text.startswith("/"):
            handled = await self._handle_command(text)
            if handled:
                self._state = "INPUT"
                self.application.invalidate()
                return

        self._state = "RUNNING"
        self.application.invalidate()

        if self._turn_count > 0:
            self._append_output("\n───\n")
        self._turn_count += 1
        self._append_output(f"\n> {text}\n")

        original_on_text_delta = self.agent.on_text_delta
        original_on_tool_end = self.agent.on_tool_end
        original_permission = self.agent.permission_callback
        original_ask_user = self.agent.ask_user_callback
        original_on_tool_start = self.agent.on_tool_start

        self.agent.on_text_delta = self._on_text_delta
        self.agent.on_tool_end = self._on_tool_end
        self.agent.permission_callback = self._permission_callback
        self.agent.ask_user_callback = self._ask_user_callback
        self.agent.on_tool_start = self._on_tool_start

        try:
            await self.agent.run_stream(text, self.cwd, session=self.session)
        except asyncio.CancelledError:
            pass
        except (KeyboardInterrupt, EOFError):
            pass
        except Exception:
            self._append_output(f"\n[Error: {traceback.format_exc()}]")
        finally:
            self.agent.on_text_delta = original_on_text_delta
            self.agent.on_tool_end = original_on_tool_end
            self.agent.permission_callback = original_permission
            self.agent.ask_user_callback = original_ask_user
            self.agent.on_tool_start = original_on_tool_start
            self._state = "INPUT"
            self.application.invalidate()

    def _on_text_delta(self, text: str):
        self._append_output(text)
        self.application.invalidate()

    def _on_tool_start(self, call: ToolCall):
        label = f"\n  [{call.name}]"
        self._append_output(label)
        self.application.invalidate()

    def _on_tool_end(self, name: str, title: str, output: str):
        label = f"\n  [{title}]"
        self._append_output(label)
        self.application.invalidate()

    async def _permission_callback(self, tool: str, target: str, reason: str) -> str:
        if tool == "bash":
            self._append_output(f"\n  [!] Dangerous command: {reason}")
            self._append_output(f"\n  Command: {target[:100]}")
            self._append_output("\n  [y]es / [n]o: ")
        else:
            self._append_output(f"\n  [!] {tool} wants to access: {target}")
            self._append_output("\n  [y]es / [n]o / [a]lways: ")

        self._state = "AWAITING_PERMISSION"
        self._permission_future = asyncio.get_running_loop().create_future()
        self.application.invalidate()

        result = await self._permission_future
        self._permission_future = None
        return result

    async def _ask_user_callback(
        self, header: str, question: str, options: list[dict], multiple: bool
    ) -> list[str]:
        self._append_output(f"\n  {header}")
        self._append_output(f"\n  {question}")
        self._append_output("\n")

        option_map: dict[str, str] = {}
        for i, opt in enumerate(options, 1):
            label = opt["label"]
            desc = opt.get("description", "")
            option_map[str(i)] = label
            option_map[label.lower()] = label
            desc_text = f" - {desc}" if desc else ""
            self._append_output(f"\n    {i}. {label}{desc_text}")

        custom_idx = len(options) + 1
        self._append_output(f"\n    {custom_idx}. Custom (type your own answer)")
        self._append_output(f"\n\n  Your answer (1-{custom_idx}{', comma-separated for multiple' if multiple else ''}): ")

        self._state = "AWAITING_QUESTION"
        self._question_multiple = multiple
        self._question_options = options
        self._question_option_map = option_map
        self._question_custom_idx = custom_idx
        self._question_future = asyncio.get_running_loop().create_future()
        self.application.invalidate()

        result = await self._question_future
        self._question_future = None
        return result

    async def _handle_question_answer(self, raw: str):
        raw = raw.strip()
        if not raw:
            if self._question_future and not self._question_future.done():
                self._question_future.set_result([])
            self._state = "RUNNING"
            self.application.invalidate()
            return

        selected = [s.strip() for s in raw.replace("，", ",").split(",") if s.strip()]
        answers: list[str] = []
        option_map = self._question_option_map
        options = self._question_options
        custom_idx = self._question_custom_idx

        for choice in selected:
            if choice in option_map:
                answers.append(option_map[choice])
            elif choice.isdigit() and int(choice) == custom_idx:
                self._append_output("\n  Type your answer: ")
                self._state = "AWAITING_QUESTION"
                self.application.invalidate()
                new_future = asyncio.get_running_loop().create_future()
                self._question_future = new_future
                custom_answer = await new_future
                answers.append(custom_answer.strip() or "(skipped)")
            elif choice.isdigit() and 1 <= int(choice) <= len(options):
                answers.append(options[int(choice) - 1]["label"])
            else:
                answers.append(choice)

        if not answers:
            answers = ["(skipped)"]

        if self._question_future and not self._question_future.done():
            self._question_future.set_result(answers)
        self._state = "RUNNING"
        self.application.invalidate()

    async def _handle_command(self, line: str) -> bool:
        parts = line.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd == "/help":
            self._append_output("\n  /help                Show this help")
            self._append_output("\n  /clear               Clear conversation history")
            self._append_output("\n  /tokens              Show token usage")
            self._append_output("\n  /vscode              Open current working directory in VS Code")
            self._append_output("\n  /sessions            Interactive session list (↑↓→← Esc)")
            self._append_output("\n  /sessions new        Start a new session")
            self._append_output("\n  /sessions <n>        Switch to session n")
            self._append_output("\n  /sessions delete <n>  Delete session n")
            self._append_output("\n  /sessions delete all  Delete all saved sessions")
            self._append_output("\n  /exit                Exit")
            return True

        if cmd == "/exit":
            self.application.exit()
            return True

        if cmd == "/clear":
            self.output_buffer.reset()
            self.session.messages.clear()
            self._append_output("\n[Conversation cleared.]")
            return True

        if cmd == "/tokens":
            self._append_output(f"\n[~{self.session.total_tokens()} tokens used.]")
            return True

        if cmd == "/vscode":
            try:
                subprocess.run(["code", self.cwd], check=True)
                self._append_output(f"\n[Opened VS Code at {self.cwd}]")
            except FileNotFoundError:
                self._append_output("\n[Error: `code` command not found.]")
            except subprocess.CalledProcessError as e:
                self._append_output(f"\n[Error: Failed to open VS Code: {e}]")
            return True

        if cmd == "/sessions":
            if not arg:
                self._refresh_session_list()
                if not self._session_files:
                    self._append_output("\n[No saved sessions.]")
                else:
                    self._append_output(f"\n[Interactive session list — use ↑↓ to navigate, → to switch, ← to delete, Esc to close]")
                    self._session_selection = 0
                    self._show_session_list = True
                    self.application.invalidate()
                return True

            if arg == "new":
                save_current(self.session, self.session_file_ref[0])
                self.session.messages.clear()
                self.session.title = ""
                self.session_file_ref[0] = session_path(self.cwd)
                self.output_buffer.reset()
                self._append_output("\n[New session started.]")
                self.application.invalidate()
                return True

            if arg.startswith("delete "):
                target = arg[7:].strip()
                if target == "all":
                    self._append_output("\n[Delete ALL sessions? Press 'y' to confirm, 'n' to cancel.]")
                    self._state = "AWAITING_PERMISSION"
                    self._permission_future = asyncio.get_running_loop().create_future()
                    self.application.invalidate()
                    result = await self._permission_future
                    self._permission_future = None
                    if result == "allow":
                        files = list_sessions(self.cwd)
                        current_abs = os.path.abspath(self.session_file_ref[0])
                        deleted = 0
                        for f in files:
                            if os.path.abspath(f) != current_abs:
                                try:
                                    os.remove(f)
                                    deleted += 1
                                except OSError:
                                    pass
                        self._append_output(f"\n[Deleted {deleted} session(s).]")
                    else:
                        self._append_output("\n[Cancelled.]")
                    self._state = "INPUT"
                    self.application.invalidate()
                    return True
                if target.isdigit():
                    index = int(target)
                    files = list_sessions(self.cwd)
                    if index < 1 or index > len(files):
                        self._append_output(f"\n[Invalid session number: {index}]")
                        return True
                    target_file = files[index - 1]
                    if os.path.abspath(target_file) == os.path.abspath(self.session_file_ref[0]):
                        self._append_output("\n[Cannot delete current active session.]")
                        return True
                    try:
                        os.remove(target_file)
                        info = session_info(target_file)
                        self._append_output(f"\n[Deleted session {index}: {info['title']}]")
                    except OSError as e:
                        self._append_output(f"\n[Error: {e}]")
                    return True
                self._append_output("\n[Usage: /sessions delete <n> or /sessions delete all]")
                return True

            if arg.isdigit():
                index = int(arg)
                files = list_sessions(self.cwd)
                if index < 1 or index > len(files):
                    self._append_output(f"\n[Invalid session number: {index}]")
                    return True
                target = files[index - 1]
                save_current(self.session, self.session_file_ref[0])
                try:
                    new_session = Session.load(target)
                except Exception:
                    self._append_output("\n[Failed to load session.]")
                    return True
                self.session.messages.clear()
                self.session.messages.extend(new_session.messages)
                self.session.title = new_session.title
                self.session_file_ref[0] = target
                self.output_buffer.reset()
                info = session_info(target)
                self._append_output(f"\n[Switched to session: {info['title']}  ({info['messages']} msgs)]")
                return True

            info = session_info(self.session_file_ref[0])
            self._append_output(f"\n[Session: {info['title']}  Messages: {info['messages']}]")
            return True

        return False

    async def _do_switch_session(self, index: int) -> None:
        """Switch to the session at the given index in the session list."""
        files = self._session_files
        if index < 0 or index >= len(files):
            return

        target = files[index]
        if os.path.abspath(target) == os.path.abspath(self.session_file_ref[0]):
            return

        save_current(self.session, self.session_file_ref[0])
        try:
            new_session = Session.load(target)
        except Exception:
            self._append_output("\n[Failed to load session.]")
            self._show_session_list = False
            self._state = "INPUT"
            self.application.invalidate()
            return

        self.session.messages.clear()
        self.session.messages.extend(new_session.messages)
        self.session.title = new_session.title
        self.session_file_ref[0] = target

        self.output_buffer.reset()
        info = self._session_infos[index] if index < len(self._session_infos) else session_info(target)
        self._append_output(f"\n[Switched to session: {info['title']}  ({info['messages']} msgs)]")

        self._show_session_list = False
        self._state = "INPUT"
        self.application.invalidate()

    async def _do_delete_session(self, index: int) -> None:
        """Delete the session at the given index in the session list."""
        files = self._session_files
        if index < 0 or index >= len(files):
            return

        target = files[index]
        if os.path.abspath(target) == os.path.abspath(self.session_file_ref[0]):
            return

        try:
            os.remove(target)
            info = self._session_infos[index] if index < len(self._session_infos) else session_info(target)
            self._append_output(f"\n[Deleted session: {info['title']}]")
        except OSError as e:
            self._append_output(f"\n[Error deleting session: {e}]")

        # Refresh the list
        self._refresh_session_list()
        if not self._session_files:
            self._show_session_list = False
            self._state = "INPUT"

        self.application.invalidate()

    def run(self) -> None:
        self._append_output("nanoClaude interactive mode. Type /help for commands, Ctrl+C to exit.\n")
        try:
            self.application.run()
        except (KeyboardInterrupt, EOFError):
            pass
