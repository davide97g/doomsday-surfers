// Your name on ghost links. No accounts: the first share makes you a roast
// handle from your character ("@hoodie.goblin.4312"), and you can rename it.
// Stored in localStorage (a per-device convenience).

import { content } from '../content/content';

const KEY = 'ds.handle';

export function loadHandle(character: number): string {
  try {
    const h = localStorage.getItem(KEY);
    if (h) return h;
  } catch {
    // Blocked storage: a fresh roast every time.
  }
  const slug = content.characters[character].name.toLowerCase().replace(/[^a-z0-9]+/g, '.').replace(/^\.|\.$/g, '');
  const h = `@${slug}.${1000 + Math.floor(Math.random() * 9000)}`;
  saveHandle(h);
  return h;
}

export function saveHandle(h: string): void {
  try {
    localStorage.setItem(KEY, h);
  } catch {
    // Nothing to do.
  }
}

/** Asks for a new name; returns the handle to use (unchanged on cancel). */
export function renameHandle(current: string): string {
  const raw = window.prompt(content.share.renamePrompt, current.replace(/^@/, ''));
  const clean = raw?.trim().replace(/^@+/, '').replace(/\s+/g, '.').slice(0, 24);
  if (!clean) return current;
  const h = `@${clean}`;
  saveHandle(h);
  return h;
}
