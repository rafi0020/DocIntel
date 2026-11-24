// Adds the demo runtime to a static export. Run from frontend/ after `next build`:
//   node demo/inject.mjs
// It copies demo/runtime.js and demo/fixtures.json into out/demo/ and puts a script tag first in every page's <head>,
// so the runtime is in place before the app's own scripts and can answer their /api requests.
import fs from "node:fs";
import path from "node:path";

const here = path.dirname(new URL(import.meta.url).pathname);
const cfg = JSON.parse(fs.readFileSync(path.join(here, "demo.json"), "utf8"));
const out = path.resolve("out");
if (!fs.existsSync(out)) throw new Error("out/ not found: run `next build` first");

fs.mkdirSync(path.join(out, "demo"), { recursive: true });
fs.copyFileSync(path.join(here, "runtime.js"), path.join(out, "demo", "runtime.js"));
fs.copyFileSync(path.join(here, "fixtures.json"), path.join(out, "demo", "fixtures.json"));

const tag =
  `<script>window.__DEMO__=${JSON.stringify({ base: cfg.base, title: cfg.title, repo: cfg.repo, extra: cfg.extra, noMic: cfg.noMic })};</script>` +
  `<script src="${cfg.base}/demo/runtime.js"></script>`;

let pages = 0;
(function walk(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) { if (entry.name !== "demo" && entry.name !== "_next") walk(full); continue; }
    if (!entry.name.endsWith(".html")) continue;
    const html = fs.readFileSync(full, "utf8");
    if (html.includes("/demo/runtime.js")) continue;
    const next = html.replace(/<head[^>]*>/i, (m) => m + tag);
    if (next === html) continue;
    fs.writeFileSync(full, next);
    pages += 1;
  }
})(out);
console.log(`demo runtime added to ${pages} pages`);
