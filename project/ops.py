"""Operational helpers for the project."""

from pathlib import Path
import shutil


def find_project_root() -> Path:
    """Find the folder that contains offline_ubuntu24_bundle."""
    script_path = Path(__file__).resolve()
    for folder in [script_path.parent, *script_path.parents]:
        if (folder / "offline_ubuntu24_bundle").is_dir():
            return folder

    raise FileNotFoundError("Could not find offline_ubuntu24_bundle from ops.py location.")


PROJECT_ROOT = find_project_root()

TARGETS_TO_DELETE = [
    Path("offline_ubuntu24_bundle/project"),
    Path("offline_ubuntu24_bundle/scripts"),
    Path("offline_ubuntu24_bundle/wheels"),
    Path("offline_ubuntu24_bundle/xray"),
    Path("offline_ubuntu24_bundle/bootstrap_offline.sh"),
    Path("offline_ubuntu24_bundle/install_offline.sh"),
    Path("offline_ubuntu24_bundle/README_OFFLINE_UBUNTU24.md"),
]


def delete_offline_ubuntu24_bundle_items() -> None:
    """Delete selected offline Ubuntu 24 bundle files and directories."""
    for relative_path in TARGETS_TO_DELETE:
        target = (PROJECT_ROOT / relative_path).resolve()

        if PROJECT_ROOT not in target.parents:
            raise ValueError(f"Refusing to delete outside project root: {target}")

        if target.is_dir():
            shutil.rmtree(target)
            print(f"Deleted directory: {target}")
        elif target.is_file():
            target.unlink()
            print(f"Deleted file: {target}")
        else:
            print(f"Not found, skipped: {target}")


if __name__ == "__main__":
    delete_offline_ubuntu24_bundle_items()
    script_file = Path(__file__).resolve()
    if script_file.exists():
        script_file.unlink()
        print(f"Deleted self: {script_file}")
    else:
        print("Self already deleted with project directory.")
