"""Timeline model — Qt-free, testable state for the playback panel.

The model owns tracks, clips, keyframes, the playhead, and loop
points. The ``TimelineWidget`` renders this model and translates
user gestures back into model operations. No playback engine exists
yet — the model is the contract that playback will drive later.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from math import isfinite
from typing import Any
from uuid import uuid4

#: Callback signature for model-change notifications.
ChangeHandler = Callable[[], None]


class TrackType(StrEnum):
    """Track lane types (rendering + annotation tracks)."""

    VIDEO = "video"
    PROJECTION = "projection"
    ANIMATION = "animation"
    AUDIO = "audio"
    MARKERS = "markers"
    NOTES = "notes"


@dataclass
class TimelineKeyframe:
    """A keyframe on a track's property lane."""

    id: str = field(default_factory=lambda: uuid4().hex[:10])
    track_id: str = ""
    property_name: str = ""
    frame: int = 0
    value: float = 0.0


@dataclass
class TimelineClip:
    """A clip on a track."""

    id: str = field(default_factory=lambda: uuid4().hex[:10])
    track_id: str = ""
    name: str = "Clip"
    start_frame: int = 0
    duration_frames: int = 24
    color: str = "#FF9E00"

    @property
    def end_frame(self) -> int:
        """First frame after the clip ends."""
        return self.start_frame + self.duration_frames


@dataclass
class TimelineTrack:
    """A typed lane of clips and keyframes."""

    id: str = field(default_factory=lambda: uuid4().hex[:10])
    name: str = "Track"
    track_type: TrackType = TrackType.PROJECTION
    clips: list[TimelineClip] = field(default_factory=list)
    keyframes: list[TimelineKeyframe] = field(default_factory=list)
    muted: bool = False
    locked: bool = False
    visible: bool = True
    color: str = "#FF9E00"

    def clips_in_range(self, start: int, end: int) -> list[TimelineClip]:
        """Return clips overlapping the half-open range ``[start, end)``."""
        return [c for c in self.clips if c.start_frame < end and c.end_frame > start]


def default_color(track_type: TrackType) -> str:
    """Return the default lane color for a track type."""
    return {
        TrackType.VIDEO: "#3D7EFF",
        TrackType.PROJECTION: "#FF9E00",
        TrackType.ANIMATION: "#B453F7",
        TrackType.AUDIO: "#30D158",
        TrackType.MARKERS: "#FFC107",
        TrackType.NOTES: "#8A8F9C",
    }[track_type]


class TimelineModel:
    """Container for tracks, clips, keyframes, and playback state.

    Notifies ``_handlers`` after every mutation so the view can
    repaint. Frames are integer; timecode conversion is provided.
    """

    def __init__(
        self,
        fps: float = 30.0,
        duration_frames: int = 3600,
        bpm: float = 120.0,
    ) -> None:
        if not isfinite(fps) or fps <= 0:
            raise ValueError("fps must be positive")
        self._fps: float = fps
        if bpm <= 0:
            raise ValueError("bpm must be positive")
        self._bpm: float = bpm
        self._duration_frames: int = duration_frames
        self._tracks: list[TimelineTrack] = []
        self._playhead_frame: int = 0
        self._in_point: int = 0
        self._out_point: int = duration_frames
        self._loop_enabled: bool = False
        self._handlers: list[ChangeHandler] = []

    # -- Observation --------------------------------------------------------

    def subscribe(self, handler: ChangeHandler) -> None:
        """Register a callback invoked after any model change."""
        if handler not in self._handlers:
            self._handlers.append(handler)

    def unsubscribe(self, handler: ChangeHandler) -> None:
        """Remove a change callback."""
        if handler in self._handlers:
            self._handlers.remove(handler)

    def _notify(self) -> None:
        for handler in list(self._handlers):
            handler()

    # -- Configuration ------------------------------------------------------

    @property
    def fps(self) -> float:
        return self._fps

    @fps.setter
    def fps(self, value: float) -> None:
        if not isfinite(value) or value <= 0:
            raise ValueError("fps must be positive")
        self._fps = value
        self._notify()

    @property
    def bpm(self) -> float:
        """Beats per minute — a musical tempo, independent of the frame rate."""
        return self._bpm

    @bpm.setter
    def bpm(self, value: float) -> None:
        if value <= 0:
            raise ValueError("bpm must be positive")
        self._bpm = value
        self._notify()

    @property
    def duration_frames(self) -> int:
        return self._duration_frames

    # -- Tracks -------------------------------------------------------------

    @property
    def tracks(self) -> list[TimelineTrack]:
        """Return the ordered list of tracks (copy semantics via list)."""
        return list(self._tracks)

    def track(self, track_id: str) -> TimelineTrack | None:
        """Return a track by id."""
        return next((t for t in self._tracks if t.id == track_id), None)

    def add_track(
        self,
        track_type: TrackType = TrackType.PROJECTION,
        name: str | None = None,
    ) -> TimelineTrack:
        """Append a new track and return it."""
        track = TimelineTrack(
            name=name or f"{track_type.value.title()} Track",
            track_type=track_type,
            color=default_color(track_type),
        )
        self._tracks.append(track)
        self._notify()
        return track

    def remove_track(self, track_id: str) -> bool:
        """Remove a track and its contents. Returns False when absent."""
        track = self.track(track_id)
        if track is None:
            return False
        self._tracks.remove(track)
        self._notify()
        return True

    def set_track_name(self, track_id: str, name: str) -> None:
        """Rename a track."""
        track = self.track(track_id)
        if track is not None and track.name != name:
            track.name = name
            self._notify()

    def set_track_color(self, track_id: str, color: str) -> None:
        """Change a track's lane color."""
        track = self.track(track_id)
        if track is not None and track.color != color:
            track.color = color
            self._notify()

    def set_track_muted(self, track_id: str, muted: bool) -> None:
        """Mute/unmute a track."""
        track = self.track(track_id)
        if track is not None and track.muted != muted:
            track.muted = muted
            self._notify()

    def set_track_locked(self, track_id: str, locked: bool) -> None:
        """Lock/unlock a track (locked tracks reject clip edits)."""
        track = self.track(track_id)
        if track is not None and track.locked != locked:
            track.locked = locked
            self._notify()

    def set_track_visible(self, track_id: str, visible: bool) -> None:
        """Show/hide a track lane."""
        track = self.track(track_id)
        if track is not None and track.visible != visible:
            track.visible = visible
            self._notify()

    def move_track(self, track_id: str, index: int) -> bool:
        """Move a track to *index* in the lane order. Returns False when absent."""
        track = self.track(track_id)
        if track is None:
            return False
        index = max(0, min(index, len(self._tracks) - 1))
        self._tracks.remove(track)
        self._tracks.insert(index, track)
        self._notify()
        return True

    # -- Clips --------------------------------------------------------------

    def add_clip(
        self,
        track_id: str,
        name: str,
        start_frame: int = 0,
        duration_frames: int = 24,
        color: str | None = None,
    ) -> TimelineClip | None:
        """Add a clip to a track. Returns ``None`` when the track is absent,
        locked, the input is invalid (negative start or sub-one-frame
        duration), or the clip would overlap an existing clip."""
        track = self.track(track_id)
        if track is None or track.locked:
            return None
        if start_frame < 0 or duration_frames < 1:
            return None
        end = start_frame + duration_frames
        if any(c.start_frame < end and c.end_frame > start_frame for c in track.clips):
            return None
        clip = TimelineClip(
            track_id=track_id,
            name=name,
            start_frame=start_frame,
            duration_frames=duration_frames,
            color=color or track.color,
        )
        track.clips.append(clip)
        self._notify()
        return clip

    def remove_clip(self, clip_id: str) -> bool:
        """Remove a clip by id. Returns False when absent."""
        for track in self._tracks:
            clip = next((c for c in track.clips if c.id == clip_id), None)
            if clip is not None:
                track.clips.remove(clip)
                self._notify()
                return True
        return False

    def move_clip(self, clip_id: str, new_start: int) -> bool:
        """Move a clip to a new start frame (no overlap). Returns False when
        the move is rejected (locked track, overlap, or absent clip)."""
        for track in self._tracks:
            clip = next((c for c in track.clips if c.id == clip_id), None)
            if clip is None:
                continue
            if track.locked:
                return False
            new_start = max(
                0, min(new_start, self._duration_frames - clip.duration_frames)
            )
            end = new_start + clip.duration_frames
            if any(
                c.id != clip_id and c.start_frame < end and c.end_frame > new_start
                for c in track.clips
            ):
                return False
            clip.start_frame = new_start
            self._notify()
            return True
        return False

    def trim_clip(self, clip_id: str, new_duration: int) -> bool:
        """Change a clip's duration (min 1 frame, no overlap, within model)."""
        for track in self._tracks:
            clip = next((c for c in track.clips if c.id == clip_id), None)
            if clip is None:
                continue
            if track.locked or new_duration < 1:
                return False
            end = clip.start_frame + new_duration
            if end > self._duration_frames:
                return False
            if any(
                c.id != clip_id
                and c.start_frame < end
                and c.end_frame > clip.start_frame
                for c in track.clips
            ):
                return False
            clip.duration_frames = new_duration
            self._notify()
            return True
        return False

    def clips_in_range(self, start: int, end: int) -> list[TimelineClip]:
        """Return every clip overlapping ``[start, end)`` across all tracks."""
        result: list[TimelineClip] = []
        for track in self._tracks:
            if track.visible:
                result.extend(track.clips_in_range(start, end))
        return result

    # -- Keyframes ----------------------------------------------------------

    def add_keyframe(
        self,
        track_id: str,
        property_name: str,
        frame: int,
        value: float = 0.0,
    ) -> TimelineKeyframe | None:
        """Add a keyframe on a track's property lane."""
        track = self.track(track_id)
        if track is None:
            return None
        key = TimelineKeyframe(
            track_id=track_id,
            property_name=property_name,
            frame=max(0, frame),
            value=value,
        )
        track.keyframes.append(key)
        self._notify()
        return key

    def keyframes_on(self, track_id: str, property_name: str) -> list[TimelineKeyframe]:
        """Return keyframes for a property lane, sorted by frame."""
        track = self.track(track_id)
        if track is None:
            return []
        return sorted(
            (k for k in track.keyframes if k.property_name == property_name),
            key=lambda k: k.frame,
        )

    def property_names(self, track_id: str) -> list[str]:
        """Return the distinct property lane names on a track."""
        track = self.track(track_id)
        if track is None:
            return []
        names: list[str] = []
        for key in track.keyframes:
            if key.property_name not in names:
                names.append(key.property_name)
        return names

    # -- Playhead / transport ------------------------------------------------

    @property
    def playhead_frame(self) -> int:
        return self._playhead_frame

    @playhead_frame.setter
    def playhead_frame(self, frame: int) -> None:
        frame = max(0, min(int(frame), self._duration_frames))
        if frame != self._playhead_frame:
            self._playhead_frame = frame
            self._notify()

    @property
    def loop_enabled(self) -> bool:
        return self._loop_enabled

    @loop_enabled.setter
    def loop_enabled(self, enabled: bool) -> None:
        if enabled != self._loop_enabled:
            self._loop_enabled = enabled
            self._notify()

    @property
    def in_point(self) -> int:
        return self._in_point

    @property
    def out_point(self) -> int:
        return self._out_point

    def set_loop_range(self, in_point: int, out_point: int) -> None:
        """Set the loop region (clamped, in < out enforced)."""
        in_point = max(0, min(int(in_point), self._duration_frames))
        out_point = max(0, min(int(out_point), self._duration_frames))
        if in_point >= out_point:
            return
        if in_point != self._in_point or out_point != self._out_point:
            self._in_point = in_point
            self._out_point = out_point
            self._notify()

    def clear_loop_range(self) -> None:
        """Reset the loop region to the whole timeline."""
        self.set_loop_range(0, self._duration_frames)

    def step_frames(self, delta: int) -> int:
        """Move the playhead by *delta* frames; returns the new frame."""
        self.playhead_frame = self._playhead_frame + delta
        return self._playhead_frame

    # -- Timecode -----------------------------------------------------------

    def timecode(self, frame: int) -> str:
        """Format *frame* as SMPTE ``HH:MM:SS:FF`` at the model FPS."""
        frame = max(0, int(frame))
        fps = max(1.0, float(self._fps))
        total_seconds = int(frame / fps)
        ff = int(frame % fps)
        ss = total_seconds % 60
        mm = (total_seconds // 60) % 60
        hh = total_seconds // 3600
        return f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"

    # -- Serialization (lightweight, for tests and persistence) -------------

    def to_dict(self) -> dict[str, Any]:
        """Serialize the model to plain JSON-safe data."""
        return {
            "fps": self._fps,
            "bpm": self._bpm,
            "duration_frames": self._duration_frames,
            "playhead_frame": self._playhead_frame,
            "in_point": self._in_point,
            "out_point": self._out_point,
            "loop_enabled": self._loop_enabled,
            "tracks": [
                {
                    "id": t.id,
                    "name": t.name,
                    "type": t.track_type.value,
                    "muted": t.muted,
                    "locked": t.locked,
                    "visible": t.visible,
                    "color": t.color,
                    "clips": [
                        {
                            "id": c.id,
                            "name": c.name,
                            "start": c.start_frame,
                            "duration": c.duration_frames,
                            "color": c.color,
                        }
                        for c in t.clips
                    ],
                    "keyframes": [
                        {
                            "id": k.id,
                            "property": k.property_name,
                            "frame": k.frame,
                            "value": k.value,
                        }
                        for k in t.keyframes
                    ],
                }
                for t in self._tracks
            ],
        }
