"""Model wrappers for the temporal classification pipeline.

Each model is a standalone module with lazy loading, VRAM-aware
initialization, and a clean inference interface. The vision backend
calls these from its inference loop.
"""
