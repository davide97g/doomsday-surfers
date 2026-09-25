// On-screen bits of the set pieces (sim/setpiece.ts): the Algorithm zone's
// badge (watching you: content +50%, or it lost interest after a habit) and
// the vignette that closes in while reality leaks into the track. Also the
// doomscroll combo ("SCROLL SPEED ×3"), which pops with every flick.

import { content } from '../content/content';
import { fill } from '../content/templates';
import type { World } from '../sim/world';

export class SetPieceUi {
  private readonly badge: HTMLElement;
  private readonly vignette: HTMLElement;
  private shown: 'watching' | 'sulking' | null = null;
  private readonly combo: HTMLElement;
  private comboShown = 0;

  constructor(parent: HTMLElement) {
    this.badge = document.createElement('div');
    this.badge.className = 'algo-badge hidden';
    this.vignette = document.createElement('div');
    this.vignette.className = 'reality-vignette';
    this.combo = document.createElement('div');
    this.combo.className = 'scroll-combo hidden';
    parent.append(this.vignette, this.badge, this.combo);
  }

  update(w: World): void {
    const state = w.setPiece === 'algorithm' && w.phase === 'running' && w.gateT < 0 ? (w.watching ? 'watching' : 'sulking') : null;
    if (state !== this.shown) {
      this.shown = state;
      this.badge.classList.toggle('hidden', !state);
      this.badge.classList.toggle('sulking', state === 'sulking');
      if (state) this.badge.textContent = content.setPieces.algorithm[state];
    }
    const combo = w.phase === 'running' ? w.combo : 0;
    if (combo !== this.comboShown) {
      this.comboShown = combo;
      this.combo.classList.toggle('hidden', combo < 2);
      if (combo >= 2) {
        this.combo.textContent = fill(content.scroll.combo, { n: combo });
        this.combo.style.setProperty('--heat', String((combo - 2) / (w.t.scroll.maxCombo - 2)));
        this.combo.classList.remove('pop');
        void this.combo.offsetWidth;
        this.combo.classList.add('pop');
      }
    }
    const below = w.t.setPieces.reality.below;
    const k = w.phase === 'running' && w.dopamine < below ? (below - w.dopamine) / below : 0;
    this.vignette.style.opacity = String(Math.min(1, 0.35 + k) * (k > 0 ? 1 : 0));
  }
}
