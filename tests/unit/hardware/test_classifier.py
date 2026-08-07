"""Tests for display classification rules."""

from __future__ import annotations

from projectionai.hardware.classifier import DEFAULT_CLASSIFIER, DisplayClassifier
from projectionai.hardware.models import (
    DisplayConnection,
    DisplayInfo,
    DisplayKind,
    DisplayMode,
)
from projectionai.infrastructure.display.mock_provider import make_display


def _display(
    *,
    name: str = "Generic Display",
    manufacturer: str = "Acme",
    model: str = "Display",
    connection: DisplayConnection = DisplayConnection.HDMI,
) -> DisplayInfo:
    return make_display(
        "d-1",
        0,
        name,
        manufacturer=manufacturer,
        model=model,
        connection=connection,
    )


def test_virtual_connection_classifies_as_virtual() -> None:
    info = _display(connection=DisplayConnection.VIRTUAL)
    assert DEFAULT_CLASSIFIER.classify(info) is DisplayKind.VIRTUAL


def test_projector_vendor_classifies_as_projector() -> None:
    assert (
        DEFAULT_CLASSIFIER.classify(_display(manufacturer="Epson"))
        is DisplayKind.PROJECTOR
    )
    assert (
        DEFAULT_CLASSIFIER.classify(_display(manufacturer="BenQ", model="TH671ST"))
        is DisplayKind.PROJECTOR
    )
    assert (
        DEFAULT_CLASSIFIER.classify(_display(model="Optoma UHZ50"))
        is DisplayKind.PROJECTOR
    )
    assert (
        DEFAULT_CLASSIFIER.classify(_display(manufacturer="Acer", model="H6517ABD"))
        is DisplayKind.PROJECTOR
    )


def test_benq_monitor_not_classified_as_projector() -> None:
    info = _display(manufacturer="BenQ", model="GW2480")
    assert DEFAULT_CLASSIFIER.classify(info) is DisplayKind.MONITOR


def test_acer_p_series_monitor_not_classified_as_projector() -> None:
    info = _display(manufacturer="Acer", model="P241W")
    assert DEFAULT_CLASSIFIER.classify(info) is DisplayKind.MONITOR


def test_unknown_fields_classify_as_unknown() -> None:
    info = _display(name="", manufacturer="", model="")
    assert DEFAULT_CLASSIFIER.classify(info) is DisplayKind.UNKNOWN


def test_plain_monitor_classifies_as_monitor() -> None:
    info = _display(manufacturer="Dell", model="U2720Q")
    assert DEFAULT_CLASSIFIER.classify(info) is DisplayKind.MONITOR


def test_reclassify_sets_kind() -> None:
    info = _display(manufacturer="Epson", model="EB-2250U")
    classified = DEFAULT_CLASSIFIER.reclassify(info)
    assert classified.kind is DisplayKind.PROJECTOR
    assert classified.display_id == info.display_id
    assert classified.current_mode == info.current_mode


def test_custom_classifier_extends_rules() -> None:
    class VenueClassifier(DisplayClassifier):
        projector_patterns = (*DisplayClassifier.projector_patterns, "mycompany")

    info = _display(manufacturer="MyCompany", model="Venue Beam")
    assert DEFAULT_CLASSIFIER.classify(info) is DisplayKind.MONITOR
    assert VenueClassifier().classify(info) is DisplayKind.PROJECTOR


def test_mode_label_and_resolution() -> None:
    mode = DisplayMode(1920, 1080, 60.0)
    assert mode.label == "1920x1080 @ 60 Hz"
    assert mode.resolution == (1920, 1080)
