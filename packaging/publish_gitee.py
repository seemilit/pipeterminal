"""Publish Windows packages to a Gitee release."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


def request_json(url: str, token: str, *, data=None, missing_ok=False):
    request = Request(
        url,
        data=urlencode(data).encode("utf-8") if data is not None else None,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=60) as response:
            return json.load(response)
    except HTTPError as error:
        if missing_ok and error.code == 404:
            return None
        raise RuntimeError(f"Gitee API request failed (HTTP {error.code}): {request.method} {url}") from None


def tag_commit(repository: str, tag: str) -> str | None:
    ref = f"refs/tags/{tag}"
    peeled = f"{ref}^{{}}"
    result = subprocess.run(
        ["git", "ls-remote", f"https://gitee.com/{repository}.git", ref, peeled],
        check=False, capture_output=True, text=True, timeout=60,
    )
    if result.returncode:
        raise RuntimeError("Could not read the release tag from Gitee.")
    refs = {}
    for line in result.stdout.splitlines():
        commit, remote_ref = line.split("\t", 1)
        refs[remote_ref] = commit
    return refs.get(peeled) or refs.get(ref)


def publish_release(repository: str, token: str, tag: str, commit: str, *packages: Path) -> None:
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+", repository):
        raise ValueError("GITEE_REPOSITORY must use owner/repo format.")
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("A version tag and the full public commit SHA are required.")
    if not token or not packages:
        raise ValueError("The Gitee release token and at least one package are required.")
    digests = {}
    for package in packages:
        if not package.is_file() or package.name in digests:
            raise ValueError(f"Missing package or duplicate filename: {package}")
        if package.stat().st_size > 100_000_000:
            raise ValueError(f"{package.name} exceeds the Gitee attachment limit (100 MB).")
        with package.open("rb") as source:
            digests[package.name] = hashlib.file_digest(source, "sha256").hexdigest()

    repository_url = f"https://gitee.com/api/v5/repos/{repository}"
    existing_commit = tag_commit(repository, tag)
    if existing_commit is None:
        request_json(f"{repository_url}/tags", token, data={"tag_name": tag, "refs": commit})
        existing_commit = tag_commit(repository, tag)
    if existing_commit != commit:
        raise RuntimeError(f"Gitee tag {tag} does not point to the built commit.")
    releases_url = f"{repository_url}/releases"
    release = request_json(f"{releases_url}/tags/{quote(tag, safe='')}", token, missing_ok=True)
    if release is None:
        checksums = "\n".join(f"- `{name}`: `{digest}`" for name, digest in digests.items())
        release = request_json(releases_url, token, data={
            "tag_name": tag,
            "target_commitish": commit,
            "name": f"PipeTerminal {tag[1:]}",
            "body": f"Windows downloads\n\nSHA-256:\n{checksums}",
        })
    if release["tag_name"] != tag or type(release["id"]) is not int:
        raise RuntimeError("Gitee returned an unexpected Release.")
    attachments_url = f"{releases_url}/{release['id']}/attach_files"
    uploaded = set()
    for attachment in request_json(attachments_url, token):
        name = attachment.get("name") or attachment.get("filename")
        if name not in digests:
            continue
        attachment_id = attachment["id"]
        if type(attachment_id) is not int:
            raise RuntimeError("Gitee returned an invalid attachment ID.")
        # Download the public asset without sending the publishing token to its host.
        with urlopen(f"{attachments_url}/{attachment_id}/download", timeout=120) as response:
            if hashlib.file_digest(response, "sha256").hexdigest() != digests[name]:
                raise RuntimeError(f"Gitee already has a different asset named {name}.")
        uploaded.add(name)
        print(f"Gitee already has the matching asset {name} for {tag}.", flush=True)

    for package in packages:
        if package.name not in uploaded:
            upload_attachment(attachments_url, token, package)


def upload_attachment(attachments_url: str, token: str, package: Path) -> None:
    print(f"Uploading {package.name} ({package.stat().st_size} bytes) to Gitee.", flush=True)
    curl = "curl.exe" if sys.platform == "win32" else "curl"
    result = subprocess.run([
        curl, "--fail", "--silent", "--show-error", "--http1.1",
        "--connect-timeout", "30", "--max-time", "10000",
        "--header", "@-", "--header", "Expect:", "--form", f"file=@{package.name}",
        "--output", os.devnull,
        "--write-out", f"Gitee upload ({package.name}): "
        "HTTP %{http_code}, sent %{size_upload} bytes in %{time_total}s\n",
        attachments_url,
    ], input=f"Authorization: Bearer {token}\n", text=True, check=False, cwd=package.parent)
    if result.returncode:
        raise RuntimeError(f"Gitee upload of {package.name} failed (curl exit {result.returncode}).")
    print(f"Published {package.name} to Gitee.", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag")
    parser.add_argument("commit")
    parser.add_argument("packages", type=Path, nargs="+")
    arguments = parser.parse_args()
    try:
        publish_release(
            os.environ.get("GITEE_REPOSITORY", ""), os.environ.get("GITEE_RELEASE_TOKEN", ""),
            arguments.tag, arguments.commit, *arguments.packages,
        )
    except (OSError, URLError, ValueError, RuntimeError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
        print(f"Gitee publishing failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
