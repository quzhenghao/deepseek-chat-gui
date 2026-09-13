from __future__ import annotations

from .. import ASSETS_DIR


ACCENT = "#171717"

_LIGHT = {
    "bg": "#FFFFFF",
    "side_bg": "#F3F3F3",
    "panel": "#FFFFFF",
    "canvas": "#FFFFFF",
    "border": "#E6E7E9",
    "border_strong": "#D4D6D9",
    "fg": "#1B1B1C",
    "fg_sub": "#5D626A",
    "fg_muted": "#92979F",
    "entry_fg": "#000000",
    "hover": "#ECEDEF",
    "selected": "#E3E5E8",
    "accent": ACCENT,
    "accent_hover": "#000000",
    "accent_soft": "#EEEEEE",
    "mode_active": "#1B1B1C",
    "mode_active_fg": "#FFFFFF",
    "primary_fg": "#FFFFFF",
    "user_bubble": "#F0F1F2",
    "reason_bg": "#F7F7F8",
    "code_bg": "#F4F5F6",
    "danger": "#D92D20",
    "danger_soft": "#FFF1F0",
    "success": "#12B76A",
    "shadow": "#1717171A",
}

_DARK = {
    "bg": "#1A1A1A",
    "side_bg": "#141414",
    "panel": "#222222",
    "canvas": "#1A1A1A",
    "border": "#333333",
    "border_strong": "#454545",
    "fg": "#F2F2F2",
    "fg_sub": "#B7B7B7",
    "fg_muted": "#858585",
    "entry_fg": "#FFFFFF",
    "hover": "#2A2A2A",
    "selected": "#363636",
    "accent": "#E8E8E8",
    "accent_hover": "#FFFFFF",
    "accent_soft": "#353535",
    "mode_active": "#F2F2F2",
    "mode_active_fg": "#141414",
    "primary_fg": "#111111",
    "user_bubble": "#2B2B2B",
    "reason_bg": "#242424",
    "code_bg": "#151515",
    "danger": "#F97066",
    "danger_soft": "#3A2426",
    "success": "#32D583",
    "shadow": "#00000055",
}

THEMES = {"light": _LIGHT, "dark": _DARK}

SIDEBAR_DEFAULT_WIDTH = 280
SIDEBAR_MIN_WIDTH = 220
RAIL_SIDEBAR_WIDTH = 56

# Keep message surfaces and the image thumbnails inside them on the same
# corner curve.  The value is in logical Qt pixels and is shared by the
# custom thumbnail painter as well as the user-message QSS surface.
CHAT_BUBBLE_RADIUS = 14

# Keep the two right-hand product surfaces aligned when switching between
# Chat and Settings.  The top bars intentionally share both their height and
# horizontal padding so the content below them starts on the same rhythm.
RIGHT_HEADER_HEIGHT = 58
RIGHT_HEADER_MARGINS = (20, 8, 16, 8)
RIGHT_HEADER_SPACING = 8

BRAND_MARK_SIZE = 30
BRAND_WORDMARK_SIZE = 20
BRAND_BADGE_SIZE = 10

FONT_STACK = '".AppleSystemUIFont", "Helvetica Neue", "PingFang SC"'


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
    font-family: {FONT_STACK};
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
QWidget#sidebarPages, QWidget#sidebarFullPage, QWidget#sidebarRail {{
    background: transparent;
    border: none;
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
    background: transparent;
}}
QWidget#chatWorkspace {{
    background: {c['canvas']};
}}
QFrame#composerCard {{
    background: {c['panel']};
    border: 1px dashed {c['border_strong']};
    border-radius: 18px;
}}
QFrame#sectionCard {{
    background: {c['panel']};
    border: 1px solid {c['border']};
    border-radius: 14px;
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
QLabel#chatBrandWordmark, QLabel#settingsBrandWordmark {{
    color: {c['fg']};
    background: transparent;
    font-size: {BRAND_WORDMARK_SIZE}px;
    font-weight: 650;
}}
QLabel#brandBadge {{
    color: #FFFFFF;
    background: #171717;
    border-radius: 4px;
    padding: 3px 6px 2px 6px;
    font-size: {BRAND_BADGE_SIZE}px;
    font-weight: 750;
    letter-spacing: 0.7px;
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
QLabel#welcomeKicker {{
    color: {c['fg_muted']};
    background: transparent;
    font-size: 12px;
    font-weight: 600;
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
QLabel#composerHint {{
    color: {c['fg_muted']};
    background: transparent;
    font-size: 11px;
}}
QLabel#sectionLabel {{
    color: {c['fg_muted']};
    font-size: 11px;
    font-weight: 600;
}}
QLabel#onboardingHint {{
    color: {c['fg_sub']};
    background: {c['accent_soft']};
    border-radius: 8px;
    padding: 7px 9px;
    font-size: 11px;
}}
QLabel#environmentStatus {{
    color: {c['fg_sub']};
    background: {c['accent_soft']};
    border-radius: 8px;
    padding: 8px 10px;
    font-size: 11px;
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
QPushButton#newChatButton {{
    color: {c['fg']};
    background: {c['panel']};
    border: 1px solid {c['border']};
    border-radius: 12px;
    min-height: 44px;
    padding: 8px 14px;
    font-size: 15px;
    font-weight: 600;
}}
QPushButton#newChatButton:hover {{
    background: {c['hover']};
    border-color: {c['border_strong']};
}}
QPushButton#thinkingBtn, QPushButton#searchBtn {{
    color: {c['fg_sub']};
    padding: 5px 9px;
}}
QPushButton#thinkingBtn:checked, QPushButton#searchBtn:checked {{
    color: {c['accent']};
    background: {c['accent_soft']};
}}
QToolButton#attachBtn {{
    background: {c['accent_soft']};
    border-radius: 17px;
    padding: 0;
}}
QToolButton#attachBtn:hover {{ background: {c['selected']}; }}
QPushButton#primaryBtn {{
    color: {c['primary_fg']};
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
/* The chat sidebar entry and the settings page exit share one flat surface:
   they blend into the rail and only darken under the pointer. */
QPushButton#sidebarFooterBtn, QPushButton#settingsBackBtn {{
    color: {c['entry_fg']};
    background: transparent;
    border: 1px solid transparent;
    border-radius: 10px;
    text-align: left;
    min-height: 22px;
    max-height: 22px;
    padding: 8px 12px;
    font-size: 14px;
}}
QPushButton#sidebarFooterBtn:hover, QPushButton#settingsBackBtn:hover {{
    color: {c['entry_fg']};
    background: {c['hover']};
}}
QPushButton#sidebarFooterBtn:pressed, QPushButton#settingsBackBtn:pressed {{
    background: {c['selected']};
}}
QToolButton#sidebarRailBtn {{
    color: {c['entry_fg']};
    background: transparent;
    border: 1px solid transparent;
    border-radius: 10px;
    padding: 0;
}}
QToolButton#sidebarRailBtn:hover {{
    color: {c['entry_fg']};
    background: {c['hover']};
}}
QToolButton#sidebarRailBtn:pressed {{
    background: {c['selected']};
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
QToolButton#expandInputBtn {{
    background: transparent;
    border: none;
    border-radius: 8px;
    padding: 0;
}}
QToolButton#expandInputBtn:hover {{ background: {c['hover']}; }}
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
QToolButton#followLatestBtn {{
    color: {c['fg']};
    background: {c['panel']};
    border: 1px solid {c['border_strong']};
    border-radius: 18px;
    padding: 0;
}}
QToolButton#followLatestBtn:hover {{
    background: {c['hover']};
    border-color: {c['fg_muted']};
}}
QToolButton#reasonToggle {{
    color: {c['fg_sub']};
    text-align: left;
    padding: 2px 4px;
}}
QWidget#reasoningPreview {{
    color: {c['fg_muted']};
    background: transparent;
    font-size: 12px;
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
    background: {c['panel']};
    border: none;
    padding: 2px 2px;
    font-size: 14px;
}}
QTextBrowser {{
    background: transparent;
    border: none;
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
/* Menus keep the platform's standard entries but are painted as a plain,
   opaque surface: macOS would otherwise show a translucent vibrancy panel. */
QMenu {{
    color: {c['fg']};
    background: {c['panel']};
    border: 1px solid {c['border_strong']};
    border-radius: 6px;
    padding: 4px;
}}
QMenu::item {{
    min-height: 20px;
    padding: 6px 22px 6px 12px;
    border-radius: 4px;
    background: transparent;
}}
QMenu::item:selected {{ color: {c['fg']}; background: {c['hover']}; }}
QMenu::item:disabled {{ color: {c['fg_muted']}; }}
QMenu::separator {{ height: 1px; background: {c['border']}; margin: 4px 8px; }}
QToolTip {{
    color: {c['fg']};
    background: {c['panel']};
    border: 1px solid {c['border']};
    border-radius: 9px;
    padding: 5px 8px;
}}
QSplitter::handle {{ background: {c['border']}; }}
"""
