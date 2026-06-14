#!/usr/bin/env python3
"""
username-recon : oracle_store.py
================================

A tiny, dependency-free manager for **oracle credentials**, the throwaway test
accounts whose only job is to be a "known-existing username" so the engine and the
site-healing skill can keep a site's detection accurate over time.

Why this exists: once an analyst (or Claude) registers a disposable account on a
new site, storing it lets Claude re-verify the oracle is still alive and re-derive
indicators later WITHOUT bothering the analyst again. Detection itself is always
done logged out. These credentials are for maintenance, not for routine probing.

SAFETY MODEL (read this)
------------------------
  * Throwaway / dedicated test accounts ONLY. Never a personal or reused password.
  * The store lives OUTSIDE the plugin tree (so it is never packaged/shared) and is
    written with 0600 permissions. A sibling .gitignore is created automatically.
  * Passwords are MASKED in `list`/`get` unless you pass --reveal, so they are not
    echoed by accident. Never paste a stored password into a report, export, chat,
    or the evidence HTML.
  * Plaintext at rest: acceptable for disposable accounts, unacceptable for real
    ones. That is the whole reason for the throwaway-only rule.

Store location (resolution order)
---------------------------------
  1. --store PATH
  2. $USERNAME_RECON_ORACLE_STORE
  3. ./oracle-credentials.json   (current working directory)

Never place the store inside the plugin folder.

Commands
--------
  add     Add/update a site's oracle account.
  get     Show one site (password masked unless --reveal).
  list    List sites (passwords masked).
  remove  Delete a site's entry.

Examples
--------
  # Add (password read from stdin so it never lands in shell history/args):
  printf 'hunter2\\n' | python3 oracle_store.py add --site "Example" \\
      --username throwaway_oracle --email me+ex@example.org \\
      --url "https://example.com/{}" --password-stdin

  python3 oracle_store.py list
  python3 oracle_store.py get --site "Example"            # masked
  python3 oracle_store.py get --site "Example" --field password --reveal
"""

import argparse
import json
import os
import stat
import sys
from datetime import datetime, timezone

WARNING = ("Throwaway OSINT oracle accounts only. Never personal credentials. "
           "Local secret file: do not share, commit, export, or include in any "
           "report. Detection runs logged out; these are for maintenance only.")


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def store_path(args):
    return (args.store
            or os.environ.get("USERNAME_RECON_ORACLE_STORE")
            or os.path.join(os.getcwd(), "oracle-credentials.json"))


def guard_not_in_plugin(path):
    """Refuse to write the secret store inside a plugin tree (it could be shared)."""
    p = os.path.abspath(path)
    if "username-recon" + os.sep + "skills" in p or os.sep + ".claude-plugin" in p:
        raise SystemExit(
            "[!] Refusing to write the credential store inside the plugin tree:\n"
            f"    {p}\n"
            "    Put it in your project folder (or set $USERNAME_RECON_ORACLE_STORE).")


def load_store(path):
    if not os.path.exists(path):
        return {"_warning": WARNING, "sites": {}}
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    data.setdefault("sites", {})
    data["_warning"] = WARNING
    return data


def save_store(path, data):
    guard_not_in_plugin(path)
    data["_warning"] = WARNING
    # Write then lock down permissions (owner read/write only).
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0600
    except OSError:
        pass
    _ensure_gitignore(path)


def _ensure_gitignore(path):
    """Make sure the store filename is gitignored next to it."""
    d = os.path.dirname(os.path.abspath(path)) or "."
    base = os.path.basename(path)
    gi = os.path.join(d, ".gitignore")
    entries = {base, "oracle-credentials.json", "*.oracle.json"}
    existing = ""
    if os.path.exists(gi):
        with open(gi, "r", encoding="utf-8") as fh:
            existing = fh.read()
        have = set(line.strip() for line in existing.splitlines())
        entries = {e for e in entries if e not in have}
    if entries:
        with open(gi, "a", encoding="utf-8") as fh:
            if existing and not existing.endswith("\n"):
                fh.write("\n")
            fh.write("# username-recon oracle credential store (never commit)\n")
            for e in sorted(entries):
                fh.write(e + "\n")


def mask(pw):
    if not pw:
        return ""
    return "•" * 8


def read_password(args):
    if args.password_stdin:
        pw = sys.stdin.readline().rstrip("\n")
        if not pw:
            raise SystemExit("[!] --password-stdin set but nothing was read on stdin.")
        return pw
    return args.password  # may be None


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #

def cmd_add(args):
    path = store_path(args)
    guard_not_in_plugin(path)
    data = load_store(path)
    pw = read_password(args)
    entry = data["sites"].get(args.site, {})
    entry.update({
        "site": args.site,
        "username": args.username if args.username is not None else entry.get("username"),
        "password": pw if pw is not None else entry.get("password"),
        "email": args.email if args.email is not None else entry.get("email"),
        "url": args.url if args.url is not None else entry.get("url"),
        "notes": args.notes if args.notes is not None else entry.get("notes"),
        "throwaway": True,
        "updated": now_utc(),
    })
    entry.setdefault("created", now_utc())
    data["sites"][args.site] = entry
    save_store(path, data)
    print(f"[*] Stored oracle for '{args.site}' in {path} (password masked: {mask(entry.get('password'))})")
    print("    Reminder: throwaway accounts only; never share or export this file.")


def cmd_get(args):
    path = store_path(args)
    data = load_store(path)
    e = data["sites"].get(args.site)
    if not e:
        raise SystemExit(f"[!] No oracle stored for '{args.site}'.")
    if args.field:
        if args.field == "password" and not args.reveal:
            raise SystemExit("[!] Refusing to print password without --reveal.")
        print(e.get(args.field, ""))
        return
    view = dict(e)
    if not args.reveal:
        view["password"] = mask(view.get("password"))
    print(json.dumps(view, indent=2))


def cmd_list(args):
    path = store_path(args)
    data = load_store(path)
    sites = data.get("sites", {})
    if not sites:
        print(f"(no oracle accounts stored in {path})")
        return
    print(f"Oracle store: {path}  ({len(sites)} site(s))")
    for name in sorted(sites, key=str.lower):
        e = sites[name]
        print(f"  {name:<24} user={e.get('username','')!s:<22} "
              f"pw={mask(e.get('password'))}  url={e.get('url','')}")


def cmd_remove(args):
    path = store_path(args)
    data = load_store(path)
    if args.site not in data.get("sites", {}):
        raise SystemExit(f"[!] No oracle stored for '{args.site}'.")
    del data["sites"][args.site]
    save_store(path, data)
    print(f"[*] Removed oracle for '{args.site}'.")


def build_parser():
    p = argparse.ArgumentParser(
        prog="oracle_store.py",
        description="Manage throwaway oracle credentials for username-recon (local, "
                    "never shared). Detection runs logged out; these are for "
                    "keeping a site's oracle alive and re-deriving indicators.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    def add_store(sp):
        sp.add_argument("--store", help="Path to the credential store JSON (default: "
                        "$USERNAME_RECON_ORACLE_STORE or ./oracle-credentials.json).")

    a = sub.add_parser("add", help="Add or update a site's oracle account.")
    add_store(a)
    a.add_argument("--site", required=True)
    a.add_argument("--username")
    a.add_argument("--password", help="Avoid this on shared machines; prefer --password-stdin.")
    a.add_argument("--password-stdin", action="store_true",
                   help="Read the password from stdin (keeps it out of args/history).")
    a.add_argument("--email")
    a.add_argument("--url", help="Profile URL pattern with {} (for convenience/reference).")
    a.add_argument("--notes")
    a.set_defaults(func=cmd_add)

    g = sub.add_parser("get", help="Show one site (password masked unless --reveal).")
    add_store(g)
    g.add_argument("--site", required=True)
    g.add_argument("--field", choices=["site", "username", "password", "email", "url", "notes"])
    g.add_argument("--reveal", action="store_true", help="Reveal the password.")
    g.set_defaults(func=cmd_get)

    ls = sub.add_parser("list", help="List stored sites (passwords masked).")
    add_store(ls)
    ls.set_defaults(func=cmd_list)

    r = sub.add_parser("remove", help="Delete a site's oracle entry.")
    add_store(r)
    r.add_argument("--site", required=True)
    r.set_defaults(func=cmd_remove)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
