"""Detection of ~/.ssh/config aliases for a git URL and host rewriting.

Allows using the canonical URL copied from the remote (`git@github.com:org/repo.git`)
and, if there are local aliases pointing to that host, rewriting it to the chosen alias
(`git@gh-work:org/repo.git`) so git uses the correct key.
"""

from __future__ import annotations

import re
from typing import List, NamedTuple, Optional

from .sshcheck import _ssh_g, list_config_hosts, Echo


class AliasMatch(NamedTuple):
    alias: str
    hostname: str
    identity_files: List[str]


class AliasReport(NamedTuple):
    host: str                    # the real hostname (resolved if the input was an alias)
    current: Optional[str]       # alias currently in effect (input host if it is an alias)
    matches: List["AliasMatch"]  # all aliases in ~/.ssh/config pointing at 'host'


def split_ssh_url(url: str):
    """(scheme, user, host, rest) for SSH URLs; None if not SSH (e.g. https)."""
    url = url.strip()
    m = re.match(r"^ssh://(?:([^@]+)@)?([^:/]+)(.*)$", url)
    if m:
        return ("ssh", m.group(1), m.group(2), m.group(3))
    if "://" not in url:
        m = re.match(r"^(?:([^@]+)@)?([^:/]+):(.*)$", url)
        if m:
            return ("scp", m.group(1), m.group(2), m.group(3))
    return None


def url_host(url: str) -> Optional[str]:
    parts = split_ssh_url(url)
    return parts[2] if parts else None


def rewrite_host(url: str, new_host: str) -> str:
    """Returns the URL with the host replaced by new_host (alias)."""
    parts = split_ssh_url(url)
    if not parts:
        return url
    scheme, user, _host, rest = parts
    user = user or "git"
    if scheme == "scp":
        return f"{user}@{new_host}:{rest}"
    return f"ssh://{user}@{new_host}{rest}"


def matching_aliases(host: str, echo: Optional[Echo] = None) -> List[AliasMatch]:
    """Aliases from ~/.ssh/config whose resolved HostName matches 'host'.

    Excludes an alias whose name is the host itself (it adds no rewriting).
    """
    out: List[AliasMatch] = []
    for alias in list_config_hosts():
        if alias.lower() == host.lower():
            continue
        cfg, err = _ssh_g(alias, echo)
        if err:
            continue
        hostname = cfg.get("hostname", "")
        if hostname.lower() == host.lower():
            out.append(AliasMatch(alias, hostname, cfg.get("identityfile", [])))
    return out


def report_for_host(host: str, echo: Optional[Echo] = None) -> AliasReport:
    """Maps a host (or an alias) to the candidate ~/.ssh/config aliases.

    If `host` is itself an alias (its resolved HostName differs), the real
    hostname is used to find siblings and `current` records the active alias.
    This is what answers "which SSH alias should this repo use?".
    """
    real = host
    current: Optional[str] = None
    cfg, err = _ssh_g(host, echo)
    if not err:
        hostname = cfg.get("hostname", "")
        if hostname and hostname.lower() != host.lower():
            real = hostname
            current = host
    return AliasReport(host=real, current=current, matches=matching_aliases(real, echo))
