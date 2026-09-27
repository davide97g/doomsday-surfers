// Downloads the CC0 texture sets listed in assets/texture-manifest.json into
// assets/textures/<id>/ (gitignored: source files for the Blender scripts,
// never shipped as-is). Sets already on disk are skipped.
//
//   bun scripts/fetch-textures.ts            every set in the manifest
//   bun scripts/fetch-textures.ts Rock051    just these ids
//   bun scripts/fetch-textures.ts --force    re-download
//
// Sources (no API keys):
//   ambientCG   https://ambientcg.com/api/v2/full_json?id=<id>&include=downloadData
//               -> <id>_<res>-JPG.zip, unzipped (files named <id>_<res>-JPG_Color.jpg, _NormalGL, ...)
//   Poly Haven  https://api.polyhaven.com/files/<id>
//               -> jpg maps diff, nor_gl, rough, ao, metal, disp (files named <id>_<map>_<res>.jpg)
// Every finished folder gets a `.source.json` (the marker for "already present").
// Credits live in assets/CREDITS.md.

import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

type Entry = { id: string; source: "ambientcg" | "polyhaven"; res: string; category?: string; use?: string };

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const manifest: { textures: Entry[] } = JSON.parse(readFileSync(join(root, "assets/texture-manifest.json"), "utf8"));
const outRoot = join(root, "assets/textures");
const args = process.argv.slice(2);
const force = args.includes("--force");
const only = args.filter((a) => !a.startsWith("--"));

const UA = { "User-Agent": "doomsday-surfers-asset-fetch/1.0" };

async function download(url: string, dest: string): Promise<number> {
  for (let attempt = 1; ; attempt++) {
    try {
      const res = await fetch(url, { headers: UA, redirect: "follow", signal: AbortSignal.timeout(180_000) });
      if (!res.ok) throw new Error(`HTTP ${res.status} for ${url}`);
      const bytes = Buffer.from(await res.arrayBuffer());
      writeFileSync(dest, bytes);
      return bytes.length;
    } catch (err) {
      if (attempt >= 3) throw err;
      await new Promise((r) => setTimeout(r, 1000 * attempt));
    }
  }
}

async function ambientcg(e: Entry, dir: string): Promise<string> {
  const res = e.res.toUpperCase(); // 1K / 2K
  const api = `https://ambientcg.com/api/v2/full_json?id=${e.id}&include=downloadData`;
  let link = `https://ambientcg.com/get?file=${e.id}_${res}-JPG.zip`;
  try {
    const j: any = await (await fetch(api, { headers: UA })).json();
    const downloads: any[] = j.foundAssets?.[0]?.downloadFolders?.default?.downloadFiletypeCategories?.zip?.downloads ?? [];
    const hit = downloads.find((d) => d.attribute === `${res}-JPG`);
    if (hit) link = hit.fullDownloadPath ?? hit.downloadLink;
    else if (downloads.length) throw new Error(`${e.id}: no ${res}-JPG (has ${downloads.map((d) => d.attribute).join(", ")})`);
  } catch (err) {
    if (String(err).includes("no ")) throw err;
    console.warn(`textures: ${e.id}: API lookup failed (${err}), trying ${link}`);
  }
  const zip = join(dir, `${e.id}_${res}-JPG.zip`);
  await download(link, zip);
  const unzip = spawnSync("unzip", ["-o", "-q", zip, "-d", dir]);
  if (unzip.status !== 0) throw new Error(`${e.id}: unzip failed: ${unzip.stderr?.toString()}`);
  rmSync(zip);
  return `https://ambientcg.com/a/${e.id}`;
}

// Poly Haven map keys -> the suffix used in their file names.
const PH_MAPS: Record<string, string> = {
  Diffuse: "diff",
  nor_gl: "nor_gl",
  Rough: "rough",
  AO: "ao",
  Metal: "metal",
  Displacement: "disp",
};

async function polyhaven(e: Entry, dir: string): Promise<string> {
  const res = e.res.toLowerCase(); // 1k / 2k
  const j: any = await (await fetch(`https://api.polyhaven.com/files/${e.id}`, { headers: UA })).json();
  if (!j.Diffuse) throw new Error(`${e.id}: not a Poly Haven texture set`);
  const jobs = Object.entries(PH_MAPS)
    .filter(([key]) => j[key]?.[res])
    .map(async ([key, suffix]) => {
      const files = j[key][res];
      const file = files.jpg ?? files.png;
      const ext = files.jpg ? "jpg" : "png";
      await download(file.url, join(dir, `${e.id}_${suffix}_${res}.${ext}`));
    });
  await Promise.all(jobs);
  return `https://polyhaven.com/a/${e.id}`;
}

mkdirSync(outRoot, { recursive: true });
const todo = manifest.textures.filter((e) => !only.length || only.includes(e.id));
let fetched = 0;
let skipped = 0;
const failed: string[] = [];

// A few at a time: the zips are 5-40 MB each.
const queue = [...todo];
async function worker() {
  for (let e = queue.shift(); e; e = queue.shift()) {
    const dir = join(outRoot, e.id);
    const marker = join(dir, ".source.json");
    if (!force && existsSync(marker)) {
      skipped++;
      continue;
    }
    rmSync(dir, { recursive: true, force: true });
    mkdirSync(dir, { recursive: true });
    try {
      const page = e.source === "ambientcg" ? await ambientcg(e, dir) : await polyhaven(e, dir);
      const files = readdirSync(dir).filter((f) => !f.startsWith("."));
      writeFileSync(marker, JSON.stringify({ ...e, page, license: "CC0", files }, null, 2));
      fetched++;
      console.log(`textures: ${e.id} (${e.source} ${e.res}) ${files.length} files`);
    } catch (err) {
      failed.push(e.id);
      console.error(`textures: FAILED ${e.id}: ${err}`);
      rmSync(dir, { recursive: true, force: true });
    }
  }
}
await Promise.all([worker(), worker(), worker(), worker()]);
console.log(`textures: ${fetched} fetched, ${skipped} already present, ${failed.length} failed -> ${outRoot}`);
if (failed.length) {
  console.error(`textures: failed: ${failed.join(", ")}`);
  process.exit(1);
}
