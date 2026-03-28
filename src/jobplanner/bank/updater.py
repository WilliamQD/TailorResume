"""AI-assisted experience bank updater."""

from __future__ import annotations

from pathlib import Path

import yaml

from jobplanner.llm.base import LLMClient

UPDATE_SYSTEM = """\
You are an experience bank updater for a resume tailoring tool.

The user will describe changes to their experience bank in natural language.
Your job is to output the COMPLETE updated YAML content of the experience
bank, incorporating the described changes.

Rules:
1. Preserve ALL existing content unless the user explicitly asks to remove it.
2. When adding new bullets, follow the existing format:
   - text: multi-line description
   - skills: list of lowercase skill tags
   - metrics: quantifiable results (or empty string)
3. When adding a new project or experience, generate a snake_case id.
4. Add appropriate tags to new entries.
5. If the user mentions new skills, also add them to the global skills section.
6. Output ONLY valid YAML — no markdown fences, no commentary.
"""


def update_bank_interactive(client: LLMClient, bank_path: Path) -> str | None:
    """Run an interactive bank update session.

    Returns the diff string if changes were made, or None if cancelled.
    """
    current_yaml = bank_path.read_text(encoding="utf-8")

    description = input("\nDescribe what changed (or 'q' to cancel):\n> ").strip()
    if not description or description.lower() == "q":
        return None

    user_msg = (
        f"Current experience bank:\n\n```yaml\n{current_yaml}\n```\n\n"
        f"Changes to apply:\n{description}\n\n"
        f"Output the complete updated YAML."
    )

    updated_yaml = client.complete_text(system=UPDATE_SYSTEM, user=user_msg)

    # Strip markdown fences if the LLM wraps output
    updated_yaml = updated_yaml.strip()
    if updated_yaml.startswith("```"):
        lines = updated_yaml.split("\n")
        # Remove first and last fence lines
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        updated_yaml = "\n".join(lines)

    # Validate the YAML is parseable
    try:
        yaml.safe_load(updated_yaml)
    except yaml.YAMLError as exc:
        print(f"\nError: AI produced invalid YAML: {exc}")
        return None

    # Show diff
    old_lines = current_yaml.splitlines()
    new_lines = updated_yaml.splitlines()

    print("\n--- Changes ---")
    # Simple line-by-line diff display
    import difflib

    diff = difflib.unified_diff(old_lines, new_lines, lineterm="", n=3)
    diff_text = "\n".join(diff)
    if not diff_text:
        print("No changes detected.")
        return None

    print(diff_text)

    confirm = input("\nApply these changes? [y/N]: ").strip().lower()
    if confirm != "y":
        print("Cancelled.")
        return None

    bank_path.write_text(updated_yaml, encoding="utf-8")
    print(f"Updated {bank_path}")
    return diff_text


def add_entry_interactive(bank_path: Path) -> None:
    """Scaffold a new project or experience entry interactively."""
    current = yaml.safe_load(bank_path.read_text(encoding="utf-8"))

    entry_type = input("Add [e]xperience or [p]roject? ").strip().lower()
    if entry_type not in ("e", "p"):
        print("Cancelled.")
        return

    id_ = input("ID (snake_case): ").strip()
    if not id_:
        print("Cancelled.")
        return

    if entry_type == "e":
        entry = {
            "id": id_,
            "organization": input("Organization: ").strip(),
            "role": input("Role: ").strip(),
            "location": input("Location: ").strip(),
            "dates": input("Dates: ").strip(),
            "tags": [t.strip() for t in input("Tags (comma-sep): ").split(",") if t.strip()],
            "bullets": [],
        }
        current.setdefault("experience", []).append(entry)
    else:
        entry = {
            "id": id_,
            "name": input("Project name: ").strip(),
            "dates": input("Dates: ").strip(),
            "url": input("URL (optional): ").strip(),
            "tags": [t.strip() for t in input("Tags (comma-sep): ").split(",") if t.strip()],
            "bullets": [],
        }
        current.setdefault("projects", []).append(entry)

    bank_path.write_text(
        yaml.dump(current, default_flow_style=False, allow_unicode=True, width=120),
        encoding="utf-8",
    )
    print(f"Added {id_!r}. Edit {bank_path} to add bullets and details.")
