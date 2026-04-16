from __future__ import annotations

import os
from pathlib import Path


def default_wiki_root() -> Path:
    env_value = os.environ.get("LLM_WIKI_ROOT")
    if env_value:
        return Path(env_value).expanduser()
    return Path.home() / ".llm-wiki" / "wikis"
