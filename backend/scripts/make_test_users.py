# -*- coding: utf-8 -*-
"""Generate the study accounts (P01…P32) handed to participants.

Writes two files from one run:

  backend/seed_users.json      user_id + password *hash* — committed, ships in the
                               Docker image, seeded into SQLite on every boot.
  test_accounts_<stamp>.csv    user_id + plaintext password — gitignored. This is
                               the sheet you hand out. Keep it; the hash cannot be
                               turned back into a password.

Passwords are shaped `abcd-4821` (no l/1/I/O/0) so they survive being read off a
screen, typed on a phone, or pasted into a chat message.

Usage (from repo root, venv active):

    python backend/scripts/make_test_users.py                 # P01…P32
    python backend/scripts/make_test_users.py --count 40      # more participants
    python backend/scripts/make_test_users.py --prefix Q --start 33
    python backend/scripts/make_test_users.py --append        # keep existing rows

Re-running without --append regenerates every password: everyone's old sheet
stops working the next time the seed runs with AGORA_SEED_USERS_RESET=1. Use
--append when you only need to add participants to a study already in the field.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import secrets
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from werkzeug.security import generate_password_hash  # noqa: E402

from user_store import validate_user_id  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEED_PATH = os.path.join(BACKEND_DIR, "seed_users.json")

# No l/1/I, no O/0 — misread characters cost a support message each.
LETTERS = "abcdefghjkmnpqrstuvwxyz"
DIGITS = "23456789"


def make_password() -> str:
    left = "".join(secrets.choice(LETTERS) for _ in range(4))
    right = "".join(secrets.choice(DIGITS) for _ in range(4))
    return f"{left}-{right}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate study accounts + credential sheet")
    ap.add_argument("--count", type=int, default=32, help="how many accounts (default 32)")
    ap.add_argument("--prefix", default="P", help="user id prefix (default P)")
    ap.add_argument("--start", type=int, default=1, help="first number (default 1)")
    ap.add_argument("--width", type=int, default=2, help="zero-pad width (default 2 → P01)")
    ap.add_argument("--append", action="store_true", help="keep existing seed rows, add new ones")
    ap.add_argument("--out-dir", default=REPO_ROOT, help="where to write the credential sheet")
    args = ap.parse_args()

    existing: list[dict] = []
    if args.append and os.path.isfile(SEED_PATH):
        with open(SEED_PATH, "r", encoding="utf-8") as fh:
            existing = (json.load(fh) or {}).get("users", [])
    taken = {u.get("user_id") for u in existing}

    rows: list[tuple[str, str]] = []
    users = list(existing)
    for n in range(args.start, args.start + args.count):
        uid = f"{args.prefix}{n:0{args.width}d}"
        if not validate_user_id(uid):
            print(f"✗ {uid} is not a valid user id (3–32 chars, letters/digits/_/-)")
            return 1
        if uid in taken:
            print(f"· {uid} already in seed file, left as is")
            continue
        password = make_password()
        users.append(
            {
                "user_id": uid,
                "password_hash": generate_password_hash(password, method="pbkdf2:sha256"),
                "is_admin": False,
            }
        )
        rows.append((uid, password))

    if not rows:
        print("Nothing to generate.")
        return 0

    payload = {
        "note": (
            "Study accounts seeded into SQLite on boot (user_store.seed_users_from_file). "
            "Hashes only — the plaintext sheet is gitignored, see scripts/make_test_users.py."
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "users": users,
    }
    with open(SEED_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    sheet = os.path.join(args.out_dir, f"test_accounts_{stamp}.csv")
    with open(sheet, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["user_id", "password"])
        w.writerows(rows)

    print(f"✓ {len(rows)} accounts: {rows[0][0]} … {rows[-1][0]}")
    print(f"✓ Seed (hashes, commit this): {SEED_PATH}")
    print(f"✓ Sheet (plaintext, do NOT commit): {sheet}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
