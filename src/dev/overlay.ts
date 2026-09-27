// On-screen console for builds where there is no inspector (a VITE_DEBUG=1
// build on a phone or simulator, or ?debug): warnings, errors and uncaught
// exceptions are listed over the game, newest at the bottom.

export function installDebugOverlay(): void {
  const box = document.createElement('pre');
  box.style.cssText =
    'position:fixed;left:6px;right:6px;bottom:6px;max-height:40vh;overflow:hidden;margin:0;padding:6px;' +
    'font:10px/1.3 ui-monospace,monospace;color:#ffb4b4;background:rgba(0,0,0,.72);z-index:99999;pointer-events:none;white-space:pre-wrap;';
  document.body.appendChild(box);
  const lines: string[] = [];
  const add = (kind: string, args: unknown[]) => {
    const text = args.map((a) => (a instanceof Error ? `${a.message} ${a.stack?.split('\n').slice(0, 3).join(' | ')}` : typeof a === 'string' ? a : JSON.stringify(a)?.slice(0, 200))).join(' ');
    lines.push(`${kind} ${text}`.slice(0, 400));
    while (lines.length > 14) lines.shift();
    box.textContent = lines.join('\n');
  };
  for (const kind of ['warn', 'error'] as const) {
    const orig = console[kind].bind(console);
    console[kind] = (...args: unknown[]) => {
      add(kind === 'warn' ? '⚠' : '✖', args);
      orig(...args);
    };
  }
  window.addEventListener('error', (e) => add('✖', [e.error ?? e.message]));
  window.addEventListener('unhandledrejection', (e) => add('✖ promise', [e.reason]));
}
