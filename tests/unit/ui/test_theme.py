"""Regression tests for theme.py font-family stylesheet generation.

Qt style sheets treat a comma inside a quoted string as part of the
family name, so ``font-family: "Inter, Noto Sans"`` is one token that
never resolves. Families must be emitted as separately quoted names so
fallbacks stay usable and in order.
"""

from __future__ import annotations

import re

from projectionai.ui import theme


class TestFontFamilies:
    def test_multi_family_fallbacks_quoted_separately(self) -> None:
        assert theme._font_families("Inter, Noto Sans") == '"Inter", "Noto Sans"'

    def test_single_family_stays_single_quoted(self) -> None:
        assert theme._font_families("Segoe UI") == '"Segoe UI"'

    def test_mono_fallbacks_quoted_separately_in_order(self) -> None:
        assert (
            theme._font_families(theme.FONT_MONO)
            == '"Cascadia Mono", "JetBrains Mono", "Consolas"'
        )


class TestStylesheetEmission:
    def test_root_rule_uses_quoted_family_list(self) -> None:
        expected = f"font-family: {theme._font_families(theme.FONT_UI)};"
        assert expected in theme.STYLESHEET

    def test_no_comma_list_wrapped_in_one_quote_token(self) -> None:
        for line in theme.STYLESHEET.splitlines():
            match = re.search(r'font-family:\s*"([^"]+)"', line)
            if match is not None:
                assert "," not in match.group(1), f"quoted as one token: {line!r}"


def _luminance(hex_color: str) -> float:
    channels = [int(hex_color.lstrip("#")[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [
        c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(fg: str, bg: str) -> float:
    hi, lo = sorted((_luminance(fg), _luminance(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


class TestAccessibility:
    """WCAG 2.1 AA: 4.5:1 for body text, visible keyboard focus."""

    def test_text_tokens_meet_aa_on_panel_surfaces(self) -> None:
        for token in (theme.TEXT, theme.TEXT_DIM, theme.TEXT_FAINT):
            for bg in (theme.WINDOW_BG, theme.WELL_BG, theme.PANEL_BG):
                assert _contrast(token, bg) >= 4.5, (token, bg)

    def test_white_label_on_filled_red_meets_aa(self) -> None:
        for bg in (theme.LIVE_RED_FILL, theme.LIVE_RED_FILL_HOVER):
            assert _contrast("#FFFFFF", bg) >= 4.5

    def test_buttons_have_focus_state(self) -> None:
        assert "QPushButton:focus" in theme.STYLESHEET
        assert "QToolButton:focus" in theme.STYLESHEET
