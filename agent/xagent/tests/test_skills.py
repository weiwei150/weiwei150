"""Tests for Agent Skills discovery, prompt injection, and loading."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401
from xagent_core import (
    Settings,
    ToolContext,
    build_default_registry,
    build_skills_prompt,
    create_session,
    discover_skills,
)
from xagent_core.skills import parse_frontmatter


def _write_skill(root: Path, folder: str, text: str, filename: str = "SKILL.md") -> Path:
    directory = root / ".agents" / "skills" / folder
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    path.write_text(text, encoding="utf-8")
    return path


class SkillTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.base = Path(self._temp.name)

    def _make_registry(self):
        skills = discover_skills(self.base)
        registry = build_default_registry(ToolContext(base_dir=self.base, skills=skills))
        return skills, registry

    def test_discover_only_metadata_and_support_frontmatter_forms(self) -> None:
        _write_skill(
            self.base,
            "alpha",
            "---\n"
            "name: alpha\n"
            "description: >-\n"
            "  Alpha description\n"
            "  across two lines.\n"
            "---\n\n"
            "# Alpha body should not be loaded at startup\n",
        )
        _write_skill(
            self.base,
            "beta",
            "---\n"
            'name: "beta"\n'
            'description: "Beta: handles #1 tasks"\n'
            "---\n"
            "# Beta body\n",
            filename="skill.md",
        )
        _write_skill(self.base, "invalid", "---\nname: invalid\n---\n没有 description\n")
        _write_skill(self.base, "plain", "没有 frontmatter\n")

        skills = discover_skills(self.base)

        self.assertEqual(skills.names, ("alpha", "beta"))
        self.assertEqual(skills.get("alpha").description, "Alpha description across two lines.")
        self.assertEqual(skills.get("beta").description, "Beta: handles #1 tasks")
        self.assertEqual(len(skills.warnings), 2)

        prompt = build_skills_prompt(skills)
        self.assertIn("- 'alpha': Alpha description", prompt)
        self.assertIn("- 'beta': Beta: handles #1 tasks", prompt)
        self.assertIn("loadSkill", prompt)
        self.assertNotIn("Alpha body", prompt)

    def test_create_session_injects_skills_and_tool(self) -> None:
        _write_skill(
            self.base,
            "alpha",
            "---\nname: alpha\ndescription: Alpha skill\n---\n# Alpha body\n",
        )
        settings = Settings(
            base_url="https://example.com",
            model_name="test-model",
            api_key="test-key",
        )
        session = create_session(settings, base_dir=self.base, model=object())

        system_prompt = session.messages[0]["content"]
        self.assertIn("Alpha skill", system_prompt)
        self.assertIn("loadSkill", system_prompt)
        self.assertNotIn("# Alpha body", system_prompt)
        self.assertIn("loadSkill", session.tool_names)

    def test_load_skill_instructions(self) -> None:
        _write_skill(
            self.base,
            "alpha",
            "---\nname: alpha\ndescription: Alpha skill\n---\n# Full instructions\n",
        )
        _, registry = self._make_registry()

        execution = registry.execute("loadSkill", {"name": "alpha"})

        self.assertTrue(execution.success, execution.content)
        self.assertEqual(execution.payload["skill"], "alpha")
        self.assertIn("# Full instructions", execution.payload["content"])

    def test_load_attachment_with_all_supported_path_forms(self) -> None:
        skill_file = _write_skill(
            self.base,
            "alpha",
            "---\nname: alpha\ndescription: Alpha skill\n---\n# Instructions\n",
        )
        attachment = skill_file.parent / "references" / "guide.md"
        attachment.parent.mkdir()
        attachment.write_text("guide content", encoding="utf-8")
        _, registry = self._make_registry()

        forms = [
            "references/guide.md",
            ".agents/skills/alpha/references/guide.md",
            str(attachment),
        ]
        for filename in forms:
            with self.subTest(filename=filename):
                execution = registry.execute("loadSkill", {"name": "alpha", "filename": filename})
                self.assertTrue(execution.success, execution.content)
                self.assertEqual(execution.payload["content"], "guide content")
                self.assertNotIn("# Instructions", execution.payload["content"])

    def test_load_bare_filename_searches_recursively(self) -> None:
        skill_file = _write_skill(
            self.base,
            "alpha",
            "---\nname: alpha\ndescription: Alpha skill\n---\n# Instructions\n",
        )
        nested = skill_file.parent / "docs" / "deep" / "unique.md"
        nested.parent.mkdir(parents=True)
        nested.write_text("unique attachment", encoding="utf-8")
        _, registry = self._make_registry()

        execution = registry.execute("loadSkill", {"name": "alpha", "filename": "unique.md"})

        self.assertTrue(execution.success, execution.content)
        self.assertEqual(execution.payload["content"], "unique attachment")

    def test_multiple_same_name_files_return_candidates(self) -> None:
        skill_file = _write_skill(
            self.base,
            "alpha",
            "---\nname: alpha\ndescription: Alpha skill\n---\n# Instructions\n",
        )
        for folder in ("a", "b"):
            target = skill_file.parent / folder / "shared.md"
            target.parent.mkdir()
            target.write_text(f"content {folder}", encoding="utf-8")
        _, registry = self._make_registry()

        execution = registry.execute("loadSkill", {"name": "alpha", "filename": "shared.md"})

        self.assertFalse(execution.success)
        self.assertEqual(execution.payload["reason"], "multiple_matches")
        self.assertEqual(len(execution.payload["candidates"]), 2)

    def test_attachment_cannot_escape_skill_directory(self) -> None:
        _write_skill(self.base, "alpha", "---\nname: alpha\ndescription: Alpha skill\n---\n")
        outside = self.base / "outside.txt"
        outside.write_text("secret", encoding="utf-8")
        _, registry = self._make_registry()

        for filename in ("../../../outside.txt", str(outside)):
            with self.subTest(filename=filename):
                execution = registry.execute("loadSkill", {"name": "alpha", "filename": filename})
                self.assertFalse(execution.success)
                self.assertEqual(execution.payload["reason"], "outside_skill_directory")
                self.assertNotIn("secret", execution.content)

    def test_missing_skill_and_missing_attachment(self) -> None:
        _write_skill(self.base, "alpha", "---\nname: alpha\ndescription: Alpha skill\n---\n")
        _, registry = self._make_registry()

        missing_skill = registry.execute("loadSkill", {"name": "nope"})
        self.assertFalse(missing_skill.success)
        self.assertEqual(missing_skill.payload["reason"], "skill_not_found")

        missing_file = registry.execute("loadSkill", {"name": "alpha", "filename": "references/missing.md"})
        self.assertFalse(missing_file.success)
        self.assertEqual(missing_file.payload["reason"], "file_not_found")

    def test_no_skills_returns_clear_error(self) -> None:
        registry = build_default_registry(ToolContext(base_dir=self.base))
        execution = registry.execute("loadSkill", {"name": "alpha"})

        self.assertFalse(execution.success)
        self.assertEqual(execution.payload["reason"], "no_skills")

    def test_parse_frontmatter_ignores_body(self) -> None:
        metadata = parse_frontmatter(
            "---\n"
            "name: demo\n"
            "description: |\n"
            "  first line\n"
            "  second line\n"
            "metadata:\n"
            "  owner: someone\n"
            "---\n"
            "body: not parsed\n"
        )
        self.assertEqual(metadata["name"], "demo")
        self.assertEqual(metadata["description"], "first line\nsecond line")
        self.assertNotIn("body", metadata)


if __name__ == "__main__":
    unittest.main()