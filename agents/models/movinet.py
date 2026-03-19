"""MoViNet-A2 streaming action recognition.

Replaces X3D-XS's 4-frame buffer approach with a streaming model that
maintains internal state across frames. ~43MB VRAM, ~10ms per frame.

MoViNet processes frames one at a time via a causal architecture,
so no frame buffering is needed. The model remembers context from
previous frames through its internal stream state.

Uses the movinets package (Atze00/MoViNet-pytorch) with Kinetics-600
pretrained weights. Streaming mode enables per-frame inference with
temporal context maintained in activation buffers.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np  # noqa: TC002 — used at runtime for frame processing

log = logging.getLogger(__name__)

_LABELS_CACHE = Path.home() / ".cache" / "hapax-voice" / "kinetics400_labels.json"
_LABELS_URL = (
    "https://dl.fbaipublicfiles.com/pyslowfast/dataset/class_names/kinetics_classnames.json"
)


def _load_kinetics_labels() -> dict[int, str]:
    """Load Kinetics class labels (K400 — indices 0-399 overlap with K600)."""
    try:
        if not _LABELS_CACHE.exists():
            _LABELS_CACHE.parent.mkdir(parents=True, exist_ok=True)
            urllib.request.urlretrieve(_LABELS_URL, _LABELS_CACHE)
        data = json.loads(_LABELS_CACHE.read_text())
        # Format: {"\"label_name\"": index, ...} — invert to {index: label_name}
        if isinstance(data, dict):
            return {int(v): k.strip().strip('"') for k, v in data.items()}
    except Exception:
        log.debug("Failed to load Kinetics labels", exc_info=True)
    return {}


class MoViNetA2:
    """Streaming MoViNet-A2 action recognition.

    Lazy-loads on first call. Uses movinets package with causal (streaming)
    mode for per-frame inference with temporal memory.
    """

    def __init__(self) -> None:
        self._model: Any = None
        self._labels: dict[int, str] = {}
        self._loaded = False
        self._failed = False
        self._last_action = "unknown"
        self._device = "cpu"

    def _load(self) -> bool:
        """Lazy-load MoViNet-A2 streaming model."""
        if self._loaded:
            return True
        if self._failed:
            return False

        try:
            import torch
            from movinets import MoViNet
            from movinets.config import _C

            self._model = MoViNet(_C.MODEL.MoViNetA2, causal=True, pretrained=True)
            self._model.eval()

            if torch.cuda.is_available():
                self._model = self._model.cuda()
                # Reinit streaming buffers on CUDA to avoid device mismatch
                self._model.clean_activation_buffers()
                self._device = "cuda"
            else:
                self._device = "cpu"

            self._labels = _load_kinetics_labels()
            self._loaded = True
            log.info(
                "MoViNet-A2 streaming loaded (%s, %d labels, %.1fM params)",
                self._device,
                len(self._labels),
                sum(p.numel() for p in self._model.parameters()) / 1e6,
            )
            return True

        except ImportError:
            log.warning(
                "movinets package not installed — pip install movinets or "
                "uv pip install 'git+https://github.com/Atze00/MoViNet-pytorch.git'"
            )
            self._failed = True
            return False
        except Exception:
            log.warning("MoViNet-A2 load failed", exc_info=True)
            self._failed = True
            return False

    def predict(self, frame: np.ndarray) -> str:
        """Run streaming action recognition on a single frame.

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

            # Resize to 224x224, BGR→RGB, normalize to [0,1]
            small = cv2.resize(frame, (224, 224))
            rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
            tensor = torch.from_numpy(rgb).permute(2, 0, 1).float() / 255.0
            # MoViNet expects (B, C, T, H, W) — T=1 for streaming
            tensor = tensor.unsqueeze(1).unsqueeze(0)

            if self._device == "cuda":
                tensor = tensor.cuda()

            with torch.no_grad():
                output = self._model(tensor)
                pred_idx = int(output.argmax(1).item())

            if self._labels:
                label = self._labels.get(pred_idx, f"action_{pred_idx}")
            else:
                label = f"action_{pred_idx}"

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
                self._model.clean_activation_buffers()
                self._device = "cuda"
