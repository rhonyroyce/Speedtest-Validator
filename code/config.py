"""Configuration loader — reads config.yaml and provides typed access to all settings."""
# Implementation: Claude Code Prompt 1 (Project Scaffold)
import yaml
from pathlib import Path

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"

def load_config(config_path: str = None) -> dict:
    """Load and return the YAML configuration."""
    path = Path(config_path) if config_path else CONFIG_PATH
    with open(path) as f:
        return yaml.safe_load(f)
