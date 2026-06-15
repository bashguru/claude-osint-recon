#!/usr/bin/env python3
"""
osint-recon : adsbexchange-analyst : creds.py
=============================================

A tiny, dependency-free store for ONE secret: the ADS-B Exchange API key (the
RapidAPI "API Lite" / Personal Use Aircraft Data key). The live-position checks and
the monitor read the key through here so it is never hard-coded, printed, or written
into a report.

This is separate from the oracle credential store used by `add-site`. That one holds
throwaway account passwords; this one holds the API key.

SAFETY MODEL (read this)
------------------------
  * The key is a password. NEVER echo it. `status` prints only whether a key exists
    plus a short, non-reversible fingerprint (first 4 + last 2 chars).
  * `get` refuses to print the key unless you pass --reveal (used only for manual
    debugging). The monitor imports resolve_key() instead of shelling out, so the
    key is never written to stdout in normal use.
  * The file store is written 0600 and auto-gitignored, and the script refuses to
    write it inside the plugin tree so it is never packaged or shared.
  * Redact the key from any error text before showing the analyst.

Resolution order (first source that has the key wins)
-----------------------------------------------------
  1. --key VALUE                 (explicit; discouraged on shared machines)
  2. --key-command 'CMD'         (custom manager; the command's stdout is the key)
  3. OS keychain                 (default on the analyst's machine; macOS `security`)
  4. $ADSBX_API_KEY              (environment variable)
  5. ./.adsbx-credentials.json   (gitignored local config, or $ADSBX_CREDENTIALS_FILE)

Commands
--------
  set     Store the key (read from stdin) into the keychain or the file store.
  status  Report whether a key is available and from where (fingerprint only).
  get     Print the key (requires --reveal). For manual debugging only.
  delete  Remove the stored key from the keychain or the file store.

Examples
--------
  printf 'YOUR_KEY\\n' | python3 creds.py set --store keychain
  python3 creds.py status
  printf 'YOUR_KEY\\n' | python3 creds.py set --store file
  python3 creds.py delete --store keychain
"""

import argparse
import json
import os
import stat
import subprocess
import sys

KEYCHAIN_SERVICE = "adsbx-api-key"
KEYCHAIN_ACCOUNT = "adsbexchange-analyst"
ENV_VAR = "ADSBX_API_KEY"
ENV_FILE = "ADSBX_CREDENTIALS_FILE"
DEFAULT_FILE = ".adsbx-credentials.json"
WARNING = ("ADS-B Exchange API key. Local secret: never share, commit, export, "
           "print, or include in any report or screenshot.")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def fingerprint(key):
    """Non-reversible hint so a human can tell which key is stored, without
    revealing it."""
    if not key:
        return "(none)"
    k = key.strip()
    if len(k) <= 8:
        return "%s… (%d chars)" % (k[:2], len(k))
    return "%s…%s (%d chars)" % (k[:4], k[-2:], len(k))


def file_path(args):
    return (getattr(args, "file", None)
            or os.environ.get(ENV_FILE)
            or os.path.join(os.getcwd(), DEFAULT_FILE))


def guard_not_in_plugin(path):
    """Refuse to write the secret store inside a plugin tree (it could be shared)."""
    p = os.path.abspath(path)
    if "osint-recon" + os.sep + "skills" in p or os.sep + ".claude-plugin" in p:
        raise SystemExit(
            "[!] Refusing to write the credential store inside the plugin tree:\n"
            "    %s\n"
            "    Put it in your working folder (or set $%s)." % (p, ENV_FILE))


def _ensure_gitignore(path):
    d = os.path.dirname(os.path.abspath(path)) or "."
    base = os.path.basename(path)
    gi = os.path.join(d, ".gitignore")
    entries = {base, DEFAULT_FILE}
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
            fh.write("# osint-recon adsbexchange-analyst API key (never commit)\n")
            for e in sorted(entries):
                fh.write(e + "\n")


# --------------------------------------------------------------------------- #
# Keychain backend (macOS `security`; degrades gracefully elsewhere)
# --------------------------------------------------------------------------- #

def _have_security():
    try:
        subprocess.run(["security", "help"], capture_output=True, timeout=5)
        return True
    except Exception:
        return False


def keychain_get():
    if not _have_security():
        return None
    try:
        r = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE,
             "-a", KEYCHAIN_ACCOUNT, "-w"],
            capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            key = r.stdout.strip()
            return key or None
    except Exception:
        return None
    return None


def keychain_set(key):
    if not _have_security():
        raise SystemExit("[!] The macOS 'security' tool is not available here. "
                         "Use --store file, or set $%s." % ENV_VAR)
    # -U updates if it already exists. Pass the key as the -w value.
    r = subprocess.run(
        ["security", "add-generic-password", "-s", KEYCHAIN_SERVICE,
         "-a", KEYCHAIN_ACCOUNT, "-U", "-w", key],
        capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        raise SystemExit("[!] Could not store the key in the keychain "
                         "(redacted error): %s" % _redact(r.stderr, key))


def keychain_delete():
    if not _have_security():
        return False
    r = subprocess.run(
        ["security", "delete-generic-password", "-s", KEYCHAIN_SERVICE,
         "-a", KEYCHAIN_ACCOUNT],
        capture_output=True, text=True, timeout=10)
    return r.returncode == 0


# --------------------------------------------------------------------------- #
# File backend
# --------------------------------------------------------------------------- #

def file_get(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        key = (data or {}).get("api_key")
        return key or None
    except Exception:
        return None


def file_set(path, key):
    guard_not_in_plugin(path)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"_warning": WARNING, "api_key": key}, fh, indent=2)
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0600
    except OSError:
        pass
    _ensure_gitignore(path)


def file_delete(path):
    if os.path.exists(path):
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"_warning": WARNING, "api_key": None}, fh, indent=2)
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
            return True
        except OSError:
            return False
    return False


# --------------------------------------------------------------------------- #
# Resolution (used by monitor.py as a module: from creds import resolve_key)
# --------------------------------------------------------------------------- #

def resolve_key(explicit=None, key_command=None, file=None):
    """Return (key, source) or (None, None). Never prints the key."""
    if explicit:
        return explicit.strip(), "argument"
    if key_command:
        try:
            r = subprocess.run(key_command, shell=True, capture_output=True,
                               text=True, timeout=15)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip(), "key-command"
        except Exception:
            pass
    k = keychain_get()
    if k:
        return k, "keychain"
    env = os.environ.get(ENV_VAR)
    if env and env.strip():
        return env.strip(), "env:%s" % ENV_VAR
    fpath = file or os.environ.get(ENV_FILE) or os.path.join(os.getcwd(), DEFAULT_FILE)
    k = file_get(fpath)
    if k:
        return k, "file:%s" % fpath
    return None, None


def _redact(text, key):
    if not text:
        return text
    if key:
        text = text.replace(key, "[REDACTED]")
    return text


def read_key_stdin():
    key = sys.stdin.readline().rstrip("\n")
    if not key:
        raise SystemExit("[!] No key read on stdin. Pipe it in, e.g. "
                         "printf 'YOUR_KEY\\n' | python3 creds.py set --store keychain")
    return key


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #

def cmd_set(args):
    key = read_key_stdin()
    if args.store == "keychain":
        keychain_set(key)
        print("[*] Stored API key in the macOS keychain (service '%s'). "
              "Fingerprint: %s" % (KEYCHAIN_SERVICE, fingerprint(key)))
    else:
        path = file_path(args)
        file_set(path, key)
        print("[*] Stored API key in %s (0600, gitignored). Fingerprint: %s"
              % (path, fingerprint(key)))
    print("    Reminder: never share, commit, or paste this key into a report.")


def cmd_status(args):
    key, source = resolve_key(explicit=args.key, key_command=args.key_command,
                              file=getattr(args, "file", None))
    if key:
        print("API key: AVAILABLE  source=%s  fingerprint=%s"
              % (source, fingerprint(key)))
    else:
        print("API key: NOT FOUND. Checked keychain, $%s, and the local config "
              "file. Run `creds.py set` to store one, or the skill can walk you "
              "through getting a key." % ENV_VAR)
        sys.exit(2)


def cmd_get(args):
    if not args.reveal:
        raise SystemExit("[!] Refusing to print the key without --reveal "
                         "(manual debugging only).")
    key, source = resolve_key(explicit=args.key, key_command=args.key_command,
                              file=getattr(args, "file", None))
    if not key:
        raise SystemExit("[!] No key available.")
    sys.stdout.write(key + "\n")


def cmd_delete(args):
    if args.store == "keychain":
        ok = keychain_delete()
        print("[*] Keychain entry %s." % ("removed" if ok else "not found"))
    else:
        path = file_path(args)
        ok = file_delete(path)
        print("[*] File store %s." % ("cleared" if ok else "not found"))


def build_parser():
    p = argparse.ArgumentParser(
        prog="creds.py",
        description="Store and resolve the ADS-B Exchange API key (local, never "
                    "shared, never echoed).")
    sub = p.add_subparsers(dest="command", required=True)

    def common(sp):
        sp.add_argument("--key", help="Explicit key (discouraged; for status/get only).")
        sp.add_argument("--key-command", help="Shell command whose stdout is the key.")
        sp.add_argument("--file", help="Path to the local config (default: "
                        "$%s or ./%s)." % (ENV_FILE, DEFAULT_FILE))

    s = sub.add_parser("set", help="Store the key (read from stdin).")
    s.add_argument("--store", choices=["keychain", "file"], default="keychain")
    s.add_argument("--file", help="Path to the local config when --store file.")
    s.set_defaults(func=cmd_set)

    st = sub.add_parser("status", help="Report whether a key is available (fingerprint only).")
    common(st)
    st.set_defaults(func=cmd_status)

    g = sub.add_parser("get", help="Print the key (requires --reveal; debugging only).")
    common(g)
    g.add_argument("--reveal", action="store_true")
    g.set_defaults(func=cmd_get)

    d = sub.add_parser("delete", help="Remove the stored key.")
    d.add_argument("--store", choices=["keychain", "file"], default="keychain")
    d.add_argument("--file", help="Path to the local config when --store file.")
    d.set_defaults(func=cmd_delete)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
