"""Discover upload artifacts without choosing a single preferred JAR."""
import fnmatch
import os
import re
import zipfile
from pathlib import Path
from common.i18n import tr


def jar_patterns(text):
    patterns = [part.strip() for part in re.split(r"[;；,，\n]+", text) if part.strip()]
    if any("/" in pattern or "\\" in pattern or pattern in {".", ".."} for pattern in patterns):
        raise ValueError(tr("JAR 筛选只填写文件名或通配符，不包含路径"))
    return patterns


def detect_jars(project, stop, filters=""):
    patterns = jar_patterns(filters)
    candidates = []
    matched = set()
    def scan_error(error):
        raise error

    for directory, folders, files in os.walk(project, followlinks=False, onerror=scan_error):
        if stop.is_set():
            raise RuntimeError(tr("执行已停止"))
        folders[:] = [name for name in folders if not (Path(directory) / name).is_symlink() and not getattr(Path(directory) / name, "is_junction", lambda: False)()]
        # Search Maven module target directories, as well as a directly selected output directory.
        if Path(directory) != Path(project) and Path(directory).name.lower() != "target":
            continue
        for name in sorted(files):
            if stop.is_set():
                raise RuntimeError(tr("执行已停止"))
            lower = name.lower()
            if not lower.endswith(".jar") or lower.startswith("original-") or lower.endswith(("-sources.jar", "-javadoc.jar", "-tests.jar", "-test.jar")):
                continue
            matching = [pattern for pattern in patterns if fnmatch.fnmatchcase(name, pattern)]
            if patterns and not matching:
                continue
            path = Path(directory) / name
            if path.is_symlink() or not path.is_file():
                continue
            try:
                with zipfile.ZipFile(path):
                    pass
            except (OSError, zipfile.BadZipFile) as error:
                raise ValueError(tr("无法读取 JAR：{0}", str(path))) from error
            candidates.append(path)
            matched.update(matching)
    if patterns and any(pattern not in matched for pattern in patterns):
        raise ValueError(tr("未匹配到 JAR：{0}", "; ".join(pattern for pattern in patterns if pattern not in matched)))
    if not candidates:
        raise ValueError(tr("未找到可上传的 JAR，请检查项目或产物目录"))
    names = {}
    for path in sorted(candidates):
        if path.name in names:
            raise ValueError(tr("不同目录存在同名 JAR：{0}", str(names[path.name]) + "\n" + str(path)))
        names[path.name] = path
    return sorted(candidates)


def select_jars(paths, filters=""):
    patterns = jar_patterns(filters)
    selected = [Path(path) for path in paths if not patterns or any(fnmatch.fnmatchcase(Path(path).name, pattern) for pattern in patterns)]
    missing = [pattern for pattern in patterns if not any(fnmatch.fnmatchcase(path.name, pattern) for path in selected)]
    if missing or not selected:
        raise ValueError(tr("未匹配到 JAR：{0}", "; ".join(missing or patterns)))
    names = {}
    for path in selected:
        if not path.is_file():
            raise ValueError(tr("上传来源不存在或类型不匹配：{0}", str(path)))
        if path.name in names:
            raise ValueError(tr("不同目录存在同名 JAR：{0}", str(names[path.name]) + "\n" + str(path)))
        names[path.name] = path
    return selected
