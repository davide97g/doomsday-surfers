// HTML overlay UI. Game-facing UI lives here (not in the canvas) because the
// satire layer (fake ads, popups, feed overlays) is much faster to build in
// HTML/CSS. Every interactive element carries data-ui so input ignores it.

import content from '../config/content.json';
import type { Phase, SimEvent } from '../sim/types';
import type { World } from '../sim/world';

export interface PerfToggles {
  bloom: boolean;
  grade: boolean;
  pixelRatio: number;
  noDrain: boolean;
}

const LOW = 25;

export class Hud {
  private readonly root: HTMLElement;
  private readonly distEl: HTMLElement;
  private readonly scoreEl: HTMLElement;
  private readonly fpsEl: HTMLElement;
  private readonly perfEl: HTMLElement;
  private readonly readyEl: HTMLElement;
  private readonly deadEl: HTMLElement;
  private readonly deadStats: HTMLElement;
  private readonly battery: HTMLElement;
  private readonly batFill: HTMLElement;
  private readonly batPct: HTMLElement;
  private readonly batLabel: HTMLElement;
  private readonly toast: HTMLElement;
  private toastTimer = 0;
  private low = false;
  private shownPct = -1;
  private phase: Phase | null = null;
  private deadAt = 0;
  onRestart: () => void = () => {};
  onPerfChange: (p: PerfToggles) => void = () => {};
  perf: PerfToggles;

  constructor(parent: HTMLElement, initial: PerfToggles) {
    this.perf = { ...initial };
    this.root = document.createElement('div');
    this.root.className = 'hud';
    this.root.innerHTML = `
      <div class="top">
        <div class="stat"><span class="label">SCROLLED</span><span class="value" id="dist">0m</span></div>
        <div class="stat right"><span class="label">ENGAGEMENT</span><span class="value" id="score">0</span></div>
      </div>
      <div class="battery" id="battery">
        <span class="label" id="bat-label">${content.battery.label}</span>
        <div class="bat-row">
          <div class="bat-body"><div class="bat-fill" id="bat-fill"></div></div>
          <div class="bat-cap"></div>
          <span class="bat-pct" id="bat-pct">70%</span>
        </div>
      </div>
      <div class="toast hidden" id="toast"></div>
      <button class="fps" id="fps" data-ui>-- fps</button>
      <div class="perf hidden" id="perf" data-ui>
        <div class="perf-title">device test</div>
        <label><input type="checkbox" id="pf-bloom"> bloom</label>
        <label><input type="checkbox" id="pf-grade"> colour grade</label>
        <label>pixel ratio
          <select id="pf-pr"><option>1</option><option>1.5</option><option>2</option><option>3</option></select>
        </label>
        <label><input type="checkbox" id="pf-nodrain"> no drain</label>
        <div class="perf-stats" id="pf-stats"></div>
      </div>
      <div class="overlay ready" id="ready">
        <div class="logo">DOOMSDAY<br>SURFERS</div>
        <div class="hint">swipe to start scrolling</div>
        <div class="controls">&larr; &rarr; switch &middot; &uarr; jump &middot; &darr; roll</div>
      </div>
      <div class="overlay dead hidden" id="dead">
        <div class="dead-line one">${content.death.line1}</div>
        <div class="dead-line two">${content.death.line2}</div>
        <div class="dead-stats" id="dead-stats"></div>
        <button class="cta" id="again" data-ui>${content.death.cta}</button>
      </div>
    `;
    parent.appendChild(this.root);
    const $ = <T extends HTMLElement>(id: string) => this.root.querySelector<T>('#' + id)!;
    this.distEl = $('dist');
    this.scoreEl = $('score');
    this.fpsEl = $('fps');
    this.perfEl = $('perf');
    this.readyEl = $('ready');
    this.deadEl = $('dead');
    this.deadStats = $('dead-stats');
    this.battery = $('battery');
    this.batFill = $('bat-fill');
    this.batPct = $('bat-pct');
    this.batLabel = $('bat-label');
    this.toast = $('toast');

    this.fpsEl.addEventListener('click', () => this.perfEl.classList.toggle('hidden'));
    // Ignore taps until the button has faded in (matches the CSS delay).
    $('again').addEventListener('click', () => {
      if (performance.now() - this.deadAt > 3800) this.onRestart();
    });

    const bloom = $<HTMLInputElement>('pf-bloom');
    const grade = $<HTMLInputElement>('pf-grade');
    const pr = $<HTMLSelectElement>('pf-pr');
    const noDrain = $<HTMLInputElement>('pf-nodrain');
    bloom.checked = this.perf.bloom;
    grade.checked = this.perf.grade;
    pr.value = String(this.perf.pixelRatio);
    if (!pr.value) pr.value = '2';
    noDrain.checked = this.perf.noDrain;
    const emit = () => {
      this.perf = { bloom: bloom.checked, grade: grade.checked, pixelRatio: Number(pr.value), noDrain: noDrain.checked };
      this.onPerfChange(this.perf);
    };
    [bloom, grade, pr, noDrain].forEach((el) => el.addEventListener('input', emit));
  }

  update(w: World, dt: number): void {
    const phase = w.phase;
    const dist = w.d;
    const score = w.score;
    this.distEl.textContent = `${Math.floor(dist)}m`;
    this.scoreEl.textContent = score.toLocaleString('en-US');

    // Battery: only touch the DOM when the shown value changes.
    const pct = Math.max(0, Math.ceil((w.dopamine / w.t.dopamine.max) * 100));
    if (pct !== this.shownPct) {
      this.shownPct = pct;
      this.batFill.style.transform = `scaleX(${pct / 100})`;
      this.batPct.textContent = `${pct}%`;
      const low = pct <= LOW;
      if (low !== this.low) {
        this.low = low;
        this.battery.classList.toggle('low', low);
        this.batLabel.textContent = low ? content.battery.low : content.battery.label;
      }
    }

    if (this.toastTimer > 0) {
      this.toastTimer -= dt;
      if (this.toastTimer <= 0) this.toast.classList.add('hidden');
    }

    if (phase !== this.phase) {
      this.phase = phase;
      this.readyEl.classList.toggle('hidden', phase !== 'ready');
      this.deadEl.classList.toggle('hidden', phase !== 'dead');
      this.battery.classList.toggle('hidden', phase === 'dead');
      if (phase !== 'running') {
        this.toast.classList.add('hidden');
        this.toastTimer = 0;
      }
      if (phase === 'dead') {
        this.deadAt = performance.now();
        this.deadStats.innerHTML = `<div><b>${Math.floor(dist)}m</b> scrolled</div><div><b>${score.toLocaleString('en-US')}</b> engagement</div>`;
      }
    }
  }

  handle(events: readonly SimEvent[]): void {
    for (const e of events) {
      if (e.type === 'habit') {
        const lines = content.habits[e.habit % content.habits.length].popups;
        this.toast.textContent = lines[Math.floor(Math.random() * lines.length)];
        this.toast.classList.remove('hidden');
        // Restart the pop-in animation.
        this.toast.style.animation = 'none';
        void this.toast.offsetWidth;
        this.toast.style.animation = '';
        this.toastTimer = 1.6;
      }
    }
  }

  setFps(fps: number, frameMs: number, calls: number, tris: number): void {
    this.fpsEl.textContent = `${fps.toFixed(0)} fps`;
    this.fpsEl.classList.toggle('bad', fps < 55);
    const stats = this.root.querySelector('#pf-stats')!;
    stats.textContent = `${frameMs.toFixed(1)}ms cpu · ${calls} calls · ${(tris / 1000).toFixed(0)}k tris`;
  }
}
