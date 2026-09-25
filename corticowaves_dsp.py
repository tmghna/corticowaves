"""Streaming DSP and adaptive attention normalization for CorticoWaves."""

from __future__ import annotations

import math
from collections.abc import Iterable

import numpy as np
from scipy.signal import welch


class AdaptiveZScoreEngine:
    """Normalize streaming attention ratios with an adaptive EWMA model.

    The first ``warmup_seconds`` of ratios establish the initial mean and
    standard deviation. During warm-up the output is neutral (Z=0, drive=0.5).
    After warm-up, mean and variance continue adapting to the live stream.
    """

    def __init__(
        self,
        sampling_rate_hz: float = 10.0,
        window_time_sec: float = 30.0,
        warmup_seconds: float = 5.0,
        sigmoid_gain: float = 1.2,
        ratio_smoothing_seconds: float = 0.4,
    ) -> None:
        if sampling_rate_hz <= 0 or window_time_sec <= 0:
            raise ValueError("sampling_rate_hz and window_time_sec must be positive")
        if warmup_seconds <= 0:
            raise ValueError("warmup_seconds must be positive")
        if sigmoid_gain <= 0:
            raise ValueError("sigmoid_gain must be positive")
        if ratio_smoothing_seconds < 0:
            raise ValueError("ratio_smoothing_seconds cannot be negative")

        self.sampling_rate_hz = float(sampling_rate_hz)
        self.window_time_sec = float(window_time_sec)
        self.warmup_frames = max(1, math.ceil(sampling_rate_hz * warmup_seconds))
        self.alpha = 1.0 / (sampling_rate_hz * window_time_sec)
        self.sigmoid_gain = float(sigmoid_gain)
        self.ratio_smoothing_alpha = (
            1.0
            if ratio_smoothing_seconds == 0
            else 1.0
            - math.exp(-1.0 / (sampling_rate_hz * ratio_smoothing_seconds))
        )
        self._warmup_samples: list[float] = []
        self._smoothed_ratio: float | None = None
        self.running_mean: float | None = None
        self.running_variance: float | None = None

    @property
    def is_warmed_up(self) -> bool:
        return len(self._warmup_samples) >= self.warmup_frames

    @property
    def running_std(self) -> float:
        return self._safe_std(self.running_variance)

    def update(self, ratio: float) -> dict[str, float]:
        """Update the model with one finite Beta/Alpha ratio."""
        ratio = float(ratio)
        if not math.isfinite(ratio) or ratio < 0:
            raise ValueError("attention ratio must be a finite non-negative number")

        if self._smoothed_ratio is None:
            self._smoothed_ratio = ratio
        else:
            self._smoothed_ratio += self.ratio_smoothing_alpha * (
                ratio - self._smoothed_ratio
            )
        normalized_ratio = self._smoothed_ratio

        if not self.is_warmed_up:
            self._warmup_samples.append(normalized_ratio)
            if len(self._warmup_samples) == self.warmup_frames:
                self.running_mean = float(np.mean(self._warmup_samples))
                self.running_variance = float(np.var(self._warmup_samples))
            mean = self.running_mean if self.running_mean is not None else ratio
            std = self.running_std
            return self._frame(0.0, mean, std)

        assert self.running_mean is not None
        assert self.running_variance is not None
        diff = normalized_ratio - self.running_mean
        self.running_mean += self.alpha * diff
        self.running_variance = (1.0 - self.alpha) * (
            self.running_variance + self.alpha * diff * diff
        )
        std = self.running_std
        z_score = (normalized_ratio - self.running_mean) / std
        return self._frame(z_score, self.running_mean, std)

    def update_many(self, ratios: Iterable[float]) -> list[dict[str, float]]:
        """Normalize a sequence in arrival order."""
        return [self.update(ratio) for ratio in ratios]

    @staticmethod
    def _safe_std(variance: float | None) -> float:
        return math.sqrt(max(variance or 0.0, 0.0)) + 1e-6

    def _frame(self, z_score: float, mean: float, std: float) -> dict[str, float]:
        drive = 1.0 / (1.0 + math.exp(-self.sigmoid_gain * z_score))
        return {
            "attention_metric": min(1.0, max(0.0, drive)),
            "z_score": float(z_score),
            "running_mean": float(mean),
            "running_std": float(std),
        }


def calculate_band_powers(
    signal_array: Iterable[float],
    fs: float,
    nperseg: int,
) -> tuple[float, float]:
    """Calculate raw alpha and beta band powers from the filtered signal."""
    signal = np.asarray(list(signal_array), dtype=float)
    if signal.size < 2:
        raise ValueError("at least two signal samples are required")
    segment = min(nperseg, signal.size)
    freqs, psd = welch(
        signal,
        fs=fs,
        nperseg=segment,
        noverlap=segment // 2,
        detrend=False,
    )
    alpha = (freqs >= 8.0) & (freqs <= 12.0)
    beta = (freqs >= 13.0) & (freqs <= 30.0)
    p_alpha = float(np.trapezoid(psd[alpha], freqs[alpha]))
    p_beta = float(np.trapezoid(psd[beta], freqs[beta]))
    return p_alpha, p_beta


def calculate_attention_ratio(
    signal_array: Iterable[float],
    fs: float,
    nperseg: int,
) -> tuple[float, float, float]:
    """Return raw alpha power, beta power, and Beta/Alpha ratio."""
    p_alpha, p_beta = calculate_band_powers(signal_array, fs, nperseg)
    return p_alpha, p_beta, p_beta / max(p_alpha, 1e-12)
