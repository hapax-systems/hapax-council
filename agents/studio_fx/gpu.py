"""GPU acceleration helpers for studio effects via OpenCV CUDA.

Provides GpuAccel — a thin wrapper that keeps frames on GPU between
operations and only downloads at the end. Falls back to CPU transparently
if CUDA is unavailable.

Usage in effects:
    from agents.studio_fx.gpu import GpuAccel
    
    gpu = GpuAccel()
    gf = gpu.upload(frame)
    gf = gpu.cvt_color(gf, cv2.COLOR_BGR2GRAY)
    gf = gpu.gaussian_blur(gf, (15, 15))
    result = gpu.download(gf)
"""

from __future__ import annotations

import logging

import cv2
import numpy as np

log = logging.getLogger(__name__)

_HAS_CUDA = False
try:
    if cv2.cuda.getCudaEnabledDeviceCount() > 0:
        _HAS_CUDA = True
        log.info("CUDA available: %d device(s)", cv2.cuda.getCudaEnabledDeviceCount())
except Exception:
    pass


def has_cuda() -> bool:
    return _HAS_CUDA


class GpuAccel:
    """Thin GPU acceleration layer with CPU fallback."""

    def __init__(self) -> None:
        self._cuda = _HAS_CUDA
        # Cached filter objects (CUDA filters use factory pattern)
        self._gauss_cache: dict[tuple, object] = {}
        self._canny: object | None = None
        self._farneback: object | None = None

    @property
    def is_cuda(self) -> bool:
        return self._cuda

    def upload(self, frame: np.ndarray) -> object:
        """Upload numpy frame to GPU. Returns GpuMat or numpy array."""
        if not self._cuda:
            return frame
        gpu = cv2.cuda_GpuMat()
        gpu.upload(frame)
        return gpu

    def download(self, mat: object) -> np.ndarray:
        """Download from GPU to numpy. Passthrough if already numpy."""
        if isinstance(mat, np.ndarray):
            return mat
        return mat.download()

    def cvt_color(self, mat: object, code: int) -> object:
        if not self._cuda:
            return cv2.cvtColor(mat, code)
        return cv2.cuda.cvtColor(mat, code)

    def gaussian_blur(self, mat: object, ksize: tuple[int, int], sigma: float = 0) -> object:
        if not self._cuda:
            return cv2.GaussianBlur(mat, ksize, sigma)
        # Determine type from GpuMat
        key = (ksize, mat.type())
        if key not in self._gauss_cache:
            self._gauss_cache[key] = cv2.cuda.createGaussianFilter(
                mat.type(), mat.type(), ksize, sigma
            )
        return self._gauss_cache[key].apply(mat)

    def canny(self, gray_mat: object, low: float, high: float) -> object:
        if not self._cuda:
            return cv2.Canny(gray_mat, low, high)
        if self._canny is None:
            self._canny = cv2.cuda.createCannyEdgeDetector(low, high)
        return self._canny.detect(gray_mat)

    def warp_affine(self, mat: object, m: np.ndarray, dsize: tuple[int, int]) -> object:
        if not self._cuda:
            return cv2.warpAffine(mat, m, dsize, borderMode=cv2.BORDER_REFLECT)
        return cv2.cuda.warpAffine(mat, m, dsize, borderMode=cv2.BORDER_REFLECT)

    def remap(
        self,
        mat: object,
        map_x: object,
        map_y: object,
        interp: int = cv2.INTER_LINEAR,
    ) -> object:
        if not self._cuda:
            return cv2.remap(mat, map_x, map_y, interp, borderMode=cv2.BORDER_REFLECT)
        # Ensure maps are on GPU
        if isinstance(map_x, np.ndarray):
            gmx = cv2.cuda_GpuMat()
            gmx.upload(map_x)
            map_x = gmx
        if isinstance(map_y, np.ndarray):
            gmy = cv2.cuda_GpuMat()
            gmy.upload(map_y)
            map_y = gmy
        return cv2.cuda.remap(mat, map_x, map_y, interp, borderMode=cv2.BORDER_REFLECT)

    def add_weighted(
        self, mat1: object, a1: float, mat2: object, a2: float, gamma: float = 0
    ) -> object:
        if not self._cuda:
            return cv2.addWeighted(mat1, a1, mat2, a2, gamma)
        return cv2.cuda.addWeighted(mat1, a1, mat2, a2, gamma)

    def resize(self, mat: object, dsize: tuple[int, int]) -> object:
        if not self._cuda:
            return cv2.resize(mat, dsize, interpolation=cv2.INTER_AREA)
        return cv2.cuda.resize(mat, dsize, interpolation=cv2.INTER_AREA)

    def optical_flow_farneback(
        self, prev_gray: object, curr_gray: object
    ) -> np.ndarray:
        """Compute dense optical flow. Returns numpy flow array (H, W, 2)."""
        if not self._cuda:
            return cv2.calcOpticalFlowFarneback(
                prev_gray, curr_gray, None,
                pyr_scale=0.5, levels=3, winsize=15,
                iterations=3, poly_n=5, poly_sigma=1.2, flags=0,
            )
        if self._farneback is None:
            self._farneback = cv2.cuda.FarnebackOpticalFlow.create(
                3, 0.5, False, 15, 3, 5, 1.2, 0
            )
        # Ensure inputs are on GPU
        if isinstance(prev_gray, np.ndarray):
            g1 = cv2.cuda_GpuMat()
            g1.upload(prev_gray)
            prev_gray = g1
        if isinstance(curr_gray, np.ndarray):
            g2 = cv2.cuda_GpuMat()
            g2.upload(curr_gray)
            curr_gray = g2
        gpu_flow = self._farneback.calc(prev_gray, curr_gray, None)
        return gpu_flow.download()

    def dilate(self, mat: object, kernel: np.ndarray, iterations: int = 1) -> object:
        if not self._cuda:
            return cv2.dilate(mat, kernel, iterations=iterations)
        filt = cv2.cuda.createMorphologyFilter(cv2.MORPH_DILATE, mat.type(), kernel)
        result = mat
        for _ in range(iterations):
            result = filt.apply(result)
        return result

    def accumulate_weighted(
        self, src: object, accum: np.ndarray, alpha: float
    ) -> np.ndarray:
        """accumulateWeighted — always CPU (no CUDA equivalent). Returns numpy."""
        if not isinstance(src, np.ndarray):
            src = self.download(src)
        cv2.accumulateWeighted(src, accum, alpha)
        return accum
