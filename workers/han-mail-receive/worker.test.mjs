import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test from "node:test";
import worker, { DAILY_LIMIT, MAX_BYTES, receive, sha256 } from "./worker.mjs";

const now = new Date("2026-09-19T09:00:00Z");
const raw = new TextEncoder().encode("From: fixture@example.invalid\r\nSubject: Self-authored fixture\r\n\r\nFOREIGN_FIXTURE_BODY\r\n");
function fixture(bytes = raw, from = "fixture@example.invalid") {
  return {
    from, to: "hrl-han@hapaxresearch.com", rawSize: bytes.length,
    raw: new Blob([bytes]).stream(), headers: new Headers(),
    rejection: null,
    setReject(reason) { this.rejection = reason; },
    forward() { assert.fail("must never forward"); },
    reply() { assert.fail("must never reply"); },
  };
}
function namespace() {
  const values = new Map();
  const writes = [];
  return {
    values, writes,
    async get(key) { return values.get(key)?.value ?? null; },
    async put(key, value, options) {
      writes.push({ key, value, options });
      values.set(key, { value, options });
    },
  };
}

test("raw SHA-256 key and metadata, two TTL debits, no raw-message expiry", async () => {
  const kv = namespace();
  const message = fixture();
  message.headers.set("authentication-results", "mx.cloudflare.net; spf=pass; dkim=fail; dmarc=none");
  await receive(message, { INBOUND: kv }, now);
  assert.equal(message.rejection, null);
  assert.equal(kv.writes.length, 3);
  const key = createHash("sha256").update(raw).digest("hex");
  assert.equal(await sha256(raw), key);
  assert.deepEqual(kv.values.get(key).value, raw);
  assert.equal(kv.values.get(key).options.metadata.size, raw.length);
  assert.equal(kv.values.get(key).options.metadata.auth.spf, "pass");
  assert.equal(kv.values.get(key).options.metadata.auth.source, "unverified_header");
  assert.equal(kv.values.get(key).options.expirationTtl, undefined);
  assert.ok(kv.writes.slice(0, 2).every((w) => w.options.expirationTtl === 172800));
});

test("size cap rejects before KV, including lying rawSize", async () => {
  for (const declared of [MAX_BYTES + 1, 1]) {
    const kv = namespace();
    const m = fixture(new Uint8Array(MAX_BYTES + 1));
    m.rawSize = declared;
    await receive(m, { INBOUND: kv }, now);
    assert.ok(m.rejection);
    assert.equal(kv.writes.length, 0);
  }
});

test("exact size boundary accepted; mismatch rejected", async () => {
  const kv = namespace();
  const m = fixture(new Uint8Array(MAX_BYTES));
  await receive(m, { INBOUND: kv }, now);
  assert.equal(m.rejection, null);
  const mismatch = fixture();
  mismatch.rawSize += 1;
  await receive(mismatch, { INBOUND: namespace() }, now);
  assert.ok(mismatch.rejection);
});

test("sender cap is three per UTC day, case-normalized, reset next day", async () => {
  const kv = namespace();
  for (let i = 0; i < 4; i++) {
    const m = fixture(raw, i % 2 ? "FIXTURE@example.invalid" : "fixture@example.invalid");
    await receive(m, { INBOUND: kv }, now);
    assert.equal(Boolean(m.rejection), i === 3);
  }
  assert.equal(kv.writes.length, 9);
  const m = fixture();
  await receive(m, { INBOUND: kv }, new Date("2026-09-20T00:00:00Z"));
  assert.equal(m.rejection, null);
});

test("global cap across senders limits ordinary traffic to 600 writes/day", async () => {
  const kv = namespace();
  for (let i = 0; i <= DAILY_LIMIT; i++) {
    const m = fixture(raw, `fixture-${i}@example.invalid`);
    await receive(m, { INBOUND: kv }, now);
    assert.equal(Boolean(m.rejection), i === DAILY_LIMIT);
  }
  assert.equal(kv.writes.length, 600);
});

test("wrong recipient, malformed counter, and provider failure fail closed", async () => {
  const kv = namespace();
  const wrong = fixture();
  wrong.to = "someone@example.invalid";
  await receive(wrong, { INBOUND: kv }, now);
  assert.ok(wrong.rejection);
  assert.equal(kv.writes.length, 0);
  kv.values.set("rate:day:2026-09-19", { value: "corrupt" });
  const corrupt = fixture();
  await receive(corrupt, { INBOUND: kv }, now);
  assert.ok(corrupt.rejection);
  const failed = fixture();
  await receive(failed, { INBOUND: { async get() { throw new Error("quota"); } } }, now);
  assert.ok(failed.rejection);
});

test("Cloudflare entrypoint accepts the runtime execution context", async () => {
  const m = fixture();
  await worker.email(m, { INBOUND: namespace() }, { waitUntil() { assert.fail("must await storage"); } });
  assert.equal(m.rejection, null);
  assert.equal(worker.fetch, undefined);
});
