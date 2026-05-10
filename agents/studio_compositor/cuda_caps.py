"""Shared CUDA caps strings for compositor graph construction."""

from __future__ import annotations


def cuda_input_caps_string(width: int, height: int, fps: int) -> str:
    return (
        "video/x-raw(memory:CUDAMemory),format=NV12,"
        f"width={width},height={height},framerate={fps}/1"
    )


def cuda_output_caps_string(width: int, height: int, fps: int) -> str:
    return (
        "video/x-raw(memory:CUDAMemory),format=NV12,"
        f"width={width},height={height},framerate={fps}/1"
    )
