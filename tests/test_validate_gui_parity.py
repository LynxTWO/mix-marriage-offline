import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = REPO_ROOT / "tools" / "validate_gui_parity.py"


def _python_cmd() -> str:
    return os.fspath(os.getenv("PYTHON", "") or sys.executable)


def _run_validator(*, repo_root: Path) -> tuple[int, dict]:
    result = subprocess.run(
        [
            _python_cmd(),
            os.fspath(VALIDATOR),
            "--repo-root",
            os.fspath(repo_root),
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    return result.returncode, json.loads(result.stdout)


def _seed_temp_repo(root: Path, parity_text: str) -> None:
    (root / "docs" / "manual").mkdir(parents=True, exist_ok=True)
    (root / "gui" / "desktop-tauri").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "gui_parity.md").write_text(parity_text, encoding="utf-8")
    (root / "docs" / "06-roadmap.md").write_text("# Roadmap\n", encoding="utf-8")
    (root / "PROJECT_WHEN_COMPLETE.md").write_text(
        "# Project When Complete\n",
        encoding="utf-8",
    )
    (root / "gui" / "desktop-tauri" / "README.md").write_text(
        "# Tauri\n",
        encoding="utf-8",
    )
    (root / "docs" / "manual" / "10-gui-walkthrough.md").write_text(
        "# GUI walkthrough\n",
        encoding="utf-8",
    )


class TestValidateGuiParity(unittest.TestCase):
    def test_validate_gui_parity_current_repo_is_ok(self) -> None:
        returncode, payload = _run_validator(repo_root=REPO_ROOT)
        self.assertEqual(returncode, 0, msg=payload)
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("errors"), [])
        self.assertEqual(payload.get("deprecated_headings"), [])
        self.assertEqual(payload.get("missing_screens"), [])
        self.assertEqual(payload.get("missing_behaviors"), [])
        self.assertEqual(payload.get("missing_links"), [])

    def test_missing_screen_item_fails(self) -> None:
        parity_text = (
            "# GUI parity checklist\n\n"
            "## Desktop App Path\n\n"
            "Tauri is the desktop app path.\n"
            "It is the only GUI surface that should gain new parity work.\n\n"
            "- [Roadmap](06-roadmap.md)\n"
            "- [Project When Complete](../PROJECT_WHEN_COMPLETE.md)\n"
            "- [Tauri desktop README](../gui/desktop-tauri/README.md)\n\n"
            "## Required Links\n\n"
            "- [Roadmap](06-roadmap.md)\n"
            "- [Project When Complete](../PROJECT_WHEN_COMPLETE.md)\n"
            "- [Tauri desktop README](../gui/desktop-tauri/README.md)\n"
            "- [Desktop GUI walkthrough](manual/10-gui-walkthrough.md)\n\n"
            "## Required Screens\n\n"
            "- [ ] Validate\n"
            "- [ ] Analyze\n"
            "- [ ] Scene\n"
            "- [ ] Render\n"
            "- [ ] Results\n\n"
            "## Required Behaviors\n\n"
            "- [ ] A/B loudness-comp compare\n"
            "- [ ] Scene locks edit\n\n"
            "## Exit Rule\n\n"
            "Parity lands in the Tauri app.\n"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            _seed_temp_repo(temp_root, parity_text)
            returncode, payload = _run_validator(repo_root=temp_root)

        self.assertNotEqual(returncode, 0, msg=payload)
        self.assertFalse(payload.get("ok"))
        self.assertIn("Compare", payload.get("missing_screens", []))

    def test_legacy_note_is_optional(self) -> None:
        parity_text = (
            "# GUI parity checklist\n\n"
            "## Desktop App Path\n\n"
            "Tauri is the desktop app path.\n\n"
            "- [Roadmap](06-roadmap.md)\n"
            "- [Project When Complete](../PROJECT_WHEN_COMPLETE.md)\n"
            "- [Tauri desktop README](../gui/desktop-tauri/README.md)\n\n"
            "## Required Links\n\n"
            "- [Roadmap](06-roadmap.md)\n"
            "- [Project When Complete](../PROJECT_WHEN_COMPLETE.md)\n"
            "- [Tauri desktop README](../gui/desktop-tauri/README.md)\n"
            "- [Desktop GUI walkthrough](manual/10-gui-walkthrough.md)\n\n"
            "## Required Screens\n\n"
            "- [x] Validate\n"
            "- [x] Analyze\n"
            "- [x] Scene\n"
            "- [x] Render\n"
            "- [x] Results\n"
            "- [x] Compare\n\n"
            "## Required Behaviors\n\n"
            "- [x] A/B loudness-comp compare\n"
            "- [x] Scene locks edit\n\n"
            "## Exit Rule\n\n"
            "Parity lands in the Tauri app.\n"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            _seed_temp_repo(temp_root, parity_text)
            returncode, payload = _run_validator(repo_root=temp_root)

        self.assertEqual(returncode, 0, msg=payload)
        self.assertTrue(payload.get("ok"))

    def test_missing_required_link_and_plan_phrase_fail(self) -> None:
        parity_text = (
            "# GUI parity checklist\n\n"
            "## Desktop App Path\n\n"
            "Tauri powers MMO on desktop.\n\n"
            "- [Roadmap](06-roadmap.md)\n"
            "- [Project When Complete](../PROJECT_WHEN_COMPLETE.md)\n"
            "- [Tauri desktop README](../gui/desktop-tauri/README.md)\n\n"
            "## Required Links\n\n"
            "- [Roadmap](06-roadmap.md)\n"
            "- [Project When Complete](../PROJECT_WHEN_COMPLETE.md)\n"
            "- [Tauri desktop README](../gui/desktop-tauri/README.md)\n\n"
            "## Required Screens\n\n"
            "- [ ] Validate\n"
            "- [ ] Analyze\n"
            "- [ ] Scene\n"
            "- [ ] Render\n"
            "- [ ] Results\n"
            "- [ ] Compare\n\n"
            "## Required Behaviors\n\n"
            "- [ ] A/B loudness-comp compare\n"
            "- [ ] Scene locks edit\n\n"
            "## Exit Rule\n\n"
            "Parity lands in the Tauri app.\n"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            _seed_temp_repo(temp_root, parity_text)
            returncode, payload = _run_validator(repo_root=temp_root)

        self.assertNotEqual(returncode, 0, msg=payload)
        self.assertFalse(payload.get("ok"))
        self.assertIn(
            "docs/manual/10-gui-walkthrough.md",
            payload.get("missing_links", []),
        )
        self.assertTrue(
            any(
                "desktop app path" in error
                for error in payload.get("errors", [])
            ),
            msg=payload,
        )

    def test_deprecated_fallback_heading_fails(self) -> None:
        parity_text = (
            "# GUI parity checklist\n\n"
            "## Desktop App Path\n\n"
            "Tauri is the desktop app path.\n\n"
            "- [Roadmap](06-roadmap.md)\n"
            "- [Project When Complete](../PROJECT_WHEN_COMPLETE.md)\n"
            "- [Tauri desktop README](../gui/desktop-tauri/README.md)\n\n"
            "## Fallback Plan Until Parity\n\n"
            "CustomTkinter is the fallback plan until parity.\n\n"
            "## Required Links\n\n"
            "- [Roadmap](06-roadmap.md)\n"
            "- [Project When Complete](../PROJECT_WHEN_COMPLETE.md)\n"
            "- [Tauri desktop README](../gui/desktop-tauri/README.md)\n"
            "- [Desktop GUI walkthrough](manual/10-gui-walkthrough.md)\n\n"
            "## Required Screens\n\n"
            "- [x] Validate\n"
            "- [x] Analyze\n"
            "- [x] Scene\n"
            "- [x] Render\n"
            "- [x] Results\n"
            "- [x] Compare\n\n"
            "## Required Behaviors\n\n"
            "- [x] A/B loudness-comp compare\n"
            "- [x] Scene locks edit\n\n"
            "## Exit Rule\n\n"
            "Parity lands in the Tauri app.\n"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            _seed_temp_repo(temp_root, parity_text)
            returncode, payload = _run_validator(repo_root=temp_root)

        self.assertNotEqual(returncode, 0, msg=payload)
        self.assertIn(
            "## Fallback Plan Until Parity",
            payload.get("deprecated_headings", []),
        )


if __name__ == "__main__":
    unittest.main()
