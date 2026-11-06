"""Link Accounts: write-only credential storage outside the repo, admin passphrase,
and the server-side Sample / Live data mode.

    from accounts import get_data_mode   # "sample" | "live"

get_data_mode() is a read selector only; it never enables writes to ad accounts
(env ATLAS_ALLOW_LIVE=1 stays the only switch for that).
"""

from accounts.store import (admin_is_set, any_linked, any_tested, get_data_mode,  # noqa: F401
                            secrets_dir, set_data_mode)
