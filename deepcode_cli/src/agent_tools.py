import os
import subprocess
import shutil
import sys
import re
import fnmatch
from pathlib import Path
from typing import List, Dict, Any, Optional


class AgentTools:
    def __init__(self, workspace_root: str, unrestricted: bool = False):
        self.workspace_root = os.path.abspath(workspace_root)
        self.unrestricted = unrestricted

    def _safe_path(self, path: str) -> str:
        if self.unrestricted:
            return os.path.abspath(path)
        abs_path = os.path.abspath(os.path.join(self.workspace_root, path))
        if not abs_path.startswith(self.workspace_root):
            raise PermissionError(f"Access denied: '{path}' is outside workspace root.")
        return abs_path

    def list_dir(self, directory: str = ".") -> str:
        try:
            target = self._safe_path(directory)
            items = sorted(os.listdir(target))
            if not items:
                return "Directory is empty."
            result = []
            for item in items:
                item_path = os.path.join(target, item)
                if os.path.isdir(item_path):
                    result.append(f"[DIR]  {item}/")
                else:
                    size = os.path.getsize(item_path)
                    result.append(f"[FILE] {item}  ({size:,} bytes)")
            return "\n".join(result)
        except Exception as e:
            return f"Error: {e}"

    def get_tree(self, directory: str = ".", max_depth: int = 3) -> str:
        SKIP = {'.git', '__pycache__', 'node_modules', '.venv', '.mypy_cache', '.pytest_cache', 'dist', 'build'}
        try:
            target = self._safe_path(directory)
            output = [f"{directory}"]

            def _walk(curr_path: str, prefix: str, depth: int):
                if depth > max_depth:
                    return
                try:
                    entries = sorted(os.listdir(curr_path))
                except PermissionError:
                    return
                entries = [e for e in entries if e not in SKIP]
                for i, entry in enumerate(entries):
                    full = os.path.join(curr_path, entry)
                    is_last = i == len(entries) - 1
                    connector = "└── " if is_last else "├── "
                    suffix = "/" if os.path.isdir(full) else ""
                    output.append(f"{prefix}{connector}{entry}{suffix}")
                    if os.path.isdir(full):
                        new_prefix = prefix + ("    " if is_last else "│   ")
                        _walk(full, new_prefix, depth + 1)

            _walk(target, "", 0)
            return "\n".join(output)
        except Exception as e:
            return f"Error: {e}"

    def read_file(self, file_path: str) -> str:
        MAX_BYTES = 500_000   # 500 KB hard limit
        MAX_LINES = 2_000
        try:
            target = self._safe_path(file_path)
            size = os.path.getsize(target)
            if size > MAX_BYTES:
                return (f"Error: File too large ({size:,} bytes). "
                        f"Max is {MAX_BYTES:,} bytes. "
                        f"Use read_file_range to read specific sections.")
            with open(target, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            lines = content.splitlines()
            total = len(lines)
            truncated = total > MAX_LINES
            display_lines = lines[:MAX_LINES] if truncated else lines
            numbered = "\n".join(f"{i+1:4d} │ {line}" for i, line in enumerate(display_lines))
            header = f"── {file_path} ({total} lines) ──"
            result = f"{header}\n{numbered}"
            if truncated:
                result += f"\n… (showing first {MAX_LINES}/{total} lines — use read_file_range for more)"
            return result
        except Exception as e:
            return f"Error: {e}"

    def read_file_range(self, file_path: str, start_line: int = 1, end_line: Optional[int] = None) -> str:
        try:
            target = self._safe_path(file_path)
            with open(target, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
            total = len(lines)
            if end_line is None:
                end_line = total
            start = max(0, start_line - 1)
            end = min(total, end_line)
            numbered = "".join(f"{i+start_line:4d} │ {lines[i+start]}" for i in range(end - start))
            return f"── {file_path} (lines {start_line}–{end_line} of {total}) ──\n{numbered}"
        except Exception as e:
            return f"Error: {e}"

    def write_file(self, file_path: str, content: str) -> str:
        try:
            target = self._safe_path(file_path)
            os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
            with open(target, 'w', encoding='utf-8') as f:
                f.write(content)
            lines = len(content.splitlines())
            return f"Wrote {lines} lines to {file_path}"
        except Exception as e:
            return f"Error: {e}"

    def replace_file_content(self, file_path: str, start_line: int, end_line: int, target_text: str, replacement_text: str) -> str:
        try:
            target = self._safe_path(file_path)
            with open(target, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
                
            start = max(0, start_line - 1)
            end = min(len(lines), end_line)
            
            chunk = "".join(lines[start:end])
            
            if target_text not in chunk:
                return f"Error: target_text not found between lines {start_line} and {end_line}."
                
            count = chunk.count(target_text)
            if count > 1:
                return f"Error: target_text appears {count} times between lines {start_line} and {end_line}. Make target_text more unique."
                
            new_chunk = chunk.replace(target_text, replacement_text, 1)
            
            # Reconstruct the file
            new_lines = "".join(lines[:start]) + new_chunk + "".join(lines[end:])
            
            with open(target, 'w', encoding='utf-8') as f:
                f.write(new_lines)
                
            return f"Replaced content in {file_path} (lines {start_line}-{end_line})"
        except Exception as e:
            return f"Error: {e}"

    def validate_and_apply(self, file_path: str, content: str) -> str:
        try:
            target = self._safe_path(file_path)
            temp_path = target + ".tmp"
            os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
            with open(temp_path, 'w', encoding='utf-8') as f:
                f.write(content)
            if file_path.endswith(".py"):
                result = subprocess.run(
                    [sys.executable, "-m", "py_compile", temp_path],
                    capture_output=True, text=True
                )
                if result.returncode != 0:
                    os.remove(temp_path)
                    return f"Error: Python syntax check failed — changes NOT applied.\n{result.stderr}"
            os.replace(temp_path, target)
            return f"Validated and applied {file_path}"
        except Exception as e:
            return f"Error: {e}"

    def delete_file(self, file_path: str) -> str:
        try:
            target = self._safe_path(file_path)
            if os.path.isdir(target):
                shutil.rmtree(target)
                return f"Deleted directory {file_path}"
            else:
                os.remove(target)
                return f"Deleted {file_path}"
        except Exception as e:
            return f"Error: {e}"

    def move_file(self, source: str, destination: str) -> str:
        try:
            src = self._safe_path(source)
            dst = self._safe_path(destination)
            os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
            shutil.move(src, dst)
            return f"Moved {source} → {destination}"
        except Exception as e:
            return f"Error: {e}"

    def search_text(self, query: str, directory: str = ".", pattern: str = "*") -> str:
        SKIP_DIRS = {'.git', '__pycache__', 'node_modules', '.venv', '.mypy_cache', 'dist', 'build', '.gemini'}
        try:
            target = self._safe_path(directory)
            matches = []
            for root, dirs, files in os.walk(target):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                for file in files:
                    if not fnmatch.fnmatch(file, pattern):
                        continue
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                            for i, line in enumerate(f, 1):
                                if query.lower() in line.lower():
                                    rel = os.path.relpath(file_path, self.workspace_root)
                                    matches.append(f"{rel}:{i}: {line.rstrip()}")
                                    if len(matches) >= 100:
                                        return "\n".join(matches) + "\n… (truncated at 100 matches)"
                    except Exception:
                        continue
            return "\n".join(matches) if matches else "No matches found."
        except Exception as e:
            return f"Error: {e}"

    def grep_search(self, query: str, directory: str = ".", pattern: str = "*", is_regex: bool = False) -> str:
        SKIP_DIRS = {'.git', '__pycache__', 'node_modules', '.venv', '.mypy_cache', 'dist', 'build', '.gemini'}
        try:
            target = self._safe_path(directory)
            matches = []

            if is_regex:
                try:
                    compiled = re.compile(query, re.IGNORECASE)
                except re.error as e:
                    return f"Error: Invalid regex pattern — {e}"
            else:
                compiled = None

            for root, dirs, files in os.walk(target):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                for file in files:
                    if not fnmatch.fnmatch(file, pattern):
                        continue
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                            for i, line in enumerate(f, 1):
                                hit = False
                                if compiled:
                                    hit = bool(compiled.search(line))
                                else:
                                    hit = query.lower() in line.lower()
                                if hit:
                                    rel = os.path.relpath(file_path, self.workspace_root)
                                    matches.append(f"{rel}:{i}: {line.rstrip()}")
                                    if len(matches) >= 200:
                                        return "\n".join(matches) + "\n… (truncated at 200 matches)"
                    except Exception:
                        continue

            if not matches:
                return "No matches found."
            return f"Found {len(matches)} match(es):\n" + "\n".join(matches)
        except Exception as e:
            return f"Error: {e}"

    def run_command(self, command: str, timeout: int = 60) -> str:
        try:
            result = subprocess.run(
                command, shell=True, cwd=self.workspace_root,
                capture_output=True, text=True, timeout=timeout,
                encoding='utf-8', errors='replace'
            )
            parts = []
            if result.stdout.strip():
                parts.append(f"STDOUT:\n{result.stdout.rstrip()}")
            if result.stderr.strip():
                parts.append(f"STDERR:\n{result.stderr.rstrip()}")
            if result.returncode != 0:
                parts.append(f"Exit code: {result.returncode}")
            return "\n\n".join(parts) if parts else "Command completed with no output."
        except subprocess.TimeoutExpired:
            return f"Error: Command timed out after {timeout}s"
        except Exception as e:
            return f"Error: {e}"

    def get_git_info(self) -> Dict[str, Optional[str]]:
        info: Dict[str, Any] = {'branch': None, 'dirty': False, 'ahead': 0, 'behind': 0}
        try:
            r = subprocess.run(
                ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
                cwd=self.workspace_root, capture_output=True, text=True, timeout=3
            )
            if r.returncode == 0:
                info['branch'] = r.stdout.strip()
            r2 = subprocess.run(
                ['git', 'status', '--porcelain'],
                cwd=self.workspace_root, capture_output=True, text=True, timeout=3
            )
            if r2.returncode == 0:
                info['dirty'] = bool(r2.stdout.strip())
        except Exception:
            pass
        return info
