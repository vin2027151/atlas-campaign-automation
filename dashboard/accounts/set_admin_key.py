"""Set the Link Accounts admin passphrase. Run on the server as the app user:

    .venv/bin/python -m accounts.set_admin_key

Prompts twice with getpass (nothing echoed, nothing in env or shell history) and
stores only a salted PBKDF2-HMAC-SHA256 hash in $ATLAS_SECRETS_DIR/admin.json (default
~/.config/atlas-dashboard/admin.json, mode 0600).
"""

import getpass
import sys

from accounts import store


def main():
    # type: () -> int
    print("Admin passphrase for Link Accounts (at least %d characters)." % store.MIN_PASSPHRASE)
    print("Stored as a salted PBKDF2-HMAC-SHA256 hash in %s" % store.secrets_dir())
    if store.admin_is_set():
        print("A passphrase is already set; this replaces it.")
    p1 = getpass.getpass("New passphrase: ")
    p2 = getpass.getpass("Repeat: ")
    if p1 != p2:
        print("The two entries differ. Nothing changed.", file=sys.stderr)
        return 1
    try:
        store.set_admin_passphrase(p1)
    except ValueError as e:
        print("%s. Nothing changed." % e, file=sys.stderr)
        return 1
    print("Saved. Restart is not needed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
