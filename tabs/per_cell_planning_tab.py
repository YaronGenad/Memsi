# -*- coding: utf-8 -*-
"""
tabs/per_cell_planning_tab.py — מסך "תכנון רכש פר-cell".

ה-use-case: מנהל-רכש בוחר סניף + מתרחיש (קונטקסט). המודל החדש
(forecast_weekly_cell) מחשב תחזית חודש-קדימה לכל קטגוריה בסניף, ומשווה
למלאי הנוכחי כדי להציע המלצת-הזמנה.

ההיגיון:
  recommended_order = max(0, forecast_next_month
                          + safety_stock(lead_time)
                          - current_stock)
"""
from __future__ import annotations
import math
from datetime import datetime
from typing import Optional

import pandas as pd
from qtpy.QtCore import Qt, QThread, Signal as pyqtSignal
from qtpy.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QPushButton, QComboBox, QSlider, QTableWidget, QTableWidgetItem,
    QHeaderView, QFileDialog, QMessageBox, QGridLayout,
)
from qtpy.QtGui import QColor, QBrush

from logger import logger
from domain_repository import get_branch_name


class PerCellForecastWorker(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(object)   # pd.DataFrame
    error = pyqtSignal(str)

    def __init__(self, branch: str, context: dict, parent=None):
        super().__init__(parent)
        self.branch = branch
        self.context = context

    def run(self):
        try:
            self.progress.emit("טוען נתונים ובונה פיצ'רים...")
            from forecast_weekly_cell import forecast_per_cell
            # branches=None מחזיר את כל הסניפים — נסנן בעצמנו
            res = forecast_per_cell(
                horizon_months=1,
                context=self.context,
                branches=[self.branch] if self.branch else None,
            )
            self.progress.emit(f"מחושב {len(res)} תחזיות")
            self.finished.emit(res)
        except Exception as e:
            import traceback
            logger.exception("PerCellForecastWorker failed")
            self.error.emit(traceback.format_exc())


class PerCellPlanningTab(QWidget):
    def __init__(self):
        super().__init__()
        self._df: Optional[pd.DataFrame] = None
        self._inventory: dict = {}  # (branch, sku) -> qty
        self._worker: Optional[PerCellForecastWorker] = None
        self._init_ui()
        self._load_branches()

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(10)

        title = QLabel("תכנון רכש פר-קטגוריה (מודל שבועי)")
        title.setStyleSheet("font-size:18px; font-weight:bold; padding:6px;")
        layout.addWidget(title)

        explain = QLabel(
            "תחזית חודש קדימה פר (סניף × קטגוריה), עם המלצת רכש לפי lead-time וקונטקסט. "
            "המודל מאומן על שבוע × סניף × קטגוריה (~70,000 נקודות-אימון)."
        )
        explain.setWordWrap(True)
        explain.setStyleSheet("color:#555; padding:4px;")
        layout.addWidget(explain)

        # ─── בחירת סניף ───────────────────────────────
        branch_row = QHBoxLayout()
        branch_row.addWidget(QLabel("סניף:"))
        self.branch_combo = QComboBox()
        self.branch_combo.setMinimumWidth(250)
        branch_row.addWidget(self.branch_combo)
        branch_row.addStretch()
        layout.addLayout(branch_row)

        # ─── Sliders ל-context ────────────────────────
        ctx_group = QGroupBox("הקשר נוכחי (Sliders)")
        ctx_grid = QGridLayout()

        # Lead time
        self.lead_slider, self.lead_label = self._make_slider(
            2, 21, 7, "ימי אספקה מהמרלו\"ג"
        )
        ctx_grid.addWidget(QLabel("ימי אספקה:"), 0, 0)
        ctx_grid.addWidget(self.lead_slider, 0, 1)
        ctx_grid.addWidget(self.lead_label, 0, 2)

        # Anxiety
        self.anx_slider, self.anx_label = self._make_slider(0, 10, 3, "חרדה")
        ctx_grid.addWidget(QLabel("חרדה (0=רגוע, 10=קיצונית):"), 1, 0)
        ctx_grid.addWidget(self.anx_slider, 1, 1)
        ctx_grid.addWidget(self.anx_label, 1, 2)

        # Economy open
        self.eco_slider, self.eco_label = self._make_slider(0, 10, 10, "פתיחות משק")
        ctx_grid.addWidget(QLabel("פתיחות המשק (0=סגור, 10=שגרה):"), 2, 0)
        ctx_grid.addWidget(self.eco_slider, 2, 1)
        ctx_grid.addWidget(self.eco_label, 2, 2)

        # Flight capacity
        self.fly_slider, self.fly_label = self._make_slider(0, 10, 10, "כושר טיסה")
        ctx_grid.addWidget(QLabel("כושר טיסה (0=שמיים סגורים, 10=שגרה):"), 3, 0)
        ctx_grid.addWidget(self.fly_slider, 3, 1)
        ctx_grid.addWidget(self.fly_label, 3, 2)

        # Consumer spending
        self.spend_slider, self.spend_label = self._make_slider(0, 10, 8, "הוצאה")
        ctx_grid.addWidget(QLabel("הוצאה צרכנית (0=חיסכון חירום, 10=ביקוש כבוש):"), 4, 0)
        ctx_grid.addWidget(self.spend_slider, 4, 1)
        ctx_grid.addWidget(self.spend_label, 4, 2)

        ctx_grid.setColumnStretch(1, 1)
        ctx_group.setLayout(ctx_grid)
        layout.addWidget(ctx_group)

        # Quick presets
        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("preset מהיר:"))
        for name, vals in [
            ("שגרה", (3, 10, 10, 8)),
            ("מבצע מוגבל", (6, 7, 7, 6)),
            ("מלחמה פעילה", (8, 5, 4, 4)),
            ("Peak attack", (10, 2, 2, 2)),
            ("התאוששות", (3, 9, 9, 10)),
        ]:
            btn = QPushButton(name)
            btn.setStyleSheet("padding:4px 10px;")
            btn.clicked.connect(lambda _=False, v=vals: self._apply_preset(v))
            preset_row.addWidget(btn)
        preset_row.addStretch()
        layout.addLayout(preset_row)

        # ─── כפתורים ───────────────────────────────
        btn_row = QHBoxLayout()
        self.compute_btn = QPushButton("חשב המלצות")
        self.compute_btn.setStyleSheet(
            "QPushButton { background:#0a7; color:white; padding:8px 18px; "
            "font-weight:bold; border-radius:4px; }"
            "QPushButton:disabled { background:#aaa; }"
        )
        self.compute_btn.clicked.connect(self._on_compute)
        btn_row.addWidget(self.compute_btn)

        self.export_btn = QPushButton("ייצא לאקסל")
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self._on_export)
        btn_row.addWidget(self.export_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # Status
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#555; padding:2px;")
        layout.addWidget(self.status_label)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "קטגוריה", "תחזית חודש קדימה",
            "מלאי נוכחי", "מינימום נדרש (lead+safety)",
            "מומלץ להזמין", "פער",
        ])
        self.table.setStyleSheet("""
            QHeaderView::section {
                background:#34495e; color:white; padding:8px;
                font-weight:bold; border:none; border-right:1px solid #2c3e50;
            }
            QTableWidget::item { padding:6px 10px; }
        """)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        layout.addWidget(self.table, 1)

        self.setLayout(layout)

    def _make_slider(self, mn, mx, val, name):
        s = QSlider(Qt.Horizontal)
        s.setMinimum(mn)
        s.setMaximum(mx)
        s.setValue(val)
        s.setTickPosition(QSlider.TicksBelow)
        s.setTickInterval(1)
        lbl = QLabel(str(val))
        lbl.setStyleSheet("font-weight:bold; min-width:30px;")
        s.valueChanged.connect(lambda v, l=lbl: l.setText(str(v)))
        return s, lbl

    def _apply_preset(self, vals):
        anx, eco, fly, spend = vals
        self.anx_slider.setValue(anx)
        self.eco_slider.setValue(eco)
        self.fly_slider.setValue(fly)
        self.spend_slider.setValue(spend)

    def _load_branches(self):
        """טוען רשימת סניפים-זכאים מ-min_stock_calculator."""
        try:
            from min_stock_calculator import eligible_branches
            branches = eligible_branches()
            for b in branches:
                name = get_branch_name(b) or ''
                label = f"{b} - {name}" if name else b
                self.branch_combo.addItem(label, b)
        except Exception as e:
            logger.exception("Failed to load branches")
            QMessageBox.warning(self, "אזהרה", f"לא ניתן לטעון רשימת סניפים: {e}")

    def _build_context(self):
        # קבלת passengers על-פי flight_capacity (סקלה)
        flight = self.fly_slider.value()
        passengers = int(200_000 + (flight / 10) * 600_000)  # 200K..800K
        return {
            'anxiety': self.anx_slider.value(),
            'economy_open': self.eco_slider.value(),
            'flight_capacity': flight,
            'consumer_spending': self.spend_slider.value(),
            'arriving_passengers': passengers,
        }

    def _on_compute(self):
        branch = self.branch_combo.currentData()
        if not branch:
            QMessageBox.warning(self, "אזהרה", "אנא בחר סניף")
            return

        if self._worker is not None and self._worker.isRunning():
            return

        self.compute_btn.setEnabled(False)
        self.export_btn.setEnabled(False)
        self.status_label.setText("מחשב…")
        self.table.setRowCount(0)

        ctx = self._build_context()
        self._worker = PerCellForecastWorker(branch, ctx, parent=self)
        self._worker.progress.connect(self.status_label.setText)
        self._worker.finished.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _load_inventory(self, branch):
        """טוען מלאי נוכחי פר-קטגוריה לסניף הנבחר."""
        try:
            import warnings
            warnings.filterwarnings('ignore', message='pandas only supports SQLAlchemy')
            from db_config import get_conn
            from domain_repository import identify_luggage
            with get_conn() as conn:
                df = pd.read_sql_query(
                    "SELECT sku, quantity FROM local_inventory WHERE warehouse_code = %s",
                    conn, params=(branch,)
                )
                # קטגוריה לכל SKU דרך תיאור
                desc = pd.read_sql_query("""
                    SELECT DISTINCT ON (partname) partname AS sku, topartdes AS desc
                    FROM logfile WHERE topartdes IS NOT NULL
                    ORDER BY partname, curdate DESC
                """, conn)
            df = df.merge(desc, on='sku', how='left')
            df['category'] = df['desc'].fillna('').apply(identify_luggage)
            df = df.dropna(subset=['category'])
            df = df[df['category'] != '']
            return df.groupby('category')['quantity'].sum().to_dict()
        except Exception as e:
            logger.exception("Failed loading inventory")
            return {}

    def _on_done(self, df: pd.DataFrame):
        self.compute_btn.setEnabled(True)
        if df is None or df.empty:
            self.status_label.setText("אין תחזיות לסניף הזה.")
            return

        branch = self.branch_combo.currentData()
        inventory_by_cat = self._load_inventory(branch)

        # מחשב המלצה
        lead_days = self.lead_slider.value()
        # safety stock פשוט: 50% מ-(תחזית-חודש × lead_days/30)
        rows = []
        for _, r in df.iterrows():
            cat = r['category']
            forecast_month = float(r['forecast'])
            current = float(inventory_by_cat.get(cat, 0))
            # נדרש = (תחזית-יומי × lead_days × 1.5) שזה כמו ב-min-stock
            daily_rate = forecast_month / 30.0
            min_required = math.ceil(daily_rate * lead_days * 1.5)
            min_required = max(1, min_required)
            recommended = max(0, math.ceil(min_required - current))
            gap = current - min_required
            rows.append({
                'category': cat,
                'forecast': round(forecast_month, 1),
                'current': int(current),
                'min_required': min_required,
                'recommended': recommended,
                'gap': int(gap),
            })

        out_df = pd.DataFrame(rows).sort_values('recommended', ascending=False)
        self._df = out_df
        self._fill_table(out_df)
        self.export_btn.setEnabled(True)
        total_rec = int(out_df['recommended'].sum())
        self.status_label.setText(
            f"{len(out_df)} קטגוריות, סה\"כ מומלץ להזמין: {total_rec}"
        )

    def _on_error(self, tb: str):
        self.compute_btn.setEnabled(True)
        self.status_label.setText("שגיאה")
        QMessageBox.critical(self, "שגיאה", tb[:1000])

    def _fill_table(self, df):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(df))
        for i, (_, r) in enumerate(df.iterrows()):
            cells = [
                r['category'],
                f"{r['forecast']:.1f}",
                str(r['current']),
                str(r['min_required']),
                str(r['recommended']),
                f"{r['gap']:+d}",
            ]
            for j, val in enumerate(cells):
                item = QTableWidgetItem(val)
                if j >= 1:
                    item.setTextAlignment(Qt.AlignCenter)
                if j == 4:  # recommended — צבע
                    rec = int(r['recommended'])
                    if rec > 5:
                        item.setForeground(QBrush(QColor(200, 0, 0)))
                    elif rec == 0:
                        item.setForeground(QBrush(QColor(0, 130, 0)))
                if j == 5:  # gap — אדום שלילי, ירוק חיובי
                    gap = int(r['gap'])
                    if gap < 0:
                        item.setForeground(QBrush(QColor(200, 0, 0)))
                    elif gap > 5:
                        item.setForeground(QBrush(QColor(0, 130, 0)))
                self.table.setItem(i, j, item)
        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(0, max(self.table.columnWidth(0), 200))
        self.table.setSortingEnabled(True)

    def _on_export(self):
        if self._df is None or self._df.empty:
            return
        branch = self.branch_combo.currentData()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        default = f"per_cell_plan_{branch}_{ts}.xlsx"
        path, _ = QFileDialog.getSaveFileName(
            self, "שמירה כאקסל", default, "Excel (*.xlsx)"
        )
        if not path:
            return
        df = self._df.copy()
        df.columns = ['קטגוריה', 'תחזית חודש', 'מלאי נוכחי',
                      'מינימום נדרש', 'מומלץ להזמין', 'פער']
        try:
            df.to_excel(path, index=False)
            QMessageBox.information(self, "נשמר", f"נשמר: {path}")
        except Exception as e:
            QMessageBox.critical(self, "שגיאה", str(e))
