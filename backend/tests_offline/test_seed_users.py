# -*- coding: utf-8 -*-
"""Acceptance for the pre-made study accounts (backend/seed_users.json):

  1. seeding    -> every entry in the shipped seed file becomes a real, non-admin
                   account whose password hash is the one in the file.
  2. idempotent -> a second boot creates nothing and touches nothing, so a
                   redeploy can never clobber a participant mid-study.
  3. intake     -> seeded profiles start empty; the participant fills intake.
  4. reset      -> AGORA_SEED_USERS_RESET restores the handout password and drops
                   live sessions, but keeps rooms/messages.
  5. bad input  -> a malformed or missing seed file is a no-op, not a crash.

No API key or network: this only touches SQLite.
"""
import json
import os
import sys
import tempfile

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)
os.chdir(tempfile.mkdtemp(prefix="seed_users_"))

from _harness import Checker  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402

import user_store  # noqa: E402

_ck = Checker(); check = _ck.check

SEED_PATH = user_store.DEFAULT_SEED_USERS_PATH
seed = json.load(open(SEED_PATH, encoding="utf-8"))["users"]
check("seed file ships accounts", len(seed) >= 1, SEED_PATH)
check("seed carries no plaintext", all("password" not in u for u in seed))
check("ids are valid", all(user_store.validate_user_id(u["user_id"]) for u in seed))
check("ids are unique", len({u["user_id"] for u in seed}) == len(seed))
check("none are admin", not any(u.get("is_admin") for u in seed))

store = user_store.UserStore(os.path.join(os.getcwd(), "seedtest.db"))

# -------------------------------------------------------------- seeding (3)
created, skipped, reset = store.seed_users_from_file(SEED_PATH)
check("all seeded on first boot", (created, skipped, reset) == (len(seed), 0, 0),
      f"{created}/{skipped}/{reset}")
ids = {u["user_id"] for u in store.list_users()}
check("every account exists", {u["user_id"] for u in seed} <= ids)

first = seed[0]["user_id"]
detail = store.get_user_detail(first)
check(f"{first} is a plain participant", detail and not detail["is_admin"], detail)

# ----------------------------------------------------------- idempotent (2)
again = store.seed_users_from_file(SEED_PATH)
check("second boot is a no-op", again == (0, len(seed), 0), again)

# -------------------------------------------------------------- intake (1)
check("profile starts empty", store.get_profile(first)["profile"] == {})

# --------------------------------------------------------------- reset (4)
# Stand in for a real handout password: rewrite one entry with a known one.
tmp_seed = os.path.join(os.getcwd(), "seed_one.json")
KNOWN = "sheet-password"
json.dump({"users": [{"user_id": first,
                      "password_hash": generate_password_hash(KNOWN, method="pbkdf2:sha256")}]},
          open(tmp_seed, "w", encoding="utf-8"))

store.create_chat_room("room-seed-test", first, scenario_type="employment", title="in flight")
store.admin_set_password(first, "participant-changed-it")
token = store.login(first, "participant-changed-it")[0]["token"]

check("reset without flag leaves password alone",
      store.seed_users_from_file(tmp_seed) == (0, 1, 0)
      and store.login(first, KNOWN)[0] is None)

check("reset restores the handout password",
      store.seed_users_from_file(tmp_seed, reset=True) == (0, 0, 1)
      and store.login(first, KNOWN)[0] is not None)
check("reset invalidates old sessions", store.resolve_token(token) is None)
check("reset keeps the participant's rooms",
      [r["room_id"] for r in store.list_chat_rooms(first)] == ["room-seed-test"])

# ----------------------------------------------------------- bad input (3)
check("missing file is a no-op", store.seed_users_from_file("nope.json") == (0, 0, 0))
open("garbage.json", "w").write("not json {")
check("unparseable file is a no-op", store.seed_users_from_file("garbage.json") == (0, 0, 0))
json.dump({"users": [{"user_id": "x", "password_hash": ""},   # id too short, no hash
                     {"user_id": "GoodOne", "password_hash": "h"}]},
          open("mixed.json", "w", encoding="utf-8"))
check("malformed rows skipped, good row kept",
      store.seed_users_from_file("mixed.json") == (1, 0, 0)
      and store.get_user_detail("GoodOne") is not None)

_ck.finish("ALL CHECKS PASSED — study accounts seed cleanly and idempotently")
