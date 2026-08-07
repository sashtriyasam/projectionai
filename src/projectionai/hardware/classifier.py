"""Display classification — monitors vs projectors vs virtual displays.

Pure string heuristics over vendor/model/name, fully extensible: rules
are a class attribute, and ``classify`` itself can be overridden by
subclasses to add platform- or venue-specific knowledge (e.g. a
projector inventory list).
"""

from __future__ import annotations

from dataclasses import replace

from projectionai.hardware.models import DisplayConnection, DisplayInfo, DisplayKind

#: Substrings that mark a display as virtual (software/network).
_VIRTUAL_PATTERNS: tuple[str, ...] = (
    "virtual",
    "mirror",
    "offscreen",
    "indirect",
    "vnc",
    "parsec",
    "spacedesk",
    "remote",
    "dummy",
)

#: Vendor/model substrings strongly associated with projectors.
#: Vendor names only match together with a projector series token so that
#: monitor lines from the same vendor (e.g. BenQ GW/PD, Acer P2xx) are not
#: misclassified.
_PROJECTOR_PATTERNS: tuple[str, ...] = (
    "projector",
    "dlp",
    "benq th",
    "benq tk",
    "benq ht",
    "benq w",
    "benq mh",
    "benq ms",
    "benq mx",
    "benq mw",
    "benq eh",
    "benq gv",
    "benq gp",
    "benq gs",
    "epson",
    "optoma",
    "vivitek",
    "viewsonic pj",
    "nec pj",
    "nec np",
    "hitachi cp",
    "sanyo plc",
    "mitsubishi xd",
    "mitsubishi hc",
    "mitsubishi wd",
    "mitsubishi fd",
    "mitsubishi ew",
    "mitsubishi xl",
    "panasonic pt-",
    "sony vpl-",
    "sony vpl",
    "acer h5",
    "acer h6",
    "acer h7",
    "acer x1",
    "acer d6",
    "acer s1",
    "acer p5",
    "acer p7",
    "acer p8",
    "lg pf",
    "lg hu",
    "casio xj",
    "canon lv",
    "christie",
    "barco hdx",
    "barco udx",
    "barco dp2k",
    "barco pgw",
    "barco fl35",
    "barco rlm",
    "barco f70",
    "digital projection",
)


class DisplayClassifier:
    """Classifies :class:`DisplayInfo` into a :class:`DisplayKind`.

    Rules are applied in priority order: connection-level virtual
    displays first, then projector vendor/model patterns, then an
    unknown fallback when no identifying information exists.
    """

    #: Overridable rule sets (subclass to specialise).
    virtual_patterns: tuple[str, ...] = _VIRTUAL_PATTERNS
    projector_patterns: tuple[str, ...] = _PROJECTOR_PATTERNS

    def classify(self, info: DisplayInfo) -> DisplayKind:
        """Return the display kind for *info*.

        Uses the display's connection, name, manufacturer, and model.
        """
        if info.connection is DisplayConnection.VIRTUAL:
            return DisplayKind.VIRTUAL
        fields = " ".join([info.name, info.manufacturer, info.model]).lower()
        if not fields.strip():
            return DisplayKind.UNKNOWN
        if self._matches(fields, self.virtual_patterns):
            return DisplayKind.VIRTUAL
        if self._matches(fields, self.projector_patterns):
            return DisplayKind.PROJECTOR
        return DisplayKind.MONITOR

    def reclassify(self, info: DisplayInfo) -> DisplayInfo:
        """Return *info* with ``kind`` set from :meth:`classify`."""
        return replace(info, kind=self.classify(info))

    @staticmethod
    def _matches(text: str, patterns: tuple[str, ...]) -> bool:
        return any(pattern in text for pattern in patterns)


#: Module-level default instance (stateless).
DEFAULT_CLASSIFIER = DisplayClassifier()
