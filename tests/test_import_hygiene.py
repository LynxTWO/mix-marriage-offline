from pathlib import Path


def test_pytest_imports_mmo_from_repo_src() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    src_dir = (repo_root / "src").resolve()

    import mmo

    module_path = Path(mmo.__file__).resolve()
    assert src_dir in module_path.parents
