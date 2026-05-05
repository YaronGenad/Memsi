# -*- coding: utf-8 -*-
"""
tabs/_widgets.py - קומפוננטות UI משותפות לכל ה-tabs.

MonthYearPicker  - בחירת חודש+שנה (ComboBoxes), כמו שהיה ב-report_tab.
DateRangePicker  - בחירת חודש+שנה לתאריך התחלה ולתאריך סיום (לדוחות מרובי-חודשים).
ExcelExporter    - עזר ליצוא DataFrame או dict-של-DataFrames לקובץ אחד עם sheets.
"""
from __future__ import annotations
import calendar
from datetime import datetime
from typing import Iterable
import pandas as pd
from qtpy.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QComboBox, QGroupBox,
)
from qtpy.QtCore import Qt


# ────────────────────────────────────────────────
#  Pickers
# ────────────────────────────────────────────────
class MonthYearPicker(QWidget):
    """
    שלוש שליטות: חודש (01..12), שנה (year_min..year_max).
    מחזיר (year:int, month:int) דרך values().
    """

    def __init__(self, parent=None,
                 year_offset_back: int = 2,
                 year_offset_fwd: int = 2):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)

        h.addWidget(QLabel("חודש:"))
        self.month_combo = QComboBox()
        self.month_combo.addItems([f"{i:02d}" for i in range(1, 13)])
        self.month_combo.setCurrentText(f"{datetime.now().month:02d}")
        h.addWidget(self.month_combo)

        h.addWidget(QLabel("שנה:"))
        self.year_combo = QComboBox()
        cy = datetime.now().year
        self.year_combo.addItems(
            [str(y) for y in range(cy - year_offset_back, cy + year_offset_fwd + 1)]
        )
        self.year_combo.setCurrentText(str(cy))
        h.addWidget(self.year_combo)

    def values(self) -> tuple[int, int]:
        return int(self.year_combo.currentText()), int(self.month_combo.currentText())

    def date_range(self) -> tuple[str, str]:
        """מחזיר (YYYY-MM-01, YYYY-MM-LAST) לפי הבחירה."""
        y, m = self.values()
        last_day = calendar.monthrange(y, m)[1]
        return f"{y}-{m:02d}-01", f"{y}-{m:02d}-{last_day:02d}"

    def year_month(self) -> str:
        y, m = self.values()
        return f"{y}-{m:02d}"


class DateRangePicker(QGroupBox):
    """
    שני MonthYearPickers: 'מ-' ועד 'עד'. מחזיר (start_date_str, end_date_str).
    """
    def __init__(self, title: str = "טווח תאריכים",
                 parent=None,
                 year_offset_back: int = 2,
                 year_offset_fwd: int = 2):
        super().__init__(title, parent)
        v = QVBoxLayout(self)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("מ:"))
        self.start = MonthYearPicker(year_offset_back=year_offset_back,
                                     year_offset_fwd=year_offset_fwd)
        row1.addWidget(self.start, 1)
        v.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("עד:"))
        self.end = MonthYearPicker(year_offset_back=year_offset_back,
                                   year_offset_fwd=year_offset_fwd)
        row2.addWidget(self.end, 1)
        v.addLayout(row2)

    def date_range(self) -> tuple[str, str]:
        start, _ = self.start.date_range()
        _, end = self.end.date_range()
        return start, end


# ────────────────────────────────────────────────
#  ExcelExporter
# ────────────────────────────────────────────────
class ExcelExporter:
    """
    עוטף את הדפוס pd.ExcelWriter(filename) → df.to_excel(sheet=...) שחוזר ב-5 טאבים.

    שימוש:
        ExcelExporter('out.xlsx').sheets({'פירוט': df1, 'סיכום': df2}).save()

    או:
        ex = ExcelExporter('out.xlsx')
        ex.add('פירוט', df1)
        ex.add('סיכום', df2)
        ex.save()
    """
    MAX_SHEET_NAME_LEN = 31  # Excel limit

    def __init__(self, filename: str, engine: str = 'openpyxl'):
        self.filename = filename
        self.engine = engine
        self._sheets: list[tuple[str, pd.DataFrame]] = []

    def add(self, sheet_name: str, df: pd.DataFrame) -> 'ExcelExporter':
        if df is None or df.empty:
            return self
        # Excel sheet name לא יכול להיות יותר מ-31 תווים
        name = str(sheet_name)[:self.MAX_SHEET_NAME_LEN]
        # תווים אסורים בשמות sheet ב-Excel
        for bad in ['/', '\\', '*', '?', '[', ']', ':']:
            name = name.replace(bad, '_')
        self._sheets.append((name, df))
        return self

    def sheets(self, mapping: dict[str, pd.DataFrame]) -> 'ExcelExporter':
        for k, v in mapping.items():
            self.add(k, v)
        return self

    def save(self) -> str | None:
        """כותב את הקובץ. מחזיר את ה-filename או None אם אין מה לכתוב."""
        if not self._sheets:
            return None
        with pd.ExcelWriter(self.filename, engine=self.engine) as writer:
            for name, df in self._sheets:
                df.to_excel(writer, sheet_name=name, index=False)
        return self.filename


def slice_by_column(df: pd.DataFrame, column: str,
                    values: Iterable | None = None) -> dict[str, pd.DataFrame]:
    """
    עוזר נפוץ: חוצה DataFrame לפי ערכי עמודה למיפוי {value_str: subset}.
    שימושי לפני העברה ל-ExcelExporter.sheets().
    """
    out = {}
    series = df[column]
    keys = list(values) if values is not None else list(series.dropna().unique())
    for k in keys:
        sub = df[series == k]
        if not sub.empty:
            out[str(k)] = sub
    return out
