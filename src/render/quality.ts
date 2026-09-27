// Quality tiers for the iPhone 14 budget. High: glass lane screens that
// reflect the sky and the phone light, full scenery, pixel ratio 2. Medium
// and Low trade those away. Auto (the default) starts High and steps down when
// the frame rate sags during a run, and remembers the tier it settled on.

export type Quality = 'high' | 'medium' | 'low';
export const QUALITIES: readonly Quality[] = ['high', 'medium', 'low'];

export interface QualitySpec {
  pixelRatio: number;
  /** Lane screens as reflective glass (MeshStandard) instead of flat emissive. */
  glass: boolean;
  /** Multiplier on scenery placement chance. */
  scenery: number;
  bloom: boolean;
}

export const SPEC: Record<Quality, QualitySpec> = {
  high: { pixelRatio: 2, glass: true, scenery: 1, bloom: true },
  medium: { pixelRatio: 1.6, glass: false, scenery: 0.6, bloom: true },
  low: { pixelRatio: 1.25, glass: false, scenery: 0.35, bloom: false },
};

const KEY = 'ds.quality';

/** The stored tier, or null for Auto. */
export function loadQuality(): Quality | 'auto' {
  try {
    const q = localStorage.getItem(KEY);
    return q === 'high' || q === 'medium' || q === 'low' ? q : 'auto';
  } catch {
    return 'auto';
  }
}

export function saveQuality(q: Quality | 'auto'): void {
  try {
    if (q === 'auto') localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, q);
  } catch {
    // Private mode: the tier just isn't remembered.
  }
}

const AUTO_KEY = 'ds.qualityAuto';

/** Where Auto starts: the tier it settled on last time (High on a first run). */
export function loadAutoStart(): Quality {
  try {
    const q = localStorage.getItem(AUTO_KEY);
    return q === 'medium' || q === 'low' ? q : 'high';
  } catch {
    return 'high';
  }
}

export function saveAutoStart(q: Quality): void {
  try {
    localStorage.setItem(AUTO_KEY, q);
  } catch {
    // Not remembered: Auto starts High again next time.
  }
}

/** Auto: step down after `windows` half-second samples in a row under `floor` fps while running. */
export class AutoQuality {
  private low = 0;
  private settled: Quality;

  constructor(start: Quality, private readonly floor = 52, private readonly windows = 6) {
    this.settled = start;
  }

  get current(): Quality {
    return this.settled;
  }

  /** Feed a half-second fps sample; returns the new tier when it steps down. */
  sample(fps: number, running: boolean): Quality | null {
    if (!running) return null;
    this.low = fps < this.floor ? this.low + 1 : 0;
    if (this.low < this.windows) return null;
    this.low = 0;
    const i = QUALITIES.indexOf(this.settled);
    if (i >= QUALITIES.length - 1) return null;
    this.settled = QUALITIES[i + 1];
    return this.settled;
  }
}
