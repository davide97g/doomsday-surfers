// Copies the Basis Universal transcoder that three's KTX2Loader needs from
// node_modules/three/examples/jsm/libs/basis/ into public/libs/basis/ (served
// as-is by Vite and Capacitor; src/render/assets.ts points KTX2Loader at it).
// Runs on `bun install` (postinstall); only rewrites files that changed, so the
// committed copy stays in step with the installed three version.
//
//   bun scripts/copy-decoders.ts

import { copyFileSync, existsSync, mkdirSync, readFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const src = join(root, "node_modules/three/examples/jsm/libs/basis");
const dst = join(root, "public/libs/basis");

if (!existsSync(src)) {
  console.warn(`decoders: ${src} not found (is three installed?), skipping`);
  process.exit(0);
}
mkdirSync(dst, { recursive: true });
let copied = 0;
for (const f of readdirSync(src)) {
  const from = join(src, f);
  const to = join(dst, f);
  if (existsSync(to) && readFileSync(from).equals(readFileSync(to))) continue;
  copyFileSync(from, to);
  copied++;
}
console.log(`decoders: ${copied ? `copied ${copied} file(s)` : "up to date"} -> public/libs/basis/`);
