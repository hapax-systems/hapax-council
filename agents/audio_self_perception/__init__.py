"""Audio self-perception loop — AVSDLC-002.

Taps broadcast-master via parecord, computes spectral features (RMS,
centroid, balance, voice/music/environment ratio), writes to /dev/shm
for the visual layer aggregator to inject into stimmung dimensions.
"""
