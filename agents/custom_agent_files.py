"""Manages .md files and memory directories for user-created custom agents.

Each custom agent gets:
- .claude/agents/custom-<slug>.md  (Claude Code agent definition)
- .claude/agent-memory/custom-<slug>/MEMORY.md  (persistent memory)

The slug is derived from the agent name (lowercased, spaces/special chars → hyphens).
"""

import re
import shutil
from pathlib import Path

AGENTS_DIR = Path(".claude/agents")
MEMORY_DIR = Path(".claude/agent-memory")


def _slugify(name: str) -> str:
    """Convert agent name to a filesystem-safe slug."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return f"custom-{slug}"


def agent_slug(name: str) -> str:
    """Public accessor for the slug."""
    return _slugify(name)


def _agent_md_path(slug: str) -> Path:
    return AGENTS_DIR / f"{slug}.md"


def _memory_dir(slug: str) -> Path:
    return MEMORY_DIR / slug


def _build_md_content(name: str, goal: str, model: str) -> str:
    """Build the full .md file content with YAML front-matter + system prompt."""
    description = (
        f"Use this agent when the user asks about topics related to: {goal[:200]}"
    )
    # Escape quotes in description for YAML
    description = description.replace('"', '\\"')

    system_prompt = (
        f"You are a financial analysis agent named '{name}'.\n\n"
        f"## Your Goal\n\n{goal}\n\n"
        "## Guidelines\n\n"
        "- You have access to the investor's portfolio context below (if provided).\n"
        "- Provide clear, actionable analysis. Use markdown formatting.\n"
        "- Be specific and quantify where possible.\n"
        "- Consider the investor's EUR denomination and German tax context "
        "(Abgeltungsteuer 26.375% on capital gains).\n"
        "- Reference specific assets, tickers, and instruments rather than generic advice.\n"
        "- Update your agent memory with key findings and patterns you discover.\n"
    )

    return (
        f"---\n"
        f'name: {name}\n'
        f'description: "{description}"\n'
        f"model: {model}\n"
        f"color: green\n"
        f"memory: project\n"
        f"---\n\n"
        f"{system_prompt}"
    )


def create_agent_files(name: str, goal: str, model: str) -> str:
    """Create the .md file and memory directory for a new custom agent.

    Returns the slug used for the agent.
    """
    slug = _slugify(name)
    md_path = _agent_md_path(slug)
    mem_dir = _memory_dir(slug)

    # Create agent .md file
    AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    md_path.write_text(_build_md_content(name, goal, model), encoding="utf-8")

    # Create memory directory with initial MEMORY.md
    mem_dir.mkdir(parents=True, exist_ok=True)
    memory_file = mem_dir / "MEMORY.md"
    if not memory_file.exists():
        memory_file.write_text(
            f"# {name} — Agent Memory\n\n"
            f"Goal: {goal}\n\n"
            "## Key Findings\n\n"
            "_(Updated automatically as the agent runs)_\n",
            encoding="utf-8",
        )

    return slug


def update_agent_files(old_name: str, new_name: str, goal: str, model: str) -> str:
    """Update an agent's .md file. If the name changed, rename files and directories.

    Returns the new slug.
    """
    old_slug = _slugify(old_name)
    new_slug = _slugify(new_name)

    if old_slug != new_slug:
        # Rename .md file
        old_md = _agent_md_path(old_slug)
        new_md = _agent_md_path(new_slug)
        if old_md.exists():
            old_md.rename(new_md)

        # Rename memory directory
        old_mem = _memory_dir(old_slug)
        new_mem = _memory_dir(new_slug)
        if old_mem.exists():
            old_mem.rename(new_mem)
    else:
        new_md = _agent_md_path(new_slug)

    # Rewrite the .md content
    new_md.write_text(_build_md_content(new_name, goal, model), encoding="utf-8")

    return new_slug


def archive_agent_files(name: str) -> None:
    """Archive an agent by renaming its .md to .md.archived (Claude Code won't load it)."""
    slug = _slugify(name)
    md_path = _agent_md_path(slug)
    if md_path.exists():
        md_path.rename(md_path.with_suffix(".md.archived"))


def reactivate_agent_files(name: str, goal: str, model: str) -> None:
    """Reactivate an archived agent by restoring its .md file."""
    slug = _slugify(name)
    archived_path = _agent_md_path(slug).with_suffix(".md.archived")
    md_path = _agent_md_path(slug)

    if archived_path.exists():
        archived_path.rename(md_path)
    elif not md_path.exists():
        # Recreate if somehow missing
        create_agent_files(name, goal, model)


def delete_agent_files(name: str) -> None:
    """Permanently delete an agent's .md file and memory directory."""
    slug = _slugify(name)

    # Remove .md file (or .md.archived)
    md_path = _agent_md_path(slug)
    archived_path = md_path.with_suffix(".md.archived")
    if md_path.exists():
        md_path.unlink()
    if archived_path.exists():
        archived_path.unlink()

    # Remove memory directory
    mem_dir = _memory_dir(slug)
    if mem_dir.exists():
        shutil.rmtree(mem_dir)


def get_system_prompt(name: str) -> str:
    """Load the system prompt from the agent's .md file."""
    slug = _slugify(name)
    md_path = _agent_md_path(slug)

    if not md_path.exists():
        raise FileNotFoundError(f"Agent file not found: {md_path}")

    from agents.loader import load_system_prompt as _load
    return _load(slug)


def agent_md_exists(name: str) -> bool:
    """Check if the agent's .md file exists (active, not archived)."""
    slug = _slugify(name)
    return _agent_md_path(slug).exists()
