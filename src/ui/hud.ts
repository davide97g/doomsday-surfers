// HTML overlay UI. Game-facing UI lives here (not in the canvas) because the
// satire layer (fake ads, popups, feed overlays) is much faster to build in
// HTML/CSS. Every interactive element carries data-ui so input ignores it.

import type { Phase } from '../sim/types';

export interface PerfToggles {
  bloom: boolean;
  grade: boolean;
  pixelRatio: number;
  dopamine: number;
}

export class Hud {
  private readonly root: HTMLElement;
  private readonly distEl: HTMLElement;
  private readonly scoreEl: HTMLElement;
  private readonly fpsEl: HTMLElement;
  private readonly perfEl: HTMLElement;
  private readonly readyEl: HTMLElement;
  private readonly deadEl: HTMLElement;
  private readonly deadStats: HTMLElement;
  private phase: Phase | null = null;
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
      <button class="fps" id="fps" data-ui>-- fps</button>
      <div class="perf hidden" id="perf" data-ui>
        <div class="perf-title">device test</div>
        <label><input type="checkbox" id="pf-bloom"> bloom</label>
        <label><input type="checkbox" id="pf-grade"> colour grade</label>
        <label>pixel ratio
          <select id="pf-pr"><option>1</option><option>1.5</option><option>2</option><option>3</option></select>
        </label>
        <label>dopamine <input type="range" id="pf-dop" min="0" max="1" step="0.01"></label>
        <div class="perf-stats" id="pf-stats"></div>
      </div>
      <div class="overlay ready" id="ready">
        <div class="logo">DOOMSDAY<br>SURFERS</div>
        <div class="hint">swipe to start scrolling</div>
        <div class="controls">&larr; &rarr; switch &middot; &uarr; jump &middot; &darr; roll</div>
      </div>
      <div class="overlay dead hidden" id="dead">
        <div class="dead-title">CONNECTION LOST</div>
        <div class="dead-stats" id="dead-stats"></div>
        <button class="cta" id="again" data-ui>SCROLL AGAIN</button>
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

    this.fpsEl.addEventListener('click', () => this.perfEl.classList.toggle('hidden'));
    $('again').addEventListener('click', () => this.onRestart());

    const bloom = $<HTMLInputElement>('pf-bloom');
    const grade = $<HTMLInputElement>('pf-grade');
    const pr = $<HTMLSelectElement>('pf-pr');
    const dop = $<HTMLInputElement>('pf-dop');
    bloom.checked = this.perf.bloom;
    grade.checked = this.perf.grade;
    pr.value = String(this.perf.pixelRatio);
    if (!pr.value) pr.value = '2';
    dop.value = String(this.perf.dopamine);
    const emit = () => {
      this.perf = { bloom: bloom.checked, grade: grade.checked, pixelRatio: Number(pr.value), dopamine: Number(dop.value) };
      this.onPerfChange(this.perf);
    };
    [bloom, grade, pr, dop].forEach((el) => el.addEventListener('input', emit));
  }

  update(phase: Phase, dist: number, score: number): void {
    this.distEl.textContent = `${Math.floor(dist)}m`;
    this.scoreEl.textContent = score.toLocaleString('en-US');
    if (phase !== this.phase) {
      this.phase = phase;
      this.readyEl.classList.toggle('hidden', phase !== 'ready');
      this.deadEl.classList.toggle('hidden', phase !== 'dead');
      if (phase === 'dead') {
        this.deadStats.innerHTML = `<div><b>${Math.floor(dist)}m</b> scrolled</div><div><b>${score.toLocaleString('en-US')}</b> engagement</div>`;
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
