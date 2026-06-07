# -*- coding: utf-8 -*-
"""
tabs/_supplier_ocr.py — Sprint C9.

OCR helper for handwritten vendor reports (Hebrew). Sends the image to
Anthropic Claude (sonnet-4-6) and asks for a structured JSON list of
repair rows. The user reviews/edits each row in a preview dialog before
anything hits the database.

Two entry points:
    extract_supplier_report(image_bytes) -> list[dict]
        Calls Claude vision and returns drafted rows.
    OcrPreviewDialog(parent, rows, vendor) -> QDialog
        Shows the editable table; on Accept, returns the corrected rows.

This module is import-safe even when the `anthropic` package is missing
or ANTHROPIC_API_KEY is unset — the import only fails at call time so the
rest of the GUI loads fine on machines that don't use OCR.
"""
from __future__ import annotations

import base64
import json
import os
from datetime import datetime

from qtpy.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QMessageBox, QComboBox, QHeaderView, QApplication,
)
from qtpy.QtCore import Qt

from logger import logger


CLAUDE_MODEL = 'claude-sonnet-4-6'

# Column order in the preview dialog. Must match the keys the OCR returns.
OCR_COLUMNS = [
    ('repair_date',  'תאריך (YYYY-MM-DD)'),
    ('branch_code',  'קוד סניף'),
    ('luggage_type', 'גודל מזוודה'),
    ('repair_notes', 'התיקון'),
    ('amount_due',   'סכום'),
]


_PROMPT_HE = """\
אתה רואה דוח ידני שנכתב בכתב יד של ספק חיצוני (תיקוני מזוודות בסניפי
חברה).

לכל שורה בדוח, חלץ את השדות הבאים והחזר אותם כ-JSON array של אובייקטים.

שדות (בעברית בכתב היד, באנגלית במפתחות JSON):
  - repair_date   : תאריך הפעולה ב-format YYYY-MM-DD. אם בכתב היד יש רק
                    DD/MM או DD/MM/YY — השלם לפי הקשר (השנה הנוכחית, חודש
                    שמופיע באותו עמוד). אם לא ברור — החזר null.
  - branch_code   : קוד סניף קצר (לדוגמה "05", "23", "07", "800", או שם
                    סניף כמו "ביאליק"). העתק את מה שנכתב, לא לתרגם.
  - luggage_type  : גודל המזוודה (לדוגמה "גדולה", "טרולי", "ענקית" וכו').
                    אם נכתב מספר כמו "28" או "30" זו ביחידות אינץ' →
                    החזר ככה ("28″" ).
  - repair_notes  : תיאור התיקון ("רוכסן", "גלגל", "ידית" וכו') — כפי
                    שנכתב, ללא תרגום.
  - amount_due    : הסכום לתשלום כמספר (לדוגמה 70 או 120.50). ללא מטבע
                    או יחידה.

אם שדה לגמרי לא ברור או חסר — החזר null עבורו (לא להמציא). שורות ריקות
או כותרות — דלג עליהן.

החזר JSON תקין בלבד, ללא הסבר, ללא ```json markers. דוגמה לפורמט:

[
  {"repair_date": "2026-06-08", "branch_code": "ביאליק", "luggage_type": "20",
   "repair_notes": "ידית", "amount_due": 70},
  {"repair_date": "2026-06-10", "branch_code": "טבריה", "luggage_type": "28",
   "repair_notes": "גלגל", "amount_due": 90}
]
"""


def _get_client():
    """Lazy-imports anthropic so the module is loadable without the SDK.
    Returns the configured client or raises with a friendly Hebrew message."""
    key = os.environ.get('ANTHROPIC_API_KEY')
    if not key:
        raise RuntimeError(
            "חסר ANTHROPIC_API_KEY ב-.env. הוסף שורה ANTHROPIC_API_KEY=sk-... "
            "לקובץ .env והפעל מחדש."
        )
    try:
        import anthropic
    except ImportError as e:
        raise RuntimeError(
            "החבילה anthropic לא מותקנת. הרץ: pip install anthropic"
        ) from e
    return anthropic.Anthropic(api_key=key)


def extract_supplier_report(image_bytes: bytes, media_type: str = 'image/png',
                             model: str = CLAUDE_MODEL) -> list[dict]:
    """Send the image to Claude and return the parsed rows.

    Args:
        image_bytes: raw image content (PNG/JPEG).
        media_type:  MIME, defaults to image/png.
        model:       overridable for testing.

    Returns:
        list of dicts with keys repair_date, branch_code, luggage_type,
        repair_notes, amount_due. Values may be None for fields the OCR
        couldn't read.

    Raises:
        RuntimeError on missing API key / bad response / non-JSON output.
    """
    client = _get_client()
    b64 = base64.standard_b64encode(image_bytes).decode('ascii')

    resp = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{
            'role': 'user',
            'content': [
                {'type': 'image',
                 'source': {'type': 'base64',
                            'media_type': media_type,
                            'data': b64}},
                {'type': 'text', 'text': _PROMPT_HE},
            ],
        }],
    )

    txt = ''.join(b.text for b in resp.content if getattr(b, 'type', '') == 'text').strip()
    logger.info("OCR raw response length=%d", len(txt))

    if txt.startswith('```'):
        first_nl = txt.find('\n')
        if first_nl > 0:
            txt = txt[first_nl + 1:]
        if txt.endswith('```'):
            txt = txt[:-3].rstrip()

    try:
        rows = json.loads(txt)
    except json.JSONDecodeError as e:
        logger.exception("OCR returned non-JSON: %r", txt[:200])
        raise RuntimeError(
            f"Claude לא החזיר JSON תקין. הראשון 200 תווים:\n{txt[:200]}"
        ) from e

    if not isinstance(rows, list):
        raise RuntimeError(f"OCR returned non-list: {type(rows).__name__}")

    return rows


class OcrPreviewDialog(QDialog):
    """Shows OCR-drafted rows in an editable QTableWidget. User picks the
    vendor once, fixes mistakes inline, drops bad rows, and clicks "שמור הכל"
    — accepted rows are exposed via .get_rows()."""

    def __init__(self, parent, drafted: list[dict],
                  known_vendors: list[str] | None = None):
        super().__init__(parent)
        self.setWindowTitle("עיבוד דוח ספק - תוצאת OCR")
        self.resize(900, 600)

        v = QVBoxLayout(self)

        # Header: vendor selector
        top = QHBoxLayout()
        top.addWidget(QLabel("ספק (משווק) לכל השורות:"))
        self.vendor = QComboBox()
        self.vendor.setEditable(True)
        if known_vendors:
            self.vendor.addItems(known_vendors)
        top.addWidget(self.vendor, 1)
        v.addLayout(top)

        info = QLabel(
            f"OCR טייט {len(drafted)} שורות. תקן ידנית מה שצריך, מחק שורות "
            "שגויות (Delete), ולחץ 'שמור הכל' כשהכול נראה תקין."
        )
        info.setStyleSheet("color:#7f8c8d;padding:4px;")
        info.setWordWrap(True)
        v.addWidget(info)

        # Editable table
        self.table = QTableWidget(len(drafted), len(OCR_COLUMNS))
        self.table.setHorizontalHeaderLabels([h for _, h in OCR_COLUMNS])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for r, row in enumerate(drafted):
            for c, (key, _) in enumerate(OCR_COLUMNS):
                val = row.get(key)
                txt = '' if val is None else str(val)
                self.table.setItem(r, c, QTableWidgetItem(txt))
        v.addWidget(self.table, 1)

        # Bottom buttons
        btns = QHBoxLayout()
        del_btn = QPushButton("מחק שורה נבחרת")
        del_btn.clicked.connect(self._delete_selected)
        btns.addWidget(del_btn)
        btns.addStretch()
        cancel = QPushButton("ביטול")
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        save = QPushButton("שמור הכל")
        save.setStyleSheet(
            "QPushButton{background:#27ae60;color:white;font-weight:bold;padding:6px 18px;}")
        save.clicked.connect(self._accept)
        btns.addWidget(save)
        v.addLayout(btns)

    def _delete_selected(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.table.removeRow(r)

    def _accept(self):
        if not self.vendor.currentText().strip():
            QMessageBox.warning(self, "שגיאה", "חובה לבחור ספק.")
            return
        # Validate amount_due is numeric on every row.
        for r in range(self.table.rowCount()):
            amt_item = self.table.item(r, 4)
            txt = (amt_item.text() if amt_item else '').strip()
            if not txt:
                QMessageBox.warning(self, "שגיאה",
                                    f"שורה {r+1}: חסר סכום.")
                return
            try:
                float(txt)
            except ValueError:
                QMessageBox.warning(self, "שגיאה",
                                    f"שורה {r+1}: סכום לא תקין '{txt}'.")
                return
        self.accept()

    def get_rows(self) -> list[dict]:
        """Returns the corrected rows (after user accepted).
        Includes vendor (same for all)."""
        vendor = self.vendor.currentText().strip()
        out = []
        for r in range(self.table.rowCount()):
            row = {'vendor': vendor}
            for c, (key, _) in enumerate(OCR_COLUMNS):
                it = self.table.item(r, c)
                txt = (it.text() if it else '').strip()
                if key == 'amount_due':
                    row[key] = float(txt) if txt else 0.0
                else:
                    row[key] = txt or None
            out.append(row)
        return out


def grab_clipboard_image_bytes() -> bytes | None:
    """Read a PNG image from the clipboard. Returns None if no image."""
    cb = QApplication.clipboard()
    img = cb.image()
    if img.isNull():
        return None
    from qtpy.QtCore import QBuffer, QByteArray, QIODevice
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    img.save(buf, 'PNG')
    return bytes(buf.data())


def read_image_file_bytes(path: str) -> tuple[bytes, str]:
    """Return (bytes, media_type) for the image at path."""
    with open(path, 'rb') as f:
        data = f.read()
    ext = os.path.splitext(path)[1].lower()
    mt = 'image/png' if ext == '.png' else 'image/jpeg'
    return data, mt
