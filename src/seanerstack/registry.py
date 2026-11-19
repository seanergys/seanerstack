# SPDX-License-Identifier: Apache-2.0
"""A small client of an OCI registry: a manifest under a tag, and its blobs.

Seanerstack keeps files of its own next to the binaries of a build cache, such
as the lockfile of the compiler, and reads and writes them itself, without
Spack. Only what that needs is here: the distribution API of OCI 1.1 over
HTTPS, with a GitLab container registry's token exchange.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from .config import Resource


MANIFEST_MEDIA_TYPE = "application/vnd.oci.image.manifest.v1+json"
TIMEOUT = 30


class RegistryError(RuntimeError):
    """A request that the registry refused or did not answer."""


@dataclass
class Registry:
    """One repository of a registry, as a build cache resource names it.

    @param base: the scheme and host, such as https://registry.example.org
    @param repository: the repository path, such as software/seanerstack/buildcache
    @param username: the user name, or None to read anonymously
    @param password: the password or token, or None to read anonymously
    """

    base: str
    repository: str
    username: str | None = None
    # Never in a printed Registry.
    password: str | None = field(default=None, repr=False)
    _token: str | None = field(default=None, repr=False)

    @classmethod
    def of(cls, resource: Resource, env) -> "Registry":
        """The repository of an OCI build cache, with its credentials from `env` where they are.

        @param resource: an OCI build cache
        @param env: the environment that holds the credential variables of the resource
        @return: the repository
        """
        if not resource.oci:
            raise ValueError(f"build cache {resource.name!r} is not in an OCI registry: {resource.url}")
        scheme, _, rest = resource.url.partition("://")
        host, _, repository = rest.partition("/")
        username, password = (env.get(name) for name in resource.credential_variables) if resource.credentials else (None, None)
        return cls(
            base=f"{'http' if scheme == 'oci+http' else 'https'}://{host}", repository=repository.strip("/"),
            username=username or None, password=password or None,
        )

    def _login(self, challenge: str) -> None:
        fields = dict(re.findall(r'(\w+)="([^"]*)"', challenge))
        query = urllib.parse.urlencode({key: fields[key] for key in ("service", "scope") if key in fields})
        headers = {}
        if self.username and self.password:
            basic = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
            headers["Authorization"] = f"Basic {basic}"
        request = urllib.request.Request(f"{fields['realm']}?{query}", headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                answer = json.load(response)
        except urllib.error.HTTPError as error:
            raise RegistryError(f"{self.base} refused the credentials for {self.repository}: HTTP {error.code}") from error
        self._token = answer.get("token") or answer["access_token"]

    def request(self, method: str, url: str, *, headers=None, data: bytes | None = None):
        """Send one request, logging in once when the registry asks for a token.

        @param method: the HTTP method
        @param url: a path below /v2/ of this repository, or an absolute URL the registry gave
        @param headers: more headers to send
        @param data: the body, or None
        @return: the status, the response headers and the body; 404 is an
            answer, any other error status raises RegistryError
        """
        if not url.startswith(("http://", "https://")):
            url = f"{self.base}/v2/{self.repository}/{url}"
        # The registry hands out a token per scope: a pull token does not push.
        for attempt in range(2):
            sent = dict(headers or {})
            if self._token:
                sent["Authorization"] = f"Bearer {self._token}"
            request = urllib.request.Request(url, method=method, headers=sent, data=data)
            try:
                with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                    return response.status, response.headers, response.read()
            except urllib.error.HTTPError as error:
                challenge = error.headers.get("WWW-Authenticate", "") if error.headers else ""
                if error.code == 401 and challenge.startswith("Bearer") and attempt == 0:
                    self._login(challenge)
                    continue
                if error.code == 404:
                    return error.code, error.headers, error.read()
                raise RegistryError(f"{method} {url}: HTTP {error.code}") from error
            except urllib.error.URLError as error:
                raise RegistryError(f"{method} {url}: {error.reason}") from error
        raise RegistryError(f"{method} {url}: the registry asked for a token again")

    def manifest(self, tag: str) -> dict | None:
        """The manifest under `tag`, or None when there is none.

        @param tag: the tag
        @return: the manifest
        """
        status, _, body = self.request("GET", f"manifests/{tag}", headers={"Accept": MANIFEST_MEDIA_TYPE})
        return None if status == 404 else json.loads(body)

    def blob(self, digest: str) -> bytes:
        """A blob, checked against its digest.

        @param digest: the digest, such as sha256:...
        @return: its content
        """
        status, _, body = self.request("GET", f"blobs/{digest}")
        if status == 404:
            raise RegistryError(f"{self.repository} has no blob {digest}")
        if f"sha256:{hashlib.sha256(body).hexdigest()}" != digest:
            raise RegistryError(f"the blob {digest} of {self.repository} does not match its digest")
        return body

    def put_blob(self, data: bytes) -> str:
        """Upload a blob in one request, unless the repository holds it.

        @param data: its content
        @return: its digest
        """
        digest = f"sha256:{hashlib.sha256(data).hexdigest()}"
        status, _, _ = self.request("HEAD", f"blobs/{digest}")
        if status == 200:
            return digest
        _, headers, _ = self.request("POST", "blobs/uploads/", data=b"")
        location = urllib.parse.urljoin(self.base, headers.get("Location", ""))
        separator = "&" if "?" in location else "?"
        self.request(
            "PUT", f"{location}{separator}digest={urllib.parse.quote(digest)}", data=data,
            headers={"Content-Type": "application/octet-stream"},
        )
        return digest

    def put_manifest(self, tag: str, manifest: dict) -> None:
        """Store a manifest under `tag`.

        @param tag: the tag
        @param manifest: the manifest, whose blobs the repository holds
        @return: nothing
        """
        body = json.dumps(manifest, separators=(",", ":")).encode()
        self.request("PUT", f"manifests/{tag}", data=body, headers={"Content-Type": MANIFEST_MEDIA_TYPE})
