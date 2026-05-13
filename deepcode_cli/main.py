"""
DeepCode v2.0 — AI coding agent powered by DeepSeek-V4
"""

import os, sys, json, re, time, io, argparse, math, logging
from typing import Optional
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "deepseek4free"))

from dsk.api import DeepSeekAPI, MODEL_FLASH, MODEL_PRO
from deepcode_cli.src.agent_tools import AgentTools
from deepcode_cli.src.config_manager import ConfigManager
from deepcode_cli.src.session_store import load_session, save_session, delete_session

from rich.console import Console
from rich.markdown import Markdown
from rich.text import Text
from rich.theme import Theme
from rich.live import Live
from rich.markup import escape
from rich.table import Table
from rich.panel import Panel

THEME = Theme({
    "brand":   "bold color(84)",       # ● green dot
    "meta":    "color(242)",            # dim metadata
    "prompt":  "bold color(75)",        # › prompt
    "tool":    "bold color(75)",        # tool name (bold cyan)
    "tool_d":  "color(242)",            # tool dim info
    "tool_ok": "color(84)",             # ✔ green
    "tool_er": "bold red",              # ✘ red
    "think":   "color(242)",            # thinking text
    "gutter":  "color(242)",            # ⎿ gutter
    "slash":   "color(75)",             # slash commands
    "warn":    "color(214)",
    "err":     "bold red",
    "ok":      "bold color(84)",
})
console = Console(theme=THEME, highlight=False)
config  = ConfigManager()

SYSTEM_PROMPT = """\
You are DeepCode, an autonomous AI coding agent powered by DeepSeek-V4.
You work inside a user's coding workspace and help with all coding tasks.

━━ WHEN TO USE TOOLS vs WHEN TO REPLY ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• CONVERSATIONAL messages (greetings, questions, clarifications, explanations):
  Respond DIRECTLY in plain text. Do NOT use any tools.
  Example: user says "Hi" → you say "Hi! What can I help you build today?"

• CODING TASKS (read/write/run/search files, implement features, debug, refactor):
  Use tools one at a time until the task is done, then reply TASK_COMPLETE.

━━ TOOL FORMAT (only when performing an action) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[TOOL]
{"action": "tool_name", "parameters": { ... }}
[/TOOL]

━━ TOOL RULES ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. ONE tool per response — never emit two [TOOL] blocks.
2. READ before EDIT — always read_file before modifying.
3. PREFER replace_file_content over write_file — when editing an existing file, DO NOT rewrite the whole file. Use replace_file_content to surgically replace specific blocks of code. Use read_file first to get exact line numbers and text.
4. SURGICAL EDITS — target_text must be the exact text you want to replace within the start_line and end_line range.
5. VERIFY — after changes, run tests or confirm with run_command.
6. NEVER use run_command just to print a message to the user. Just write it.
7. CONCISE — you are talking to an expert developer. No preamble.

━━ AVAILABLE TOOLS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
list_dir(directory=".")
get_tree(directory=".", max_depth=3)
read_file(path)
read_file_range(path, start_line, end_line)
write_file(path, content)
replace_file_content(file_path, start_line, end_line, target_text, replacement_text)
validate_and_apply(file_path, content)
delete_file(file_path)
move_file(source, destination)
run_command(command)
search_text(query, directory=".", pattern="*")
grep_search(query, directory=".", pattern="*", is_regex=False)

When a coding task is fully done: TASK_COMPLETE: <one-line summary>

⚠ CRITICAL — TOOL CALL PLACEMENT:
  Your [TOOL] block MUST appear in your RESPONSE TEXT, not inside your thinking/reasoning.
  Tool calls written inside <think>...</think> are invisible to the system and will be ignored.
  Finish reasoning first, then emit the [TOOL] block in your actual reply.
"""

SLASH_HELP = {
    "/help":      "Show available commands",
    "/clear":     "Clear screen, start new conversation",
    "/think":     "Toggle extended thinking on/off",
    "/search":    "Toggle web search on/off",
    "/model":     "Switch model: flash or pro (creates new chat)",
    "/status":    "Show session status",
    "/workspace": "Show/change working directory",
    "/session":   "Show session info  (/session del to reset)",
    "/config":    "Open deepcode folder in file explorer",
    "/exit":      "Exit DeepCode",
    "/quit":      "Exit DeepCode",
}


def _home(path: str) -> str:
    return path.replace(os.path.expanduser("~"), "~")

def _git_branch(workspace: str) -> Optional[str]:
    try:
        import subprocess
        r = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=workspace, capture_output=True, text=True, timeout=2
        )
        if r.returncode == 0:
            branch = r.stdout.strip()
            d = subprocess.run(["git", "status", "--porcelain"],
                               cwd=workspace, capture_output=True, text=True, timeout=2)
            dirty = "*" if (d.returncode == 0 and d.stdout.strip()) else ""
            return f"{branch}{dirty}"
    except Exception:
        pass
    return None

def _describe_tool(action: str, params: dict) -> str:
    p = params
    if action == "read_file":            return p.get("path") or p.get("file_path", "")
    if action == "read_file_range":      return f"{p.get('path','')}:{p.get('start_line','')}-{p.get('end_line','')}"
    if action == "write_file":           return p.get("path") or p.get("file_path", "")
    if action == "replace_file_content": return f"{p.get('file_path') or p.get('path', '')}:{p.get('start_line', '')}-{p.get('end_line', '')}"
    if action == "validate_and_apply":   return p.get("file_path") or p.get("path", "")
    if action == "delete_file":          return p.get("file_path") or p.get("path", "")
    if action == "move_file":            return f"{p.get('source','')} → {p.get('destination','')}"
    if action in ("list_dir","get_tree"):return p.get("directory",".")
    if action == "run_command":
        cmd = p.get("command","")
        return cmd[:55] + ("…" if len(cmd) > 55 else "")
    if action in ("search_text","grep_search"):
        regex = " (regex)" if p.get("is_regex") else ""
        query = p.get("query", "")[:40]
        return f'"{query}"{regex}'
    return ""



class DeepCode:

    SPINNER = "⣾⣽⣻⢿⡿⣟⣯⣷"

    def __init__(self, workspace: str, unrestricted: bool = False,
                 auto_pilot: bool = False, thinking: Optional[bool] = None):
        token = config.get("deepseek_auth_token") or os.getenv("DEEPSEEK_AUTH_TOKEN")
        
        if not token:
            os.makedirs(config.config_dir, exist_ok=True)
            console.print("[err]✗ DeepSeek auth token not found.[/]")
            console.print("[meta]To get your token: Go to chat.deepseek.com, open DevTools Console, run: JSON.parse(localStorage.getItem(\"userToken\")).value[/]")
            try:
                token = console.input("\n[prompt]Paste your DEEPSEEK_AUTH_TOKEN here:[/prompt] ").strip()
                if not token:
                    console.print("[err]Token cannot be empty. Exiting.[/]")
                    sys.exit(1)
                config.set("deepseek_auth_token", token)
                console.print(f"[ok]✓ Token saved to {config.config_dir}/config.json[/]\n")
            except (KeyboardInterrupt, EOFError):
                sys.exit(1)

        self.api          = DeepSeekAPI(token)
        self.workspace    = os.path.abspath(workspace)
        self.tools        = AgentTools(self.workspace, unrestricted=unrestricted)
        self.auto_pilot   = auto_pilot
        self.chat_id: Optional[str]       = None
        self.parent_id: Optional[str]     = None
        self.iteration    = 0
        self._resumed     = False
        self.thinking     = thinking if thinking is not None else config.get("thinking_enabled", True)
        self.web_search   = config.get("web_search_enabled", True)
        self.model_type   = config.get("model_type", "flash")


    def _header(self):
        ver    = config.get("version", "2.0.0")
        ws     = _home(self.workspace)
        branch = _git_branch(self.workspace)
        think  = "on" if self.thinking else "off"
        search = "on" if self.web_search else "off"
        model_label = "deepseek-v4-pro" if self.model_type == "pro" else "deepseek-v4-flash"
        parts  = [f"[bold]DeepCode[/]", f"[meta]v{ver}[/]", f"[meta]{model_label}[/]", f"[meta]{ws}[/]"]
        if branch:
            parts.append(f"[meta]({branch})[/]")
        parts.append(f"[meta]thinking:{think}[/]")
        parts.append(f"[meta]search:{search}[/]")
        
        console.print(Panel(
            "  ".join(parts),
            title="[brand]●[/] [bold]Welcome to DeepCode[/]",
            border_style="brand",
            padding=(0, 2)
        ))
        console.print()

    def _status_line(self):
        ws     = _home(self.workspace)
        branch = _git_branch(self.workspace)
        think  = "on" if self.thinking else "off"
        search = "on" if self.web_search else "off"
        model_label = "expert" if self.model_type == "pro" else "instant"
        parts  = [f"deepseek-r1·{model_label}", ws]
        if branch: parts.append(f"({branch})")
        if self.iteration > 0:
            parts.append(f"step {self.iteration}/{config.get('max_iterations',20)}")
        parts.append(f"thinking:{think}")
        parts.append(f"search:{search}")
        console.print(f"[meta]{' · '.join(parts)}[/]")

    def _connect(self) -> bool:
        saved_chat, saved_parent = load_session(self.workspace, self.model_type)
        if saved_chat:
            self.chat_id  = saved_chat
            self.parent_id = saved_parent
            self._resumed = True
            console.print(f"[meta]↩  Resumed previous {self.model_type} session[/]")
            return True
        try:
            console.print(f"[meta]Connecting to DeepSeek ({self.model_type})…[/]", end="\r")
            self.chat_id = self.api.create_chat_session()
            console.print("                              ", end="\r")
            save_session(self.workspace, self.model_type, self.chat_id, self.parent_id)
            return True
        except Exception as e:
            console.print(f"[err]✗ Connection failed: {e}[/]")
            return False

    def start(self):
        os.system("cls" if os.name == "nt" else "clear")
        sys.stdout.write("\033]0;DeepCode\007")
        sys.stdout.flush()
        self._header()
        if not self._connect():
            return
        console.print("[meta]Type [bold]/help[/bold] for commands  ·  Ctrl+C to exit[/]\n")
        while True:
            try:
                user_input = console.input("[prompt]›[/] ").strip()
                if not user_input:
                    continue
                if user_input.startswith("/"):
                    if not self._slash(user_input):
                        break
                    continue
                self.iteration = 0
                self._run(user_input)
                console.print()
            except KeyboardInterrupt:
                console.print("\n[meta]Ctrl+C  ·  /exit to quit[/]")
            except EOFError:
                break


    def _slash(self, cmd: str) -> bool:
        parts = cmd.split(None, 1)
        name  = parts[0].lower()
        arg   = parts[1].strip() if len(parts) > 1 else ""

        if name in ("/exit", "/quit"):
            console.print("[meta]Goodbye.[/]"); return False

        elif name == "/help":
            console.print()
            console.print("[bold]Commands[/]")
            for k, v in SLASH_HELP.items():
                console.print(f"  [slash]{k:<14}[/] [meta]{v}[/]")
            console.print()

        elif name == "/clear":
            if self.chat_id:
                try:
                    self.api.delete_chat_session(self.chat_id)
                except Exception:
                    pass
            delete_session(self.workspace, self.model_type)
            self.parent_id = None
            try:
                self.chat_id = self.api.create_chat_session()
                save_session(self.workspace, self.model_type, self.chat_id, self.parent_id)
            except Exception as e:
                console.print(f"[err]✗ {e}[/]")
            os.system("cls" if os.name == "nt" else "clear")
            self._header()
            console.print("[meta]New conversation started.[/]\n")

        elif name == "/think":
            self.thinking = not self.thinking
            config.set("thinking_enabled", self.thinking)
            state = "on" if self.thinking else "off"
            console.print(f"[ok]✓ Thinking: {state}[/]")
            if self.parent_id:
                console.print("[meta]  Note: changing mid-session may reduce coherence.[/]")

        elif name == "/search":
            self.web_search = not self.web_search
            config.set("web_search_enabled", self.web_search)
            state = "on" if self.web_search else "off"
            console.print(f"[ok]✓ Web search: {state}[/]")

        elif name == "/status":
            console.print()
            self._status_line()
            console.print()

        elif name == "/workspace":
            if arg:
                new = os.path.abspath(arg)
                if os.path.isdir(new):
                    self.workspace = new
                    self.tools = AgentTools(self.workspace)
                    console.print(f"[slash]✓ Workspace: {new}[/]")
                else:
                    console.print(f"[err]✗ Not a directory: {arg}[/]")
            else:
                try:
                    import tkinter as tk
                    from tkinter import filedialog
                    root = tk.Tk()
                    root.withdraw()
                    root.attributes('-topmost', True)
                    console.print("[meta]Please select a new workspace directory in the dialog...[/]")
                    new_dir = filedialog.askdirectory(title="Select New Workspace", initialdir=self.workspace)
                    root.destroy()
                    if new_dir:
                        self.workspace = os.path.abspath(new_dir)
                        self.tools = AgentTools(self.workspace)
                        console.print(f"[slash]✓ Workspace changed to: {self.workspace}[/]")
                    else:
                        console.print(f"[meta]Workspace selection cancelled. Current: {_home(self.workspace)}[/]")
                except Exception as e:
                    console.print(f"[err]✗ Could not open file dialog: {e}[/]")
                    console.print(f"[slash]Current workspace: {_home(self.workspace)}[/]")

        elif name == "/session":
            if arg.lower() == "del":
                if self.chat_id:
                    try:
                        self.api.delete_chat_session(self.chat_id)
                    except Exception as e:
                        console.print(f"[err]✗ Failed to delete session on API: {e}[/]")
                if delete_session(self.workspace, self.model_type):
                    console.print("[ok]✓ Session deleted.[/]")
                    self.chat_id = None
                    self.parent_id = None
                    try:
                        self.chat_id = self.api.create_chat_session()
                        save_session(self.workspace, self.model_type, self.chat_id, self.parent_id)
                    except Exception as e:
                        console.print(f"[err]✗ {e}[/]")
                else:
                    console.print("[meta]No saved session.[/]")
            else:
                console.print(f"  [meta]chat_id   :[/] [slash]{self.chat_id or 'none'}[/]")
                console.print(f"  [meta]parent_id :[/] [slash]{self.parent_id or 'none'}[/]")
                console.print(f"  [meta]resumed   :[/] [slash]{'yes' if self._resumed else 'no'}[/]")
                
        elif name == "/config":
            self._open_config_folder()
            console.print(f"[ok]✓ Opened {config.config_dir}[/]")

        elif name == "/model":
            valid = {"flash", "pro"}
            if not arg:
                console.print(f"  [meta]current model :[/] [slash]{self.model_type}[/]")
                console.print(f"  [meta]available     :[/] [slash]flash · pro[/]")
            elif arg.lower() not in valid:
                console.print(f"[err]\u2717 Unknown model '{arg}'. Use: flash or pro[/]")
            elif arg.lower() == self.model_type:
                console.print(f"[meta]Already using '{self.model_type}' model.[/]")
            else:
                new_model = arg.lower()
                
                if self.parent_id:
                    console.print(f"\n[warn]⚠ Warning: Switching models will start a new session (or resume a previous {new_model} session).[/]")
                    try:
                        if console.input(f"[prompt]  Switch to {new_model}? (y/n) > [/]").strip().lower() != "y":
                            return True
                    except (KeyboardInterrupt, EOFError):
                        return True

                if self.chat_id:
                    save_session(self.workspace, self.model_type, self.chat_id, self.parent_id)

                self.model_type = new_model
                config.set("model_type", self.model_type)
                
                saved_chat, saved_parent = load_session(self.workspace, self.model_type)
                if saved_chat:
                    self.chat_id = saved_chat
                    self.parent_id = saved_parent
                    self._resumed = True
                    console.print(f"[ok]\u2713 Switched to '{self.model_type}' model \u2014 resumed previous session.[/]")
                else:
                    self.parent_id = None
                    self._resumed = False
                    try:
                        console.print(f"[meta]Connecting to DeepSeek ({self.model_type})…[/]", end="\r")
                        self.chat_id = self.api.create_chat_session()
                        save_session(self.workspace, self.model_type, self.chat_id, self.parent_id)
                        console.print(f"[ok]\u2713 Switched to '{self.model_type}' model \u2014 new session started.[/]")
                    except Exception as e:
                        console.print(f"[err]\u2717 {e}[/]")

        else:
            console.print(f"[warn]Unknown command: {name}  ·  /help for list[/]")

        return True

    def _open_config_folder(self):
        conf_dir = config.config_dir
        os.makedirs(conf_dir, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(conf_dir)
        elif sys.platform == "darwin":
            import subprocess
            subprocess.Popen(["open", conf_dir])
        else:
            import subprocess
            subprocess.Popen(["xdg-open", conf_dir])

    def _run(self, prompt: str):
        max_iter = config.get("max_iterations", 20)

        if not self.parent_id:
            current = f"{SYSTEM_PROMPT}\n\nUSER REQUEST: {prompt}"
        else:
            current = (
                f"USER REQUEST: {prompt}\n\n"
                "[Reminder: you are DeepCode. For coding tasks use [TOOL]{{...}}[/TOOL]. "
                "For simple replies just respond in plain text — no tools needed. "
                "NEVER place a [TOOL] block inside your thinking. "
                "NEVER use run_command to print messages. Reply TASK_COMPLETE when a task is done.]"
            )

        while self.iteration < max_iter:
            self.iteration += 1
            result = self._stream(current)
            if result is None:
                break
            response, thinking_buf = result
            save_session(self.workspace, self.model_type, self.chat_id, self.parent_id)

            m = re.search(r"TASK_COMPLETE[:\s]*(.*)", response, re.IGNORECASE | re.DOTALL)
            if m:
                summary = m.group(1).strip()
                if summary:
                    console.print(f"\n[ok]✓ {escape(summary)}[/]")
                else:
                    console.print(f"\n[ok]✓ Task completed.[/]")
                break

            m = re.search(r"\[TOOL\]\s*(.*?)\s*\[/TOOL\]", response, re.DOTALL)
            if m:
                raw_json = m.group(1).strip()
            else:
                fallback_m = re.search(r"(\{\s*\"action\"\s*:\s*\".*?\".*)", response, re.DOTALL)
                if fallback_m:
                    raw_json = fallback_m.group(1).strip()
                elif re.search(r"\[TOOL\]", thinking_buf):
                    console.print("[warn]⚠ Tool call detected in thinking stream — retrying…[/]")
                    current = (
                        "SYSTEM REMINDER: Your previous [TOOL] block was placed inside your "
                        "<think> block and was NOT received by the system. "
                        "You MUST emit the [TOOL] block in your RESPONSE TEXT, not in thinking. "
                        "Please repeat your last intended tool call now."
                    )
                    continue
                else:
                    break

            try:
                tj     = self._parse_tool_json(raw_json)
                action = tj.get("action", "")
                params = tj.get("parameters", tj)
            except (json.JSONDecodeError, Exception) as e:
                console.print(f"\n[err]✗ Tool JSON could not be parsed.[/]")
                current = (
                    f"TOOL_ERROR: Your [TOOL] block contained invalid JSON.\n"
                    f"Error: {e}\n\n"
                    "RULES TO FIX:\n"
                    "1. Use edit_file with a SHORT target_text — never embed entire file contents in JSON.\n"
                    "2. For write_file, keep content simple; escape quotes as \\\" and newlines as \\n.\n"
                    "3. One tool per response. Emit only valid JSON between [TOOL] and [/TOOL].\n"
                    "Try again with a corrected [TOOL] block."
                )
                continue

            if action == "TASK_COMPLETE":
                console.print(f"\n[ok]✓ {escape(params.get('summary', str(params)))}[/]")
                break

            result  = self._exec_tool(action, params)
            current = f"TOOL_RESULT:\n{result}"
        else:
            console.print(f"\n[warn]⚠ Max iterations ({max_iter}) reached.[/]")

    def _stream(self, prompt: str) -> Optional[tuple]:
        full_response   = ""
        thinking_buf    = ""
        text_buf        = ""
        think_start     = None
        spin_frame      = 0
        spin_t          = time.time()
        think_done      = False

        SPIN_CHARS = self.SPINNER
        SPIN_MS    = 0.08
        live_ctx   = None

        def _shimmer_ansi() -> str:
            t_sec = time.time()
            opc   = (math.sin(t_sec * math.pi * 2 / 2.0) + 1) / 2
            v     = int(153 + (185 - 153) * opc)
            return f"\033[38;2;{v};{v};{v}m"

        ANSI_RESET = "\033[0m"

        def _spin_char() -> str:
            return SPIN_CHARS[spin_frame % len(SPIN_CHARS)]

        def _render_thinking_line(text: str):
            snippet = text[-120:].replace("\n", " ").strip() if text else "Thinking..."
            col = _shimmer_ansi()
            sys.stdout.write(f"\r\033[K  {_spin_char()}  {col}{snippet[:80]}...{ANSI_RESET}")
            sys.stdout.flush()

        def _clear_line():
            sys.stdout.write("\r" + " " * 120 + "\r")
            sys.stdout.flush()

        api_model = MODEL_PRO if self.model_type == "pro" else MODEL_FLASH
        try:
            stream = self.api.chat_completion(
                self.chat_id,
                prompt,
                parent_message_id=self.parent_id,
                thinking_enabled=self.thinking,
                search_enabled=self.web_search,
                model_type=api_model,
            )
            for chunk in stream:
                ctype   = chunk.get("type")
                content = chunk.get("content", "")

                if chunk.get("message_id"):
                    self.parent_id = chunk["message_id"]

                now = time.time()
                if now - spin_t >= SPIN_MS:
                    spin_frame += 1
                    spin_t = now

                if ctype == "thinking":
                    if think_start is None:
                        think_start = now
                    thinking_buf += content
                    _render_thinking_line(thinking_buf)

                elif ctype == "text":
                    if not think_done:
                        think_done = True
                        _clear_line()
                        if thinking_buf:
                            think_duration = now - (think_start or now)
                            secs = max(1, round(think_duration))
                            console.print(f"[meta]\u22c5 thought for {secs}s[/]")
                        
                        live_ctx = Live(console=console, auto_refresh=False, vertical_overflow="visible")
                        live_ctx.start()

                    clean = content
                    if clean.strip() == "FINISHED" or clean == "FINISHED":
                        continue
                    clean = re.sub(r'FINISHED\s*$', '', clean)
                    text_buf      += clean
                    full_response += clean
                    
                    if live_ctx:
                        display = re.sub(r"\[TOOL\].*?(?:\[/TOOL\]|$)", "", text_buf, flags=re.DOTALL)
                        display = re.sub(r"TASK_COMPLETE[:\s]*.*", "", display, flags=re.IGNORECASE | re.DOTALL)
                        if "USER REQUEST:" in display:
                            m = re.search(r"USER REQUEST:.*?\n\n", display, re.DOTALL)
                            if m:
                                display = display[m.end():]
                        display = display.strip()
                        
                        is_tool = "[TOOL]" in text_buf and "[/TOOL]" not in text_buf
                        
                        if display or is_tool:
                            grid = Table.grid()
                            grid.add_column()
                            grid.add_column()
                            
                            if display:
                                grid.add_row("[gutter]  \u23bf [/]", Markdown(display))
                                
                            if is_tool:
                                action_m = re.search(r'"action"\s*:\s*"([^"]+)"', text_buf[text_buf.rfind("[TOOL]"):])
                                action_name = action_m.group(1) if action_m else "tool payload"
                                msg = f"[meta]{_spin_char()}[/]  [think]Preparing {action_name}…[/]"
                                if display:
                                    grid.add_row("", "")
                                grid.add_row("[gutter]  │ [/]", msg)
                                
                            live_ctx.update(grid, refresh=True)

        except KeyboardInterrupt:
            _clear_line()
            console.print("\n[meta]Interrupted. Stopping generation...[/]")
            if self.parent_id:
                try:
                    self.api.stop_stream(self.chat_id, self.parent_id)
                except Exception:
                    pass
            if live_ctx: live_ctx.stop()
            return None
        except Exception as e:
            _clear_line()
            console.print(f"\n[err]✗ API error: {e}[/]")
            if live_ctx: live_ctx.stop()
            return None
        
        if live_ctx:
            live_ctx.stop()

        _clear_line()

        if thinking_buf and not text_buf:
            think_duration = time.time() - (think_start or time.time())
            secs = max(1, round(think_duration))
            console.print(f"[meta]· thought for {secs}s[/]")

        if config.get("show_thinking", False) and thinking_buf:
            think_grid = Table.grid()
            think_grid.add_column()
            think_grid.add_column()
            think_grid.add_row("[gutter]  \u23bf [/]", Text(thinking_buf.strip(), style="think"))
            console.print(think_grid)

        if text_buf:
            display = re.sub(r"\[TOOL\].*?\[/TOOL\]", "", text_buf, flags=re.DOTALL)
            display = re.sub(r'\bFINISHED\b\s*$', '', display)
            display = re.sub(r"TASK_COMPLETE[:\s]*.*", "", display, flags=re.IGNORECASE | re.DOTALL)
            if "USER REQUEST:" in display:
                m = re.search(r"USER REQUEST:.*?\n\n", display, re.DOTALL)
                if m:
                    display = display[m.end():]
            display = display.strip()
            if display and display != text_buf.strip():
                grid = Table.grid()
                grid.add_column()
                grid.add_column()
                grid.add_row("[gutter]  \u23bf [/]", Markdown(display))
                console.print(grid)

        console.print()
        return full_response, thinking_buf

    def _exec_tool(self, action: str, params: dict) -> str:
        max_iter = config.get("max_iterations", 20)
        desc     = _describe_tool(action, params)
        step_str = f"[meta][{self.iteration}/{max_iter}][/]"
        is_last  = False

        RISKY_ACTIONS = {"delete_file", "move_file"}
        RISKY_CMD_KWS = {"rm ", "rmdir", "del ", "git reset --hard", "git push -f", "format"}
        is_risky = action in RISKY_ACTIONS or (
            action == "run_command" and
            any(k in params.get("command", "").lower() for k in RISKY_CMD_KWS)
        )
        if is_risky and not self.auto_pilot:
            console.print(f"\n[warn]⚠ Risky: [bold]{action}[/bold] {desc}[/]")
            try:
                if console.input("[prompt]  Proceed? (y/n) > [/]").strip().lower() != "y":
                    return "Cancelled by user."
            except (KeyboardInterrupt, EOFError):
                return "Cancelled by user."

        console.print(f"  [meta]├─[/] [tool]{action}[/]  [tool_d]{escape(desc)}[/]  {step_str}")

        console.print(f"  [meta]│  ⏿[/]  [think]Running…[/]", end="\r")

        result = self._dispatch(action, params)

        ok         = not result.startswith("Error")
        icon       = "[tool_ok]✓[/]" if ok else "[tool_er]✗[/]"
        
        lines = result.split("\n")
        preview_lines = lines[:3]
        preview = "\n".join(preview_lines)
        if len(preview) > 200:
            preview = preview[:200] + "…"
        if len(lines) > 3:
            preview += f" … (+{len(lines)-3} lines)"

        sys.stdout.write("\r" + " " * 60 + "\r")
        console.print(f"  [meta]└─[/] {icon}  [meta]{escape(preview)}[/]")
        console.print()

        return result

    @staticmethod
    def _parse_tool_json(raw: str) -> dict:
        raw = raw.strip()

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        try:
            def _escape_newlines_in_strings(s: str) -> str:
                result   = []
                in_str   = False
                escaped  = False
                for ch in s:
                    if escaped:
                        result.append(ch)
                        escaped = False
                        continue
                    if ch == "\\" and in_str:
                        result.append(ch)
                        escaped = True
                        continue
                    if ch == '"':
                        in_str = not in_str
                        result.append(ch)
                        continue
                    if in_str and ch == "\n":
                        result.append("\\n")
                        continue
                    if in_str and ch == "\r":
                        result.append("\\r")
                        continue
                    if in_str and ch == "\t":
                        result.append("\\t")
                        continue
                    result.append(ch)
                return "".join(result)

            fixed = _escape_newlines_in_strings(raw)
            return json.loads(fixed)
        except (json.JSONDecodeError, Exception):
            pass

        try:
            action_m = re.search(r'"action"\s*:\s*"([^"]+)"', raw)
            if not action_m:
                raise ValueError("no action field")
            action = action_m.group(1)

            params_m = re.search(r'"parameters"\s*:\s*(\{.*)', raw, re.DOTALL)
            if params_m:
                frag  = params_m.group(1)
                depth = 0
                end   = 0
                for i, ch in enumerate(frag):
                    if ch == "{": depth += 1
                    elif ch == "}": depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
                params_raw = frag[:end]
                try:
                    params = json.loads(params_raw)
                    return {"action": action, "parameters": params}
                except json.JSONDecodeError:
                    pass

            params: dict = {}
            for field in ("path", "file_path", "command", "directory",
                          "source", "destination", "query", "content",
                          "target_text", "replacement_text"):
                m = re.search(rf'"{re.escape(field)}"\s*:\s*"((?:[^\\"]|\\.)*)"', raw)
                if m:
                    params[field] = m.group(1).replace("\\n", "\n").replace(
                        "\\t", "\t").replace("\\\\", "\\").replace('\\"', '"')
            return {"action": action, "parameters": params}
        except Exception:
            pass

        raise json.JSONDecodeError("All repair strategies failed", raw, 0)


    def _dispatch(self, action: str, params: dict) -> str:
        p = params
        try:
            if action == "list_dir":
                return self.tools.list_dir(p.get("directory", "."))
            elif action == "get_tree":
                return self.tools.get_tree(p.get("directory", "."), int(p.get("max_depth", 3)))
            elif action == "read_file":
                return self.tools.read_file(p.get("path") or p.get("file_path", ""))
            elif action == "read_file_range":
                return self.tools.read_file_range(
                    p.get("path") or p.get("file_path", ""),
                    int(p.get("start_line", 1)), p.get("end_line"))
            elif action == "write_file":
                return self.tools.write_file(p.get("path") or p.get("file_path", ""), p.get("content", ""))
            elif action == "replace_file_content":
                return self.tools.replace_file_content(
                    p.get("file_path") or p.get("path", ""),
                    int(p.get("start_line", 0)), int(p.get("end_line", 0)), 
                    p.get("target_text", ""), p.get("replacement_text", ""))
            elif action == "validate_and_apply":
                return self.tools.validate_and_apply(
                    p.get("file_path") or p.get("path", ""), p.get("content", ""))
            elif action == "delete_file":
                return self.tools.delete_file(p.get("file_path") or p.get("path", ""))
            elif action == "move_file":
                return self.tools.move_file(p.get("source", ""), p.get("destination", ""))
            elif action == "run_command":
                return self.tools.run_command(p.get("command", ""))
            elif action == "search_text":
                return self.tools.search_text(p.get("query",""), p.get("directory","."), p.get("pattern","*"))
            elif action == "grep_search":
                return self.tools.grep_search(
                    p.get("query",""), p.get("directory","."),
                    p.get("pattern","*"), bool(p.get("is_regex", False)))
            else:
                return f"Error: Unknown tool '{action}'"
        except Exception as e:
            return f"Error: {e}"

def main():
    parser = argparse.ArgumentParser(
        description="DeepCode — AI coding agent powered by DeepSeek-R1")
    parser.add_argument("-d", "--directory",  help="Workspace directory")
    parser.add_argument("-p", "--prompt",     help="One-shot prompt (non-interactive)")
    parser.add_argument("-f", "--full-access", action="store_true", help="Allow access outside workspace")
    parser.add_argument("-a", "--auto-pilot",  action="store_true", help="Skip confirmations")
    parser.add_argument("--thinking",          action="store_true", help="Enable thinking mode")
    parser.add_argument("--no-thinking",       action="store_true", help="Disable thinking mode")
    args = parser.parse_args()

    workspace = args.directory or os.getcwd()

    thinking = None
    if args.thinking:    thinking = True
    if args.no_thinking: thinking = False

    agent = DeepCode(
        workspace   = workspace,
        unrestricted= args.full_access,
        auto_pilot  = args.auto_pilot,
        thinking    = thinking,
    )

    if args.prompt:
        agent.chat_id = agent.api.create_chat_session()
        save_session(agent.workspace, agent.model_type, agent.chat_id, agent.parent_id)
        agent._run(args.prompt)
    else:
        agent.start()


if __name__ == "__main__":
    main()
