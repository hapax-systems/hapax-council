"""Tests for wake word audio augmentation pipeline."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

# scripts/ is not a package — add it to sys.path so we can import train_wake_word
_scripts_dir = str(Path(__file__).resolve().parents[2] / "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)


def test_build_augmentation_pipeline_returns_compose():
    """build_augmentation_pipeline returns an audiomentations Compose."""
    from train_wake_word import build_augmentation_pipeline

    pipeline = build_augmentation_pipeline()
    assert pipeline is not None
    from audiomentations import Compose

    assert isinstance(pipeline, Compose)


def test_augment_clips_increases_sample_count():
    """augment_clips produces more clips than input."""
    from train_wake_word import augment_clips

    clips = [np.random.randint(-1000, 1000, size=8000, dtype=np.int16) for _ in range(3)]
    augmented = augment_clips(clips, n_augmented_per_clip=4)
    # originals (3) + augmented (3 * 4 = 12) = 15
    assert len(augmented) == 15


def test_augment_clips_preserves_dtype():
    """Augmented clips are int16 at 16kHz."""
    from train_wake_word import augment_clips

    clips = [np.random.randint(-1000, 1000, size=8000, dtype=np.int16)]
    augmented = augment_clips(clips, n_augmented_per_clip=2)
    for clip in augmented:
        assert clip.dtype == np.int16


def test_augment_clips_zero_augments_returns_originals():
    """With n_augmented_per_clip=0, returns originals only."""
    from train_wake_word import augment_clips

    clips = [np.random.randint(-1000, 1000, size=8000, dtype=np.int16) for _ in range(5)]
    augmented = augment_clips(clips, n_augmented_per_clip=0)
    assert len(augmented) == 5


def test_extract_features_accepts_augment_param():
    """extract_features_from_clips accepts augment_positive parameter."""
    import inspect

    from train_wake_word import extract_features_from_clips

    sig = inspect.signature(extract_features_from_clips)
    assert "augment_positive" in sig.parameters
    assert "n_augmented_per_clip" in sig.parameters


def test_train_model_accepts_real_weight_param():
    """train_model accepts real_sample_weight parameter."""
    import inspect

    from train_wake_word import train_model

    sig = inspect.signature(train_model)
    assert "real_sample_weight" in sig.parameters
