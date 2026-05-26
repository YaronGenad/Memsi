# -*- coding: utf-8 -*-
"""
config_check.py — בדיקות-תצורה לכניסה ל-CLI scripts.

Sprint C7.7: עד C7.6 ה-scripts (nightly_sync, load_flight_data, וכו')
עשו `os.environ['PRIORITY_AUTH_HEADER']` ישיר, ונפלו עם KeyError לא
ידידותי אם ה-.env לא נטען. עכשיו: assert_env_configured() כותב הודעה
ברורה ל-stderr ויוצא עם exit code 2 (config error).

שימוש בראש של script:

    from config_check import assert_env_configured
    assert_env_configured('PRIORITY_AUTH_HEADER', 'PRIORITY_BASE_URL')
"""
from __future__ import annotations
import os
import sys


def assert_env_configured(*keys: str) -> None:
    """וודא שכל ה-env vars מוגדרים (לא None ולא ריק).
    אם חסר אחד או יותר — exit עם הודעה ברורה ל-stderr."""
    missing = [k for k in keys if not os.environ.get(k)]
    if not missing:
        return
    sys.stderr.write(
        "ERROR: missing required environment variables:\n"
        + "\n".join(f"  - {k}" for k in missing)
        + "\n\nFix: edit .env (in the project root) or set them via shell.\n"
          "See .env.example for the full list.\n"
    )
    sys.exit(2)
