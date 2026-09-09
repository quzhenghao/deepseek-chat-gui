from __future__ import annotations

from .. import ASSETS_DIR


ACCENT = "#4D6BFE"

_LIGHT = {
    "bg": "#FFFFFF",
    "side_bg": "#F6F8FC",
    "panel": "#FFFFFF",
    "canvas": "#FFFFFF",
    "border": "#E5EAF2",
    "border_strong": "#D6DDE9",
    "fg": "#182230",
    "fg_sub": "#667085",
    "fg_muted": "#98A2B3",
    "hover": "#EDF1F7",
    "selected": "#E9EDFF",
    "accent": ACCENT,
    "accent_hover": "#405CF2",
    "accent_soft": "#EEF1FF",
    "user_bubble": "#F0F2F6",
    "reason_bg": "#F7F8FB",
    "code_bg": "#F5F7FA",
    "danger": "#D92D20",
    "danger_soft": "#FFF1F0",
    "success": "#12B76A",
    "shadow": "#1A23331A",
}

_DARK = {
    "bg": "#1A1D24",
    "side_bg": "#14171D",
    "panel": "#20242D",
    "canvas": "#1A1D24",
    "border": "#303641",
    "border_strong": "#414958",
    "fg": "#F2F4F7",
    "fg_sub": "#B7C0CE",
    "fg_muted": "#7F8998",
    "hover": "#272C36",
    "selected": "#2B3355",
    "accent": "#6E85FF",
    "accent_hover": "#7D92FF",
    "accent_soft": "#293052",
    "user_bubble": "#2A2F39",
    "reason_bg": "#222731",
    "code_bg": "#151923",
    "danger": "#F97066",
    "danger_soft": "#3A2426",
    "success": "#32D583",
    "shadow": "#00000055",
}

THEMES = {"light": _LIGHT, "dark": _DARK}

# Shared sidebar geometry so the chat view and settings page always agree on
# the default width and keep a usable minimum when the user drags the handle.
SIDEBAR_DEFAULT_WIDTH = 300
SIDEBAR_MIN_WIDTH = 240


def colors(theme: str = "light") -> dict[str, str]:
    return THEMES.get(theme, _LIGHT)


def build_qss(theme: str = "light") -> str:
    c = colors(theme)
    arrow = (ASSETS_DIR / "chevron-down.svg").as_posix()
    arrow_up = (ASSETS_DIR / "chevron-up.svg").as_posix()
    check = (ASSETS_DIR / "check-white.svg").as_posix()
    return f"""
QWidget {{
    color: {c['fg']};
    font-size: 14px;
}}
QMainWindow, QDialog, QWidget#central, QWidget#chatPage, QWidget#welcomePage,
QWidget#settingsPage, QWidget#settingsRight, QWidget#settingsContent {{
    background: {c['bg']};
}}
QScrollArea#settingsScroll, QWidget#settingsHost {{
    background: {c['bg']};
    border: none;
}}
QWidget#sidebar, QWidget#settingsSidebar {{
    background: {c['side_bg']};
    border-right: 1px solid {c['border']};
}}
QSplitter#mainSplitter {{
    background: {c['side_bg']};
    border: none;
}}
QWidget#chatHeader, QWidget#settingsHeader {{
    background: {c['canvas']};
    border-bottom: 1px solid {c['border']};
}}
QWidget#composerArea {{
    background: {c['canvas']};
}}
QFrame#composerCard, QFrame#sectionCard {{
    background: {c['panel']};
    border: 1px solid {c['border_strong']};
    border-radius: 16px;
}}
QFrame#reasoningPanel {{
    background: {c['reason_bg']};
    border: 1px solid {c['border']};
    border-radius: 11px;
}}
QFrame#errorCard {{
    background: {c['danger_soft']};
    border: 1px solid {c['danger']};
    border-radius: 10px;
}}
QLabel#settingsBrand {{
    color: {c['fg']};
    font-size: 19px;
    font-weight: 650;
}}
QLabel#settingsPageTitle {{
    color: {c['fg']};
    font-size: 18px;
    font-weight: 650;
}}
QLabel#welcomeTitle {{
    color: {c['fg']};
    font-size: 26px;
    font-weight: 650;
}}
QLabel#sectionTitle {{
    color: {c['fg']};
    font-size: 15px;
    font-weight: 650;
}}
QLabel#subText, QLabel#hintLabel, QLabel#timeLabel, QLabel#metaLabel {{
    color: {c['fg_sub']};
}}
QLabel#tinyLabel {{
    color: {c['fg_muted']};
    font-size: 11px;
}}
QLabel#sectionLabel {{
    color: {c['fg_muted']};
    font-size: 11px;
    font-weight: 600;
}}
QLabel#visionChip, QLabel#statusChip {{
    color: {c['accent']};
    background: {c['accent_soft']};
    border-radius: 10px;
    padding: 4px 9px;
    font-size: 11px;
    font-weight: 600;
}}
QPushButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 9px;
    padding: 8px 12px;
}}
QPushButton:hover {{ background: {c['hover']}; }}
QPushButton:pressed {{ background: {c['selected']}; }}
QPushButton:disabled {{ color: {c['fg_muted']}; }}
QPushButton#suggestionBtn {{
    color: {c['fg_sub']};
    background: {c['panel']};
    border: 1px solid {c['border']};
    padding: 9px 13px;
}}
QPushButton#suggestionBtn:hover {{
    color: {c['fg']};
    border-color: {c['border_strong']};
    background: {c['hover']};
}}
QPushButton#thinkingBtn {{
    color: {c['fg_sub']};
    padding: 5px 9px;
}}
QPushButton#thinkingBtn:checked {{
    color: {c['accent']};
    background: {c['accent_soft']};
}}
QPushButton#primaryBtn {{
    color: #FFFFFF;
    background: {c['accent']};
    border-radius: 9px;
    font-weight: 600;
    padding: 8px 18px;
}}
QPushButton#primaryBtn:hover {{ background: {c['accent_hover']}; }}
QPushButton#dangerBtn {{ color: {c['danger']}; }}
QPushButton#dangerBtn:hover {{ background: {c['danger_soft']}; }}
QPushButton#settingsNavBtn {{
    color: {c['fg_sub']};
    background: transparent;
    border: 1px solid transparent;
    border-radius: 10px;
    text-align: left;
    padding: 10px 12px;
    font-weight: 550;
}}
QPushButton#settingsNavBtn:hover {{
    color: {c['fg']};
    background: {c['hover']};
}}
QPushButton#settingsNavBtn:checked {{
    color: {c['accent']};
    background: {c['accent_soft']};
    border-color: {c['selected']};
}}
QPushButton#settingsBackBtn, QPushButton#sidebarFooterBtn {{
    color: {c['fg_sub']};
    background: {c['panel']};
    border: 1px solid {c['border']};
    border-radius: 10px;
    text-align: left;
    padding: 9px 12px;
}}
QPushButton#settingsBackBtn:hover, QPushButton#sidebarFooterBtn:hover {{
    color: {c['fg']};
    background: {c['hover']};
    border-color: {c['border_strong']};
}}
QToolButton {{
    color: {c['fg_sub']};
    background: transparent;
    border: none;
    border-radius: 8px;
    padding: 5px;
}}
QToolButton:hover {{ color: {c['fg']}; background: {c['hover']}; }}
QToolButton:pressed {{ background: {c['selected']}; }}
QToolButton:disabled {{ color: {c['fg_muted']}; }}
QToolButton#actionBtn {{
    background: {c['accent']};
    border-radius: 18px;
    min-width: 36px;
    max-width: 36px;
    min-height: 36px;
    max-height: 36px;
    padding: 0;
}}
QToolButton#actionBtn:hover {{ background: {c['accent_hover']}; }}
QToolButton#actionBtn:disabled {{ background: {c['hover']}; }}
QToolButton#stopBtn {{
    background: {c['fg']};
    border-radius: 18px;
    min-width: 36px;
    max-width: 36px;
    min-height: 36px;
    max-height: 36px;
    padding: 0;
}}
QToolButton#reasonToggle {{
    color: {c['fg_sub']};
    text-align: left;
    padding: 2px 4px;
}}
QListWidget#convList {{
    background: transparent;
    border: none;
    outline: none;
}}
QListWidget#convList::item {{
    border-radius: 9px;
    margin: 1px 0;
}}
QListWidget#convList::item:hover {{ background: {c['hover']}; }}
QListWidget#convList::item:selected {{ background: {c['selected']}; }}
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit {{
    color: {c['fg']};
    background: {c['panel']};
    border: 1px solid {c['border_strong']};
    border-radius: 9px;
    padding: 7px 10px;
    selection-background-color: {c['accent']};
    selection-color: #FFFFFF;
}}
QComboBox:hover, QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover,
QPlainTextEdit:hover {{ border-color: {c['fg_muted']}; }}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QPlainTextEdit:focus {{ border-color: {c['accent']}; }}
QPlainTextEdit#systemPromptEdit {{
    border-radius: 12px;
    padding: 12px 14px;
    line-height: 1.5;
}}
QComboBox:disabled {{ color: {c['fg_muted']}; background: {c['hover']}; }}
QComboBox#modelCombo {{
    background: transparent;
    border: none;
    font-size: 14px;
    font-weight: 600;
    padding: 7px 26px 7px 8px;
}}
QComboBox#effortCombo {{
    border: none;
    background: transparent;
    padding: 4px 22px 4px 7px;
    min-width: 44px;
}}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{
    image: url({arrow});
    width: 12px;
    height: 8px;
    margin-right: 8px;
}}
QComboBox QAbstractItemView {{
    color: {c['fg']};
    background: {c['panel']};
    border: 1px solid {c['border_strong']};
    border-radius: 12px;
    selection-background-color: {c['selected']};
    selection-color: {c['fg']};
    outline: none;
    padding: 6px;
}}
QComboBox QAbstractItemView::item {{
    min-height: 22px;
    padding: 7px 10px;
    border-radius: 8px;
}}
QComboBox QAbstractItemView::item:hover {{ background: {c['hover']}; }}
QComboBox QAbstractItemView::item:selected {{
    color: {c['accent']};
    background: {c['accent_soft']};
}}
QSpinBox, QDoubleSpinBox {{ padding-right: 32px; }}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 28px;
    border: none;
    border-left: 1px solid {c['border']};
    border-bottom: 1px solid {c['border']};
    border-top-right-radius: 8px;
    background: transparent;
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 28px;
    border: none;
    border-left: 1px solid {c['border']};
    border-bottom-right-radius: 8px;
    background: transparent;
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background: {c['hover']};
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: url({arrow_up});
    width: 10px;
    height: 6px;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: url({arrow});
    width: 10px;
    height: 6px;
}}
QTextEdit#chatInput {{
    color: {c['fg']};
    background: transparent;
    border: none;
    padding: 2px 2px;
    font-size: 14px;
    selection-background-color: {c['accent']};
}}
QTextBrowser {{
    background: transparent;
    border: none;
    selection-background-color: {c['accent']};
}}
QCheckBox {{ spacing: 7px; color: {c['fg_sub']}; }}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid {c['border_strong']};
    background: {c['panel']};
}}
QCheckBox::indicator:checked {{
    background: {c['accent']};
    border-color: {c['accent']};
    image: url({check});
}}
QScrollBar:vertical {{ background: transparent; width: 9px; margin: 2px; }}
QScrollBar::handle:vertical {{
    background: {c['border_strong']};
    border-radius: 4px;
    min-height: 32px;
}}
QScrollBar::handle:vertical:hover {{ background: {c['fg_muted']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 9px; }}
QScrollBar::handle:horizontal {{ background: {c['border_strong']}; border-radius: 4px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QMenu {{
    color: {c['fg']};
    background: {c['panel']};
    border: 1px solid {c['border_strong']};
    border-radius: 12px;
    padding: 6px;
}}
QMenu::item {{
    min-height: 22px;
    padding: 7px 10px;
    border-radius: 8px;
    font-weight: 400;
}}
QMenu::item:selected {{ color: {c['accent']}; background: {c['accent_soft']}; }}
QMenu::item:disabled {{ color: {c['fg_muted']}; }}
QMenu::separator {{ height: 1px; background: {c['border']}; margin: 4px 7px; }}
QToolTip {{
    color: {c['fg']};
    background: {c['panel']};
    border: 1px solid {c['border']};
    border-radius: 9px;
    padding: 5px 8px;
}}
QSplitter::handle {{ background: {c['border']}; }}
"""
