import re
from pathlib import Path
from config import AGENTS_DIR


_FRONT_MATTER_SEP = re.compile(r"^---\s*$", re.MULTILINE)


def load_system_prompt(agent_name: str) -> str:
    """Read agent .md file and return the system prompt (content after YAML front-matter)."""
    agent_file = AGENTS_DIR / f"{agent_name}.md"
    if not agent_file.exists():
        raise FileNotFoundError(f"Agent file not found: {agent_file}")

    content = agent_file.read_text(encoding="utf-8")

    # Split on --- separators; front-matter is between first and second ---
    # parts[0] = "" (before first ---), parts[1] = YAML, parts[2] = body
    parts = _FRONT_MATTER_SEP.split(content)

    if len(parts) >= 3:
        # Strip leading/trailing whitespace from body
        return parts[2].strip()

    # No front-matter found — return whole content
    return content.strip()


def load_agent_model(agent_name: str) -> str:
    """Read the model field from an agent's YAML front-matter. Defaults to 'sonnet'."""
    agent_file = AGENTS_DIR / f"{agent_name}.md"
    if not agent_file.exists():
        return "sonnet"

    content = agent_file.read_text(encoding="utf-8")
    parts = _FRONT_MATTER_SEP.split(content)
    if len(parts) >= 3:
        yaml_block = parts[1]
        match = re.search(r"^model:\s*(\S+)", yaml_block, re.MULTILINE)
        if match:
            return match.group(1)
    return "sonnet"


def load_all_agents() -> dict[str, str]:
    """Return {agent_name: system_prompt} for all configured agents."""
    from config import AGENT_NAMES
    return {name: load_system_prompt(name) for name in AGENT_NAMES}
