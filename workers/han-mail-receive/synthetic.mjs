// One explicit synthetic Worker-handler invocation against the deployed KV binding.
// No SMTP, forwarding, fetch endpoint, or operator mailbox. No real message reads.
import { execFileSync } from "node:child_process";
import { appendFileSync, existsSync, readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import worker, { sha256 } from "./worker.mjs";

const row = `${process.env.HOME}/Documents/Personal/20-projects/hapax-cc-tasks/active/han-mail-receive-capability-20260919.md`;
const receiptPath = "/store-fast/tmp/han-mail/synthetic-receipt.json";
async function main() {
  if (existsSync(receiptPath)) throw new Error("Synthetic invocation already recorded; do not send another");
  const secret = (name) => execFileSync("hapax-secret", [name], { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }).trim();
  const token = secret("cloudflare-api-api_token");
  const account = secret("cloudflare-api-account_id");
  const config = JSON.parse(execFileSync("uv", ["run", "--no-sync", "python", "-c",
    "import json,sys,tomllib; from pathlib import Path; print(json.dumps(tomllib.loads(Path(sys.argv[1]).read_text())))",
    fileURLToPath(new URL("deployment.toml", import.meta.url)),
  ], { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }));
  const source = readFileSync(fileURLToPath(new URL("worker.mjs", import.meta.url)));
  if (await sha256(source) !== config.source_sha256) throw new Error("Source differs from deployed receipt");
  const base = `https://api.cloudflare.com/client/v4/accounts/${account}`;
  const kvBase = `${base}/storage/kv/namespaces/${config.namespace_id}`;
  const headers = { Authorization: `Bearer ${token}` };
  const receipts = [];
  async function request(method, url, body) {
    const response = await fetch(url, { method, headers, body, redirect: "error", signal: AbortSignal.timeout(30000) });
    if (!response.ok && !(method === "GET" && response.status === 404)) {
      throw new Error(`Cloudflare refused synthetic operation: HTTP ${response.status}; STOP`);
    }
    if (method === "PUT") {
      const data = await response.json();
      if (!data.success) throw new Error("Cloudflare refused synthetic write; STOP");
      const receipt = { time: new Date().toISOString(), action: "synthetic handler KV write", response_id: response.headers.get("cf-ray"), key: decodeURIComponent(new URL(url).pathname.split("/").at(-1)) };
      receipts.push(receipt);
      appendFileSync(row, `\n- Cloudflare change: ${JSON.stringify(receipt)}\n`);
    }
    return response;
  }
  const subscriptions = await (await request("GET", `${base}/subscriptions`)).json();
  if (!subscriptions.success || subscriptions.result.some((s) => JSON.stringify(s.rate_plan).toLowerCase().includes("worker"))) {
    throw new Error("STOP: Workers free plan must be re-established");
  }
  const raw = new TextEncoder().encode(
    "From: synthetic-han@example.invalid\r\nTo: hrl-han@hapaxresearch.com\r\nSubject: HAN receive self-authored synthetic check\r\nMessage-ID: <han-mail-receive-20260919@example.invalid>\r\n\r\nSELF_AUTHORED_HAN_BODY_NOT_FOR_NOTIFICATION\r\n",
  );
  const key = await sha256(raw);
  const kv = {
    async get(name) {
      if (!name.startsWith("rate:")) throw new Error("Synthetic adapter refuses message reads");
      const response = await request("GET", `${kvBase}/values/${encodeURIComponent(name)}`);
      return response.status === 404 ? null : response.text();
    },
    async put(name, value, options) {
      if (name !== key && !name.startsWith("rate:")) throw new Error("Unexpected synthetic key");
      const data = new FormData();
      data.set("value", new Blob([value]));
      if (options.metadata) data.set("metadata", JSON.stringify(options.metadata));
      const query = options.expirationTtl ? `?expiration_ttl=${options.expirationTtl}` : "";
      await request("PUT", `${kvBase}/values/${encodeURIComponent(name)}${query}`, data);
    },
  };
  let rejection = null;
  await worker.email({
    from: "synthetic-han@example.invalid", to: "hrl-han@hapaxresearch.com",
    raw: new Blob([raw]).stream(), rawSize: raw.length, headers: new Headers(),
    setReject(reason) { rejection = reason; },
    forward() { throw new Error("Forbidden forwarding"); },
    reply() { throw new Error("Forbidden reply"); },
  }, { INBOUND: kv }, {});
  writeFileSync(receiptPath, JSON.stringify({ key, size: raw.length, rejection, receipts }, null, 2) + "\n", { mode: 0o600 });
  if (rejection) throw new Error("Synthetic handler rejected intake; see safe receipt");
  console.log(JSON.stringify({ synthetic_key: key, size: raw.length, writes: receipts.length, status: "stored" }));
}
main().catch(() => { console.error("Synthetic invocation stopped; inspect safe receipts. No automatic retry or upgrade."); process.exitCode = 1; });
