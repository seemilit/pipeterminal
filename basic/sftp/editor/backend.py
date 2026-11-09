"""Read and publish remote text without modifying Qt widgets."""

import codecs
import posixpath
import stat
from dataclasses import dataclass
from uuid import uuid4

from common.i18n import tr
from ..backend import check_cancelled, open_sftp
from ..file_operations.backend import concrete_path


MAX_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class RemoteDocument:
    path: str
    original: bytes
    encoding: str
    newline: str
    text: str


def read_bytes(sftp, context, cancel, path):
    attributes = sftp.lstat(path)
    if not stat.S_ISREG(attributes.st_mode or 0):
        raise ValueError(tr("只能编辑普通文本文件"))
    if (attributes.st_size or 0) > MAX_BYTES:
        raise ValueError(tr("编辑器仅支持 4 MB 以内的文本文件"))
    blocks, length = [], 0
    with sftp.open(path, "rb") as source:
        while True:
            check_cancelled(context, cancel)
            data = source.read(min(65536, MAX_BYTES + 1 - length))
            if not data:
                break
            blocks.append(data)
            length += len(data)
            if length > MAX_BYTES:
                raise ValueError(tr("编辑器仅支持 4 MB 以内的文本文件"))
    return b"".join(blocks), attributes


def decode_document(path, data):
    if data.startswith(codecs.BOM_UTF8):
        encoding = "utf-8-sig"
    elif data.startswith(codecs.BOM_UTF16_LE):
        encoding = "utf-16-le"
    elif data.startswith(codecs.BOM_UTF16_BE):
        encoding = "utf-16-be"
    else:
        encoding = "utf-8"
    value = data[2:] if encoding.startswith("utf-16-") else data
    try:
        text = value.decode(encoding)
    except UnicodeError:
        encoding = "gb18030"
        text = data.decode(encoding)
    if "\0" in text or any(ord(char) < 32 and char not in "\r\n\t\f" for char in text):
        raise ValueError(tr("这不是可编辑的文本文件，请下载后打开"))
    newline = "\r\n" if "\r\n" in text else "\r" if "\r" in text and "\n" not in text else "\n"
    return RemoteDocument(path, data, encoding, newline, text)


def load(context, cancel, result, progress, path):
    with open_sftp(context, cancel) as sftp:
        path = concrete_path(sftp, path)
        data, _attributes = read_bytes(sftp, context, cancel, path)
        result["document"] = decode_document(path, data)


def encode_document(document, text):
    value = text.replace("\n", document.newline).encode(document.encoding)
    if document.encoding.startswith("utf-16-"):
        value = document.original[:2] + value
    if len(value) > MAX_BYTES:
        raise ValueError(tr("编辑器仅支持 4 MB 以内的文本文件"))
    return value


def save(context, cancel, result, progress, document, data):
    with open_sftp(context, cancel) as sftp:
        path = concrete_path(sftp, document.path)
        original, attributes = read_bytes(sftp, context, cancel, path)
        if original != document.original or path != document.path:
            raise ValueError(tr("服务器文件已变化，未覆盖，请另存本地后重新打开"))
        result["affected"] = (posixpath.dirname(path),)
        temporary = posixpath.join(posixpath.dirname(path), f".pipeterminal-edit-{uuid4().hex}.part")
        try:
            with sftp.open(temporary, "wx") as output:
                sftp.chmod(temporary, 0o600)
                for index in range(0, len(data), 65536):
                    check_cancelled(context, cancel)
                    output.write(data[index:index + 65536])
                output.flush()
            written = sftp.stat(temporary)
            if written.st_size != len(data):
                raise ValueError(tr("保存校验失败"))
            if attributes.st_uid is not None and attributes.st_gid is not None and (written.st_uid, written.st_gid) != (attributes.st_uid, attributes.st_gid):
                sftp.chown(temporary, attributes.st_uid, attributes.st_gid)
            sftp.chmod(temporary, stat.S_IMODE(attributes.st_mode or 0))
            latest, latest_attributes = read_bytes(sftp, context, cancel, path)
            if latest != document.original or (
                latest_attributes.st_mode, latest_attributes.st_uid, latest_attributes.st_gid
            ) != (attributes.st_mode, attributes.st_uid, attributes.st_gid):
                raise ValueError(tr("服务器文件已变化，未覆盖，请另存本地后重新打开"))
            check_cancelled(context, cancel)
            sftp.posix_rename(temporary, path)
            temporary = ""
            result["document"] = decode_document(path, data)
            result["selected_paths"] = (path,)
        finally:
            if temporary:
                try:
                    sftp.remove(temporary)
                except Exception:
                    result["leftovers"] = (temporary,)
