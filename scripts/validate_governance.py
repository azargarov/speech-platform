"""Portable skill structure/link checks; semantic review remains a human/agent task."""

import re
import sys
from pathlib import Path

import yaml

SKILLS = frozenset(
    {
        "architecture-design",
        "clean-code",
        "api-contracts",
        "testing-validation",
        "security-privacy",
        "deployment-operations",
        "milestone-management",
    }
)
SECTIONS = (
    "Triggers",
    "Required inputs",
    "Workflow",
    "Expected outputs",
    "Validation checklist",
    "Stop and escalation",
)


def validate_skill(path):
    """Return actionable errors without requiring a machine-specific Codex install."""
    errors = []
    source = path / "SKILL.md"
    if not source.is_file():
        return [f"{source}: missing"]
    text = source.read_text()
    match = re.match(r"\A---\n(.*?)\n---\n(.*)\Z", text, re.DOTALL)
    if not match:
        return [f"{source}: invalid frontmatter delimiters"]
    try:
        pairs = yaml.compose(match[1])
        if not isinstance(pairs, yaml.MappingNode):
            return [f"{source}: frontmatter must be a mapping"]
        keys = [key.value for key, _value in pairs.value]
        if len(keys) != len(set(keys)):
            errors.append(f"{source}: duplicate frontmatter key")
        data = yaml.safe_load(match[1])
    except yaml.YAMLError as error:
        return [f"{source}: invalid YAML: {error}"]
    if set(data) != {"name", "description"}:
        errors.append(
            f"{source}: repository convention requires name and description only"
        )
    if data.get("name") != path.name or not re.fullmatch(
        r"[a-z0-9]+(?:-[a-z0-9]+)*", path.name
    ):
        errors.append(f"{source}: name must match skill directory")
    if len(path.name) > 64:
        errors.append(f"{source}: name too long")
    description = data.get("description")
    if (
        not isinstance(description, str)
        or not description.strip()
        or len(description) > 1024
        or "<" in description
        or ">" in description
    ):
        errors.append(f"{source}: invalid description")
    body = match[2]
    for section in SECTIONS:
        section_match = re.search(
            rf"^## {re.escape(section)}\n(.*?)(?=^## |\Z)",
            body,
            re.MULTILINE | re.DOTALL,
        )
        if not section_match or not section_match[1].strip():
            errors.append(f"{source}: missing/empty section {section}")
    if re.search(r"\[TODO:|\bTBD\b", text):
        errors.append(f"{source}: unfinished placeholder")
    return errors


def validate_links(path):
    errors = []
    for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", path.read_text()):
        if "://" in target or target.startswith("#"):
            continue
        relative = target.split("#", 1)[0]
        if relative and not (path.parent / relative).exists():
            errors.append(f"{path}: broken local reference {target}")
    return errors


def validate_repository(root):
    folder = root / ".codex/skills"
    actual = (
        {path.name for path in folder.iterdir() if path.is_dir()}
        if folder.exists()
        else set()
    )
    errors = []
    if actual != SKILLS:
        errors.append(
            f"skill inventory mismatch: missing={sorted(SKILLS - actual)}, extra={sorted(actual - SKILLS)}"
        )
    for name in sorted(SKILLS):
        errors.extend(validate_skill(folder / name))
    documents = [
        root / "AGENTS.md",
        root / "docs/development/methodology.md",
        root / "docs/architecture/principles.md",
        root / "PLANS.md",
    ]
    documents.extend(
        root / f"docs/milestones/M00B/{name}.md"
        for name in (
            "plan",
            "implementation",
            "verification",
            "user-validation",
            "result",
        )
    )
    documents.extend(folder.glob("*/SKILL.md"))
    for document in documents:
        if not document.is_file():
            errors.append(f"{document}: missing")
        else:
            errors.extend(validate_links(document))
    return errors


def main():
    errors = validate_repository(Path(__file__).resolve().parents[1])
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("PASS: seven skill structures/frontmatter and governance local references")
    print(
        "Scope: structural checks only; does not prove semantic consistency or Codex discovery"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
