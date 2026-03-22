# Voice Image Generation Tool Design

**Goal:** Enable the voice assistant to capture images from cameras and generate/edit images using AI models, with output delivered to the operator's screen or phone.

**Decision:** Gemini image generation via LiteLLM, with webcam capture as optional input. Output saved to disk and opened with `xdg-open`, with optional SMS delivery.

---

## Use Cases

1. *"Take a pic of me and make it look like the I'm fine meme"* — capture + style transfer / meme composition
2. *"Generate album art for a dusty boom bap beat"* — text-to-image, no camera input
3. *"What would this studio look like with better lighting?"* — capture + edit prompt
4. *"Make a flyer for Saturday's session"* — text-to-image with context from calendar/notes

---

## Architecture

```
User speaks image request
  → LLM decides to call generate_image tool
  → Handler:
    1. If camera source requested: capture frame via WebcamCapturer
    2. Send prompt + optional image to Gemini 2.0 Flash (image gen)
    3. Save result to ~/Pictures/hapax-generated/
    4. Open with xdg-open (shows on screen immediately)
    5. Return description to LLM for spoken confirmation
  → LLM speaks: "Done — I put it up on your screen"
```

### Why Gemini, Not ComfyUI

| Factor | Gemini Flash | ComfyUI |
|--------|-------------|---------|
| API simplicity | Single HTTP call | Workflow JSON, polling, node setup |
| Text understanding | Native — handles "I'm fine meme" naturally | Needs explicit LoRA/checkpoint per style |
| Image editing | Built-in (send image + prompt) | Requires img2img workflow config |
| Latency | ~2-4s | ~10-30s (depends on workflow) |
| VRAM | None (cloud) | Shares RTX 3090 with Ollama |
| Quality ceiling | Good for memes/edits, not photorealistic | Higher quality, more control |

Gemini wins for conversational image gen — the operator is talking, not configuring workflows. ComfyUI is better for production-quality output but wrong for voice interaction latency.

**Fallback path:** If Gemini image gen is unavailable or the operator wants higher quality, a future `generate_image_hq` tool could route to ComfyUI. Not in scope for this design.

---

## Tool Schema

```python
_generate_image = FunctionSchema(
    name="generate_image",
    description=(
        "Generate or edit an image using AI. Can optionally capture a photo "
        "from a camera first as a starting point. The result is saved to disk "
        "and displayed on screen."
    ),
    properties={
        "prompt": {
            "type": "string",
            "description": "What to generate or how to edit the image",
        },
        "camera_source": {
            "type": "string",
            "enum": ["operator", "hardware", "screen"],
            "description": "Optional: capture a photo first as input for editing",
        },
        "send_to_phone": {
            "type": "boolean",
            "description": "Also send the result via SMS to the operator's phone",
        },
    },
    required=["prompt"],
)
```

---

## Handler Implementation

```python
async def handle_generate_image(params: FunctionCallParams):
    prompt = params.arguments["prompt"]
    camera = params.arguments.get("camera_source")
    send_sms = params.arguments.get("send_to_phone", False)

    # 1. Optional camera capture
    input_image_b64 = None
    if camera and _webcam_capturer:
        input_image_b64 = _webcam_capturer.capture(camera)

    # 2. Call Gemini image generation
    client = OpenAI(
        base_url=os.environ.get("LITELLM_BASE_URL", "http://127.0.0.1:4000"),
        api_key=os.environ.get("LITELLM_API_KEY", "not-set"),
    )

    messages = [{"role": "user", "content": []}]
    if input_image_b64:
        messages[0]["content"].append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{input_image_b64}"},
        })
    messages[0]["content"].append({"type": "text", "text": prompt})

    response = client.chat.completions.create(
        model="gemini-2.0-flash",  # or gemini-2.0-flash-preview-image-generation
        messages=messages,
        # Gemini-specific: request image output
        extra_body={"generation_config": {"response_modalities": ["TEXT", "IMAGE"]}},
    )

    # 3. Extract generated image from response
    # Gemini returns base64 image in response content
    result_image_b64 = _extract_image_from_response(response)

    if result_image_b64 is None:
        await params.result_callback({"error": "No image generated"})
        return

    # 4. Save to disk
    output_dir = Path.home() / "Pictures" / "hapax-generated"
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_path = output_dir / f"{timestamp}.png"
    output_path.write_bytes(base64.b64decode(result_image_b64))

    # 5. Display on screen
    subprocess.Popen(["xdg-open", str(output_path)])

    # 6. Optional SMS delivery
    if send_sms and _voice_config and _voice_config.sms_contacts:
        # Send to operator's own phone number (if configured)
        # This would need a "self" contact or phone number config
        pass

    await params.result_callback({
        "status": "generated",
        "path": str(output_path),
        "description": f"Image saved to {output_path.name} and opened on screen",
    })
```

---

## Output Delivery

The generated image needs to reach the operator's eyes. Voice can only confirm it happened.

### Primary: xdg-open (screen)

```bash
xdg-open ~/Pictures/hapax-generated/20260309-143022.png
```

COSMIC's default image viewer opens immediately. The operator sees it on screen within 1-2s of generation completing. This is the simplest and most immediate path.

### Secondary: SMS to self

If the operator says "send it to my phone too", the handler can send the image via the Android SMS Gateway. This requires:
- MMS support in the SMS Gateway app (check if it handles image attachments)
- Or: upload to a temporary URL and send the link

This is out of scope for v1 — `xdg-open` is sufficient.

### File Organization

```
~/Pictures/hapax-generated/
  20260309-143022.png
  20260309-143055.png
  ...
```

No cleanup needed — these are the operator's creative output, not temp files.

---

## Gemini Image Generation API

### Model Selection

Gemini 2.0 Flash supports image generation natively with `response_modalities: ["IMAGE"]`. This is the simplest path — same model already used for `analyze_scene`, just requesting image output instead of text.

### LiteLLM Routing

The model alias in LiteLLM needs to support image generation parameters. Current `gemini-2.0-flash` alias may need `response_modalities` passthrough. Verify with:

```bash
curl http://127.0.0.1:4000/chat/completions \
  -H "Authorization: Bearer $(pass show litellm/master-key)" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini-2.0-flash",
    "messages": [{"role": "user", "content": "Generate a simple test image of a red circle"}],
    "generation_config": {"response_modalities": ["TEXT", "IMAGE"]}
  }'
```

If LiteLLM doesn't pass through `generation_config`, the handler may need to call the Gemini API directly via `google.generativeai` SDK instead of through LiteLLM. This is the most likely blocker.

### Response Format

Gemini returns images inline in the response as base64-encoded data:

```json
{
  "candidates": [{
    "content": {
      "parts": [
        {"text": "Here's the image you requested:"},
        {"inline_data": {"mime_type": "image/png", "data": "base64..."}}
      ]
    }
  }]
}
```

The handler needs to extract the `inline_data` part from the response.

---

## Dependencies

| Dependency | Source | Already in project? |
|------------|--------|---------------------|
| `openai` (client) | Gemini via LiteLLM | Yes |
| `subprocess` (xdg-open) | Display output | Yes (stdlib) |
| `base64` | Image encoding | Yes (stdlib) |
| WebcamCapturer | Camera capture | Yes |

No new dependencies. If LiteLLM passthrough doesn't work, `google-generativeai` SDK would be needed (already in project for Gemini Live).

---

## Tool Registration

Add to the existing `tools.py`:
- Schema: `_generate_image` FunctionSchema
- Handler: `handle_generate_image` async function
- Register in `register_tool_handlers()`
- Add to `_ALL_TOOLS` list in `get_tool_schemas()`

This follows the exact same pattern as the existing 8 tools.

---

## System Prompt Awareness

The system prompt already covers vision ("You can see through cameras and the screen when asked"). Add:

```
"You can generate and edit images — take photos and transform them, "
"create artwork, make memes. Results appear on screen. "
```

---

## Testing Strategy

### Unit Tests (mocked Gemini)
- Schema has required `prompt` field
- Handler calls webcam_capturer when camera_source specified
- Handler calls Gemini API with correct message format
- Handler saves output to ~/Pictures/hapax-generated/
- Handler calls xdg-open with saved path
- Missing image in response returns error
- No camera available gracefully skips capture

### Integration Tests (real Gemini, if key available)
- Text-to-image: "a red circle on white background" → PNG saved
- Image edit: capture + "make it look vintage" → PNG saved

### Manual Validation
- Say "hapax, take a pic of me and make it a cartoon" — image appears on screen
- Say "hapax, generate album art for a dusty boom bap beat" — image appears
- Verify ~/Pictures/hapax-generated/ directory structure

---

## Open Questions

1. **LiteLLM passthrough:** Does LiteLLM forward `generation_config.response_modalities` to Gemini? If not, direct Gemini SDK call needed.
2. **MMS via SMS Gateway:** Does Android SMS Gateway support image attachments? If yes, "send it to my phone" becomes trivial.
3. **COSMIC image viewer:** Does `xdg-open` on a PNG launch a viewer in COSMIC, or does it need a specific app association?
4. **Rate limits:** Gemini image generation may have tighter rate limits than text. Worth checking before heavy use.

---

## Out of Scope

- **ComfyUI integration** — higher quality but wrong latency profile for voice
- **Image-to-image with specific style models** — needs ComfyUI workflows
- **Gallery/history browsing** — files are saved, user can browse manually
- **Multi-turn image editing** — "now make the background blue" requires conversation state for images, complex
- **Video generation** — different domain entirely
