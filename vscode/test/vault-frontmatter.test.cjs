const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");
const esbuild = require("esbuild");

function loadFrontmatterModule() {
  const outdir = fs.mkdtempSync(path.join(os.tmpdir(), "hapax-vault-test-"));
  const outfile = path.join(outdir, "frontmatter.cjs");
  esbuild.buildSync({
    entryPoints: [path.join(__dirname, "..", "src", "frontmatter.ts")],
    bundle: true,
    platform: "node",
    format: "cjs",
    outfile,
    logLevel: "silent",
  });
  return require(outfile);
}

test("parseFrontmatter reads YAML and preserves markdown body", () => {
  const { parseFrontmatter } = loadFrontmatterModule();
  const parsed = parseFrontmatter("---\ntitle: Note\ntags:\n  - a\n---\n# Body\n");

  assert.deepEqual(parsed.data, { title: "Note", tags: ["a"] });
  assert.equal(parsed.content, "# Body\n");
});

test("parseFrontmatter handles CRLF, empty maps, and non-object YAML", () => {
  const { parseFrontmatter } = loadFrontmatterModule();

  assert.deepEqual(parseFrontmatter("---\r\ntitle: Note\r\n---\r\nBody\r\n"), {
    data: { title: "Note" },
    content: "Body\r\n",
  });
  assert.deepEqual(parseFrontmatter("---\n---\nBody\n"), {
    data: {},
    content: "Body\n",
  });
  assert.deepEqual(parseFrontmatter("---\n- item\n---\nBody\n"), {
    data: {},
    content: "Body\n",
  });
});

test("serializeFrontmatter writes parseable YAML frontmatter", () => {
  const { parseFrontmatter, serializeFrontmatter } = loadFrontmatterModule();
  const raw = serializeFrontmatter({ title: "Note", count: 2 }, "Body\n");

  assert.equal(raw.startsWith("---\n"), true);
  assert.deepEqual(parseFrontmatter(raw), {
    data: { title: "Note", count: 2 },
    content: "Body\n",
  });
});

test("serializeFrontmatter fails loudly for unsupported YAML values", () => {
  const { serializeFrontmatter } = loadFrontmatterModule();

  assert.throws(
    () => serializeFrontmatter({ unsupported: Symbol("x") }, "Body\n"),
    /Tag not resolved for Symbol value/,
  );
});
