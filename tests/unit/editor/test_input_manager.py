"""Tests for InputManager — event routing and keyboard shortcuts."""

from __future__ import annotations

from projectionai.editor.input_manager import InputManager, MouseState


def test_initial_state() -> None:
    im = InputManager()
    state = im.mouse_state
    assert state.x == 0.0
    assert state.y == 0.0
    assert not state.any_button


def test_mouse_press() -> None:
    im = InputManager()
    tracked: list[str] = []

    def handler(state: MouseState) -> None:
        if state.left:
            tracked.append("left")
        if state.middle:
            tracked.append("middle")
        if state.right:
            tracked.append("right")

    im.add_press_handler(handler)
    im.on_press(100, 200, "left", [])
    assert tracked == ["left"]
    assert im.mouse_state.x == 100
    assert im.mouse_state.y == 200


def test_mouse_release() -> None:
    im = InputManager()
    im.on_press(0, 0, "left", [])
    assert im.mouse_state.left

    im.on_release(0, 0, "left", [])
    assert not im.mouse_state.left


def test_mouse_move() -> None:
    im = InputManager()
    moves: list[tuple[float, float]] = []

    def handler(state: MouseState) -> None:
        moves.append((state.dx, state.dy))

    im.add_move_handler(handler)
    im.on_move(100, 200, [])
    assert moves[-1] == (100.0, 200.0)  # first move from (0,0)

    im.on_move(150, 220, [])
    assert moves[-1] == (50.0, 20.0)


def test_wheel() -> None:
    im = InputManager()
    deltas: list[float] = []

    def handler(delta: float) -> None:
        deltas.append(delta)

    im.add_wheel_handler(handler)
    im.on_wheel(120.0, [])
    assert deltas == [120.0]

    im.on_wheel(-120.0, [])
    assert deltas == [120.0, -120.0]


def test_modifiers_tracked() -> None:
    im = InputManager()
    im.on_press(0, 0, "left", ["ctrl", "shift"])
    state = im.mouse_state
    assert state.ctrl
    assert state.shift
    assert not state.alt


def test_remove_handler() -> None:
    im = InputManager()
    calls: list[str] = []

    def handler(state: MouseState) -> None:
        calls.append("called")

    im.add_move_handler(handler)
    im.on_move(10, 20, [])
    assert len(calls) == 1

    im.remove_move_handler(handler)
    im.on_move(30, 40, [])
    assert len(calls) == 1  # no additional call


def test_clear_handlers() -> None:
    im = InputManager()
    calls: list[str] = []

    def handler(state: MouseState) -> None:
        calls.append("called")

    im.add_move_handler(handler)
    im.add_press_handler(handler)
    im.clear_handlers()
    im.on_move(10, 20, [])
    im.on_press(10, 20, "left", [])
    assert len(calls) == 0


def test_reset_state() -> None:
    im = InputManager()
    im.on_press(100, 200, "left", ["ctrl"])
    im.reset_state()
    state = im.mouse_state
    assert state.x == 0.0
    assert state.y == 0.0
    assert not state.ctrl


def test_shortcut_register_and_match() -> None:
    im = InputManager()
    im.register_shortcut("translate", "W", description="Translate tool")
    im.register_shortcut("save", "S", ("ctrl",), description="Save")
    im.register_shortcut("delete", "D", description="Delete")
    im.register_shortcut("duplicate", "D", ("ctrl",), description="Duplicate")

    assert im.on_key("W", []) == "translate"
    assert im.on_key("w", []) == "translate"  # case-insensitive
    assert im.on_key("S", ["ctrl"]) == "save"
    assert im.on_key("S", []) is None  # wrong modifiers
    assert im.on_key("D", []) == "delete"
    assert im.on_key("D", ["ctrl"]) == "duplicate"


def test_shortcut_no_match() -> None:
    im = InputManager()
    im.register_shortcut("delete", "Delete")
    assert im.on_key("Space", []) is None


def test_shortcuts_property() -> None:
    im = InputManager()
    im.register_shortcut("translate", "W", description="Translate")
    shortcuts = im.shortcuts
    assert "translate" in shortcuts
    assert shortcuts["translate"].key == "W"


def test_wheel_with_modifiers() -> None:
    im = InputManager()
    im.on_wheel(120.0, ["shift"])
    state = im.mouse_state
    assert state.shift


def test_mouse_state_snapshot() -> None:
    im = InputManager()
    im.on_press(50, 60, "left", ["ctrl"])
    state = im.mouse_state
    # Mutating the snapshot shouldn't affect internal state
    # (snapshot is a copy)
    assert state is not im.mouse_state
