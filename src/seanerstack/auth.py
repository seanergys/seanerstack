# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

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
    return GitAuth(username=username, password=password)


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
