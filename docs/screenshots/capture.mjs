// Regenerate the README screenshots from a running GraphAgent Lab instance.
//
//   npm i puppeteer-core          (anywhere; not a project dependency)
//   node docs/screenshots/capture.mjs [baseUrl]
//
// Captures workspace.png, execution.png, execution-graph.png, graph.png and
// benchmark.png at 1440×900 @2x into this directory. Assumes the flowgate
// benchmark run (make seed-flowgate + a completed run) exists; set FLOWGATE_RUN
// to a different run id if needed. Uses the backend's static frontend mount so
// no vite dev server is required.
import puppeteer from "puppeteer-core";
import { mkdirSync } from "node:fs";

const CHROME = process.env.CHROME_PATH
  ?? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const BASE = process.argv[2] ?? "http://127.0.0.1:8010";
const OUT = new URL(".", import.meta.url).pathname;
const RUN = process.env.FLOWGATE_RUN ?? "run_7ebda5a524";

mkdirSync(OUT, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: true,
  args: ["--no-sandbox", "--hide-scrollbars"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 2 });

const nav = (label) => page.evaluate((text) => {
  [...document.querySelectorAll("button,nav a,aside a")]
    .find((b) => b.textContent.trim() === text)?.click();
}, label);
const pickSelect = (predSrc, value) => page.evaluate((src, val) => {
  const pred = eval(src);
  const sel = [...document.querySelectorAll("select")]
    .find((s) => [...s.options].some((o) => pred(o)));
  if (!sel) return false;
  const opt = [...sel.options].find((o) => pred(o));
  Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, "value")
    .set.call(sel, val ?? opt.value);
  sel.dispatchEvent(new Event("change", { bubbles: true }));
  return true;
}, predSrc.toString(), value);
const shot = async (name) => {
  await sleep(800);
  await page.screenshot({ path: `${OUT}${name}.png` });
  console.log(`saved ${name}.png`);
};

// 1 · Workspace with flowgate selected
await page.goto(`${BASE}/`, { waitUntil: "networkidle2", timeout: 30000 });
await page.evaluate(() => {
  [...document.querySelectorAll("button.repo-item")]
    .find((x) => x.textContent.includes("flowgate_repo"))?.click();
});
await page.waitForFunction(() => document.body.innerText.includes("FILE VIEWER"),
  { timeout: 15000 });
await shot("workspace");

// 2 · Execution: A failed / B, C succeeded (three cards side by side)
await nav("Live Execution");
await page.waitForFunction(
  () => [...document.querySelectorAll("select")]
    .some((s) => [...s.options].some((o) => o.value.startsWith("run_"))),
  { timeout: 15000 });
await pickSelect((o) => o.value === "run_7ebda5a524", RUN);
await page.waitForFunction(() => document.body.innerText.includes("GRAPH QUERIES"),
  { timeout: 20000 });
await shot("execution");

// 3 · Execution: B's graph navigation events
await page.evaluate(() => {
  const el = [...document.querySelectorAll("*")]
    .filter((n) => n.children.length === 0 &&
      /neighbors of app\/dispatcher\.py/.test(n.textContent))[0];
  el?.scrollIntoView({ block: "center" });
});
await shot("execution-graph");

// 4 · Graph Explorer zoomed on the run overlay + trail
await nav("Graph Explorer");
await page.waitForFunction(
  () => [...document.querySelectorAll("select")]
    .some((s) => [...s.options].some((o) => o.textContent.includes("flowgate"))),
  { timeout: 15000 });
await pickSelect((o) => o.textContent.includes("flowgate"));
await page.waitForFunction(
  () => document.querySelectorAll(".react-flow__node").length > 40,
  { timeout: 20000 });
await sleep(800);
for (let i = 0; i < 4; i++) {
  await page.click(".react-flow__controls-zoomin").catch(() => {});
  await sleep(250);
}
await pickSelect((o) => o.value === "run_7ebda5a524", RUN).catch(() => {});
await page.evaluate(() => {
  [...document.querySelectorAll("button")]
    .find((b) => b.textContent.trim() === "Show trail")?.click();
});
await shot("graph");

// 5 · Benchmark dashboard
await nav("Benchmark");
// NOTE: the heading is uppercased by CSS — match what innerText returns.
await page.waitForFunction(
  () => document.body.innerText.includes("SYSTEM COMPARISON") &&
        document.querySelectorAll("svg").length >= 5,
  { timeout: 20000 });
await shot("benchmark");

await browser.close();
console.log("done");
