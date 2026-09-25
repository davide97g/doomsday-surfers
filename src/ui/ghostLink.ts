// Challenge links: a ghost run packed into the URL fragment (#g=…), so it
// never reaches a server log and needs no backend. deflate-raw + base64url
// keeps a 3-minute run around 2–3 KB.
// On the web the link points at wherever the game is being served; in the
// native app it needs `share.webUrl` (empty until the public web build is
// hosted, and then the link is simply left out).

import { content } from '../content/content';
import { GhostTrack, type GhostHeader, type GhostRecorder } from '../sim/ghost';

const PARAM = 'g';

async function pipe(bytes: Uint8Array, stream: CompressionStream | DecompressionStream): Promise<Uint8Array> {
  const out = new Response(new Blob([bytes as BlobPart]).stream().pipeThrough(stream));
  return new Uint8Array(await out.arrayBuffer());
}

function toBase64Url(bytes: Uint8Array): string {
  let bin = '';
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function fromBase64Url(s: string): Uint8Array {
  const bin = atob(s.replace(/-/g, '+').replace(/_/g, '/'));
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

/** Where links point, or null when there's nowhere a friend could open them. */
export function webBase(): string | null {
  if (location.protocol === 'http:' || location.protocol === 'https:') return `${location.origin}${location.pathname}`;
  return content.share.webUrl || null;
}

export async function ghostUrl(rec: GhostRecorder, header: GhostHeader): Promise<string | null> {
  const base = webBase();
  if (!base || rec.samples < 2) return null;
  try {
    const packed = await pipe(rec.encode(header), new CompressionStream('deflate-raw'));
    return `${base}#${PARAM}=${toBase64Url(packed)}`;
  } catch (e) {
    console.warn('ghost link failed', e);
    return null;
  }
}

/** The ghost in this page's URL, if any (and valid). */
export async function ghostFromUrl(): Promise<GhostTrack | null> {
  const m = location.hash.match(new RegExp(`[#&]${PARAM}=([A-Za-z0-9_-]+)`));
  if (!m) return null;
  try {
    return GhostTrack.decode(await pipe(fromBase64Url(m[1]), new DecompressionStream('deflate-raw')));
  } catch {
    return null;
  }
}

/** Drop the ghost from the address bar (after declining, so a reload doesn't bring it back). */
export function clearGhostFromUrl(): void {
  history.replaceState(null, '', `${location.pathname}${location.search}`);
}
