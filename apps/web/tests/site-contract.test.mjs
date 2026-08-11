import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { isArxivUrl } from "../data/source-classification.ts";

const root = new URL("../", import.meta.url);
const requiredRoutes = ["radar", "events", "stories", "actions", "capabilities", "for-you", "search", "watch", "corrections", "contribute", "settings", "admin"];

test("core working-surface routes exist", async () => {
  await Promise.all(requiredRoutes.map(async (route) => {
    const source = await readFile(new URL(`app/${route}/page.tsx`, root), "utf8");
    assert.match(source, /export default/);
  }));
});

test("radar adapter preserves evidence and action fields", async () => {
  const source = await readFile(new URL("data/radar.ts", root), "utf8");
  for (const field of ["confidence", "evidence", "actionSlug", "unknowns", "waveform"]) assert.match(source, new RegExp(field));
});

test("public fact routes load server data without baking fixture params", async () => {
  const routes = ["radar", "events", "actions", "stories", "for-you", "search", "capabilities", "corrections", "admin", "methodology/coverage"];
  for (const route of routes) {
    const source = await readFile(new URL(`app/${route}/page.tsx`, root), "utf8");
    assert.match(source, /getRadarDataset/);
    assert.doesNotMatch(source, /from ["'][^"']*data\/radar["']/);
  }

  for (const route of ["event/[slug]", "action/[slug]", "story/[slug]", "briefings/[date]"]) {
    const source = await readFile(new URL(`app/${route}/page.tsx`, root), "utf8");
    assert.match(source, /force-dynamic/);
    assert.doesNotMatch(source, /generateStaticParams/);
  }
});

test("briefing pages render embedded immutable events instead of joining live facts", async () => {
  const source = await readFile(new URL("data/server.ts", root), "utf8");
  const start = source.indexOf("export async function getBriefingDataset");
  const end = source.indexOf("export async function getEventBySlug", start);
  const briefingAdapter = source.slice(start, end);
  const apiBranch = briefingAdapter.slice(briefingAdapter.indexOf("  try {"));
  assert.match(briefingAdapter, /snapshot\.event_snapshots\.map/);
  assert.doesNotMatch(apiBranch, /getRadarDataset/);
  assert.doesNotMatch(apiBranch, /dataset\.events/);
});

test("container and liveness contracts are present", async () => {
  const [dockerfile, nextConfig, healthRoute] = await Promise.all([
    readFile(new URL("Dockerfile", root), "utf8"),
    readFile(new URL("next.config.ts", root), "utf8"),
    readFile(new URL("app/healthz/route.ts", root), "utf8")
  ]);
  assert.match(dockerfile, /AS development/);
  assert.match(dockerfile, /AS production/);
  assert.match(dockerfile, /RADAR_DATA_MODE=api/);
  assert.match(nextConfig, /output:\s*["']standalone["']/);
  assert.match(healthRoute, /status:\s*["']ok["']/);
});

test("arXiv classification uses the parsed hostname boundary", () => {
  for (const url of [
    "https://arxiv.org/abs/2608.00001",
    "https://export.arxiv.org/api/query?search_query=all:radar",
    "https://ARXIV.ORG./pdf/2608.00001"
  ]) {
    assert.equal(isArxivUrl(url), true, url);
  }

  for (const url of [
    "https://evil.example/?next=https://arxiv.org/abs/1",
    "https://arxiv.org.evil.example/paper",
    "https://evil-arxiv.org/paper",
    "https://arxiv.org@evil.example/paper",
    "not a url"
  ]) {
    assert.equal(isArxivUrl(url), false, url);
  }
});
