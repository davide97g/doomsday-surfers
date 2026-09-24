// The content bank for the current mode. "Personal" is the doomscroll feed
// (content.json); "Work" is the corporate parody (content.work.json laid over
// it: objects merge, arrays replace). The sim never sees the mode: Work only
// changes what each content type, habit and zone *means* on screen.
// The mode is picked on the title screen and applied on reload (textures are
// built once at boot). `?mode=work|personal` overrides it for testing.

import base from '../config/content.json';
import workJson from '../config/content.work.json';

export type Mode = 'personal' | 'work';
export type Content = typeof base;
export type WorkBank = typeof workJson.work;

const KEY = 'ds.mode';

function readMode(): Mode {
  const param = new URLSearchParams(location.search).get('mode');
  if (param === 'work' || param === 'personal') return param;
  try {
    return localStorage.getItem(KEY) === 'work' ? 'work' : 'personal';
  } catch {
    return 'personal';
  }
}

export const mode: Mode = readMode();

/** Remember the mode and restart the app in it. */
export function switchMode(next: Mode): void {
  try {
    localStorage.setItem(KEY, next);
  } catch {
    // Blocked storage: the switch still works for this launch via the URL.
  }
  const url = new URL(location.href);
  if (url.searchParams.has('mode')) url.searchParams.set('mode', next);
  location.replace(url.toString());
}

type Json = unknown;

function isObject(v: Json): v is Record<string, Json> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function merge(a: Json, b: Json, path: string): Json {
  if (!isObject(a) || !isObject(b)) return b;
  const out: Record<string, Json> = { ...a };
  for (const k of Object.keys(b)) {
    // A key the base bank doesn't have is a typo in the work bank.
    if (!(k in a) && import.meta.env.DEV) console.warn(`content.work.json: unknown key ${path}${k}`);
    out[k] = k in a ? merge(a[k], b[k], `${path}${k}.`) : b[k];
  }
  return out;
}

const { work: bank, ...overrides } = workJson;

export const content: Content = mode === 'work' ? (merge(base, overrides, '') as Content) : base;
/** Work-only copy (card kinds, meeting captions, status labels). */
export const work: WorkBank = bank;
