// Pure simulation types. No rendering imports here: this layer is meant to be
// portable (e.g. to a future Godot port) and testable headless.

import tuningJson from '../config/tuning.json';

export type Tuning = typeof tuningJson;
export const TUNING: Tuning = tuningJson;

export type Action = 'left' | 'right' | 'up' | 'down' | 'tap';

/** `fading` is the slow-down into grey reality between losing and the death screen. */
export type Phase = 'ready' | 'running' | 'fading' | 'dead';

export type DeathCause = 'empty' | 'crash';

/** `habit` is a healthy habit: it drains dopamine and slows you, but never kills. */
export type ObstacleKind = 'low' | 'high' | 'post' | 'movingPost' | 'habit';

export interface Obstacle {
  id: number;
  kind: ObstacleKind;
  lane: number;
  /** Track distance of the obstacle's near edge (the edge the player meets first). */
  s: number;
  /** Extent along the track (0-ish for thin barriers). */
  length: number;
  /** Speed toward the player once active (m/s). 0 for static obstacles. */
  speed: number;
  active: boolean;
  /** Visual variant index, chosen by the generator so renders are deterministic.
   *  For habits it is the habit type (index into the content bank). */
  variant: number;
  /** Habits only: already walked into (they don't respawn). */
  hit: boolean;
}

export interface Pickup {
  id: number;
  lane: number;
  s: number;
  y: number;
  taken: boolean;
  /** Content type (like, notification, reel, outrage); each has its own tolerance. */
  type: number;
}

export interface PlayerState {
  lane: number;
  prevLane: number;
  x: number;
  y: number;
  vy: number;
  grounded: boolean;
  rollT: number;
  rollQueued: boolean;
  stumbleT: number;
}

export type SimEvent =
  | { type: 'start' }
  | { type: 'jump' }
  | { type: 'land' }
  | { type: 'roll' }
  | { type: 'lane'; dir: -1 | 1 }
  | { type: 'edge'; dir: -1 | 1 }
  | { type: 'stumble' }
  | { type: 'pickup'; id: number; content: number; gain: number; tolerance: number }
  | { type: 'habit'; id: number; habit: number; cost: number }
  | { type: 'crash'; kind: ObstacleKind }
  | { type: 'empty' }
  | { type: 'dead'; cause: DeathCause };

export function laneX(lane: number, t: Tuning = TUNING): number {
  return (lane - (t.lanes.count - 1) / 2) * t.lanes.width;
}
