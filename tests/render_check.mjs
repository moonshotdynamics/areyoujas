// Render check: run the built page's script against a stub DOM and assert it
// actually produces the cards and the hero jump. node tests/render_check.mjs
import { readFileSync } from "node:fs";

const html = readFileSync(new URL("../dist/index.html", import.meta.url), "utf8");
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

const els = {};
const store = {};
globalThis.localStorage = { getItem: k => store[k] ?? null, setItem: (k, v) => (store[k] = v) };
globalThis.fetch = async () => ({ json: async () => ({}) });
const el = id => (els[id] ??= { innerHTML: "", textContent: "", value: "", oninput: null, onchange: null,
                               checked: false, dataset: {}, addEventListener: () => {} });
globalThis.document = { getElementById: el };

new Function(script)();          // runs the IIFE that boots off the inlined data
await new Promise(r => setTimeout(r, 50));

const grid = els.grid.innerHTML;
const cards = (grid.match(/class="card"/g) || []).length;
const listed = JSON.parse(readFileSync(new URL("../data.json", import.meta.url), "utf8"));

if (!cards) throw new Error("no cards rendered");
if (listed && cards !== listed.listings.length) throw new Error(`rendered ${cards} cards, data has ${listed.listings.length}`);
if (!/9 Rouwkoop Road/.test(grid)) throw new Error("hero property missing");
if (!/\+173%/.test(grid)) throw new Error("jump badge missing");
if (!els.stats.innerHTML.includes("listings tracked")) throw new Error("stats strip empty");
if (!els.soldTable.innerHTML.includes("R/m")) throw new Error("sold table empty");
if (!/data-kind="jas"/.test(grid)) throw new Error("reaction buttons missing");

console.log(`ok: ${cards} cards, stats + sold table rendered`);
