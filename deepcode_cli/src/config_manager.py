import json
import os

DEFAULT_CONFIG = {
    # Core Agent Settings
    "agent_name": "DeepCode",
    "version": "2.0.0",
    
    # Enabled capabilities by default
    "thinking_enabled": True,       # Toggle DeepSeek-R1's extended thinking process
    "web_search_enabled": True,     # Toggle web search capability
    
    # UI and Session Settings
    "show_thinking": False,         # Whether to display the raw thinking text after completion
    "default_workspace": ".",       # Default starting directory
    "max_iterations": 20,           # Max automated steps the agent can take per request
    "delete_on_exit": False,        # Whether to delete session history when exiting
    "deepseek_auth_token": "",      # Your DeepSeek API key
    
    # Terminal UI Colors (ANSI 256 color codes)
    "theme": {
        "primary": "84",            # Green
        "secondary": "75",          # Blue
        "accent": "214",            # Orange
        "dim": "242"                # Gray
    }
}

class ConfigManager:
    def __init__(self, config_path=None):
        if config_path is None:
            if os.name == 'nt':
                appdata = os.getenv('APPDATA')
                self.config_dir = os.path.join(appdata, "DeepCode") if appdata else os.path.join(os.path.expanduser("~"), ".deepcode")
            else:
                self.config_dir = os.path.join(os.path.expanduser("~"), ".deepcode")
            os.makedirs(self.config_dir, exist_ok=True)
            self.config_path = os.path.join(self.config_dir, "config.json")
        else:
            self.config_path = config_path
        self.config = self.load_config()
        if not os.path.exists(self.config_path):
            self.save_config()

    def load_config(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r') as f:
                    return {**DEFAULT_CONFIG, **json.load(f)}
            except Exception:
                return DEFAULT_CONFIG.copy()
        return DEFAULT_CONFIG.copy()

    def save_config(self):
        with open(self.config_path, 'w') as f:
            json.dump(self.config, f, indent=4)

    def get(self, key, default=None):
        return self.config.get(key, default)

    def set(self, key, value):
        self.config[key] = value
        self.save_config()
