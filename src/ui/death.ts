// After the fade to grey:
//   offer  -> "Watch a short ad to feel something again?" (once per run)
//   ad     -> unskippable fake ad, then the sim revives
//   final  -> "You are present. … Disgusting." + the receipt + [PROOF OF DOOM] [SCROLL AGAIN]
// Everything in `final` is revealed on a timer, and the buttons only work once
// they are visible, so a panicked swipe can't skip the moment. The receipt
// feeds up out of a printer slot line by line; drag it to read the top.

import { content } from '../content/content';
import { fill, pick } from '../content/templates';
import { TUNING } from '../sim/types';
import type { World } from '../sim/world';
import type { Nags } from './nags';
import { buildReceipt, drawReceipt, shareCard, type Paper, type Receipt } from './receipt';
import type { Sfx } from './sfx';
import { shareImage } from './share';

type State = 'hidden' | 'offer' | 'ad' | 'final';

const LINE1_AT = 0.4;
const LINE2_AT = 2.0;
const PRINT_AT = 3.0;
/** Vertical room the death lines and buttons need around the printer window (CSS px). */
const CHROME = 300;

export class Death {
  onRevive: () => void = () => {};
  onRestart: () => void = () => {};
  private state: State = 'hidden';
  private readonly offer: HTMLElement;
  private readonly ad: HTMLElement;
  private readonly adCount: HTMLElement;
  private readonly adSkip: HTMLElement;
  private readonly final: HTMLElement;
  private readonly printer: HTMLElement;
  private readonly strip: HTMLElement;
  private reveal: { el: HTMLElement; at: number }[] = [];
  private receipt: Receipt | null = null;
  private paper: Paper | null = null;
  /** CSS px per canvas px of the displayed receipt. */
  private paperScale = 1;
  private windowH = 0;
  private printed = -1;
  /** How far the reader dragged the strip down from its resting place (CSS px). */
  private drag = 0;
  private dragFrom: { y: number; drag: number } | null = null;
  private sharing = false;
  private finalT = 0;
  private adLeft = 0;
  private buttonLive = false;
  private world: World | null = null;
  private nags: Nags | null = null;

  constructor(parent: HTMLElement, private readonly sfx: Sfx) {
    const r = content.revive;
    const d = content.death;
    this.offer = document.createElement('div');
    this.offer.className = 'overlay dead offer hidden';
    this.offer.innerHTML = `
      <div class="prompt-card" data-ui>
        <div class="prompt-title">${r.title}</div>
        <div class="prompt-body">${r.body}</div>
        <button class="cta" data-act="watch">${r.cta}</button>
        <button class="decline" data-act="decline">${r.decline}</button>
      </div>`;
    this.offer.addEventListener('click', (e) => {
      const act = (e.target as HTMLElement).dataset.act;
      this.sfx.click();
      if (act === 'watch') this.show('ad');
      else if (act === 'decline') this.show('final');
    });

    this.ad = document.createElement('div');
    this.ad.className = 'overlay fake-ad hidden';
    this.ad.dataset.ui = '';
    this.ad.innerHTML = `
      <span class="banner-tag">${content.banner.tag}</span>
      <div class="ad-count"></div>
      <div class="ad-product"></div>
      <div class="ad-brand"></div>
      <div class="ad-line"></div>
      <button class="ad-skip">${r.skip}</button>`;
    this.adCount = this.ad.querySelector('.ad-count')!;
    this.adSkip = this.ad.querySelector('.ad-skip')!;
    this.adSkip.addEventListener('click', () => {
      this.sfx.click();
      this.adSkip.textContent = r.skipDenied;
    });

    this.final = document.createElement('div');
    this.final.className = 'overlay dead final hidden';
    this.final.innerHTML = `
      <div class="dead-line" data-at="${LINE1_AT}">${d.line1}</div>
      <div class="dead-line" data-at="${LINE2_AT}">${d.line2}</div>
      <div class="printer" data-at="${PRINT_AT}" data-ui><div class="strip"></div><div class="slot"></div></div>
      <div class="dead-buttons">
        <button class="cta receipt-cta" id="proof" data-ui>${content.report.cta}</button>
        <button class="cta" id="again" data-ui>${d.cta}</button>
      </div>`;
    this.printer = this.final.querySelector('.printer')!;
    this.strip = this.final.querySelector('.strip')!;
    this.final.querySelector('#again')!.addEventListener('click', () => {
      if (!this.buttonLive) return;
      this.sfx.click();
      this.onRestart();
    });
    this.final.querySelector('#proof')!.addEventListener('click', () => {
      if (!this.buttonLive) return;
      this.sfx.click();
      void this.share();
    });
    this.printer.addEventListener('pointerdown', (e) => {
      if (!this.buttonLive) return;
      this.dragFrom = { y: e.clientY, drag: this.drag };
      this.printer.setPointerCapture(e.pointerId);
    });
    this.printer.addEventListener('pointermove', (e) => {
      if (!this.dragFrom) return;
      this.drag = this.dragFrom.drag + e.clientY - this.dragFrom.y;
      this.placeStrip();
    });
    const endDrag = () => (this.dragFrom = null);
    this.printer.addEventListener('pointerup', endDrag);
    this.printer.addEventListener('pointercancel', endDrag);

    parent.append(this.offer, this.ad, this.final);
  }

  update(w: World, dt: number, nags: Nags): void {
    this.world = w;
    this.nags = nags;
    if (w.phase !== 'dead') {
      if (this.state !== 'hidden') this.show('hidden');
      return;
    }
    if (this.state === 'hidden') this.show(w.revivesLeft > 0 ? 'offer' : 'final');
    if (this.state === 'ad') {
      this.adLeft -= dt;
      this.adCount.textContent = fill(content.revive.countdown, { n: Math.max(1, Math.ceil(this.adLeft)) });
      if (this.adLeft <= 0) {
        this.adLeft = Infinity;
        this.sfx.reward();
        this.onRevive();
      }
    }
    if (this.state === 'final') {
      this.finalT += dt;
      for (const r of this.reveal) {
        if (r.at > this.finalT || r.el.classList.contains('on')) continue;
        r.el.classList.add('on');
        if (r.el.classList.contains('dead-buttons')) this.buttonLive = true;
      }
      this.print();
    }
  }

  /** Feeds the strip up one line at a time, ticking like a thermal printer. */
  private print(): void {
    const paper = this.paper;
    if (!paper) return;
    const n = Math.min(paper.stops.length, Math.floor((this.finalT - PRINT_AT) / TUNING.report.printEvery) + 1);
    if (n <= this.printed + 1 || n <= 0) return;
    this.printed = n - 1;
    if (this.printed % 2 === 0) this.sfx.tick();
    this.placeStrip();
  }

  private placeStrip(): void {
    const paper = this.paper;
    if (!paper || this.printed < 0) return;
    const full = paper.canvas.height * this.paperScale;
    const done = this.printed >= paper.stops.length - 1;
    // Printed part sits above the slot; once the whole strip is out, it can be dragged down to read the top.
    const out = done ? full : paper.stops[this.printed] * this.paperScale;
    const maxDrag = Math.max(0, full - this.windowH);
    this.drag = done ? Math.min(maxDrag, Math.max(0, this.drag)) : 0;
    this.strip.style.transform = `translateY(${this.windowH - out + this.drag}px)`;
  }

  private async share(): Promise<void> {
    if (this.sharing || !this.paper || !this.receipt) return;
    this.sharing = true;
    try {
      const r = content.report;
      const blob = await shareCard(this.paper);
      await shareImage(blob, 'proof-of-doom.png', r.shareTitle, fill(r.shareText, { distance: this.receipt.distance, killer: this.receipt.killer.toLowerCase() }));
    } finally {
      this.sharing = false;
    }
  }

  private show(state: State): void {
    if (state === 'final') this.buildReport();
    this.state = state;
    this.offer.classList.toggle('hidden', state !== 'offer');
    this.ad.classList.toggle('hidden', state !== 'ad');
    this.final.classList.toggle('hidden', state !== 'final');
    if (state === 'ad') this.startAd();
    if (state === 'final') {
      this.finalT = 0;
      this.printed = -1;
      this.drag = 0;
      this.dragFrom = null;
      this.buttonLive = false;
      for (const r of this.reveal) r.el.classList.remove('on');
    }
  }

  private startAd(): void {
    const brand = pick(content.brands);
    this.ad.style.setProperty('--ad-bg', brand.bg);
    this.ad.style.setProperty('--ad-fg', brand.fg);
    this.ad.querySelector('.ad-brand')!.textContent = brand.name;
    this.ad.querySelector('.ad-line')!.textContent = brand.line;
    this.adSkip.textContent = content.revive.skip;
    this.adLeft = TUNING.revive.adSeconds;
    this.adCount.textContent = fill(content.revive.countdown, { n: this.adLeft });
    this.sfx.jingle(brand.jingle);
  }

  private buildReport(): void {
    this.receipt = buildReceipt(this.world!, this.nags!);
    const paper = drawReceipt(this.receipt);
    this.paper = paper;
    const cssW = Math.min(320, window.innerWidth * 0.84);
    this.paperScale = cssW / paper.canvas.width;
    const full = paper.canvas.height * this.paperScale;
    this.windowH = Math.max(180, Math.min(full, window.innerHeight - CHROME));
    paper.canvas.style.width = `${cssW}px`;
    paper.canvas.style.height = `${full}px`;
    this.strip.replaceChildren(paper.canvas);
    this.printer.style.width = `${cssW}px`;
    this.printer.style.height = `${this.windowH}px`;
    this.strip.style.transform = `translateY(${this.windowH}px)`;

    this.reveal = [];
    for (const el of this.final.querySelectorAll<HTMLElement>('[data-at]')) {
      this.reveal.push({ el, at: Number(el.dataset.at) });
    }
    const buttons = this.final.querySelector<HTMLElement>('.dead-buttons')!;
    this.reveal.push({ el: buttons, at: PRINT_AT + paper.stops.length * TUNING.report.printEvery + 0.5 });
  }
}
