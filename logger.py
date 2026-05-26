# -*- coding: utf-8 -*-
import logging
import logging.handlers
import os
import sys
import tempfile
from pathlib import Path


def _resolve_log_dir() -> Path:
    """Sprint C7.8: log dir דרך env override, עם fallback ל-home, ועם
    fallback סופי ל-tempdir. הלוגיקה:
      1. MEMSI_LOG_DIR אם מוגדר.
      2. אחרת ~/.memsi/logs.
      3. אם המקור הנבחר לא writable (UNC path, permission, disk full) —
         tempdir, עם warning ל-stderr כדי שמישהו יבחין.
    """
    env_dir = os.environ.get('MEMSI_LOG_DIR', '').strip()
    primary = Path(env_dir).expanduser() if env_dir else (Path.home() / '.memsi' / 'logs')
    try:
        primary.mkdir(parents=True, exist_ok=True)
        return primary
    except (OSError, PermissionError) as e:
        fallback = Path(tempfile.gettempdir()) / 'memsi_logs'
        try:
            fallback.mkdir(parents=True, exist_ok=True)
        except Exception:
            # אם גם tempdir נפל — אין הרבה מה לעשות; נחזיר אותו ונאפשר ל-FileHandler ליפול עם שגיאה ברורה.
            pass
        sys.stderr.write(
            f"WARN: cannot write logs to {primary}: {e}; falling back to {fallback}\n"
        )
        return fallback


_LOG_DIR = _resolve_log_dir()

_handler = logging.handlers.TimedRotatingFileHandler(
    _LOG_DIR / 'memsi.log',
    when='midnight',
    backupCount=30,
    encoding='utf-8',
)
_handler.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)-8s %(name)s — %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
))

logger = logging.getLogger('memsi')
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    logger.addHandler(_handler)
