# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import base64
from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import stat
import tempfile
from typing import Iterator, Mapping

from .config import Resource
from .secrets import SecretStore


@dataclass(frozen=True)
class GitAuth:
    username: str
    password: str
    url: str
    """The resource URL; credentials are sent only to URLs under it."""


def git_auth(resource: Resource, secrets: SecretStore) -> GitAuth | None:
    if resource.credentials is None:
        return None
    values = secrets.credentials(resource.credentials)
    username = values.get("username", "oauth2")
    password = values.get("password", values.get("token"))
    if not isinstance(username, str) or not isinstance(password, str):
        raise ValueError(
            f"credentials {resource.credentials!r} for {resource.name!r} require username/password or token"
        )
    return GitAuth(username=username, password=password, url=resource.url)


@contextmanager
def git_environment(auth: GitAuth | None) -> Iterator[Mapping[str, str]]:
    env = os.environ.copy()
    if auth is None:
        yield env
        return

    with tempfile.TemporaryDirectory(prefix="seanerstack-git-auth-") as temp:
        helper = Path(temp) / "askpass"
        helper.write_text(
            "#!/bin/sh\n"
            "case \"$1\" in\n"
            "  *sername*) printf '%s\\n' \"$SEANERSTACK_GIT_USERNAME\" ;;\n"
            "  *)         printf '%s\\n' \"$SEANERSTACK_GIT_PASSWORD\" ;;\n"
            "esac\n",
            encoding="utf-8",
        )
        helper.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        # Git otherwise sends credentials only after a 401, which a server
        # never answers for a public repository, so an invalid token would
        # go unnoticed. The header is set through the environment rather than
        # `git -c`, which would put it on the command line.
        index = int(env.get("GIT_CONFIG_COUNT") or 0)
        basic = base64.b64encode(f"{auth.username}:{auth.password}".encode("utf-8")).decode("ascii")
        env.update(
            {
                f"GIT_CONFIG_KEY_{index}": f"http.{auth.url}.extraHeader",
                f"GIT_CONFIG_VALUE_{index}": f"Authorization: Basic {basic}",
                "GIT_CONFIG_COUNT": str(index + 1),
            }
        )
        env.update(
            {
                "GIT_ASKPASS": str(helper),
                "GIT_TERMINAL_PROMPT": "0",
                "SEANERSTACK_GIT_USERNAME": auth.username,
                "SEANERSTACK_GIT_PASSWORD": auth.password,
            }
        )
        yield env


def http_auth_headers(auth: GitAuth | None) -> dict[str, str]:
    """Headers authenticating an HTTPS download from a Git resource.

    GitLab accepts a token as PRIVATE-TOKEN for repository archives; it does
    not accept HTTP basic authentication there.
    """
    if auth is None:
        return {}
    return {"PRIVATE-TOKEN": auth.password}


def spack_resource_environment(resource: Resource, secrets: SecretStore) -> dict[str, str]:
    if resource.credentials is None:
        return {}
    user_variable, secret_variable = resource.credential_variables
    if resource.oci:
        # A GitLab container registry takes the same user name and token as Git.
        auth = git_auth(resource, secrets)
        assert auth is not None
        return {user_variable: auth.username, secret_variable: auth.password}
    values = secrets.credentials(resource.credentials)
    access_key = values.get("access_key_id", values.get("access_key"))
    secret_key = values.get("secret_access_key", values.get("secret_key"))
    token = values.get("session_token", values.get("access_token"))
    if not isinstance(access_key, str) or not isinstance(secret_key, str):
        raise ValueError(
            f"credentials {resource.credentials!r} for {resource.name!r} require access_key_id and secret_access_key"
        )
    env = {user_variable: access_key, secret_variable: secret_key}
    if isinstance(token, str):
        env[f"{resource.env_prefix}_SESSION_TOKEN"] = token
    return env
