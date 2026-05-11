# -*- coding: utf-8 -*-
"""
errors.py — סיווג שגיאות לאפליקציה.

שלושה סוגים:
- ConfigError: בעיית קונפיגורציה. fail-fast ב-startup; אין מה לעשות בזמן-ריצה.
- TransientNetworkError: רעש זמני (Priority API נפל לרגע, DB אבד חיבור).
  הקוד אמור לנסות שוב, ובלוח-הזמנים — להציג למשתמש "נסה שוב".
- BusinessRuleError: פעולה לא חוקית מבחינה לוגית (למשל "כתיבה במצב offline").
  אין סיבה לנסות שוב; להציג למשתמש הסבר.

כל המחלקות חושפות to_user_message() שמחזיר טקסט בעברית מוכן להצגה ב-UI.
"""
from __future__ import annotations


class MemsiError(Exception):
    """Base class. אין לזרוק ישירות; השתמש בתת-מחלקות."""

    def to_user_message(self) -> str:
        return str(self)


class ConfigError(MemsiError):
    """משתנה סביבה חסר, קובץ קונפיגורציה לא נמצא, וכו'.

    זה fail-fast — אם זה קורה ב-startup, המשתמש צריך לתקן את הקונפיגורציה לפני
    שהאפליקציה תעבוד. אין retry.
    """

    def to_user_message(self) -> str:
        return f"שגיאת קונפיגורציה: {self}"


class TransientNetworkError(MemsiError):
    """שגיאת רשת/DB זמנית. ניתן לנסות שוב.

    דוגמאות:
    - Priority API החזיר HTTP 503.
    - postgres סירב חיבור (postgres לא רץ או הופסק זמנית).
    - timeout על בקשה איטית.

    הקוד הצרכן (worker/retry layer) צריך לתפוס TransientNetworkError ולהציג
    למשתמש אופציה "נסה שוב".
    """

    def to_user_message(self) -> str:
        return f"בעיה זמנית בחיבור: {self}\nנסה שוב בעוד רגע."


class BusinessRuleError(MemsiError):
    """פעולה לא חוקית מבחינה לוגית-עסקית.

    דוגמאות:
    - "כתיבה במצב offline" כש-DB לא זמין.
    - "אין הרשאות לערוך תיק זה".
    - "ניסיון לשמור מחיר שלילי".

    אין retry — צריך לתקן את הקלט או את ההקשר.
    """

    def to_user_message(self) -> str:
        return str(self)
