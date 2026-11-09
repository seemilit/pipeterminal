"""Capture unmerged index stages on the worker; apply explicit UI resolutions."""

import codecs
from difflib import SequenceMatcher
from pathlib import Path, PurePosixPath
from common.i18n import tr
from .merge import GitMergeError


def resolve_conflicts(git, directory, left_label, right_label):
    directory = Path(directory).resolve()
    records = git._run(directory, "ls-files", "--unmerged", "-z", binary=True).stdout.split(b"\0")
    files = {}
    for record in records:
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        mode, oid, stage = metadata.decode("ascii").split()
        path = raw_path.decode("utf-8", "strict")
        relative = PurePosixPath(path)
        if relative.is_absolute() or ".." in relative.parts or "\\" in path or ":" in path:
            raise GitMergeError(tr("无法安全处理冲突路径：{0}", path))
        target = directory / path
        if not target.parent.resolve().is_relative_to(directory):
            raise GitMergeError(tr("无法安全处理冲突路径：{0}", path))
        item = files.setdefault(path, {"path": path, "stages": {}})
        size = int(git._run(directory, "cat-file", "-s", oid).stdout.strip()) if mode != "160000" else 0
        editable = mode in {"100644", "100755"} and size <= 2 * 1024 * 1024
        content = git._run(directory, "cat-file", "blob", oid, binary=True).stdout if editable else b""
        item["stages"][int(stage)] = {"mode": mode, "oid": oid, "content": content, "editable": editable}
    for item in files.values():
        item["text"] = all(stage["editable"] and b"\0" not in stage["content"] for stage in item["stages"].values())
        try:
            for stage in item["stages"].values():
                if stage["editable"] and b"\0" not in stage["content"]:
                    stage["text"] = stage["content"].decode("utf-8-sig")
        except UnicodeDecodeError:
            item["text"] = False
        path = directory / item["path"]
        preferred = item["stages"].get(2) or item["stages"].get(3) or item["stages"][1]
        raw = preferred["content"]
        encoding = "utf-8"
        if item["text"]:
            attributes = git._run(directory, "check-attr", "-z", "working-tree-encoding", "--", item["path"], binary=True).stdout.split(b"\0")
            value = attributes[2].decode("ascii", "replace") if len(attributes) >= 3 else "unspecified"
            if value not in {"unspecified", "unset", "set"}:
                encoding = value
            if path.is_file() and not path.is_symlink():
                raw = path.read_bytes()
            try:
                item["encoding"], item["bom"], decoded = _decode(raw, encoding)
                item["result"] = decoded
                item["original_text"] = decoded
                item["newline"] = "\r\n" if decoded.count("\r\n") > decoded.count("\n") - decoded.count("\r\n") else "\n"
            except (UnicodeError, LookupError):
                item["text"] = False
    from .conflict_session import FileMerge
    drafts = {path: FileMerge(item) for path, item in files.items()}
    resolutions = git.resolve({"files": list(files.values()), "left": str(left_label), "right": str(right_label), "drafts": drafts})
    if resolutions is None:
        raise GitMergeError(tr("已取消合并，当前操作已回退"))
    if set(resolutions) != set(files):
        raise GitMergeError(tr("仍有未解决的冲突"))
    for path, resolution in resolutions.items():
        item = files[path]
        choice, text = resolution
        if choice in {"left", "right"}:
            stage = item["stages"].get(2 if choice == "left" else 3)
            mode, oid = (stage["mode"], stage["oid"]) if stage else (None, None)
        elif choice == "delete":
            mode, oid = None, None
        elif choice == "text" and item["text"]:
            raw = item["bom"] + _line_endings(item["original_text"], text, item["newline"]).encode(item["encoding"])
            oid = git._run(directory, "hash-object", "-w", f"--path={path}", "--stdin", binary=True, input_data=raw).stdout.decode().strip()
            mode = item["stages"].get(2, item["stages"].get(3, {})).get("mode", "100644")
        else:
            raise GitMergeError(tr("仍有未解决的冲突"))
        if mode is None:
            git._run(directory, "update-index", "--force-remove", "--", path)
            target = directory / path
            if target.is_symlink() or target.is_file():
                target.unlink()
        else:
            git._run(directory, "update-index", "--add", "--cacheinfo", mode, oid, path)
            if mode != "160000":
                git._run(directory, "checkout-index", "--force", "--", path)
    if git._run(directory, "ls-files", "--unmerged", "-z", binary=True).stdout:
        raise GitMergeError(tr("仍有未解决的冲突"))


def _decode(raw, encoding):
    normalized = encoding.lower().replace("_", "-")
    if normalized in {"utf-16le-bom", "utf-16be-bom"}:
        normalized = normalized.replace("-bom", "")
    for bom, codec in ((codecs.BOM_UTF8, "utf-8"), (codecs.BOM_UTF32_LE, "utf-32-le"), (codecs.BOM_UTF32_BE, "utf-32-be"), (codecs.BOM_UTF16_LE, "utf-16-le"), (codecs.BOM_UTF16_BE, "utf-16-be")):
        if raw.startswith(bom):
            return codec, bom, raw[len(bom):].decode(codec)
    codec = codecs.lookup(normalized).name
    return codec, b"", raw.decode(codec)


def _line_endings(original, edited, default):
    old_lines = original.splitlines(keepends=True)
    new_lines = edited.replace("\r\n", "\n").splitlines(keepends=True)
    old_values = [line.rstrip("\r\n") for line in old_lines]
    new_values = [line.rstrip("\r\n") for line in new_lines]
    endings = {}
    for old, new, length in SequenceMatcher(None, old_values, new_values, autojunk=True).get_matching_blocks():
        for offset in range(length):
            line = old_lines[old + offset]
            endings[new + offset] = "\r\n" if line.endswith("\r\n") else "\r" if line.endswith("\r") else "\n"
    return "".join(line.rstrip("\r\n") + (endings.get(index, default) if line.endswith(("\r", "\n")) else "") for index, line in enumerate(new_lines))
