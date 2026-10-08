"""CLI adapters for the shared signing operations."""
from pathlib import Path

from ...core import signing, signingdoctor
from ...core.errors import UsageError
from .._shared import _base_dir, _common


def cmd_signing(args, out):
    kwargs = {"cwd": str(_base_dir(args)), "dry_run": args.dry_run, "echo": out.git_echo}
    if args.signing_command == "doctor":
        error = None
        if args.error_file:
            try:
                with Path(args.error_file).open("rb") as stream:
                    data = stream.read(signingdoctor.MAX_ERROR + 1)
                if len(data) > signingdoctor.MAX_ERROR:
                    raise UsageError("Signing error file exceeds 16 KiB; supply a short relevant excerpt.")
                error = data.decode("utf-8")
            except (OSError, UnicodeError) as exc:
                raise UsageError("Cannot read the signing error file as UTF-8.") from exc
        result = signingdoctor.diagnose(test=args.test, fix=args.fix, error_text=error, **kwargs)
        out.result = result
        out.message = "Signing diagnosis completed." if result["ok"] else "Signing diagnosis found pending problems."
        if not out.json_mode:
            for f in result["remaining_findings"]:
                out.warn(f["message"] + " " + f["action"])
            out.plain("Test: " + result["test"]["status"] + ". " + result["test"]["message"])
        return 0 if result["ok"] else 1
    result = signingdoctor.sanitize(signing.configure(enable=args.signing_command == "enable",
                                                      account=getattr(args, "account", None), key=getattr(args, "key", None),
                                                      scope=args.scope, scope_dir=args.scope_dir, **kwargs))
    out.result = result
    out.message = result["message"]
    if not out.json_mode:
        out.plain(result["message"])
        for change in result["changes"]:
            out.plain(f"{change['key']}: {change['before']} -> {change['after']} ({change['file']})")
        out.plain("Effective automatic signing: " + ("enabled" if result["enabled"] else "disabled"))
    return 0


def register_signing(sub):
    parser = sub.add_parser("signing", help="configure and diagnose SSH commit signing")
    commands = parser.add_subparsers(dest="signing_command", required=True)
    for name in ("enable", "disable", "doctor"):
        command = commands.add_parser(name, help={"enable": "enable SSH signing with an explicit key/account",
                                                 "disable": "remove Grove-managed signing settings",
                                                 "doctor": "diagnose signing and interpret previous errors"}[name])
        _common(command)
        command.add_argument("--dry-run", action="store_true", help="preview only; never configure, repair or sign")
        if name == "doctor":
            command.add_argument("--test", action="store_true", help="sign and verify a disposable commit; may execute the configured signer/key command")
            command.add_argument("--fix", action="store_true", help="restrict selected private-key permissions or attempt non-interactive agent loading")
            command.add_argument("--error-file", help="UTF-8 signing error to diagnose (maximum 16 KiB)")
        else:
            command.add_argument("--scope", choices=("repo", "zone"), required=True, help="shared repository config or existing identity zone")
            command.add_argument("--scope-dir", help="existing identity zone directory")
            if name == "enable":
                selection = command.add_mutually_exclusive_group(required=True)
                selection.add_argument("--account", help="existing Grove SSH account alias")
                selection.add_argument("--key", help="signing private/public key path")
        command.set_defaults(func=cmd_signing)
