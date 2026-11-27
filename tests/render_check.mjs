// Render check: run the built page's script against a stub DOM and assert it
// actually produces the cards and the hero jump. node tests/render_check.mjs
import { readFileSync } from "node:fs";

const html = readFileSync(new URL("../dist/index.html", import.meta.url), "utf8");
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const data = readFileSync(new URL("../data.json", import.meta.url), "utf8");

const els = {};
const store = {};
globalThis.localStorage = { getItem: k => store[k] ?? null, setItem: (k, v) => (store[k] = v) };
globalThis.fetch = async url => ({ json: async () => String(url).includes("data.json") ? JSON.parse(data) : {} });
const el = id => (els[id] ??= { innerHTML: "", textContent: "", value: "", open: false,
                                oninput: null, onchange: null, onclick: null, checked: false,
                                dataset: {}, children: [], addEventListener: () => {},
                                querySelectorAll: () => [], querySelector: () => null,
                                showModal() { this.open = true; }, close() { this.open = false; } });
globalThis.document = { getElementById: el };

new Function(script)();          // runs the IIFE that boots off the inlined data
await new Promise(r => setTimeout(r, 80));

const grid = els.grid.innerHTML;
const cards = (grid.match(/class="card"/g) || []).length;
const listed = JSON.parse(data);

if (!cards) throw new Error("no cards rendered");
// the grid opens on sold-price pairs only
if (cards !== listed.stats.matched) throw new Error(`rendered ${cards} cards, ${listed.stats.matched} have a sold price`);
if (!/9 Rouwkoop Road/.test(grid)) throw new Error("hero property missing");
if (!/\+173%/.test(grid)) throw new Error("jump badge missing");
if (!els["s-listings"].textContent) throw new Error("hero stats empty");
if (!els.soldTable.innerHTML.includes("Sold for")) throw new Error("sold table empty");
if (!/data-kind="jas"/.test(grid)) throw new Error("reaction buttons missing");
if (!/class="track"/.test(grid)) throw new Error("photo carousel missing");

console.log(`ok: ${cards} cards, carousel + stats + sold table rendered`);
