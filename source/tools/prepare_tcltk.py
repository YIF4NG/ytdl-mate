from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from pathlib import Path, PurePosixPath

from PyInstaller.utils.hooks.tcl_tk import tcltk_info


def _extract_embedded_library(
    source: Path,
    archive_prefix: str,
    destination: Path,
    required_file: str,
) -> int:
    count = 0
    with zipfile.ZipFile(source) as archive:
        for member in archive.infolist():
            if member.is_dir() or not member.filename.startswith(archive_prefix):
                continue

            relative_name = member.filename[len(archive_prefix) :]
            relative = PurePosixPath(relative_name)
            if not relative.parts or relative.is_absolute() or ".." in relative.parts:
                raise RuntimeError(f"Unsafe Tcl/Tk archive member: {member.filename!r}")

            target = destination.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source_file, target.open("wb") as target_file:
                shutil.copyfileobj(source_file, target_file)
            count += 1

    if not (destination / required_file).is_file():
        raise RuntimeError(
            f"{source.name} did not contain {archive_prefix}{required_file}"
        )
    return count


def prepare(output: Path) -> bool:
    if output.exists():
        shutil.rmtree(output)

    tcl_zipfs = str(tcltk_info.tcl_data_dir or "").startswith("//zipfs:/")
    tk_zipfs = str(tcltk_info.tk_data_dir or "").startswith("//zipfs:/")
    if not (tcl_zipfs or tk_zipfs):
        print("Tcl/Tk uses ordinary data directories; PyInstaller will collect them.")
        return False

    if sys.platform != "win32":
        raise RuntimeError("Embedded Tcl/Tk library extraction is only supported on Windows.")
    if not (tcl_zipfs and tk_zipfs):
        raise RuntimeError("Tcl and Tk must use the same embedded-library layout.")

    tcl_dll = Path(tcltk_info.tcl_shared_library or "")
    tk_dll = Path(tcltk_info.tk_shared_library or "")
    if not tcl_dll.is_file() or not tk_dll.is_file():
        raise RuntimeError("Unable to locate the Tcl/Tk shared libraries.")

    tcl_count = _extract_embedded_library(
        tcl_dll, "tcl_library/", output / "_tcl_data", "init.tcl"
    )
    tk_count = _extract_embedded_library(
        tk_dll, "tk_library/", output / "_tk_data", "tk.tcl"
    )
    print(f"Prepared embedded Tcl/Tk data: {tcl_count} Tcl files, {tk_count} Tk files.")
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.output.resolve())


if __name__ == "__main__":
    main()
