// Hands files (the clip, the receipt) to the system share sheet: Capacitor on
// device (writes cache files first), Web Share in a browser, plain downloads as
// a last resort.

import { Capacitor } from '@capacitor/core';
import { Directory, Filesystem } from '@capacitor/filesystem';
import { Share } from '@capacitor/share';

function base64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).split(',')[1]);
    r.onerror = () => reject(r.error);
    r.readAsDataURL(blob);
  });
}

/** Resolves once the sheet closes. Cancelling the sheet is not an error. */
export async function shareFiles(files: { blob: Blob; name: string }[], title: string, text: string): Promise<void> {
  try {
    if (Capacitor.isNativePlatform()) {
      const uris: string[] = [];
      for (const f of files) {
        const { uri } = await Filesystem.writeFile({ path: f.name, data: await base64(f.blob), directory: Directory.Cache });
        uris.push(uri);
      }
      await Share.share({ title, text, files: uris });
      return;
    }
    const list = files.map((f) => new File([f.blob], f.name, { type: f.blob.type }));
    if (navigator.canShare?.({ files: list })) {
      await navigator.share({ files: list, title, text });
      return;
    }
  } catch (e) {
    const msg = String((e as Error)?.message ?? e);
    if ((e as Error)?.name === 'AbortError' || /cancel/i.test(msg)) return;
    console.warn('share failed, downloading instead', e);
  }
  for (const f of files) {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(f.blob);
    a.download = f.name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  }
}

/** Text only (the Daily's emoji grid, for group chats). Falls back to the clipboard. */
export async function shareText(title: string, text: string): Promise<void> {
  try {
    if (Capacitor.isNativePlatform()) {
      await Share.share({ title, text });
      return;
    }
    if (navigator.share) {
      await navigator.share({ title, text });
      return;
    }
  } catch (e) {
    const msg = String((e as Error)?.message ?? e);
    if ((e as Error)?.name === 'AbortError' || /cancel/i.test(msg)) return;
    console.warn('share failed, copying instead', e);
  }
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    // Nothing else to try.
  }
}

/** Social apps' in-app browsers, where Web Share and downloads are unreliable. */
const IN_APP: [RegExp, string][] = [
  [/Instagram/, 'Instagram'],
  [/FBAN|FBAV|FB_IAB/, 'Facebook'],
  [/BytedanceWebview|musical_ly|TikTok/i, 'TikTok'],
];

/** The app whose in-app browser we're in, and a link that reopens this page in the real browser. Null elsewhere. */
export function inAppBrowser(): { app: string; browser: string; href: string } | null {
  if (Capacitor.isNativePlatform()) return null;
  const ua = navigator.userAgent;
  const hit = IN_APP.find(([re]) => re.test(ua));
  if (!hit) return null;
  const { host, pathname, search } = location;
  // iOS 17+ hands x-safari-https links to Safari; Android takes an intent for Chrome.
  if (/iPhone|iPad|iPod/.test(ua)) return { app: hit[1], browser: 'Safari', href: `x-safari-https://${host}${pathname}${search}` };
  if (/Android/.test(ua)) {
    return { app: hit[1], browser: 'Chrome', href: `intent://${host}${pathname}${search}#Intent;scheme=https;package=com.android.chrome;end` };
  }
  return null;
}
