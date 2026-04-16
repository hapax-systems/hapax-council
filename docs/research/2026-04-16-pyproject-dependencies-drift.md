---
title: pyproject.toml dependencies drift audit
date: 2026-04-16
queue_item: '310'
status: catalog
---

# pyproject.toml — dependency drift

Verify declared deps match actual imports across `agents/`, `shared/`, `logos/`.

## Summary

| Metric | Count |
|---|---|
| Declared packages (deps + all extras) | 59 |

## Declared

```
chat-downloader
evdev
fastapi
faster-whisper
google-api-python-client
google-auth-oauthlib
google-genai
hapax-council
hsemotion-onnx
httpx
jinja2
kokoro
langfuse
litellm
llmlingua
matplotlib
mediapipe
mido
mistralai
model2vec
moderngl
moviepy
obsws-python
ollama
opencv-python-headless
opentelemetry-api
opentelemetry-exporter-otlp-proto-http
opentelemetry-instrumentation-fastapi
opentelemetry-instrumentation-httpx
opentelemetry-instrumentation-logging
opentelemetry-sdk
openwakeword
panns-inference
pillow
pipecat-ai
playwright
prometheus-fastapi-instrumentator
pvporcupine
pyannote-audio
pyaudio
pycairo
pydantic
pydantic-ai
pygobject
pyte
python-json-logger
python-rtmidi
python-toon
pyyaml
qdrant-client
sdnotify
silero-vad
soundfile
sse-starlette
torchaudio
ultralytics
uvicorn
uvloop
watchdog
```
