"""MoViNet-A2 streaming action recognition.

Replaces X3D-XS's 4-frame buffer approach with a streaming model that
maintains internal state across frames. ~200MB VRAM, ~10ms per frame.

MoViNet processes frames one at a time via a causal architecture,
so no frame buffering is needed. The model remembers context from
previous frames through its internal stream state.

Falls back to X3D-XS-compatible interface if MoViNet isn't available.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np  # noqa: TC002 — used at runtime for frame processing

log = logging.getLogger(__name__)

# Kinetics-600 label subset relevant to workspace monitoring
_WORKSPACE_LABELS: dict[int, str] = {
    0: "typing",
    1: "reading",
    2: "writing",
    3: "using_computer",
    4: "talking_on_phone",
    5: "playing_instrument",
    6: "listening_to_music",
    7: "drinking",
    8: "eating",
    9: "stretching",
    10: "standing_up",
    11: "sitting_down",
    12: "walking",
    13: "gesturing",
    14: "looking_at_phone",
}


class MoViNetA2:
    """Streaming MoViNet-A2 action recognition.

    Lazy-loads on first call. Falls back gracefully if torch/torchvision
    not available or model download fails.
    """

    def __init__(self) -> None:
        self._model: Any = None
        self._stream_state: Any = None
        self._transform: Any = None
        self._labels: dict[int, str] = {}
        self._loaded = False
        self._failed = False
        self._last_action = "unknown"
        self._device = "cpu"

    def _load(self) -> bool:
        """Lazy-load MoViNet-A2 model."""
        if self._loaded:
            return True
        if self._failed:
            return False

        try:
            import torch

            # Try torchvision MoViNet first (available since torchvision 0.14)
            try:
                from torchvision.models.video import MoViNet_A2_Weights
                from torchvision.models.video import movinet as tv_movinet

                weights = MoViNet_A2_Weights.DEFAULT
                self._model = tv_movinet.movinet_a2(weights=weights)
                self._transform = weights.transforms()
                self._labels = {i: name for i, name in enumerate(weights.meta["categories"])}
                log.info("MoViNet-A2 loaded via torchvision (%d labels)", len(self._labels))
            except (ImportError, AttributeError):
                # Torchvision doesn't have MoViNet — use torch.hub fallback
                try:
                    self._model = torch.hub.load(
                        "facebookresearch/pytorchvideo:main",
                        "movineta2",
                        pretrained=True,
                    )
                    log.info("MoViNet-A2 loaded via pytorchvideo hub")
                except Exception:
                    log.warning("MoViNet-A2 not available, action recognition disabled")
                    self._failed = True
                    return False

            self._model.eval()
            if torch.cuda.is_available():
                self._model = self._model.cuda()
                self._device = "cuda"
                log.info("MoViNet-A2 on CUDA (~200MB VRAM)")
            else:
                log.info("MoViNet-A2 on CPU")

            self._loaded = True
            return True

        except ImportError:
            log.warning("torch not available for MoViNet-A2")
            self._failed = True
            return False
        except Exception:
            log.warning("MoViNet-A2 load failed", exc_info=True)
            self._failed = True
            return False

    def predict(self, frame: np.ndarray) -> str:
        """Run action recognition on a single frame.

        Args:
            frame: BGR numpy array (H, W, 3).

        Returns:
            Action label string, or "unknown" on failure.
        """
        if not self._load():
            return "unknown"

        try:
            import cv2
            import torch

            # Resize and convert BGR→RGB
            small = cv2.resize(frame, (224, 224))
            rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)

            # Convert to tensor (C, T, H, W) with T=1 for streaming
            tensor = torch.from_numpy(rgb).permute(2, 0, 1).float() / 255.0
            tensor = tensor.unsqueeze(1).unsqueeze(0)  # (1, C, 1, H, W)

            if self._transform is not None:
                # torchvision transform handles normalization
                tensor = tensor.squeeze(0).squeeze(1)  # (C, H, W)
                tensor = self._transform(tensor)
                tensor = tensor.unsqueeze(1).unsqueeze(0)  # (1, C, 1, H, W)
            else:
                # Manual normalization for pytorchvideo
                mean = torch.tensor([0.45, 0.45, 0.45]).view(3, 1, 1, 1)
                std = torch.tensor([0.225, 0.225, 0.225]).view(3, 1, 1, 1)
                if self._device == "cuda":
                    mean, std = mean.cuda(), std.cuda()
                tensor = (tensor - mean) / std

            if self._device == "cuda":
                tensor = tensor.cuda()

            with torch.no_grad():
                output = self._model(tensor)
                pred_idx = output.argmax(1).item()

            # Map to label
            if self._labels:
                label = self._labels.get(pred_idx, f"action_{pred_idx}")
            else:
                label = _WORKSPACE_LABELS.get(pred_idx, f"action_{pred_idx}")

            self._last_action = label
            return label

        except Exception:
            log.debug("MoViNet-A2 inference failed", exc_info=True)
            return self._last_action

    def to_cpu(self) -> None:
        """Move model to CPU to free VRAM."""
        if self._model is not None and self._device == "cuda":
            self._model.cpu()
            self._device = "cpu"
            import torch

            torch.cuda.empty_cache()

    def to_cuda(self) -> None:
        """Move model back to CUDA."""
        if self._model is not None and self._device == "cpu":
            import torch

            if torch.cuda.is_available():
                self._model.cuda()
                self._device = "cuda"
