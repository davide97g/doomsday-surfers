// Aura popups (aura farming, Oxford's 2025 shortlist): every clip-worthy thing
// floats "+1,000 AURA" up from the runner, every healthy habit costs aura, and
// a crash is "-∞ AURA". The same weights add up to the receipt's aura line.

import { content } from '../content/content';
import { fill } from '../content/templates';
import { TUNING, type SimEvent } from '../sim/types';

const MAX = 5;

export class AuraPops {
  private readonly layer: HTMLElement;

  constructor(parent: HTMLElement) {
    this.layer = document.createElement('div');
    this.layer.className = 'aura-layer';
    parent.append(this.layer);
  }

  handle(events: readonly SimEvent[]): void {
    const a = TUNING.report.aura;
    for (const e of events) {
      if (e.type === 'thrill') this.pop(a.thrill);
      else if (e.type === 'gate') this.pop(a.gate);
      else if (e.type === 'boost') this.pop(a.opened);
      else if (e.type === 'smash') this.pop(a.smashed);
      else if (e.type === 'habit') this.pop(a.habit);
      else if (e.type === 'crash') this.pop(-Infinity);
      else if (e.type === 'power') this.pop(a.power);
      else if (e.type === 'shield') this.pop(a.shield);
      else if (e.type === 'grind' && !e.on) this.pop(a.grind);
      else if (e.type === 'mantle') this.pop(a.roof);
    }
  }

  private pop(n: number): void {
    const c = content.aura;
    const el = document.createElement('div');
    el.className = `aura-pop ${n > 0 ? 'good' : 'bad'}`;
    el.textContent = n === -Infinity ? c.crash : fill(n > 0 ? c.plus : c.minus, { n: Math.abs(n).toLocaleString('en-US') });
    el.style.setProperty('--dx', `${Math.round((Math.random() - 0.5) * 120)}px`);
    el.addEventListener('animationend', () => el.remove());
    this.layer.append(el);
    while (this.layer.children.length > MAX) this.layer.firstElementChild!.remove();
  }
}
