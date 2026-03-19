"""CLIP ViT-B/32 zero-shot scene state classification.

Classifies the current scene state from workspace-relevant labels:
"focused coding", "music production", "meeting", "reading", etc.

Uses open_clip (already a dependency for SigLIP-2) with pre-computed
text embeddings for fast inference. ~400MB VRAM.

Complements SigLIP-2's room-type classification with activity-focused
scene understanding.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np  # noqa: TC002 — used at runtime for frame processing

log = logging.getLogger(__name__)

# Workspace scene state labels for zero-shot classification
SCENE_STATE_LABELS: list[str] = [
    "a person focused on coding at a computer",
    "a person producing music in a studio",
    "a person in a video meeting",
    "a person reading or studying",
    "a person writing notes",
    "a person having a conversation",
    "a person eating a meal",
    "a person exercising or stretching",
    "a person resting or sleeping",
    "an empty room with equipment",
    "a person browsing the web",
    "a person playing a musical instrument",
    "a person on the phone",
    "a person gaming",
    "a person doing creative work",
]

# Short labels for the overlay (parallel to SCENE_STATE_LABELS)
SCENE_STATE_SHORT: list[str] = [
    "focused coding",
    "music production",
    "video meeting",
    "reading",
    "writing",
    "conversation",
    "eating",
    "exercising",
    "resting",
    "empty room",
    "browsing",
    "playing instrument",
    "on phone",
    "gaming",
    "creative work",
]


class CLIPSceneClassifier:
    """Zero-shot scene state classification using CLIP ViT-B/32.

    Lazy-loads on first call. Text embeddings pre-computed once.
    """

    def __init__(self) -> None:
        self._model: Any = None
        self._preprocess: Any = None
        self._text_features: Any = None
        self._loaded = False
        self._failed = False
        self._last_scene = ""
        self._device = "cpu"

    def _load(self) -> bool:
        """Lazy-load CLIP model and pre-compute text embeddings."""
        if self._loaded:
            return True
        if self._failed:
            return False

        try:
            import open_clip
            import torch

            model, _, preprocess = open_clip.create_model_and_transforms(
                "ViT-B-32",
                pretrained="openai",
                device="cuda" if torch.cuda.is_available() else "cpu",
            )
            model.eval()
            self._model = model
            self._preprocess = preprocess
            self._device = "cuda" if torch.cuda.is_available() else "cpu"

            # Pre-compute L2-normalized text embeddings
            tokenizer = open_clip.get_tokenizer("ViT-B-32")
            text_tokens = tokenizer(SCENE_STATE_LABELS).to(self._device)
            with torch.no_grad():
                self._text_features = model.encode_text(text_tokens)
                self._text_features /= self._text_features.norm(dim=-1, keepdim=True)

            self._loaded = True
            log.info(
                "CLIP ViT-B/32 scene classifier loaded (%d labels, %s)",
                len(SCENE_STATE_LABELS),
                self._device,
            )
            return True

        except ImportError:
            log.warning("open_clip not available for CLIP scene classifier")
            self._failed = True
            return False
        except Exception:
            log.warning("CLIP scene classifier load failed", exc_info=True)
            self._failed = True
            return False

    def predict(self, frame: np.ndarray) -> str:
        """Classify current scene state from a single frame.

        Args:
            frame: BGR numpy array (H, W, 3).

        Returns:
            Short scene state label, or "" on failure.
        """
        if not self._load():
            return ""

        try:
            import cv2
            import torch
            from PIL import Image

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(rgb)
            input_tensor = self._preprocess(pil_img).unsqueeze(0).to(self._device)

            with torch.no_grad():
                image_features = self._model.encode_image(input_tensor)
                image_features /= image_features.norm(dim=-1, keepdim=True)
                similarity = (image_features @ self._text_features.T).squeeze(0)
                idx = similarity.argmax().item()
                score = similarity[idx].item()

            if score < 0.15:  # low confidence threshold
                return self._last_scene

            label = SCENE_STATE_SHORT[idx]
            self._last_scene = label
            return label

        except Exception:
            log.debug("CLIP scene classification failed", exc_info=True)
            return self._last_scene

    def to_cpu(self) -> None:
        """Move model to CPU to free VRAM."""
        if self._model is not None and self._device == "cuda":
            self._model.cpu()
            if self._text_features is not None:
                self._text_features = self._text_features.cpu()
            self._device = "cpu"
            import torch

            torch.cuda.empty_cache()

    def to_cuda(self) -> None:
        """Move model back to CUDA."""
        if self._model is not None and self._device == "cpu":
            import torch

            if torch.cuda.is_available():
                self._model.cuda()
                if self._text_features is not None:
                    self._text_features = self._text_features.cuda()
                self._device = "cuda"
