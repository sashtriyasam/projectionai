"""ProjectionAI dark theme — OBS-inspired professional chrome.

Single source of truth for colors, fonts, and the global stylesheet.
The palette is exposed as module constants so widgets can compute
state-dependent colors (e.g., the LIVE indicator) without duplicating
hex values. Theme is applied once to the QApplication.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

# ---------------------------------------------------------------------------
# Palette tokens
# ---------------------------------------------------------------------------

WINDOW_BG = "#16181D"  # main window / dock background
WELL_BG = "#0F1114"  # viewport canvases, list wells
PANEL_BG = "#1B1E26"  # panel surfaces
PANEL_ALT_BG = "#20242E"  # hover / alternate rows
BORDER = "#2A2D35"  # panel and widget borders
BORDER_LIGHT = "#343947"

TEXT = "#D8DAE0"
TEXT_DIM = "#8A8F9C"
TEXT_FAINT = "#5C616E"

ACCENT = "#FF9E00"  # amber — selection, active, focus
ACCENT_DIM = "#B37100"
LIVE_RED = "#FF3B30"  # live / record / errors
WARN_YELLOW = "#FFC107"
OK_GREEN = "#30D158"

SELECTION_BG = "#2E3542"
TRACK_BG = "#101318"

# Track type colors (timeline)
TRACK_COLORS = {
    "video": "#3D7EFF",
    "projection": "#FF9E00",
    "animation": "#B453F7",
    "audio": "#30D158",
    "markers": "#FFC107",
    "notes": "#8A8F9C",
}

STATE_COLORS = {
    "idle": TEXT_DIM,
    "preview": "#4A90E2",
    "armed": WARN_YELLOW,
    "live": LIVE_RED,
    "blackout": "#000000",
    "freeze": "#B453F7",
}


def _is_windows() -> bool:
    import sys

    return sys.platform == "win32"


FONT_UI = "Segoe UI" if _is_windows() else "Inter, Noto Sans"
FONT_MONO = "Cascadia Mono, JetBrains Mono, Consolas"


def _font_families(names: str) -> str:
    """Quote each family separately so Qt resolves fallbacks in order."""
    return ", ".join(f'"{name.strip()}"' for name in names.split(",") if name.strip())


def qcolor(token: str) -> QColor:
    """Return a QColor for a hex token (or token name)."""
    return QColor(token)


def apply_theme(app: QApplication) -> None:
    """Apply the dark palette and stylesheet to *app*."""
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(WINDOW_BG))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor(WELL_BG))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(PANEL_ALT_BG))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor(PANEL_BG))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(PANEL_BG))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(SELECTION_BG))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(TEXT_FAINT))
    palette.setColor(QPalette.ColorRole.Link, QColor(ACCENT))
    app.setPalette(palette)
    app.setStyleSheet(STYLESHEET)


STYLESHEET = f"""
* {{
    font-family: {_font_families(FONT_UI)};
    font-size: 12px;
    color: {TEXT};
    outline: none;
}}

QMainWindow, QDialog {{
    background-color: {WINDOW_BG};
}}

QWidget {{
    background-color: transparent;
}}

/* -- Panels ------------------------------------------------------------ */

QDockWidget {{
    color: {TEXT};
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
}}

QDockWidget::title {{
    background-color: {PANEL_BG};
    border: 1px solid {BORDER};
    border-bottom: none;
    padding: 4px 8px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.5px;
    text-transform: uppercase;
    color: {TEXT_DIM};
}}

QDockWidget::title:hover {{
    color: {TEXT};
}}

/* -- Menu bar / menus -------------------------------------------------- */

QMenuBar {{
    background-color: {WINDOW_BG};
    border-bottom: 1px solid {BORDER};
    padding: 2px 4px;
}}

QMenuBar::item {{
    background: transparent;
    padding: 4px 10px;
    border-radius: 3px;
}}

QMenuBar::item:selected {{
    background-color: {SELECTION_BG};
    color: {TEXT};
}}

QMenu {{
    background-color: {PANEL_BG};
    border: 1px solid {BORDER_LIGHT};
    padding: 4px;
}}

QMenu::item {{
    padding: 5px 24px 5px 12px;
    border-radius: 3px;
}}

QMenu::item:selected {{
    background-color: {SELECTION_BG};
}}

QMenu::item:disabled {{
    color: {TEXT_FAINT};
}}

QMenu::separator {{
    height: 1px;
    background-color: {BORDER};
    margin: 4px 8px;
}}

/* -- Toolbar ----------------------------------------------------------- */

QToolBar {{
    background-color: {PANEL_BG};
    border-bottom: 1px solid {BORDER};
    padding: 3px;
    spacing: 2px;
}}

QToolBar::separator {{
    background-color: {BORDER_LIGHT};
    width: 1px;
    margin: 4px 6px;
}}

QToolButton {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 4px 8px;
    color: {TEXT_DIM};
}}

QToolButton:hover {{
    background-color: {SELECTION_BG};
    color: {TEXT};
}}

QToolButton:checked {{
    background-color: {SELECTION_BG};
    border-color: {ACCENT_DIM};
    color: {ACCENT};
}}

QToolButton#armLiveButton {{
    background-color: {LIVE_RED};
    color: #FFFFFF;
    font-weight: 700;
    padding: 5px 14px;
    border-radius: 4px;
}}

QToolButton#armLiveButton:hover {{
    background-color: #FF5A4E;
}}

QToolButton#armLiveButton:checked {{
    background-color: {LIVE_RED};
    border: 1px solid #FFFFFF;
}}

/* -- Docks ------------------------------------------------------------- */

QDockWidget > QWidget {{
    background-color: {PANEL_BG};
    border: 1px solid {BORDER};
}}

/* -- Tabs -------------------------------------------------------------- */

QTabWidget::pane {{
    border: 1px solid {BORDER};
    background-color: {PANEL_BG};
    top: -1px;
}}

QTabBar::tab {{
    background-color: {WINDOW_BG};
    color: {TEXT_DIM};
    border: 1px solid {BORDER};
    border-bottom: none;
    padding: 5px 14px;
    margin-right: 2px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
}}

QTabBar::tab:selected {{
    background-color: {PANEL_BG};
    color: {ACCENT};
    border-bottom: 2px solid {ACCENT};
}}

QTabBar::tab:hover:!selected {{
    color: {TEXT};
}}

/* -- Status bar -------------------------------------------------------- */

QStatusBar {{
    background-color: {PANEL_BG};
    border-top: 1px solid {BORDER};
    color: {TEXT_DIM};
    min-height: 24px;
}}

QStatusBar::item {{
    border: none;
}}

QStatusBar QLabel {{
    padding: 2px 8px;
    font-size: 11px;
    color: {TEXT_DIM};
}}

QStatusBar QLabel#liveStateLabel {{
    font-weight: 700;
    letter-spacing: 1px;
}}

/* -- Trees / lists / tables ------------------------------------------- */

QTreeView, QListView, QTableView, QTableWidget, QListWidget {{
    background-color: {WELL_BG};
    alternate-background-color: {PANEL_ALT_BG};
    border: 1px solid {BORDER};
    border-radius: 3px;
    selection-background-color: {SELECTION_BG};
    selection-color: {TEXT};
}}

QTreeView::item, QListView::item, QListWidget::item {{
    padding: 3px 4px;
    border-radius: 2px;
}}

QTreeView::item:hover, QListView::item:hover, QListWidget::item:hover {{
    background-color: {PANEL_ALT_BG};
}}

QTreeView::item:selected, QListView::item:selected, QListWidget::item:selected {{
    background-color: {SELECTION_BG};
    color: {ACCENT};
}}

QHeaderView::section {{
    background-color: {PANEL_BG};
    border: none;
    border-bottom: 1px solid {BORDER};
    border-right: 1px solid {BORDER};
    padding: 4px 6px;
    font-weight: 600;
    color: {TEXT_DIM};
}}

/* -- Inputs ------------------------------------------------------------ */

QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background-color: {WELL_BG};
    border: 1px solid {BORDER_LIGHT};
    border-radius: 3px;
    padding: 4px 6px;
    selection-background-color: {SELECTION_BG};
}}

QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus,
QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {ACCENT_DIM};
}}

QComboBox::drop-down {{
    border: none;
    width: 18px;
}}

QComboBox QAbstractItemView {{
    background-color: {PANEL_BG};
    border: 1px solid {BORDER_LIGHT};
    selection-background-color: {SELECTION_BG};
}}

/* -- Buttons ----------------------------------------------------------- */

QPushButton {{
    background-color: {PANEL_ALT_BG};
    border: 1px solid {BORDER_LIGHT};
    border-radius: 4px;
    padding: 5px 12px;
    color: {TEXT};
}}

QPushButton:hover {{
    background-color: {SELECTION_BG};
    border-color: {BORDER_LIGHT};
}}

QPushButton:pressed {{
    background-color: #262B36;
}}

QPushButton:disabled {{
    color: {TEXT_FAINT};
    background-color: {PANEL_BG};
}}

QPushButton#primaryButton {{
    background-color: {ACCENT};
    color: #1A1400;
    font-weight: 600;
}}

QPushButton#primaryButton:hover {{
    background-color: #FFB324;
}}

QPushButton#dangerButton {{
    background-color: {LIVE_RED};
    color: #FFFFFF;
}}

/* -- Checkboxes -------------------------------------------------------- */

QCheckBox {{
    spacing: 6px;
}}

QCheckBox::indicator {{
    width: 14px;
    height: 14px;
    border: 1px solid {BORDER_LIGHT};
    border-radius: 3px;
    background-color: {WELL_BG};
}}

QCheckBox::indicator:checked {{
    background-color: {ACCENT};
    border-color: {ACCENT};
}}

/* -- Scrollbars -------------------------------------------------------- */

QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background: {BORDER_LIGHT};
    border-radius: 5px;
    min-height: 24px;
}}

QScrollBar::handle:vertical:hover {{
    background: #4A5060;
}}

QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 0;
}}

QScrollBar::handle:horizontal {{
    background: {BORDER_LIGHT};
    border-radius: 5px;
    min-width: 24px;
}}

QScrollBar::handle:horizontal:hover {{
    background: #4A5060;
}}

QScrollBar::add-line, QScrollBar::sub-line {{
    width: 0;
    height: 0;
}}

QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}

/* -- Splitters --------------------------------------------------------- */

QSplitter::handle {{
    background-color: {BORDER};
}}

QSplitter::handle:hover {{
    background-color: {ACCENT_DIM};
}}

QSplitter::handle:horizontal {{
    width: 2px;
}}

QSplitter::handle:vertical {{
    height: 2px;
}}

/* -- Misc -------------------------------------------------------------- */

QToolTip {{
    background-color: {PANEL_BG};
    color: {TEXT};
    border: 1px solid {BORDER_LIGHT};
    padding: 4px 6px;
}}

QProgressBar {{
    background-color: {WELL_BG};
    border: 1px solid {BORDER};
    border-radius: 3px;
    height: 10px;
    text-align: center;
}}

QProgressBar::chunk {{
    background-color: {ACCENT};
    border-radius: 2px;
}}

QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 4px;
    margin-top: 10px;
    padding-top: 6px;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
    color: {TEXT_DIM};
}}

QMessageBox {{
    background-color: {PANEL_BG};
}}

QFrame#hintBar {{
    background-color: {PANEL_ALT_BG};
    border-radius: 3px;
}}

QLabel#panelHeader {{
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.5px;
    color: {TEXT_DIM};
    padding: 4px 6px;
    border-bottom: 1px solid {BORDER};
}}

QLabel#liveBadge {{
    font-weight: 800;
    letter-spacing: 1.5px;
    font-size: 11px;
}}

/* -- Property editor ----------------------------------------------------- */

QWidget#propContainer {{
    background-color: transparent;
}}

QToolButton#sectionHeader {{
    text-align: left;
    font-weight: 600;
    color: {TEXT_DIM};
    padding: 5px 8px;
    border-bottom: 1px solid {BORDER};
    border-radius: 0;
}}

QToolButton#sectionHeader:hover {{
    background-color: {PANEL_ALT_BG};
    color: {TEXT};
}}

QWidget#propSection {{
    background-color: {PANEL_BG};
}}

QLabel#propLabel {{
    color: {TEXT_DIM};
    font-size: 11px;
}}

QLabel#propValueLabel {{
    color: {TEXT_FAINT};
    font-size: 11px;
}}

QToolButton#keyframeBtn {{
    border: 1px solid {BORDER_LIGHT};
    border-radius: 3px;
    background-color: {WELL_BG};
    padding: 0;
}}

QToolButton#keyframeBtn:hover {{
    border-color: {ACCENT};
    background-color: {SELECTION_BG};
}}

QPushButton#sectionActionButton {{
    text-align: center;
    font-weight: 600;
    padding: 4px 8px;
}}
"""
