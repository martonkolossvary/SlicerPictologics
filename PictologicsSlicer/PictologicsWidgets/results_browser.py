"""Slicer/Qt-only browser, kept in a package to avoid scripted-module discovery."""

from __future__ import annotations

import copy

import qt
from PictologicsLib.result_browser import filter_result_indices, result_details, roi_identity


class ResultsBrowser:
    PAGE_SIZE = 200
    COLUMNS = (
        ("Feature", "feature_name"),
        ("Value", "value"),
        ("ROI", "roi_name"),
        ("Configuration", "configuration"),
        ("Family", "feature_family"),
        ("Status", "status"),
    )

    def __init__(self, parent, refresh):
        self.dialog = qt.QDialog(parent)
        self.dialog.setWindowTitle("Pictologics — results and provenance")
        self.dialog.resize(1100, 750)
        self.rows = []
        self.history = []
        self.indices = []
        self.page = 0
        self.roi_keys = [None]
        self.refresh_callback = refresh
        layout = qt.QVBoxLayout(self.dialog)
        self.source = qt.QLabel()
        self.source.setTextFormat(qt.Qt.PlainText)
        self.source.setWordWrap(True)
        layout.addWidget(self.source)
        search_row = qt.QHBoxLayout()
        self.search = qt.QLineEdit()
        self.search.setPlaceholderText(
            "Search feature name, IBSI code, native key, or preprocessing…"
        )
        search_row.addWidget(self.search)
        self.refresh_button = qt.QPushButton("Refresh selected table")
        search_row.addWidget(self.refresh_button)
        self.reset_button = qt.QPushButton("Clear filters")
        search_row.addWidget(self.reset_button)
        layout.addLayout(search_row)
        filters = qt.QGridLayout()
        self.filters = {}
        for index, (key, title) in enumerate(
            (
                ("roi", "ROI"),
                ("configuration", "Configuration"),
                ("family", "Family"),
                ("status", "Status"),
            )
        ):
            combo = qt.QComboBox()
            combo.setSizeAdjustPolicy(qt.QComboBox.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(18)
            filters.addWidget(qt.QLabel(title), index // 2, (index % 2) * 2)
            filters.addWidget(combo, index // 2, (index % 2) * 2 + 1)
            self.filters[key] = combo
            combo.connect("currentIndexChanged(int)", self.apply_filters)
        layout.addLayout(filters)
        splitter = qt.QSplitter(qt.Qt.Vertical)
        self.table = qt.QTableWidget()
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels([title for title, _ in self.COLUMNS])
        self.table.setEditTriggers(qt.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(qt.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(qt.QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        splitter.addWidget(self.table)
        self.details = qt.QPlainTextEdit()
        self.details.setReadOnly(True)
        splitter.addWidget(self.details)
        layout.addWidget(splitter)
        navigation = qt.QHBoxLayout()
        self.previous = qt.QPushButton("Previous")
        self.next = qt.QPushButton("Next")
        self.count = qt.QLabel()
        navigation.addWidget(self.previous)
        navigation.addWidget(self.count)
        navigation.addWidget(self.next)
        layout.addLayout(navigation)
        note = qt.QLabel(
            "Read-only snapshot. Filters affect this view only; Export still saves the full results table."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.search.connect("textChanged(QString)", self.apply_filters)
        self.table.connect("itemSelectionChanged()", self.show_details)
        self.previous.connect("clicked()", self.previous_page)
        self.next.connect("clicked()", self.next_page)
        self.reset_button.connect("clicked()", self.clear_filters)
        self.refresh_button.connect("clicked()", self.refresh)

    def refresh(self):
        self.refresh_callback()

    def set_data(self, name, rows, history, warning=""):
        self.rows, self.history = copy.deepcopy(rows), copy.deepcopy(history)
        self.source.setText(f"Snapshot: {name} — {len(rows)} feature rows. {warning}")
        self.roi_keys = [None]
        labels = []
        seen = set()
        for row in rows:
            key = roi_identity(row)
            if key not in seen:
                seen.add(key)
                self.roi_keys.append(key)
                labels.append(f"{row['roi_name']} | {row['image_name']} | run {row['run_id']}")
        for key, combo in self.filters.items():
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("All")
            values = (
                labels
                if key == "roi"
                else sorted(
                    {
                        str(
                            row[
                                {
                                    "configuration": "configuration",
                                    "family": "feature_family",
                                    "status": "status",
                                }[key]
                            ]
                        )
                        for row in rows
                    }
                )
            )
            combo.addItems(values)
            combo.blockSignals(False)
        self.clear_filters()

    def clear_filters(self):
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        for combo in self.filters.values():
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)
        self.apply_filters()

    def apply_filters(self, *args):
        self.page = 0
        roi_index = self.filters["roi"].currentIndex
        choices = {
            key: str(combo.currentText) if combo.currentIndex > 0 else ""
            for key, combo in self.filters.items()
            if key != "roi"
        }
        self.indices = filter_result_indices(
            self.rows,
            query=str(self.search.text),
            roi=self.roi_keys[roi_index] if roi_index >= 0 else None,
            **choices,
        )
        self.render_page()

    def render_page(self):
        start = self.page * self.PAGE_SIZE
        visible = self.indices[start : start + self.PAGE_SIZE]
        self.table.blockSignals(True)
        self.table.clearContents()
        self.table.setRowCount(len(visible))
        for view_index, row_index in enumerate(visible):
            row = self.rows[row_index]
            for column, (_, key) in enumerate(self.COLUMNS):
                value = row[key]
                item = qt.QTableWidgetItem("Not available" if value is None else str(value))
                item.setToolTip(str(value))
                self.table.setItem(view_index, column, item)
        self.table.resizeColumnsToContents()
        self.table.blockSignals(False)
        self.count.setText(
            f"{len(self.indices)} of {len(self.rows)} rows match; showing "
            f"{start + 1 if visible else 0}–{start + len(visible)}"
        )
        self.previous.setEnabled(self.page > 0)
        self.next.setEnabled(start + self.PAGE_SIZE < len(self.indices))
        if visible:
            self.table.selectRow(0)
        self.show_details()

    def previous_page(self):
        if self.page > 0:
            self.page -= 1
            self.render_page()

    def next_page(self):
        if (self.page + 1) * self.PAGE_SIZE < len(self.indices):
            self.page += 1
            self.render_page()

    def show_details(self):
        selected = self.table.currentRow()
        position = self.page * self.PAGE_SIZE + selected
        text = (
            result_details(self.rows[self.indices[position]], self.history)
            if selected >= 0 and position < len(self.indices)
            else "No matching result selected."
        )
        self.details.setPlainText(text)

    def close(self):
        self.dialog.close()
        self.set_data("No table", [], [])
