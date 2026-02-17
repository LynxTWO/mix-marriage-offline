from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mmo.resources import temp_dir

_REPO_ROOT = Path(__file__).resolve().parents[1]
_MMO_TMP_ROOT = (_REPO_ROOT / ".mmo_tmp").resolve()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


class TestTempHygiene(unittest.TestCase):
    def test_tempfile_gettempdir_is_repo_local(self) -> None:
        current_temp = Path(tempfile.gettempdir()).resolve()
        self.assertTrue(
            _is_within(current_temp, _MMO_TMP_ROOT),
            (
                "Expected tempfile.gettempdir() to be inside repo-local temp root: "
                f"tempfile={current_temp.as_posix()} root={_MMO_TMP_ROOT.as_posix()}"
            ),
        )

    def test_temp_root_exists_and_is_writable(self) -> None:
        current_root = temp_dir().resolve()
        self.assertTrue(current_root.is_dir(), f"Expected existing directory: {current_root.as_posix()}")

        marker = current_root / "temp_hygiene_write_probe.txt"
        if marker.exists():
            marker.unlink()
        marker.write_text("ok", encoding="utf-8")
        self.assertEqual(marker.read_text(encoding="utf-8"), "ok")
        marker.unlink()


if __name__ == "__main__":
    unittest.main()
