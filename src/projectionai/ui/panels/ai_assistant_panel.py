"""AiAssistantPanel — bottom-right AI chat copilot.

Per UX-ARCHITECTURE §11: a context bar (what the AI knows), a scope
selector (Selection / Scene / Whole Show), suggestion chips, a chat
transcript, and a prompt input. Generations are async; the panel posts
prompts through :class:`AiViewModel` and renders the transcript.

When no AI provider is attached the panel shows a disabled hint state
instead of the composer.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from projectionai.ui.panels.base import ViewModelPanel
from projectionai.ui.panels.common import make_action_button, make_section_header
from projectionai.ui.theme import ACCENT, TEXT_DIM, TEXT_FAINT
from projectionai.ui.widgets.panel_base import run_async

_SCOPES: list[tuple[str, str]] = [
    ("Selection", "selection"),
    ("Scene", "scene"),
    ("Whole Show", "whole_show"),
]

#: Contextual, selection-driven suggestion prompts (§11.1).
_SUGGESTIONS: list[str] = [
    "Animate only the crown",
    "Add divine particles",
    "Make projection warmer",
    "Morph warp to curve B",
]


class AiAssistantPanel(ViewModelPanel):
    """AI Assistant dock panel (bottom-right)."""

    panel_id = "ai_assistant"

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self.setObjectName("aiAssistantPanel")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(make_section_header("AI ASSISTANT"))

        # -- Context bar -----------------------------------------------------
        self.context_label = QLabel()
        self.context_label.setObjectName("propLabel")
        self.context_label.setWordWrap(True)
        self.context_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        root.addWidget(self.context_label)

        # -- Suggestion chips --------------------------------------------------
        chips = QHBoxLayout()
        chips.setContentsMargins(4, 2, 4, 2)
        chips.setSpacing(4)
        for text in _SUGGESTIONS:
            chip = QToolButton()
            chip.setObjectName("sectionActionButton")
            chip.setText(text)
            chip.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            chip.clicked.connect(lambda _checked=False, t=text: self._use_suggestion(t))
            chips.addWidget(chip)
        root.addLayout(chips)

        # -- Transcript ----------------------------------------------------------
        self.transcript = QListWidget()
        self.transcript.setObjectName("aiTranscript")
        self.transcript.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.transcript.setWordWrap(True)
        root.addWidget(self.transcript, stretch=1)

        # -- Composer -------------------------------------------------------------
        composer = QWidget()
        composer.setObjectName("aiComposer")
        composer_layout = QVBoxLayout(composer)
        composer_layout.setContentsMargins(4, 4, 4, 4)
        composer_layout.setSpacing(4)

        scope_row = QHBoxLayout()
        scope_row.setSpacing(4)
        scope_label = QLabel("Scope:")
        scope_label.setObjectName("propLabel")
        scope_row.addWidget(scope_label)
        self.scope_combo = QComboBox()
        self.scope_combo.setObjectName("aiScope")
        for display, value in _SCOPES:
            self.scope_combo.addItem(display, value)
        scope_row.addWidget(self.scope_combo, stretch=1)
        composer_layout.addLayout(scope_row)

        input_row = QHBoxLayout()
        input_row.setSpacing(4)
        self.prompt_edit = QLineEdit()
        self.prompt_edit.setPlaceholderText("Describe what to create…")
        self.prompt_edit.returnPressed.connect(self._send)
        input_row.addWidget(self.prompt_edit, stretch=1)
        self.send_btn = make_action_button("Send", self._send)
        input_row.addWidget(self.send_btn)
        composer_layout.addLayout(input_row)

        self.hint_label = QLabel()
        self.hint_label.setObjectName("propValueLabel")
        self.hint_label.setWordWrap(True)
        self.hint_label.hide()
        composer_layout.addWidget(self.hint_label)

        root.addWidget(composer)

    # -- View model -------------------------------------------------------------

    def bind_viewmodel(self, viewmodel: Any) -> None:
        """Attach the AI view model and sync the composer state."""
        super().bind_viewmodel(viewmodel)
        self._sync_available()

    # -- Refresh ------------------------------------------------------------------

    def refresh(self) -> None:
        """Render the transcript and context from the bound view model."""
        if self._refreshing:
            return
        self._refreshing = True
        try:
            self._sync_available()
            self._render_transcript()
        finally:
            self._refreshing = False

    def clear(self) -> None:
        """Clear the transcript and context."""
        self.transcript.clear()
        self.context_label.setText("")
        self._sync_available()

    def _render_transcript(self) -> None:
        vm = self._viewmodel
        self.transcript.clear()
        if vm is None:
            return
        for message in vm.transcript():
            role = getattr(message, "role", "assistant")
            content = getattr(message, "content", "")
            item = QListWidgetItem(f"{role.title()}: {content}")
            if role == "assistant":
                item.setForeground(QColor(ACCENT))
            elif role == "user":
                item.setForeground(QColor(TEXT_DIM))
            else:
                item.setForeground(QColor(TEXT_FAINT))
            self.transcript.addItem(item)
        self.transcript.scrollToBottom()

    # -- Context ------------------------------------------------------------------

    def set_context(
        self,
        scene: str = "",
        selection: str = "",
        camera: str = "",
        projector: str = "",
    ) -> None:
        """Update the context bar chips from the main window."""
        parts = []
        if scene:
            parts.append(f"Scene: {scene}")
        if camera:
            parts.append(f"Cam: {camera}")
        if projector:
            parts.append(f"Proj: {projector}")
        if selection:
            parts.append(f"Sel: {selection}")
        self.context_label.setText("  ·  ".join(parts) if parts else "")

    # -- Composer --------------------------------------------------------------------

    def _use_suggestion(self, text: str) -> None:
        """Fill the prompt box with a suggestion chip."""
        self.prompt_edit.setText(text)
        self.prompt_edit.setFocus()

    def _send(self) -> None:
        """Post the prompt to the view model and clear the box."""
        vm = self._viewmodel
        if vm is None:
            return
        text = self.prompt_edit.text().strip()
        if not text:
            return
        self.prompt_edit.clear()
        run_async(vm.chat(text))

    def _sync_available(self) -> None:
        """Enable/disable the composer based on provider availability."""
        vm = self._viewmodel
        available = bool(vm is not None and vm.available)
        self.prompt_edit.setEnabled(available)
        self.send_btn.setEnabled(available)
        self.scope_combo.setEnabled(available)
        if available:
            self.hint_label.hide()
        else:
            provider = vm.provider_name if vm is not None else ""
            if provider:
                self.hint_label.setText(f"Provider: {provider} — assistant unavailable")
            else:
                self.hint_label.setText(
                    "No AI provider configured — install a provider plugin "
                    "to enable the assistant."
                )
            self.hint_label.show()
