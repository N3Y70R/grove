"""Unit tests for the SSH account/zone model and read-only inventory."""

from grove.core import blockedit, sshprov
from grove.core import platform as plat


def _seed(home, ssh_config="", gitconfig="", identities=None):
    (home / ".ssh").mkdir(parents=True, exist_ok=True)
    if ssh_config:
        (home / ".ssh" / "config").write_text(ssh_config, encoding="utf-8")
    if gitconfig:
        (home / ".gitconfig").write_text(gitconfig, encoding="utf-8")
    idir = home / ".config" / "grove" / "identities"
    idir.mkdir(parents=True, exist_ok=True)
    for fname, text in (identities or {}).items():
        (idir / fname).write_text(text, encoding="utf-8")


def _paths(home):
    return plat.Paths(
        home=home, ssh_dir=home / ".ssh", ssh_config=home / ".ssh" / "config",
        gitconfig=home / ".gitconfig",
        identities_dir=home / ".config" / "grove" / "identities",
        backups_dir=home / ".config" / "grove" / "backups",
    )


SSH_CONFIG = """\
# my own host, untouched
Host legacy
    HostName example.com

# >>> grove:account=dropi-gh >>>
Host dropi-gh
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_ed25519_dropi_gh
    IdentitiesOnly yes
# <<< grove:account=dropi-gh <<<

# >>> grove:account=dropi-bb >>>
Host dropi-bb
    HostName bitbucket.org
    User git
    IdentityFile ~/.ssh/id_ed25519_dropi_bb
    IdentitiesOnly yes
# <<< grove:account=dropi-bb <<<
"""

GITCONFIG = """\
[user]
    name = Victor

# >>> grove:zone=dropi >>>
[includeIf "gitdir:{home}/dropi/"]
    path = {home}/.config/grove/identities/dropi.gitconfig
# <<< grove:zone=dropi <<<
"""

IDENTITY = """\
[user]
    email = victor.orobio@dropi.co
[url "git@dropi-bb:"]
    insteadOf = git@bitbucket.org:
    insteadOf = https://bitbucket.org/
[url "git@dropi-gh:"]
    insteadOf = git@github.com:
    insteadOf = https://github.com/
"""


def test_read_inventory_accounts_and_zone(tmp_path):
    home = tmp_path
    _seed(home, SSH_CONFIG, GITCONFIG.format(home=home.as_posix()),
          {"dropi.gitconfig": IDENTITY})
    inv = sshprov.read_inventory(_paths(home))

    assert [a.name for a in inv.accounts] == ["dropi-bb", "dropi-gh"]
    gh = next(a for a in inv.accounts if a.name == "dropi-gh")
    assert gh.host == "github.com"
    assert gh.key.endswith("id_ed25519_dropi_gh")

    assert len(inv.zones) == 1
    z = inv.zones[0]
    assert z.email == "victor.orobio@dropi.co"
    assert z.rewrites == {"bitbucket.org": "dropi-bb", "github.com": "dropi-gh"}


def test_routing_state(tmp_path):
    home = tmp_path
    _seed(home, SSH_CONFIG, GITCONFIG.format(home=home.as_posix()),
          {"dropi.gitconfig": IDENTITY})
    inv = sshprov.read_inventory(_paths(home))
    for a in inv.accounts:
        assert inv.routing_state(a) == "ok"
        assert inv.zone_of(a).scope_dir.endswith("/dropi/")


def test_routing_partial_when_rewrite_missing(tmp_path):
    home = tmp_path
    identity = """\
[user]
    email = x@y.z
[url "git@dropi-bb:"]
    insteadOf = git@bitbucket.org:
"""
    _seed(home, SSH_CONFIG, GITCONFIG.format(home=home.as_posix()),
          {"dropi.gitconfig": identity})
    inv = sshprov.read_inventory(_paths(home))
    gh = next(a for a in inv.accounts if a.name == "dropi-gh")
    bb = next(a for a in inv.accounts if a.name == "dropi-bb")
    assert inv.routing_state(bb) == "ok"
    assert inv.routing_state(gh) == "none"  # no rewrite references dropi-gh


def test_empty_when_no_files(tmp_path):
    inv = sshprov.read_inventory(_paths(tmp_path))
    assert inv.accounts == [] and inv.zones == []


def test_ignores_unmanaged_blocks(tmp_path):
    home = tmp_path
    _seed(home, SSH_CONFIG)
    inv = sshprov.read_inventory(_paths(home))
    assert all(a.name != "legacy" for a in inv.accounts)
