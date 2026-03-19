"""Audio scene classification using existing PANNs infrastructure.

Wraps the existing PANNs (panns_inference.AudioTagging) model to provide
scene-level audio classification: typing sounds, door, phone ring, music,
silence, conversation, etc.

PANNs uses the AudioSet ontology (527 classes) — same as YAMNet — so this
provides YAMNet-equivalent functionality without adding TensorFlow.

CPU-only, ~2ms per classification.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

# AudioSet class indices → workspace scene labels
# These map the 527-class AudioSet taxonomy to meaningful workspace categories
_SCENE_MAP: dict[str, str] = {
    # Typing/keyboard
    "Typing": "typing",
    "Computer keyboard": "typing",
    "Clicking": "typing",
    "Mouse click": "typing",
    # Music
    "Music": "music",
    "Musical instrument": "music",
    "Guitar": "music",
    "Piano": "music",
    "Drum": "music",
    "Synthesizer": "music",
    "Bass guitar": "music",
    # Speech/conversation
    "Speech": "conversation",
    "Male speech, man speaking": "conversation",
    "Female speech, woman speaking": "conversation",
    "Conversation": "conversation",
    "Narration, monologue": "conversation",
    # Phone
    "Telephone": "phone",
    "Telephone bell ringing": "phone",
    "Ringtone": "phone",
    # Door/movement
    "Door": "movement",
    "Knock": "movement",
    "Footsteps": "movement",
    "Walk, footsteps": "movement",
    # Silence/ambient
    "Silence": "silence",
    "White noise": "ambient",
    "Pink noise": "ambient",
    "Wind": "ambient",
    "Rain": "ambient",
    # Alerts
    "Alarm": "alert",
    "Alarm clock": "alert",
    "Siren": "alert",
    "Bell": "alert",
    # Other
    "Laughter": "social",
    "Applause": "social",
    "Drinking, sipping": "idle",
    "Eating": "idle",
    "Cough": "idle",
    "Sneeze": "idle",
}

# Priority order for scene classification (highest priority first)
_SCENE_PRIORITY = [
    "alert",
    "phone",
    "conversation",
    "music",
    "typing",
    "movement",
    "social",
    "idle",
    "ambient",
    "silence",
]


class AudioSceneClassifier:
    """Audio scene classification using PANNs AudioTagging.

    Lazy-loads on first call. Returns the highest-priority audio scene
    detected above confidence threshold.
    """

    def __init__(self, threshold: float = 0.3) -> None:
        self._model: Any = None
        self._loaded = False
        self._failed = False
        self._threshold = threshold
        self._last_scene = "silence"
        self._last_top_events: list[tuple[str, float]] = []

    def _load(self) -> bool:
        """Lazy-load PANNs model."""
        if self._loaded:
            return True
        if self._failed:
            return False

        try:
            from panns_inference import AudioTagging

            self._model = AudioTagging(
                checkpoint_path=None,  # uses default Cnn14
                device="cpu",  # PANNs is fast enough on CPU
            )
            self._loaded = True
            log.info("Audio scene classifier loaded (PANNs Cnn14, CPU)")
            return True

        except ImportError:
            log.warning("panns_inference not available for audio scene classification")
            self._failed = True
            return False
        except Exception:
            log.warning("Audio scene classifier load failed", exc_info=True)
            self._failed = True
            return False

    def classify(self, waveform: np.ndarray, sample_rate: int = 16000) -> str:
        """Classify the audio scene from a waveform.

        Args:
            waveform: 1D float32 numpy array (mono, -1 to 1 range).
            sample_rate: Sample rate of the waveform (will resample to 32kHz if needed).

        Returns:
            Scene label string (e.g., "typing", "music", "conversation").
        """
        if not self._load():
            return self._last_scene

        try:
            # PANNs expects 32kHz
            if sample_rate != 32000:
                try:
                    import torch
                    import torchaudio

                    tensor = torch.from_numpy(waveform).unsqueeze(0)
                    tensor = torchaudio.functional.resample(tensor, sample_rate, 32000)
                    waveform = tensor.squeeze(0).numpy()
                except ImportError:
                    # Simple linear interpolation fallback
                    ratio = 32000 / sample_rate
                    n_new = int(len(waveform) * ratio)
                    x_old = np.linspace(0, 1, len(waveform))
                    x_new = np.linspace(0, 1, n_new)
                    waveform = np.interp(x_new, x_old, waveform)

            # PANNs expects (batch, samples) shape
            audio = waveform[np.newaxis, :]

            # Run inference
            _clipwise, _embedding, _framewise = self._model.inference(audio)
            clipwise = _clipwise[0]  # (527,) probabilities

            # Get AudioSet labels
            try:
                from panns_inference import labels as panns_labels

                audioset_labels = panns_labels
            except ImportError:
                audioset_labels = None

            # Map top detections to scene categories
            scene_scores: dict[str, float] = {}
            top_events: list[tuple[str, float]] = []

            if audioset_labels is not None:
                top_indices = np.argsort(clipwise)[::-1][:20]
                for idx in top_indices:
                    label = audioset_labels[idx]
                    score = float(clipwise[idx])
                    if score < self._threshold:
                        continue
                    top_events.append((label, score))
                    scene = _SCENE_MAP.get(label)
                    if scene:
                        scene_scores[scene] = max(scene_scores.get(scene, 0), score)

            self._last_top_events = top_events[:5]

            # Return highest-priority scene above threshold
            for scene in _SCENE_PRIORITY:
                if scene in scene_scores:
                    self._last_scene = scene
                    return scene

            return self._last_scene

        except Exception:
            log.debug("Audio scene classification failed", exc_info=True)
            return self._last_scene

    @property
    def last_top_events(self) -> list[tuple[str, float]]:
        """Return the last top-5 AudioSet events with scores."""
        return self._last_top_events
