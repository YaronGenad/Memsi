# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QPushButton, QListWidget, QAbstractItemView, QCheckBox,
    QComboBox, QTableWidget, QTableWidgetItem, QSplitter,
    QTextEdit, QScrollArea, QFrame, QMessageBox, QProgressBar,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QColor

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from forecast_db import ForecastDB
from forecast_engine import run_all_models
from branch_names import get_display_label, get_branch_name


# ────────────────────────────────────────────────
#  Worker thread — מריץ מודלים ברקע
# ────────────────────────────────────────────────
class ForecastWorker(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(dict)
    error    = pyqtSignal(str)

    def __init__(self, series, horizon, events_df, context):
        super().__init__()
        self.series    = series
        self.horizon   = horizon
        self.events_df = events_df
        self.context   = context

    def run(self):
        try:
            import io, sys
            # הפנה print ל-signal
            class Emitter:
                def __init__(self, sig): self.sig = sig
                def write(self, s):
                    if s.strip(): self.sig.emit(s.strip())
                def flush(self): pass

            old_out = sys.stdout
            sys.stdout = Emitter(self.progress)
            results = run_all_models(self.series, self.horizon,
                                     self.events_df, self.context)
            sys.stdout = old_out
            self.finished.emit(results)
        except Exception as e:
            import traceback
            self.error.emit(traceback.format_exc())


# ────────────────────────────────────────────────
#  ווידג'ט גרף matplotlib
# ────────────────────────────────────────────────
class ForecastChart(QWidget):
    def __init__(self):
        super().__init__()
        self.figure  = Figure(figsize=(10, 4), tight_layout=True)
        self.canvas  = FigureCanvas(self.figure)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)

    def plot(self, history_series: pd.Series, results: dict, title: str):
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        ax.set_title(title, fontsize=11, pad=8)
        ax.set_xlabel("חודש")
        ax.set_ylabel("כמות")

        # היסטוריה
        hist_x = list(history_series.index)
        ax.plot(hist_x, history_series.values, color='#2c3e50',
                linewidth=2, label='היסטוריה', zorder=5)

        colors = {'arima': '#3498db', 'prophet': '#27ae60', 'xgboost': '#e67e22'}
        labels = {'arima': 'ARIMA', 'prophet': 'Prophet', 'xgboost': 'XGBoost'}

        for model, color in colors.items():
            if model not in results:
                continue
            df = results[model]
            ax.plot(df['year_month'], df['forecast'], color=color,
                    linewidth=2, linestyle='--', label=labels[model])
            ax.fill_between(df['year_month'], df['lower'], df['upper'],
                            color=color, alpha=0.12)

        # קו הפרדה היסטוריה/עתיד
        if hist_x:
            ax.axvline(x=hist_x[-1], color='gray', linestyle=':', linewidth=1)

        ax.set_xticks(range(0, len(hist_x) + len(results.get('arima', pd.DataFrame())), 3))
        all_months = hist_x + list(results.get('arima', pd.DataFrame()).get('year_month', []))
        tick_labels = [all_months[i] if i < len(all_months) else ''
                       for i in range(0, len(all_months), 3)]
        ax.set_xticklabels(tick_labels, rotation=45, ha='right', fontsize=8)
        ax.legend(fontsize=9)
        ax.grid(axis='y', alpha=0.3)
        self.canvas.draw()


# ────────────────────────────────────────────────
#  לשונית תחזיות
# ────────────────────────────────────────────────
class ForecastTab(QWidget):
    def __init__(self):
        super().__init__()
        self.fdb        = None
        self.results    = {}
        self.history_df = pd.DataFrame()
        self._init_ui()
        self._load_branches()

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(10)

        title = QLabel("לשונית תחזיות — ניתוח ביקוש עתידי")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #2c3e50;")
        title.setAlignment(Qt.AlignCenter)
        root.addWidget(title)

        splitter = QSplitter(Qt.Horizontal)

        # ── פאנל שמאל: בחירות ──────────────────────
        left = QWidget()
        left.setMaximumWidth(280)
        left_layout = QVBoxLayout(left)
        left_layout.setSpacing(8)

        # סניפים
        grp_branches = QGroupBox("סניפים")
        gl = QVBoxLayout(grp_branches)
        self.branch_list = QListWidget()
        self.branch_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self.branch_list.setMaximumHeight(160)
        gl.addWidget(self.branch_list)
        btn_all = QPushButton("בחר הכל")
        btn_all.clicked.connect(self.branch_list.selectAll)
        gl.addWidget(btn_all)
        left_layout.addWidget(grp_branches)

        # אופק תחזית
        grp_horizon = QGroupBox("אופק תחזית")
        hl = QVBoxLayout(grp_horizon)
        self.horizon_combo = QComboBox()
        self.horizon_combo.addItems(["חודש הבא (1)", "3 חודשים", "6 חודשים", "12 חודשים"])
        hl.addWidget(self.horizon_combo)
        left_layout.addWidget(grp_horizon)

        # קונטקסט נוכחי
        grp_ctx = QGroupBox("קונטקסט נוכחי")
        cl = QVBoxLayout(grp_ctx)
        self.cb_war     = QCheckBox("מלחמה פעילה")
        self.cb_op      = QCheckBox("מבצע צבאי")
        self.cb_cease   = QCheckBox("הפסקת אש")
        self.cb_passov  = QCheckBox("פסח (עונת שיא)")
        self.cb_highh   = QCheckBox("חגי תשרי (ר\"ה/סוכות)")
        self.cb_summer  = QCheckBox("קיץ (יולי-אוגוסט)")
        self.cb_weather = QCheckBox("מזג אוויר קיצוני")
        self.cb_cease.setChecked(True)
        for cb in [self.cb_war, self.cb_op, self.cb_cease, self.cb_passov,
                   self.cb_highh, self.cb_summer, self.cb_weather]:
            cl.addWidget(cb)
        left_layout.addWidget(grp_ctx)

        # כפתור הרצה
        self.run_btn = QPushButton("הרץ תחזית")
        self.run_btn.setStyleSheet("""
            QPushButton {
                background-color: #2980b9; color: white;
                font-size: 15px; font-weight: bold;
                padding: 10px; border-radius: 6px;
            }
            QPushButton:hover { background-color: #1f6891; }
            QPushButton:disabled { background-color: #bdc3c7; }
        """)
        self.run_btn.clicked.connect(self._run_forecast)
        left_layout.addWidget(self.run_btn)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)
        left_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("font-size: 11px; color: #555;")
        left_layout.addWidget(self.status_label)

        left_layout.addStretch()
        splitter.addWidget(left)

        # ── פאנל ימין: תוצאות ──────────────────────
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setSpacing(8)

        self.chart = ForecastChart()
        self.chart.setMinimumHeight(280)
        right_layout.addWidget(self.chart)

        # טבלת תוצאות
        self.result_table = QTableWidget(0, 5)
        self.result_table.setHorizontalHeaderLabels(
            ["חודש", "ARIMA", "Prophet", "XGBoost", "ממוצע"])
        self.result_table.setMaximumHeight(200)
        self.result_table.horizontalHeader().setStretchLastSection(True)
        self.result_table.setEditTriggers(QTableWidget.NoEditTriggers)
        right_layout.addWidget(self.result_table)

        # Newsvendor + הסברים
        grp_nv = QGroupBox("המלצת רכש (Newsvendor)")
        nv_layout = QHBoxLayout(grp_nv)
        self.nv_labels = {}
        for key, label in [('mean_demand','ביקוש ממוצע'),
                            ('safety_stock','מלאי בטחון'),
                            ('order_quantity','כמות מומלצת להזמנה')]:
            box = QVBoxLayout()
            title_lbl = QLabel(label)
            title_lbl.setAlignment(Qt.AlignCenter)
            title_lbl.setStyleSheet("font-size: 10px; color: #777;")
            val_lbl = QLabel("—")
            val_lbl.setAlignment(Qt.AlignCenter)
            val_lbl.setStyleSheet("font-size: 18px; font-weight: bold; color: #2c3e50;")
            box.addWidget(title_lbl)
            box.addWidget(val_lbl)
            nv_layout.addLayout(box)
            self.nv_labels[key] = val_lbl
        right_layout.addWidget(grp_nv)

        # הסברי מודלים
        self.desc_text = QTextEdit()
        self.desc_text.setReadOnly(True)
        self.desc_text.setMaximumHeight(90)
        self.desc_text.setStyleSheet("font-size: 11px; background: #f8f9fa;")
        right_layout.addWidget(self.desc_text)

        splitter.addWidget(right)
        splitter.setSizes([260, 800])
        root.addWidget(splitter)

    # ────────────────────────────────────────────
    #  טעינת סניפים
    # ────────────────────────────────────────────
    def _load_branches(self):
        try:
            self.fdb = ForecastDB()
            self.fdb.setup_tables()
            # רק סניפים שהיו פעילים ב-5 החודשים האחרונים
            active_branches = self.fdb.get_active_branches(inactive_months=5)
            self._branch_code_map = {}  # label → code
            self.branch_list.clear()
            for code in active_branches:
                label = get_display_label(code)
                self._branch_code_map[label] = code
                self.branch_list.addItem(label)
            total = len(self.fdb.get_branches())
            if active_branches:
                self.status_label.setText(
                    f"{len(active_branches)} סניפים פעילים (מתוך {total} בסה\"כ)")
            else:
                self.status_label.setText(
                    "אין נתונים — הרץ תחילה את backfill_history.py")
        except Exception as e:
            self.status_label.setText(f"שגיאת DB: {e}")

    # ────────────────────────────────────────────
    #  הרצת תחזית
    # ────────────────────────────────────────────
    def _get_horizon(self) -> int:
        mapping = {"חודש הבא (1)": 1, "3 חודשים": 3,
                   "6 חודשים": 6, "12 חודשים": 12}
        return mapping.get(self.horizon_combo.currentText(), 6)

    def _build_context(self) -> dict:
        ctx = {
            'is_war':         int(self.cb_war.isChecked()),
            'is_military_op': int(self.cb_op.isChecked()),
            'is_ceasefire':   int(self.cb_cease.isChecked()),
            'is_summer_peak': int(self.cb_summer.isChecked()),
        }
        if self.cb_passov.isChecked():
            ctx['jewish_holiday'] = 1
        elif self.cb_highh.isChecked():
            ctx['jewish_holiday'] = 2
        else:
            ctx['jewish_holiday'] = 0

        if ctx['is_war']:
            ctx['travel_impact'] = 'very_low'
        elif ctx['is_military_op']:
            ctx['travel_impact'] = 'low'
        elif ctx['is_summer_peak'] or ctx['jewish_holiday']:
            ctx['travel_impact'] = 'high'
        else:
            ctx['travel_impact'] = 'normal'
        return ctx

    def _run_forecast(self):
        selected_labels = [item.text() for item in self.branch_list.selectedItems()]
        if not selected_labels:
            QMessageBox.warning(self, "בחירה", "יש לבחור לפחות סניף אחד")
            return

        if not self.fdb:
            return

        # המרת תוויות חזרה לקודים לשליפת DB
        selected = [self._branch_code_map.get(lbl, lbl) for lbl in selected_labels]

        horizon    = self._get_horizon()
        context    = self._build_context()
        events_df  = self.fdb.get_events()
        hist_df    = self.fdb.get_history(branches=selected)

        if hist_df.empty:
            QMessageBox.warning(self, "נתונים", "אין היסטוריה לסניפים שנבחרו")
            return

        # אגרוג כל הסניפים שנבחרו ביחד
        agg = (hist_df.groupby('year_month')['quantity']
               .sum().sort_index())
        series = pd.Series(agg.values, index=agg.index)

        self.run_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.status_label.setText("מריץ מודלים...")

        self._worker = ForecastWorker(series, horizon, events_df, context)
        self._worker.progress.connect(self.status_label.setText)
        self._worker.finished.connect(self._on_results)
        self._worker.error.connect(self._on_error)
        self._worker.start()

        self._series = series
        self._selected_branches = selected

    def _on_results(self, results: dict):
        self.results = results
        self.run_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.status_label.setText("הושלם")

        title = f"תחזית — {', '.join(self._selected_branches[:3])}" + \
                ("..." if len(self._selected_branches) > 3 else "")
        self.chart.plot(self._series, results, title)
        self._fill_table(results)
        self._fill_newsvendor(results.get('newsvendor', {}))
        self._fill_descriptions(results.get('descriptions', {}))

    def _on_error(self, tb: str):
        self.run_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.status_label.setText("שגיאה — ראה פרטים בחלון")
        QMessageBox.critical(self, "שגיאה בהרצת מודלים", tb[:800])

    def _fill_table(self, results: dict):
        models = ['arima', 'prophet', 'xgboost']
        dfs    = {m: results[m].set_index('year_month') for m in models if m in results}
        months = results['arima']['year_month'].tolist() if 'arima' in results else []

        self.result_table.setRowCount(len(months))
        for row, ym in enumerate(months):
            self.result_table.setItem(row, 0, QTableWidgetItem(ym))
            vals = []
            for col, model in enumerate(models, start=1):
                v = int(dfs[model].loc[ym, 'forecast']) if ym in dfs.get(model, {}).index else 0
                vals.append(v)
                item = QTableWidgetItem(str(v))
                item.setTextAlignment(Qt.AlignCenter)
                self.result_table.setItem(row, col, item)
            avg_item = QTableWidgetItem(str(round(sum(vals) / len(vals))))
            avg_item.setTextAlignment(Qt.AlignCenter)
            avg_item.setBackground(QColor("#eaf4fb"))
            self.result_table.setItem(row, 4, avg_item)

    def _fill_newsvendor(self, nv: dict):
        for key, lbl in self.nv_labels.items():
            lbl.setText(str(nv.get(key, '—')))

    def _fill_descriptions(self, descs: dict):
        text = ""
        labels = {'arima': 'ARIMA', 'prophet': 'Prophet',
                  'xgboost': 'XGBoost', 'newsvendor': 'Newsvendor'}
        for model, desc in descs.items():
            text += f"<b>{labels.get(model, model)}:</b> {desc}<br>"
        self.desc_text.setHtml(text)
