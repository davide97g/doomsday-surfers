// Pure simulation types. No rendering imports here: this layer is meant to be
// portable (e.g. to a future Godot port) and testable headless.

import tuningJson from '../config/tuning.json';

export type Tuning = typeof tuningJson;
export const TUNING: Tuning = tuningJson;

export type Action = 'left' | 'right' | 'up' | 'down' | 'tap';

export type Phase = 'ready' | 'running' | 'dead';

export type ObstacleKind = 'low' | 'high' | 'post' | 'movingPost';

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
  /** Visual variant index, chosen by the generator so renders are deterministic. */
  variant: number;
}

export interface Pickup {
  id: number;
  lane: number;
  s: number;
  y: number;
  taken: boolean;
  variant: number;
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
  | { type: 'pickup'; id: number }
  | { type: 'crash'; kind: ObstacleKind };

export function laneX(lane: number, t: Tuning = TUNING): number {
  return (lane - (t.lanes.count - 1) / 2) * t.lanes.width;
}
