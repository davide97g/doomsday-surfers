// HTML overlay UI. Game-facing UI lives here (not in the canvas) because the
// satire layer (fake ads, popups, feed overlays) is much faster to build in
// HTML/CSS. Every interactive element carries data-ui so input ignores it.

import content from '../config/content.json';
import type { Phase, SimEvent } from '../sim/types';
import type { World } from '../sim/world';
import { restartAnimation } from './nags';

export interface PerfToggles {
  bloom: boolean;
  grade: boolean;
  pixelRatio: number;
}

const LOW = 25;

export class Hud {
  readonly root: HTMLElement;
  private readonly distEl: HTMLElement;
  private readonly scoreEl: HTMLElement;
  private readonly fpsEl: HTMLElement;
  private readonly perfEl: HTMLElement;
  private readonly battery: HTMLElement;
  private readonly batFill: HTMLElement;
  private readonly batPct: HTMLElement;
  private readonly batLabel: HTMLElement;
  private readonly toast: HTMLElement;
  private toastTimer = 0;
  private low = false;
  private boosting = false;
  private shownPct = -1;
  private phase: Phase | null = null;
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
        <div class="perf-stats" id="pf-stats"></div>
      </div>
    `;
    parent.appendChild(this.root);
    const $ = <T extends HTMLElement>(id: string) => this.root.querySelector<T>('#' + id)!;
    this.distEl = $('dist');
    this.scoreEl = $('score');
    this.fpsEl = $('fps');
    this.perfEl = $('perf');
    this.battery = $('battery');
    this.batFill = $('bat-fill');
    this.batPct = $('bat-pct');
    this.batLabel = $('bat-label');
    this.toast = $('toast');

    this.fpsEl.addEventListener('click', () => this.perfEl.classList.toggle('hidden'));

    const bloom = $<HTMLInputElement>('pf-bloom');
    const grade = $<HTMLInputElement>('pf-grade');
    const pr = $<HTMLSelectElement>('pf-pr');
    bloom.checked = this.perf.bloom;
    grade.checked = this.perf.grade;
    pr.value = String(this.perf.pixelRatio);
    if (!pr.value) pr.value = '2';
    const emit = () => {
      this.perf = { bloom: bloom.checked, grade: grade.checked, pixelRatio: Number(pr.value) };
      this.onPerfChange(this.perf);
    };
    [bloom, grade, pr].forEach((el) => el.addEventListener('input', emit));
  }

  update(w: World, dt: number): void {
    const phase = w.phase;
    this.distEl.textContent = `${Math.floor(w.d)}m`;
    this.scoreEl.textContent = w.score.toLocaleString('en-US');

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

    const boosting = w.boostT > 0;
    if (boosting !== this.boosting) {
      this.boosting = boosting;
      this.battery.classList.toggle('boost', boosting);
    }

    if (this.toastTimer > 0) {
      this.toastTimer -= dt;
      if (this.toastTimer <= 0) this.toast.classList.add('hidden');
    }

    if (phase !== this.phase) {
      this.phase = phase;
      this.battery.classList.toggle('hidden', phase === 'dead');
      // The title screen has its own layout; run stats come in with the run.
      this.root.classList.toggle('title', phase === 'ready');
      if (phase !== 'running') {
        this.toast.classList.add('hidden');
        this.toastTimer = 0;
      }
    }
  }

  handle(events: readonly SimEvent[]): void {
    for (const e of events) {
      if (e.type === 'habit') {
        const lines = content.habits[e.habit % content.habits.length].popups;
        this.showToast(lines[Math.floor(Math.random() * lines.length)], false);
      }
      if (e.type === 'thrill') {
        const th = content.thrill[e.kind];
        const line = th.lines[Math.floor(Math.random() * th.lines.length)];
        this.showToast(`${th.title} +${Math.round(e.gain)}%\n${line}`, true);
      }
      if (e.type === 'boost') {
        const b = content.notifications.boost;
        const line = b.lines[Math.floor(Math.random() * b.lines.length)];
        this.showToast(`${b.title} +${Math.round(e.gain)}%\n${line}`, true);
      }
    }
  }

  private showToast(text: string, boost: boolean): void {
    this.toast.textContent = text;
    this.toast.classList.toggle('boost', boost);
    this.toast.classList.remove('hidden');
    restartAnimation(this.toast);
    this.toastTimer = boost ? 1.8 : 1.6;
  }

  setFps(fps: number, frameMs: number, calls: number, tris: number): void {
    this.fpsEl.textContent = `${fps.toFixed(0)} fps`;
    this.fpsEl.classList.toggle('bad', fps < 55);
    const stats = this.root.querySelector('#pf-stats')!;
    stats.textContent = `${frameMs.toFixed(1)}ms cpu · ${calls} calls · ${(tris / 1000).toFixed(0)}k tris`;
  }
}
