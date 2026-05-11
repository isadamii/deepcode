# DeepCode

**DeepCode** is an autonomous AI coding agent powered by DeepSeek-R1. It operates directly inside your coding workspace, capable of reading, writing, editing files, running commands, and completing full coding tasks. It features a beautiful, terminal UI inspired by Claude Code.

## Features
- **Autonomous Coding**: Give it a task and it will iteratively use tools (read files, write files, run terminal commands) until the task is complete.
- **DeepSeek-R1 Powered**: Designed specifically to work with the DeepSeek-R1 model, utilizing its `thinking` capabilities.
- **Beautiful Terminal UI**: Real-time streaming, syntax highlighting, and a gorgeous responsive layout built with Rich.
- **Cross-Platform**: Works on Windows, macOS, and Linux.

## Installation

You can install DeepCode globally on your system using `pip`:

```bash
git clone <your-repo-url>
cd deepcode
pip install -e .
```

This will make the `deepcode` command available globally in your terminal.

## Configuration

To use DeepCode, you must provide your DeepSeek API token. 

When you run `deepcode` for the very first time, the terminal will automatically pause and ask you to paste your token:
`Paste your DEEPSEEK_AUTH_TOKEN here:`

Simply paste it and press Enter. DeepCode will securely save it to your global configuration file (`%APPDATA%\DeepCode\config.json` on Windows, or `~/.deepcode/config.json` on Mac/Linux) and launch immediately!

**How to get your DeepSeek token:**
1. Go to [chat.deepseek.com](https://chat.deepseek.com) and log in.
2. Open your browser's Developer Tools (F12 or Right Click -> Inspect).
3. Go to the **Console** tab.
4. Paste the following command and press Enter:
   ```javascript
   JSON.parse(localStorage.getItem("userToken")).value
   ```
5. Copy the returned string (without the quotes) and paste it into your terminal when prompted.

## Usage

Navigate to any directory you want to work on and run:
```bash
deepcode
```

### Slash Commands
Once inside the interface, you can type `/help` to see available commands:
- `/help`: Show commands
- `/clear`: Clear the screen and start a new conversation
- `/think`: Toggle DeepSeek extended thinking on/off
- `/search`: Toggle web search capabilities on/off
- `/workspace`: View or change the current working directory (opens file explorer picker)
- `/session`: Show active session info
- `/config`: Open the global config folder
- `/exit`: Exit the agent

### Command Line Arguments
- `deepcode -d <path>`: Start DeepCode in a specific directory
- `deepcode -p "fix the bug in main.py"`: One-shot prompt mode (non-interactive)
- `deepcode -f`: Allow full filesystem access (outside workspace)
- `deepcode -a`: Auto-pilot mode (skip confirmations for risky commands)

## Credits

A special thanks to [xtekky/deepseek4free](https://github.com/xtekky/deepseek4free) for the original underlying `deepseek4free` library API wrapper. The library has been modified and bundled into this project to provide additional tooling and autonomous capabilities specifically tailored for DeepCode.

## License

MIT License. See `LICENSE` for more information.
