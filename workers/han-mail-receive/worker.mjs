// han-mail-receive-capability-20260919: foreign bytes only; no HTTP handler.
export const MAX_BYTES = 256 * 1024;
export const DAILY_LIMIT = 200;
export const SENDER_DAILY_LIMIT = 3;
const encoder = new TextEncoder();

export async function sha256(bytes) {
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

async function readBounded(stream) {
  const reader = stream.getReader();
  const chunks = [];
  let size = 0;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > MAX_BYTES) {
        await reader.cancel();
        throw new Error("size");
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return bytes;
}

function authMetadata(headers) {
  // The public EmailMessage API supplies headers, not authenticated verdict fields.
  // Preserve observations, but never promote sender-controlled headers to trust.
  const header = (headers.get("authentication-results") || "").slice(0, 2048);
  const auth = { source: header ? "unverified_header" : "unavailable" };
  for (const method of ["spf", "dkim", "dmarc"]) {
    const match = header.match(new RegExp(`(?:^|[;\\s])${method}=(pass|fail|softfail|neutral|none|temperror|permerror)(?=[;\\s]|$)`, "i"));
    auth[method] = match ? match[1].toLowerCase() : "unknown";
  }
  return auth;
}

async function count(kv, key) {
  const value = await kv.get(key);
  if (value === null) return 0;
  const n = Number(value);
  if (!Number.isSafeInteger(n) || n < 0) throw new Error("invalid rate state");
  return n;
}

export async function receive(message, env, now = new Date()) {
  try {
    if (message.to.toLowerCase() !== "hrl-han@hapaxresearch.com") {
      message.setReject("Recipient not supported");
      return;
    }
    if (!Number.isSafeInteger(message.rawSize) || message.rawSize < 0 || message.rawSize > MAX_BYTES) {
      message.setReject("Message exceeds 256 KiB limit");
      return;
    }
    if (encoder.encode(message.from).length > 254 || encoder.encode(message.to).length > 254) {
      message.setReject("Envelope exceeds supported length");
      return;
    }
    const kv = env.INBOUND;
    const day = now.toISOString().slice(0, 10);
    const globalKey = `rate:day:${day}`;
    const senderKey = `rate:sender:${day}:${await sha256(encoder.encode(message.from.toLowerCase()))}`;
    const globalCount = await count(kv, globalKey);
    if (globalCount >= DAILY_LIMIT) {
      message.setReject("Daily intake capacity reached");
      return;
    }
    const senderCount = await count(kv, senderKey);
    if (senderCount >= SENDER_DAILY_LIMIT) {
      message.setReject("Sender daily intake capacity reached");
      return;
    }
    const bytes = await readBounded(message.raw);
    if (bytes.byteLength !== message.rawSize) throw new Error("size mismatch");
    const key = await sha256(bytes);
    // KV is eventually consistent: these are conservative admission counters,
    // not atomic locks. Workers FREE hard quotas are the final spend boundary.
    // Debit before storage; partial failures spend capacity, never admit extra work.
    await kv.put(globalKey, String(globalCount + 1), { expirationTtl: 172800 });
    await kv.put(senderKey, String(senderCount + 1), { expirationTtl: 172800 });
    const metadata = {
      schema: 1,
      sender: message.from,
      recipient: message.to,
      received_at: now.toISOString(),
      size: bytes.byteLength,
      auth: authMetadata(message.headers),
    };
    if (encoder.encode(JSON.stringify(metadata)).length > 1024) throw new Error("metadata size");
    // No expiry: the sole remote copy survives until a verified durable pull.
    await kv.put(key, bytes, { metadata });
  } catch {
    // Never log message bytes, headers, envelope values, or provider errors.
    message.setReject("Intake unavailable or message exceeds supported limits");
  }
}

export default {
  async email(message, env) {
    await receive(message, env);
  },
};
