"""Build Windows packages in an isolated environment."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import sysconfig
import tempfile
from datetime import datetime
from pathlib import Path


PUBLIC_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PUBLIC_ROOT))
from app.version import VERSION_RESOURCE, version_from_git


EXCLUDED_MODULES = (
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel",
    "PyQt5",
    "PyQt6",
    "PySide2",
    "development",
    "tools.issue_license",
)


def run_command(command: list[str], environment: dict[str, str]) -> None:
    subprocess.run(command, cwd=PUBLIC_ROOT, env=environment, check=True)


def prepare_environment(project_root: Path, environment: dict[str, str]) -> Path:
    build_venv = project_root / "build" / "packaging" / ".venv"
    python = build_venv / "Scripts" / "python.exe"
    if not python.is_file():
        run_command([sys.executable, "-m", "venv", str(build_venv)], environment)
    command = [
        str(python), "-m", "pip", "install", "--upgrade",
        "-r", str(PUBLIC_ROOT / "requirements.txt"),
        "-r", str(PUBLIC_ROOT / "packaging" / "requirements.txt"),
    ]
    extra_requirements = project_root / "requirements.txt"
    if project_root != PUBLIC_ROOT and extra_requirements.is_file():
        command.extend(["-r", str(extra_requirements)])
    run_command(command, environment)
    return python


def create_icon(python: Path, work_root: Path, environment: dict[str, str]) -> Path:
    icon_path = work_root / "app_icon.ico"
    run_command([
        str(python), "-c",
        "import sys; from PIL import Image; "
        "image = Image.open(sys.argv[1]).convert('RGBA'); "
        "image.save(sys.argv[2], format='ICO', "
        "sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])",
        str(PUBLIC_ROOT / "resources" / "app_icon.png"), str(icon_path),
    ], environment)
    return icon_path


def build_package(
    python: Path,
    project_root: Path,
    name: str,
    extension_packages: list[str],
    work_root: Path,
    environment: dict[str, str],
    version: str,
    *,
    onefile: bool = False,
) -> Path:
    icon = create_icon(python, work_root, environment)
    version_file = work_root / VERSION_RESOURCE
    version_file.write_text(version + "\n", encoding="ascii")
    command = [
        str(python), "-m", "PyInstaller",
        "--onefile" if onefile else "--onedir", "--windowed", "--noupx",
        "--name", name,
        "--distpath", str(work_root / "dist"),
        "--workpath", str(work_root / "analysis"),
        "--specpath", str(work_root),
        "--paths", str(PUBLIC_ROOT),
        "--icon", str(icon),
        "--add-data", f"{PUBLIC_ROOT / 'resources' / 'app_icon.png'}:resources",
        "--add-data", f"{version_file}:resources",
        "--hidden-import", "pkgutil",
    ]
    translations_root = python.parent.parent / "Lib" / "site-packages" / "PySide6" / "translations"
    for language in ("en", "zh_CN", "zh_TW", "ja", "ko", "es"):
        translation = translations_root / f"qtbase_{language}.qm"
        if not translation.is_file():
            raise RuntimeError(f"Qt translation file is missing: {translation}")
        command.extend(["--add-data", f"{translation}:PySide6/translations"])
    keys_path = project_root / "resources" / "license_public_keys.json"
    if not keys_path.is_file():
        keys_path = PUBLIC_ROOT / "resources" / "license_public_keys.json"
    if extension_packages:
        trust = json.loads(keys_path.read_text(encoding="utf-8-sig"))
        if not isinstance(trust, dict) or not isinstance(trust.get("keys"), dict) or not trust["keys"]:
            raise RuntimeError("Initialize the private issuer's verification keys before building an extension release")
    command.extend(["--add-data", f"{keys_path}:resources"])
    if project_root != PUBLIC_ROOT:
        command.extend(["--paths", str(project_root)])
    # Dynamic module.py imports must be present in the frozen import archive.
    # PyInstaller's pkgutil runtime hook keeps startup discovery working.
    for package in ["basic", *extension_packages]:
        command.extend(["--collect-submodules", package, "--collect-data", package])
    for module in EXCLUDED_MODULES:
        command.extend(["--exclude-module", module])
    command.append(str(project_root / "main.py"))
    run_command(command, environment)
    dist_root = work_root / "dist"
    package_root = dist_root / name
    executable = (dist_root if onefile else package_root) / f"{name}.exe"
    if not executable.is_file():
        raise RuntimeError("PyInstaller did not produce the expected executable.")
    if onefile:
        run_command([
            str(python), "-c",
            "import sys; from PyInstaller.archive.readers import CArchiveReader; "
            "unexpected = [name for name in CArchiveReader(sys.argv[1]).toc "
            "if 'webengine' in name.lower() or 'webchannel' in name.lower()]; "
            "sys.exit(f'Unexpected Web terminal dependencies: {unexpected}' if unexpected else 0)",
            str(executable),
        ], environment)
        return executable
    for path in package_root.rglob("*"):
        if "webengine" in path.name.lower() or "webchannel" in path.name.lower():
            raise RuntimeError(f"Unexpected Web terminal dependency: {path.name}")
    return package_root


def publish_package(package_root: Path, project_root: Path, name: str) -> Path:
    release_name = f"{name}-{datetime.now():%Y%m%d-%H%M%S}"
    dist_root = project_root / "dist"
    dist_root.mkdir(parents=True, exist_ok=True)
    destination = dist_root / release_name
    if destination.exists() or destination.with_suffix(".zip").exists():
        raise RuntimeError(f"Output already exists: {destination}")
    # Each build gets a new directory; existing conf/history/logs are untouched.
    shutil.copytree(package_root, destination)
    archive = shutil.make_archive(
        str(destination), "zip", root_dir=dist_root, base_dir=release_name,
    )
    print(f"\nExecutable: {destination / (name + '.exe')}")
    print(f"Portable ZIP: {archive}")
    print("Keep the complete directory beside the executable when distributing it.")
    return destination


def publish_executable(executable: Path, project_root: Path, release_stem: str) -> Path:
    destination = project_root / "dist" / f"{release_stem}.exe"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with executable.open("rb") as source:
        output = destination.open("xb")
        try:
            with output:
                shutil.copyfileobj(source, output)
        except OSError:
            destination.unlink(missing_ok=True)
            raise
    print(f"\nExecutable: {destination}")
    return destination


def find_installer_compiler() -> str:
    compiler = shutil.which("ISCC.exe")
    if compiler:
        return compiler
    for variable in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        root = os.environ.get(variable)
        if root:
            candidate = Path(root) / ("Programs" if variable == "LOCALAPPDATA" else "") / "Inno Setup 6" / "ISCC.exe"
            if candidate.is_file():
                return str(candidate)
    raise RuntimeError("Install Inno Setup 6 or add ISCC.exe to PATH to build the installer.")


def stage_installer_runtime(python: Path, package_root: Path) -> None:
    qt_root = python.parent.parent / "Lib" / "site-packages" / "PySide6"
    for name in (
        "msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll",
        "vcruntime140.dll", "vcruntime140_1.dll",
    ):
        source = qt_root / name
        if not source.is_file():
            raise RuntimeError(f"PySide6 runtime DLL is missing: {source}")
        shutil.copy2(source, package_root / name)


def publish_release_formats(
    python: Path, executable: Path, package_root: Path, project_root: Path, name: str, version: str,
    compiler: str, work_root: Path, environment: dict[str, str], *, release_stem: str, installer_stem: str,
) -> None:
    archive = Path(shutil.make_archive(
        str(work_root / release_stem), "zip",
        root_dir=package_root.parent, base_dir=package_root.name,
    ))
    # Place the runtime beside the installed EXE, after the portable ZIP is sealed.
    stage_installer_runtime(python, package_root)
    run_command([
        compiler, f"/O{work_root}", f"/F{installer_stem}",
        f"/DProductName={name}", f"/DProductVersion={version}", f"/DPackageDir={package_root}",
        str(PUBLIC_ROOT / "packaging" / "installer.iss"),
    ], environment)
    installer = work_root / f"{installer_stem}.exe"
    if not installer.is_file():
        raise RuntimeError("Inno Setup did not produce the expected installer.")

    dist_root = project_root / "dist"
    for filename in (f"{release_stem}.exe", archive.name, installer.name):
        if (dist_root / filename).exists():
            raise RuntimeError(f"Output already exists: {dist_root / filename}")
    publish_executable(executable, project_root, release_stem)
    for source in (archive, installer):
        destination = dist_root / source.name
        shutil.move(source, destination)
        print(f"Package: {destination}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--release-name", help="Product name in versioned release filenames")
    parser.add_argument("--project-root", type=Path, default=PUBLIC_ROOT)
    parser.add_argument("--extension-package", action="append", default=[])
    formats = parser.add_mutually_exclusive_group()
    formats.add_argument("--onefile", action="store_true", help="Publish a single versioned portable EXE")
    formats.add_argument("--release-formats", action="store_true", help="Publish a standalone EXE, portable ZIP and installer")
    arguments = parser.parse_args()
    if sys.platform != "win32" or sys.version_info < (3, 10):
        parser.error("Use Windows with Python 3.10 or newer (Python 3.12 recommended).")
    if Path(arguments.name).name != arguments.name or arguments.name in (".", ".."):
        parser.error("--name must be a directory name without a path.")
    release_name = arguments.release_name or arguments.name
    if Path(release_name).name != release_name or release_name in (".", ".."):
        parser.error("--release-name must be a filename component without a path.")
    if (arguments.onefile or arguments.release_formats) and sysconfig.get_platform() != "win-amd64":
        parser.error("Use x64 Python to build the x64 release packages.")
    project_root = arguments.project_root.resolve()
    if not (project_root / "main.py").is_file():
        parser.error(f"Entry point not found: {project_root / 'main.py'}")
    for package in arguments.extension_package:
        if not package.isidentifier() or not (project_root / package / "__init__.py").is_file():
            parser.error(f"Extension package not found: {package}")
    environment = os.environ.copy()
    environment.pop("PYTHONHOME", None)
    environment["PYTHONPATH"] = os.pathsep.join(
        dict.fromkeys([str(PUBLIC_ROOT), str(project_root)]),
    )
    try:
        version = version_from_git(PUBLIC_ROOT)
        release_stem = f"{release_name}-x64-{version}"
        installer_stem = f"{release_name}-Setup-x64-{version}"
        print(f"PipeTerminal version: {version}", flush=True)
        compiler = find_installer_compiler() if arguments.release_formats else None
        python = prepare_environment(project_root, environment)
        build_root = project_root / "build" / "packaging"
        work_root = Path(tempfile.mkdtemp(prefix="run-", dir=build_root))
        package_root = build_package(
            python, project_root, arguments.name, arguments.extension_package,
            work_root, environment, version, onefile=arguments.onefile or arguments.release_formats,
        )
        if compiler:
            folder_work_root = work_root / "folder"
            folder_work_root.mkdir()
            folder = build_package(
                python, project_root, "PipeTerminal", arguments.extension_package,
                folder_work_root, environment, version,
            )
            publish_release_formats(
                python, package_root, folder, project_root, arguments.name, version, compiler, work_root, environment,
                release_stem=release_stem, installer_stem=installer_stem,
            )
        elif arguments.onefile:
            publish_executable(package_root, project_root, release_stem)
        else:
            publish_package(package_root, project_root, arguments.name)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"\nBuild failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
