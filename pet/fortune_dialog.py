# -*- coding: utf-8 -*-
"""算命对象管理窗：可以存多个人，右键菜单按这里的名单展开。"""
from __future__ import annotations

import uuid

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .fortune import (
    MAX_PROFILES,
    SHICHEN_LABELS,
    explain_profile,
    load_profiles,
    profile_menu_label,
)


def _stylesheet(widget: QWidget) -> str:
    dark = widget.palette().color(QPalette.ColorRole.Window).lightness() < 128
    if dark:
        window, card, border = "#202024", "#2a2a30", "#3a3a42"
        text, hint, hover = "#e0e0e6", "#9a9aa3", "#303036"
    else:
        window, card, border = "#fcfcfd", "#ffffff", "#e2e4e8"
        text, hint, hover = "#252525", "#777777", "#f4f5f6"
    accent = "#0a84ff"
    return f"""
    QDialog, QWidget#fortuneBody {{
        background: {window};
        color: {text};
        font-size: 13px;
    }}
    QLabel#fortuneTitle {{
        font-size: 15px;
        font-weight: 600;
        color: {text};
        background: transparent;
    }}
    QLabel#fortuneHint, QLabel#fortuneStatus {{
        color: {hint};
        font-size: 12px;
        background: transparent;
    }}
    QLineEdit, QComboBox, QListWidget {{
        background: {card};
        color: {text};
        border: 1px solid {border};
        border-radius: 7px;
        padding: 4px 8px;
        min-height: 22px;
    }}
    QListWidget::item {{ padding: 6px 8px; }}
    QListWidget::item:selected {{ background: {accent}; color: #ffffff; }}
    QCheckBox {{ color: {text}; background: transparent; }}
    QPushButton {{
        background: {card};
        color: {text};
        border: 1px solid {border};
        border-radius: 7px;
        min-height: 26px;
        padding: 3px 14px;
    }}
    QPushButton:hover {{ background: {hover}; }}
    QPushButton:focus {{ border: 1px solid {accent}; }}
    QPushButton:disabled {{ color: {hint}; }}
    QPushButton[accent="true"] {{
        background: {accent};
        color: #ffffff;
        border: 1px solid {accent};
    }}
    """


class FortuneProfilesDialog(QDialog):
    """非模态。保存后立刻写入主配置，下次打开菜单就能选到。"""

    def __init__(self, config, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._profiles = load_profiles(config)
        self._editing_id = None
        self._filling = False
        self.setWindowTitle("算命对象")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setMinimumSize(640, 460)
        self._build()
        self.setStyleSheet(_stylesheet(self))
        self._reload_list(select=None)
        self._fill_blank()

    def reload_from_config(self) -> None:
        self._profiles = load_profiles(self._config)
        self._editing_id = None
        self._reload_list(select=None)
        self._fill_blank()
        self._status.setText("")

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)
        title = QLabel("算命对象")
        title.setObjectName("fortuneTitle")
        root.addWidget(title)
        hint = QLabel(
            "可以存多个人。排盘在这台电脑上算，解读用你现在 AI 对话里的模型。"
            "出生地只做记录，不换算真太阳时。只选子时、不填钟点时，按当天 0 点后的早子时排。"
        )
        hint.setObjectName("fortuneHint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        body = QHBoxLayout()
        body.setSpacing(12)
        self._list = QListWidget()
        self._list.setMinimumWidth(220)
        self._list.currentRowChanged.connect(self._on_row)
        body.addWidget(self._list, 2)

        form_host = QWidget()
        form_host.setObjectName("fortuneBody")
        form = QFormLayout(form_host)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)
        self._name = QLineEdit()
        self._name.setPlaceholderText("怎么称呼")
        self._sex = QComboBox()
        self._sex.addItem("男", "男")
        self._sex.addItem("女", "女")
        self._calendar = QComboBox()
        self._calendar.addItem("阳历", "solar")
        self._calendar.addItem("农历", "lunar")
        self._calendar.currentIndexChanged.connect(self._sync_leap)
        self._date = QLineEdit()
        self._date.setPlaceholderText("1990-05-15")
        self._leap = QCheckBox("闰月")
        self._shichen = QComboBox()
        for value, label in SHICHEN_LABELS:
            self._shichen.addItem(label, value)
        self._place = QLineEdit()
        self._place.setPlaceholderText("可选，例如上海")
        form.addRow("称呼", self._name)
        form.addRow("性别", self._sex)
        form.addRow("历法", self._calendar)
        form.addRow("生日", self._date)
        form.addRow("", self._leap)
        form.addRow("时辰", self._shichen)
        form.addRow("出生地", self._place)
        body.addWidget(form_host, 3)
        root.addLayout(body, 1)

        self._status = QLabel("")
        self._status.setObjectName("fortuneStatus")
        self._status.setWordWrap(True)
        root.addWidget(self._status)

        buttons = QHBoxLayout()
        create = QPushButton("新建")
        create.clicked.connect(self._new)
        remove = QPushButton("删除")
        remove.clicked.connect(self._delete)
        save = QPushButton("保存")
        save.setProperty("accent", True)
        save.clicked.connect(self._save)
        buttons.addWidget(create)
        buttons.addWidget(remove)
        buttons.addStretch(1)
        buttons.addWidget(save)
        root.addLayout(buttons)
        self._sync_leap()

    def _sync_leap(self) -> None:
        lunar = self._calendar.currentData() == "lunar"
        self._leap.setEnabled(lunar)
        if not lunar:
            self._leap.setChecked(False)

    def _fields(self) -> dict:
        return {
            "name": self._name.text(),
            "sex": self._sex.currentData(),
            "calendar": self._calendar.currentData(),
            "date": self._date.text(),
            "leap": self._leap.isChecked(),
            "shichen": self._shichen.currentData(),
            "place": self._place.text(),
        }

    def _fill_blank(self) -> None:
        self._filling = True
        self._name.clear()
        self._sex.setCurrentIndex(0)
        self._calendar.setCurrentIndex(0)
        self._date.clear()
        self._leap.setChecked(False)
        self._shichen.setCurrentIndex(0)
        self._place.clear()
        self._filling = False
        self._sync_leap()

    def _fill(self, profile: dict) -> None:
        self._filling = True
        self._editing_id = profile["id"]
        self._name.setText(profile["name"])
        self._sex.setCurrentIndex(0 if profile["sex"] == "男" else 1)
        self._calendar.setCurrentIndex(0 if profile["calendar"] == "solar" else 1)
        self._date.setText(profile["date"])
        self._leap.setChecked(bool(profile["leap"]))
        shichen_index = self._shichen.findData(profile["shichen"])
        self._shichen.setCurrentIndex(shichen_index if shichen_index >= 0 else 0)
        self._place.setText(profile["place"])
        self._filling = False
        self._sync_leap()

    def _reload_list(self, select: str | None) -> None:
        self._filling = True
        self._list.clear()
        selected_row = -1
        for index, profile in enumerate(self._profiles):
            label = profile_menu_label(profile, self._profiles)
            when = f"{profile['shichen']}时" if profile["shichen"] else "时辰未填"
            calendar = "农历" if profile["calendar"] == "lunar" else "阳历"
            leap = "闰" if profile["leap"] else ""
            self._list.addItem(f"{label}  {profile['sex']}  {calendar}{leap}{profile['date']} {when}")
            self._list.item(index).setData(Qt.ItemDataRole.UserRole, profile["id"])
            if profile["id"] == select:
                selected_row = index
        if selected_row >= 0:
            self._list.setCurrentRow(selected_row)
        self._filling = False

    def _on_row(self, row: int) -> None:
        if self._filling or row < 0:
            return
        item = self._list.item(row)
        if item is None:
            return
        profile_id = item.data(Qt.ItemDataRole.UserRole)
        profile = next((entry for entry in self._profiles if entry["id"] == profile_id), None)
        if profile is not None:
            self._fill(profile)

    def _new(self) -> None:
        self._editing_id = None
        self._fill_blank()
        self._filling = True
        self._list.clearSelection()
        self._list.setCurrentRow(-1)
        self._filling = False
        self._status.setText("填写后点保存")
        self._name.setFocus()

    def _save(self) -> None:
        profile_id = self._editing_id or uuid.uuid4().hex
        profile, error = explain_profile(self._fields(), profile_id=profile_id)
        if error:
            self._status.setText(error)
            return
        if self._editing_id is None and len(self._profiles) >= MAX_PROFILES:
            self._status.setText(f"最多保存 {MAX_PROFILES} 个人")
            return
        replaced = False
        updated = []
        for item in self._profiles:
            if item["id"] == profile["id"]:
                updated.append(profile)
                replaced = True
            else:
                updated.append(item)
        if not replaced:
            updated.append(profile)
        self._profiles = updated
        self._editing_id = profile["id"]
        if not self._persist():
            return
        self._reload_list(select=profile["id"])
        self._status.setText("已保存。右键桌宠 → AI算命，就能选到这个人")

    def _delete(self) -> None:
        if not self._editing_id:
            self._status.setText("先在左边选中一个人")
            return
        self._profiles = [item for item in self._profiles if item["id"] != self._editing_id]
        self._editing_id = None
        if not self._persist():
            return
        self._reload_list(select=None)
        self._fill_blank()
        self._status.setText("已删除")

    def _persist(self) -> bool:
        self._config.set("fortune_profiles", self._profiles)
        save = getattr(self._config, "save", None)
        if callable(save) and save() is False:
            self._status.setText("没保存上，请稍后再试")
            return False
        return True
