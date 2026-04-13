"""
config_loader.py
────────────────
Loads configuration from YAML files.
Tries config.local.yaml first, then falls back to config.yaml.
"""

import os
import yaml


def load_config() -> dict:
    """Load configuration from YAML file and return as a dictionary."""

    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Try local config first (for real credentials), then fall back
    for filename in ("config.local.yaml", "config.yaml"):
        path = os.path.join(script_dir, filename)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            print(f"[config] Loaded configuration from {filename}")
            return config

    raise FileNotFoundError(
        "No config.yaml or config.local.yaml found in the project folder."
    )
