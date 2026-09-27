// Compresses a Blender-exported .glb for the game (assets/blender/lib/export.py
// calls this; see docs/assets-v2.md "Compress").
//
//   bun scripts/compress-glb.ts in.glb [out.glb] [--max-texture 1024]
//       [--textures auto|ktx2|webp|keep] [--quantize-position] [--no-meshopt]
//
// Steps (gltf-transform API):
//   1. dedup + prune
//   2. textures resized to fit --max-texture (never upscaled)
//   3. KTX2 when the `ktx` binary is found (tools/ktx/ or PATH): UASTC for
//      normal maps, ETC1S for colour/ORM/emissive; else WebP
//   4. meshopt (EXT_meshopt_compression). POSITION stays float by default: the
//      quantized form moves a dequantize transform into each node's matrix
//      (and splits nodes that have children), which breaks code that takes a
//      node's geometry without its matrix. --quantize-position turns it on
//      (fine for skinned characters, which are used as a whole scene).
//      Normals, UVs in 0..1, joints and weights are quantized.

import { spawnSync } from "node:child_process";
import { existsSync, statSync } from "node:fs";
import { delimiter, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { Mode, toktx } from "@gltf-transform/cli";
import { Accessor, type Document, NodeIO, type Transform } from "@gltf-transform/core";
import { ALL_EXTENSIONS, EXTMeshoptCompression, KHRMeshQuantization } from "@gltf-transform/extensions";
import { dedup, prune, quantize, reorder, textureCompress } from "@gltf-transform/functions";
import { MeshoptDecoder, MeshoptEncoder } from "meshoptimizer";
import sharp from "sharp";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const args = process.argv.slice(2);
const opt = (name: string, fallback: string) => {
  const i = args.indexOf(`--${name}`);
  return i >= 0 && i + 1 < args.length ? args[i + 1] : fallback;
};
const files = args.filter((a, i) => !a.startsWith("--") && !(i > 0 && ["--max-texture", "--textures"].includes(args[i - 1])));
if (!files.length) {
  console.error("usage: bun scripts/compress-glb.ts in.glb [out.glb] [--max-texture 1024] [--textures auto|ktx2|webp|keep]");
  process.exit(2);
}
const input = resolve(files[0]);
const output = resolve(files[1] ?? files[0]);
const maxTexture = Number(opt("max-texture", "1024"));
let textures = opt("textures", "auto");
const quantizePosition = args.includes("--quantize-position");
const useMeshopt = !args.includes("--no-meshopt");

// The ktx binary (KTX-Software >= 4.4) from tools/ktx/, fetched by scripts/setup-assets.sh.
// gltf-transform finds it through PATH with execSync, and Bun's child processes
// only see the PATH the process started with, so re-run with it added.
const ktxDir = join(root, "tools", "ktx");
const pathList = (process.env.PATH ?? "").split(delimiter);
if (existsSync(join(ktxDir, "ktx")) && !pathList.includes(ktxDir)) {
  const env = { ...process.env, PATH: [ktxDir, ...pathList].join(delimiter) };
  const again = spawnSync(process.execPath, process.argv.slice(1), { env, stdio: "inherit" });
  process.exit(again.status ?? 1);
}
const hasKtx = spawnSync("ktx", ["--version"], { env: process.env }).status === 0; // env: Bun only sees the new PATH when passed explicitly
if (textures === "auto") textures = hasKtx ? "ktx2" : "webp";
if (textures === "ktx2" && !hasKtx) {
  console.error("compress: --textures ktx2 needs the `ktx` binary (run `bun run assets:setup`)");
  process.exit(1);
}

await MeshoptEncoder.ready;
await MeshoptDecoder.ready;
const io = new NodeIO()
  .registerExtensions(ALL_EXTENSIONS)
  .registerDependencies({ "meshopt.encoder": MeshoptEncoder, "meshopt.decoder": MeshoptDecoder });
const doc: Document = await io.read(input);

const steps: Transform[] = [dedup(), prune({ keepAttributes: true, keepLeaves: true })];
if (textures !== "keep") steps.push(textureCompress({ encoder: sharp, resize: [maxTexture, maxTexture] }));
if (textures === "ktx2") {
  steps.push(
    toktx({ encoder: sharp, mode: Mode.UASTC, slots: /^normalTexture$/, level: 2, rdo: true, rdoLambda: 2, zstd: 18 }),
    toktx({ encoder: sharp, mode: Mode.ETC1S, slots: /^(?!normalTexture$).*$/, quality: 192, compression: 2 }),
  );
} else if (textures === "webp") {
  steps.push(textureCompress({ encoder: sharp, targetFormat: "webp", quality: 88 }));
}
if (useMeshopt) {
  steps.push(
    reorder({ encoder: MeshoptEncoder, target: "size" }),
    quantize({
      pattern: quantizePosition
        ? /^(POSITION|NORMAL|TANGENT|TEXCOORD|JOINTS|WEIGHTS|COLOR)(_\d+)?$/
        : /^(NORMAL|TANGENT|TEXCOORD|JOINTS|WEIGHTS|COLOR)(_\d+)?$/,
      quantizeNormal: 10,
      quantizeTexcoord: 14,
    }),
  );
  doc
    .createExtension(EXTMeshoptCompression)
    .setRequired(true)
    .setEncoderOptions({ method: EXTMeshoptCompression.EncoderMethod.FILTER });
}
await doc.transform(...steps);
// quantize() only declares KHR_mesh_quantization when POSITION is quantized;
// normals/UVs stored as normalized ints need it too (the validator insists).
const quantized = doc
  .getRoot()
  .listMeshes()
  .some((m) => m.listPrimitives().some((p) => p.listAttributes().some((a) => a.getComponentType() !== Accessor.ComponentType.FLOAT)));
if (quantized) doc.createExtension(KHRMeshQuantization).setRequired(true);
await io.write(output, doc);

const kb = (p: string) => Math.round(statSync(p).size / 1024);
console.log(
  `compress: ${output} ${kb(output)} KB (textures ${textures}, max ${maxTexture}, meshopt ${useMeshopt ? "on" : "off"}` +
    `${quantizePosition ? ", positions quantized" : ""})`,
);
