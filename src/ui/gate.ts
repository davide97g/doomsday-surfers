// Checkpoint gate overlay. While the camera circles the runner, a viewfinder
// frames them and a profiling log types itself out from this run's stats.
// When the scan lets go, the new feed zone is announced.

import { content } from '../content/content';
import { fill } from '../content/templates';
import { zoneLook, type SimEvent } from '../sim/types';
import type { World } from '../sim/world';
import { restartAnimation } from './nags';
import type { Sfx } from './sfx';

const LINES = 4;
const ZONE_SHOW = 2.6;

export class GateScan {
  private readonly scan: HTMLElement;
  private readonly log: HTMLElement;
  private readonly zone: HTMLElement;
  private reveal: { el: HTMLElement; at: number }[] = [];
  private scanT = -1;
  private zoneLeft = 0;

  constructor(parent: HTMLElement, private readonly sfx: Sfx) {
    this.scan = document.createElement('div');
    this.scan.className = 'scan hidden';
    this.scan.innerHTML = `
      <div class="scan-frame"><i></i><i></i><i></i><i></i></div>
      <div class="scan-tag"><span class="rec"></span>${content.gate.tag}</div>
      <div class="scan-log"></div>`;
    this.log = this.scan.querySelector('.scan-log')!;

    this.zone = document.createElement('div');
    this.zone.className = 'zone hidden';
    this.zone.innerHTML = `
      <div class="zone-kicker">${content.gate.kicker}</div>
      <div class="zone-name"></div>
      <div class="zone-tag"></div>`;

    parent.append(this.scan, this.zone);
  }

  handle(events: readonly SimEvent[], w: World): void {
    for (const e of events) {
      if (e.type === 'gate') this.startScan(w);
      if (e.type === 'gateEnd') this.showZone(e.zone);
    }
  }

  update(w: World, dt: number): void {
    if (w.phase !== 'running') {
      this.scan.classList.add('hidden');
      this.zone.classList.add('hidden');
      this.scanT = -1;
      this.zoneLeft = 0;
      return;
    }
    if (this.scanT >= 0) {
      this.scanT += dt;
      for (const r of this.reveal) {
        if (r.at > this.scanT || r.el.classList.contains('on')) continue;
        r.el.classList.add('on');
        this.sfx.tick();
      }
    }
    if (this.zoneLeft > 0) {
      this.zoneLeft -= dt;
      if (this.zoneLeft <= 0) this.zone.classList.add('hidden');
    }
  }

  private startScan(w: World): void {
    const g = content.gate;
    let top = 0;
    w.takenByType.forEach((n, i) => {
      if (n > w.takenByType[top]) top = i;
    });
    const vars = {
      id: 10000 + Math.floor(Math.random() * 89999),
      span: Math.max(0.4, 8 * Math.pow(0.985, w.pickupsTaken)).toFixed(1),
      top: w.pickupsTaken > 0 ? content.contentTypes[top].name : 'Anything',
      mum: w.mumIgnored,
      dodged: w.habitsDodged,
      thumb: Math.round(60 + w.time * 0.8 + Math.random() * 20),
      value: (0.01 + w.pickupsTaken * 0.003).toFixed(2),
      blink: Math.round(w.time),
      n: w.zone * (40 + Math.floor(Math.random() * 300)),
    };
    const pool = [...g.lines];
    const rows = [fill(g.header, vars)];
    for (let i = 0; i < LINES && pool.length > 0; i++) rows.push(fill(pool.splice(Math.floor(Math.random() * pool.length), 1)[0], vars));
    rows.push(g.final, fill(g.verdict, vars));
    this.log.innerHTML = rows.map((r, i) => `<div class="scan-line${i === rows.length - 1 ? ' verdict' : ''}">${r}</div>`).join('');

    // Spread the lines over the scan, leaving the verdict time to land.
    const span = w.t.gate.duration - 0.9;
    const els = [...this.log.children] as HTMLElement[];
    this.reveal = els.map((el, i) => ({ el, at: 0.15 + (span * i) / (els.length - 1) }));
    this.scanT = 0;
    this.zone.classList.add('hidden');
    this.scan.classList.remove('hidden');
    restartAnimation(this.scan);
  }

  private showZone(zone: number): void {
    const z = content.zones[zoneLook(zone) % content.zones.length];
    this.scan.classList.add('hidden');
    this.scanT = -1;
    this.zone.querySelector('.zone-name')!.textContent = z.name;
    this.zone.querySelector('.zone-tag')!.textContent = z.tagline;
    // The zone's seam colour, squashed out of HDR for CSS.
    const [r, g, b] = z.seam.map((v) => Math.round(Math.min(255, v * 150)));
    this.zone.style.setProperty('--zone', `rgb(${r}, ${g}, ${b})`);
    this.zone.classList.remove('hidden');
    restartAnimation(this.zone);
    this.zoneLeft = ZONE_SHOW;
  }
}
