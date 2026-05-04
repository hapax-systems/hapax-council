# youtube_chat_reader — integration contract

Owner: epsilon (cc-task `youtube-chat-ingestion-impingement`).

This `__init__.py` is a Protocol-only stub. The poster lane (cc-task
`chat-response-verbal-and-text`) imports `get_active_reader()` and
uses the returned reader's `live_chat_id()` as the POST target for
`liveChatMessages.insert`.

When epsilon lands the real reader:

1. Their concrete class must satisfy `YoutubeChatReader` Protocol —
   `live_chat_id()` returning the active broadcast's `liveChatId`,
   `recent_messages(limit=50)` returning the last N
   `ChatMessageSnapshot`s.
2. Their startup hook calls `register_reader(self)` once the YouTube
   Live Streaming API has resolved the active broadcast.
3. No changes required on the poster side — `get_active_reader()`
   begins returning the concrete reader and the poster's `_emit()`
   reads `live_chat_id()` from it.

If the reader is not yet registered (or a broadcast is not active),
`get_active_reader()` returns `None`. The poster's
`response_dispatch.dispatch_response()` treats this as "chat path
inactive" — the verbal modality still emits via the existing Evil
Pet broadcast TTS path.

Shared credentials: both lanes consume `shared.google_auth.get_google_credentials([scopes])`.
Reader typically requests `youtube.readonly`; poster requests
`youtube.force-ssl`. Operator can mint a single token covering both
scopes; `google-auth` handles refresh transparently.
