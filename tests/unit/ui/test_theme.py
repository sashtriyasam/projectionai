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
