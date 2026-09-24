// Hands an image to the system share sheet: Capacitor on device (writes a
// cache file first), Web Share in a browser, a plain download as a last resort.

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
export async function shareImage(blob: Blob, name: string, title: string, text: string): Promise<void> {
  try {
    if (Capacitor.isNativePlatform()) {
      const { uri } = await Filesystem.writeFile({ path: name, data: await base64(blob), directory: Directory.Cache });
      await Share.share({ title, text, files: [uri] });
      return;
    }
    const file = new File([blob], name, { type: blob.type });
    if (navigator.canShare?.({ files: [file] })) {
      await navigator.share({ files: [file], title, text });
      return;
    }
  } catch (e) {
    const msg = String((e as Error)?.message ?? e);
    if ((e as Error)?.name === 'AbortError' || /cancel/i.test(msg)) return;
    console.warn('share failed, downloading instead', e);
  }
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}
