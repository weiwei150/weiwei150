"""Agent Skills 发现、提示词注入和 loadSkill 工具测试。"""

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
        registry = build_default_registry(
            ToolContext(base_dir=self.base, skills=skills)
        )
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
        _write_skill(
            self.base,
            "invalid",
            "---\nname: invalid\n---\n没有 description\n",
        )
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
                execution = registry.execute(
                    "loadSkill",
                    {"name": "alpha", "filename": filename},
                )
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

        execution = registry.execute(
            "loadSkill",
            {"name": "alpha", "filename": "unique.md"},
        )

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

        execution = registry.execute(
            "loadSkill",
            {"name": "alpha", "filename": "shared.md"},
        )

        self.assertFalse(execution.success)
        self.assertEqual(execution.payload["reason"], "multiple_matches")
        self.assertEqual(len(execution.payload["candidates"]), 2)

    def test_attachment_cannot_escape_skill_directory(self) -> None:
        _write_skill(
            self.base,
            "alpha",
            "---\nname: alpha\ndescription: Alpha skill\n---\n",
        )
        outside = self.base / "outside.txt"
        outside.write_text("secret", encoding="utf-8")
        _, registry = self._make_registry()

        for filename in ("../../../outside.txt", str(outside)):
            with self.subTest(filename=filename):
                execution = registry.execute(
                    "loadSkill",
                    {"name": "alpha", "filename": filename},
                )
                self.assertFalse(execution.success)
                self.assertEqual(
                    execution.payload["reason"],
                    "outside_skill_directory",
                )
                self.assertNotIn("secret", execution.content)

    def test_missing_skill_and_missing_attachment(self) -> None:
        _write_skill(
            self.base,
            "alpha",
            "---\nname: alpha\ndescription: Alpha skill\n---\n",
        )
        _, registry = self._make_registry()

        missing_skill = registry.execute("loadSkill", {"name": "nope"})
        self.assertFalse(missing_skill.success)
        self.assertEqual(missing_skill.payload["reason"], "skill_not_found")

        missing_file = registry.execute(
            "loadSkill",
            {"name": "alpha", "filename": "references/missing.md"},
        )
        self.assertFalse(missing_file.success)
        self.assertEqual(missing_file.payload["reason"], "file_not_found")

    def test_no_skills_returns_clear_error(self) -> None:
        registry = build_default_registry(ToolContext(base_dir=self.base))
        execution = registry.execute("loadSkill", {"name": "alpha"})

        self.assertFalse(execution.success)
        self.assertEqual(execution.payload["reason"], "no_skills")

    def test_create_skill_generates_frontmatter_and_body(self) -> None:
        _, registry = self._make_registry()

        execution = registry.execute(
            "createSkill",
            {
                "name": "My PDF Tools",
                "skillContext": "# PDF Tools\n\nUse this skill to extract PDF tables.\n",
            },
        )

        self.assertTrue(execution.success, execution.content)
        self.assertEqual(execution.payload["skill"], "my-pdf-tools")
        skill_file = self.base / ".agents" / "skills" / "my-pdf-tools" / "SKILL.md"
        self.assertTrue(skill_file.is_file())

        metadata = parse_frontmatter(skill_file.read_text(encoding="utf-8"))
        self.assertEqual(metadata["name"], "my-pdf-tools")
        self.assertEqual(metadata["description"], "PDF Tools")
        self.assertIn("description: PDF Tools\n", skill_file.read_text(encoding="utf-8"))
        self.assertIn("Use this skill to extract PDF tables.", skill_file.read_text(encoding="utf-8"))

        # 新建后立即注册，可以在同一会话中通过 loadSkill 读取
        self.assertIsNotNone(registry.context.skills.get("my-pdf-tools"))
        loaded = registry.execute("loadSkill", {"name": "my-pdf-tools"})
        self.assertTrue(loaded.success, loaded.content)
        self.assertIn("Use this skill to extract PDF tables.", loaded.payload["content"])

    def test_create_skill_reuses_frontmatter_description_and_normalizes_name(self) -> None:
        _, registry = self._make_registry()

        execution = registry.execute(
            "createSkill",
            {
                "name": "Code_Review",
                "skillContext": (
                    "---\n"
                    "name: old-name\n"
                    'description: "Review: local changes and report issues"\n'
                    "---\n\n"
                    "# Code Review\n\nCheck the diff.\n"
                ),
            },
        )

        self.assertTrue(execution.success, execution.content)
        skill_file = self.base / ".agents" / "skills" / "code-review" / "SKILL.md"
        metadata = parse_frontmatter(skill_file.read_text(encoding="utf-8"))
        self.assertEqual(metadata["name"], "code-review")
        self.assertEqual(
            metadata["description"],
            "Review: local changes and report issues",
        )
        text = skill_file.read_text(encoding="utf-8")
        self.assertEqual(text.count("---"), 2)
        self.assertIn("Check the diff.", text)

    def test_create_skill_does_not_overwrite_existing_skill(self) -> None:
        _, registry = self._make_registry()
        first = registry.execute(
            "createSkill",
            {
                "name": "alpha",
                "skillContext": "# Alpha\n\nOriginal content.\n",
            },
        )
        self.assertTrue(first.success, first.content)
        skill_file = self.base / ".agents" / "skills" / "alpha" / "SKILL.md"
        original = skill_file.read_text(encoding="utf-8")

        duplicate = registry.execute(
            "createSkill",
            {
                "name": "alpha",
                "skillContext": "# Alpha\n\nReplacement content.\n",
            },
        )

        self.assertFalse(duplicate.success)
        self.assertEqual(duplicate.payload["reason"], "skill_exists")
        self.assertIn("未覆盖", duplicate.payload["error"])
        self.assertEqual(skill_file.read_text(encoding="utf-8"), original)

    def test_create_skill_rejects_invalid_name_and_empty_context(self) -> None:
        _, registry = self._make_registry()

        invalid = registry.execute(
            "createSkill",
            {"name": "天气查询", "skillContext": "# Weather\n\nBody.\n"},
        )
        self.assertFalse(invalid.success)
        self.assertEqual(invalid.payload["reason"], "invalid_name")

        empty = registry.execute(
            "createSkill",
            {"name": "empty-skill", "skillContext": "   \n"},
        )
        self.assertFalse(empty.success)
        self.assertEqual(empty.payload["reason"], "missing_context")

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
