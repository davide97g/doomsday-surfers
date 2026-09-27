// HTML overlay UI. Game-facing UI lives here (not in the canvas) because the
// satire layer (fake ads, popups, feed overlays) is much faster to build in
// HTML/CSS. Every interactive element carries data-ui so input ignores it.
// In Work mode the dopamine battery is a presence pill instead: Available,
// Away, Be right back, then Offline at zero (tuning work.status thresholds).

import { content, mode, work } from '../content/content';
import { fill } from '../content/templates';
import { POWER_KINDS, TUNING, type Phase, type PowerKind, type SimEvent } from '../sim/types';
import type { World } from '../sim/world';
import { ICON } from './icons';
import { restartAnimation } from './nags';

/** Compact view counts: 950, 12.4K, 1.2M. */
export function views(n: number): string {
  if (n < 1000) return `${Math.floor(n)}`;
  if (n < 1e6) return `${(n / 1000).toFixed(n < 1e4 ? 1 : 0)}K`;
  return `${(n / 1e6).toFixed(1)}M`;
}

export interface PerfToggles {
  bloom: boolean;
  grade: boolean;
  pixelRatio: number;
}

const LOW = 25;
/** Below this the label drops the clinical voice: "you're cooked". */
const COOKED = 10;
const WORK = mode === 'work';
type Presence = keyof typeof work.status;

function presence(pct: number): Presence {
  const s = TUNING.work.status;
  return pct >= s.awayBelow ? 'available' : pct >= s.brbBelow ? 'away' : pct > 0 ? 'brb' : 'offline';
}

const BATTERY = WORK
  ? `
      <div class="battery status" id="battery" data-state="available">
        <div class="st-pill">
          <span class="st-avatar">ME<i class="st-dot"></i></span>
          <span class="st-label" id="bat-label">${work.status.available}</span>
          <span class="bat-pct" id="bat-pct">70%</span>
        </div>
        <div class="st-track"><div class="bat-fill" id="bat-fill"></div></div>
      </div>`
  : `
      <div class="battery" id="battery">
        <span class="label" id="bat-label">${content.battery.label}</span>
        <div class="bat-row">
          <div class="bat-body"><div class="bat-fill" id="bat-fill"></div></div>
          <div class="bat-cap"></div>
          <span class="bat-pct" id="bat-pct">70%</span>
        </div>
      </div>`;

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
  private cooked = false;
  private boosting = false;
  private shownPct = -1;
  private presence: Presence = 'available';
  private phase: Phase | null = null;
  private readonly powersEl: HTMLElement;
  private readonly chips = new Map<PowerKind, { el: HTMLElement; full: number; shown: string }>();
  private readonly viewsEl: HTMLElement;
  private viewCount = 0;
  onPerfChange: (p: PerfToggles) => void = () => {};
  perf: PerfToggles;

  constructor(parent: HTMLElement, initial: PerfToggles) {
    this.perf = { ...initial };
    this.root = document.createElement('div');
    this.root.className = 'hud';
    this.root.innerHTML = `
      <div class="top">
        <div class="stat"><span class="label">${content.hud.distance}</span><span class="value" id="dist">0m</span></div>
        <div class="stat right"><span class="label">${content.hud.score}</span><span class="value" id="score">0</span></div>
      </div>${BATTERY}
      <div class="powers" id="powers"></div>
      <div class="views hidden" id="views"></div>
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
    this.powersEl = $('powers');
    this.viewsEl = $('views');
    for (const kind of POWER_KINDS) {
      const el = document.createElement('div');
      el.className = 'pw hidden';
      el.dataset.kind = kind;
      el.innerHTML = `<i>${ICON[kind]}</i>`;
      this.powersEl.appendChild(el);
      this.chips.set(kind, { el, full: 1, shown: '' });
    }

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
      const cooked = pct <= COOKED;
      if (low !== this.low || cooked !== this.cooked) {
        this.low = low;
        this.cooked = cooked;
        this.battery.classList.toggle('low', low);
        if (!WORK) this.batLabel.textContent = cooked ? content.battery.cooked : low ? content.battery.low : content.battery.label;
      }
      const p = presence(pct);
      if (WORK && p !== this.presence) {
        this.presence = p;
        this.battery.dataset.state = p;
        this.batLabel.textContent = work.status[p];
      }
    }

    const boosting = w.boostT > 0;
    if (boosting !== this.boosting) {
      this.boosting = boosting;
      this.battery.classList.toggle('boost', boosting);
    }

    // Power-ups: a chip each, its ring draining with what's left.
    for (const [kind, chip] of this.chips) {
      const left = kind === 'viral' ? (w.flying ? Math.max(0, w.flyTo - w.d) : 0) : w.power[kind];
      const k = left > 0 ? Math.min(1, left / chip.full) : 0;
      const shown = left > 0 ? k.toFixed(2) : '';
      if (shown === chip.shown) continue;
      chip.shown = shown;
      chip.el.classList.toggle('hidden', left <= 0);
      chip.el.classList.toggle('ending', left > 0 && (kind === 'viral' ? left < 40 : left < 2));
      chip.el.style.setProperty('--left', shown || '0');
    }
    // Going Viral: the view counter runs away with itself.
    if (w.flying) {
      this.viewCount = this.viewCount * (1 + dt * 1.6) + dt * 9000;
      this.viewsEl.textContent = fill(content.powers.viral.views, { views: views(this.viewCount) });
    }
    this.viewsEl.classList.toggle('hidden', !w.flying);
    if (!w.flying) this.viewCount = 0;

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
      if (e.type === 'power') {
        const c = content.powers[e.kind];
        const chip = this.chips.get(e.kind)!;
        chip.full = Math.max(e.duration, 0.01);
        chip.shown = '';
        const line = fill(c.lines[Math.floor(Math.random() * c.lines.length)], { views: views(1000 + Math.random() * 9000) });
        this.showToast(`${c.title}\n${line}`, true);
      }
      if (e.type === 'shield') this.showToast(content.powers.protector.break, true);
      if (e.type === 'powerEnd' && e.kind !== 'protector') this.showToast(content.powers[e.kind].end, false);
      if (e.type === 'fly' && e.stage === 'land') this.showToast(content.powers.viral.end, false);
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
