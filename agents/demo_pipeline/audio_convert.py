"""Re-export from hapax-demo package for backwards compatibility."""

from demo.pipeline.audio_convert import *  # noqa: F401, F403
from demo.pipeline.audio_convert import (  # noqa: F401
    convert_all_wav_to_mp3,
    get_ffmpeg_path,
    wav_to_mp3,
)
