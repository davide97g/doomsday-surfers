// Haptics via Capacitor on device; silently does nothing in a browser.
// Like audio, it reacts to SimEvents and reads sim state, never mutates.

import { Capacitor } from '@capacitor/core';
import { Haptics as H, ImpactStyle, NotificationType } from '@capacitor/haptics';
import type { SimEvent } from '../sim/types';
import type { World } from '../sim/world';

const PICKUP_GAP = 0.08; // seconds between pickup ticks, so lines don't buzz constantly
const LOW = 25; // dopamine % where the heartbeat starts

export class GameHaptics {
  private readonly on = Capacitor.isNativePlatform();
  private sincePickup = 1;
  private beatIn = 0;

  handle(events: readonly SimEvent[]): void {
    if (!this.on) return;
    for (const e of events) {
      switch (e.type) {
        case 'lane':
          void H.selectionChanged();
          break;
        case 'pickup':
          if (this.sincePickup >= PICKUP_GAP) {
            this.sincePickup = 0;
            void H.impact({ style: ImpactStyle.Light });
          }
          break;
        case 'habit':
          void H.impact({ style: ImpactStyle.Medium });
          break;
        case 'crash':
          void H.impact({ style: ImpactStyle.Heavy });
          break;
        case 'scroll':
          void H.selectionChanged();
          break;
        case 'thumb':
          if (e.stage === 'warn') void H.impact({ style: ImpactStyle.Light });
          else if (e.stage === 'slam') void H.impact({ style: ImpactStyle.Heavy });
          break;
        case 'stumble':
          void H.impact({ style: ImpactStyle.Medium });
          break;
        case 'boost':
          void H.notification({ type: NotificationType.Success });
          break;
        case 'smash':
          void H.impact({ style: ImpactStyle.Medium });
          break;
        case 'empty':
          void H.notification({ type: NotificationType.Error });
          break;
        case 'gate':
          void H.impact({ style: ImpactStyle.Heavy });
          break;
        case 'gateEnd':
          void H.notification({ type: NotificationType.Success });
          break;
        case 'pad':
          void H.impact({ style: e.kind === 'autoplay' ? ImpactStyle.Light : ImpactStyle.Heavy });
          break;
        case 'lift':
          void H.impact({ style: ImpactStyle.Light });
          break;
        case 'thrill':
          void H.notification({ type: NotificationType.Success });
          break;
        case 'revive':
          void H.notification({ type: NotificationType.Success });
          break;
        default:
          break;
      }
    }
  }

  update(w: World, dt: number): void {
    if (!this.on) return;
    this.sincePickup += dt;
    const pct = (w.dopamine / w.t.dopamine.max) * 100;
    if (w.phase !== 'running' || pct > LOW) {
      this.beatIn = 0;
      return;
    }
    // Heartbeat, faster as you run dry.
    this.beatIn -= dt;
    if (this.beatIn <= 0) {
      this.beatIn = 60 / (70 + (LOW - pct) * 2.4);
      void H.impact({ style: ImpactStyle.Light });
      setTimeout(() => void H.impact({ style: ImpactStyle.Medium }), 150);
    }
  }

  /** Fake push notification: the double buzz of a real one. */
  buzz(): void {
    if (!this.on) return;
    void H.notification({ type: NotificationType.Warning });
  }
}
