# SPDX-License-Identifier: Apache-2.0
"""Build the SEANERGYS toolchain and push it to a build cache."""
from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from .config import Resource


def _registry(resource: Resource) -> tuple[str, str]:
    scheme, _, rest = resource.url.partition("://")
    host, _, repository = rest.partition("/")
    return f"{'http' if scheme == 'oci+http' else 'https'}://{host}", repository


def _send(url: str, method: str, headers: dict[str, str]):
    request = urllib.request.Request(url, method=method, headers=headers, data=b"" if method == "POST" else None)
    return urllib.request.urlopen(request, timeout=30)


def _bearer_token(challenge: str, username: str, password: str) -> str:
    fields = dict(re.findall(r'(\w+)="([^"]*)"', challenge))
    query = urllib.parse.urlencode({key: fields[key] for key in ("service", "scope") if key in fields})
    basic = base64.b64encode(f"{username}:{password}".encode()).decode()
    with _send(f"{fields['realm']}?{query}", "GET", {"Authorization": f"Basic {basic}"}) as response:
        answer = json.load(response)
    return answer.get("token") or answer["access_token"]


def check_push_access(resource: Resource, env) -> None:
    """Fail now, not when a build of hours tries its first push.

    Starting an upload needs write access and stores nothing. The registry only
    grants a token what its owner may do, so asking for a push token proves nothing.
    """
    if not resource.oci:
        return
    username, password = (env.get(name, "") for name in resource.credential_variables)
    base, repository = _registry(resource)
    uploads = f"{base}/v2/{repository}/blobs/uploads/"
    denied = (
        f"the credentials of {resource.name!r} cannot push to {resource.url}; "
        "a GitLab registry needs a token with write_registry"
    )
    headers: dict[str, str] = {}
    for _ in range(2):
        try:
            with _send(uploads, "POST", headers) as response:
                location = urllib.parse.urljoin(base, response.headers.get("Location", ""))
        except urllib.error.HTTPError as error:
            challenge = error.headers.get("WWW-Authenticate", "")
            if error.code != 401 or headers or not challenge.startswith("Bearer"):
                raise RuntimeError(denied) from error
            try:
                headers = {"Authorization": f"Bearer {_bearer_token(challenge, username, password)}"}
            except urllib.error.HTTPError as login:
                raise RuntimeError(denied) from login
            continue
        try:
            _send(location, "DELETE", headers).close()
        except urllib.error.URLError:
            pass  # The registry drops an abandoned upload by itself.
        return
    raise RuntimeError(denied)
