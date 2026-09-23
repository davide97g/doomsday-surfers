// Touch + keyboard input -> sim actions.
// Swipes fire as soon as the finger passes the threshold (not on release),
// which is what makes runners feel responsive.

import type { Action } from '../sim/types';

const SWIPE_PX = 26;

export class Input {
  private queue: Action[] = [];
  private startX = 0;
  private startY = 0;
  private tracking = false;
  private consumed = false;
  private pointerId = -1;

  constructor(target: HTMLElement) {
    target.addEventListener('pointerdown', this.onDown, { passive: false });
    window.addEventListener('pointermove', this.onMove, { passive: false });
    window.addEventListener('pointerup', this.onUp);
    window.addEventListener('pointercancel', this.onUp);
    window.addEventListener('keydown', this.onKey);
    // iOS: block rubber-band scrolling and double-tap zoom.
    document.addEventListener('touchmove', (e) => e.preventDefault(), { passive: false });
    document.addEventListener('gesturestart', (e) => e.preventDefault());
  }

  drain(): Action[] {
    const q = this.queue;
    this.queue = [];
    return q;
  }

  push(a: Action): void {
    this.queue.push(a);
  }

  private isUi(e: Event): boolean {
    const el = e.target as HTMLElement | null;
    return !!el?.closest?.('[data-ui]');
  }

  private onDown = (e: PointerEvent): void => {
    if (this.isUi(e)) return;
    e.preventDefault();
    this.tracking = true;
    this.consumed = false;
    this.pointerId = e.pointerId;
    this.startX = e.clientX;
    this.startY = e.clientY;
  };

  private onMove = (e: PointerEvent): void => {
    if (!this.tracking || this.consumed || e.pointerId !== this.pointerId) return;
    const dx = e.clientX - this.startX;
    const dy = e.clientY - this.startY;
    if (Math.max(Math.abs(dx), Math.abs(dy)) < SWIPE_PX) return;
    this.consumed = true;
    if (Math.abs(dx) > Math.abs(dy)) this.queue.push(dx < 0 ? 'left' : 'right');
    else this.queue.push(dy < 0 ? 'up' : 'down');
  };

  private onUp = (e: PointerEvent): void => {
    if (!this.tracking || e.pointerId !== this.pointerId) return;
    if (!this.consumed) this.queue.push('tap');
    this.tracking = false;
  };

  private onKey = (e: KeyboardEvent): void => {
    if (e.repeat) return;
    const map: Record<string, Action> = {
      ArrowLeft: 'left',
      KeyA: 'left',
      ArrowRight: 'right',
      KeyD: 'right',
      ArrowUp: 'up',
      KeyW: 'up',
      ArrowDown: 'down',
      KeyS: 'down',
      Space: 'tap',
      Enter: 'tap',
    };
    const a = map[e.code];
    if (a) {
      e.preventDefault();
      this.queue.push(a);
    }
  };
}
