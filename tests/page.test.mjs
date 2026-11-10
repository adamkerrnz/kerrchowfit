// Checks on logic that lives inside index.html. Run with: node --test tests/page.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");

function extract(startMarker, endMarker) {
  const a = html.indexOf(startMarker);
  assert.ok(a >= 0, `not found in index.html: ${startMarker}`);
  const b = html.indexOf(endMarker, a);
  return html.slice(a, b);
}

test("the weekly exercise shuffle is a stable permutation", () => {
  const seededOrder = new Function(`${extract("function seededOrder(", "  const lastRevealed")}; return seededOrder;`)();
  const a = seededOrder(6, "2026-11-09|w1|a");
  assert.deepEqual(a, seededOrder(6, "2026-11-09|w1|a"), "same seed gives the same order on every device");
  assert.deepEqual([...a].sort(), [0, 1, 2, 3, 4, 5], "every exercise appears exactly once");
  const orders = new Set();
  for (let w = 1; w <= 12; w++) for (const s of ["a", "b"]) orders.add(seededOrder(6, `2026-11-09|w${w}|${s}`).join(""));
  assert.ok(orders.size >= 12, "weeks and sessions get different orders");
});

test("every script in the page parses", () => {
  const scripts = [...html.matchAll(/<script>\n([\s\S]*?)<\/script>/g)].map((m) => m[1]);
  assert.ok(scripts.length >= 6);
  for (const src of scripts) new Function(src);
});

test("the page still contains the wording the self-hosted server swaps", () => {
  const main = readFileSync(new URL("../docker/app/main.py", import.meta.url), "utf8");
  const block = main.slice(main.indexOf("COPY = ["), main.indexOf("\n]\n", main.indexOf("COPY = [")));
  const olds = [...block.matchAll(/^\s*\(\s*"((?:[^"\\]|\\.)*)"\s*,/gm)].map((m) => m[1]);
  assert.ok(olds.length >= 4);
  for (const text of olds) assert.ok(html.includes(text), `page no longer contains: ${text}`);
});

test("each strength exercise has a how-to and a demo figure", () => {
  const names = [...extract("const SESSIONS = {", "const WEEKS = 12;").matchAll(/\{ name: "([^"]+)"/g)].map((m) => m[1]);
  assert.equal(names.length, 12);
  const howto = extract("const HOWTO = {", "const WEEKS = 12;");
  for (const n of names) assert.ok(howto.includes(`"${n}": { fig:`), `no how-to for ${n}`);
});
