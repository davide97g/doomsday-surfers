// Pure simulation types. No rendering imports here: this layer is meant to be
// portable (e.g. to a future Godot port) and testable headless.

import tuningJson from '../config/tuning.json';

export type Tuning = typeof tuningJson;
export const TUNING: Tuning = tuningJson;

export type Action = 'left' | 'right' | 'up' | 'down' | 'tap';

/** `fading` is the slow-down into grey reality between losing and the death screen. */
export type Phase = 'ready' | 'running' | 'fading' | 'dead';

export type DeathCause = 'empty' | 'crash';

/** `habit` is a healthy habit: it drains dopamine and slows you, but never kills.
 *  `thumb` is the Thumb set piece: a giant thumb that drops onto a lane and drags down it. */
export type ObstacleKind = 'low' | 'high' | 'post' | 'movingPost' | 'habit' | 'thumb';

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
  /** Already walked into (habits) or smashed during a boost (anything). Never collides again. */
  hit: boolean;
  /** Thumbs: seconds since it started dropping (only counts once `active`). */
  age: number;
}

/** Rideable track toys: a "Swipe up" ramp and a pull-to-refresh bouncer launch
 *  you into the air, an autoplay strip gives a short speed burst. All optional. */
export type PadKind = 'ramp' | 'bouncer' | 'autoplay';

export interface Pad {
  id: number;
  kind: PadKind;
  lane: number;
  s: number;
  length: number;
  used: boolean;
}

/** Rollercoaster moments that give a dopamine hit (with their own shared tolerance). */
export type ThrillKind = 'loop' | 'corkscrew' | 'drop' | 'air';

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
  /** A push notification landed: a small dopamine bump just for looking. */
  | { type: 'notified'; gain: number }
  /** Opened a notification: dopamine (with its own tolerance) plus the super boost. */
  | { type: 'boost'; gain: number; tolerance: number }
  /** Ran through an obstacle while boosting. */
  | { type: 'smash'; id: number; kind: ObstacleKind; lane: number }
  /** Launched by a ramp or bouncer, or hit an autoplay strip. */
  | { type: 'pad'; kind: PadKind; lane: number }
  /** A crest threw you off the track by itself. */
  | { type: 'lift' }
  | { type: 'thrill'; kind: ThrillKind; gain: number; tolerance: number }
  | { type: 'empty' }
  | { type: 'revive' }
  /** Crossed a checkpoint gate: bullet time + scan begin, the feed moves to `zone`. */
  | { type: 'gate'; zone: number }
  | { type: 'gateEnd'; zone: number }
  | { type: 'dead'; cause: DeathCause }
  /** The Thumb: starts dropping onto `lane` (warn), lands and drags (slam), lets go (lift). */
  | { type: 'thumb'; stage: 'warn' | 'slam' | 'lift'; lane: number }
  /** The Algorithm zone's eye turned to you (watching: content +bonus) or away (you hit a habit). */
  | { type: 'algorithm'; watching: boolean }
  /** A doomscroll flick (a quick second swipe up): combo level and the dopamine it gave. */
  | { type: 'scroll'; combo: number; gain: number };

export function laneX(lane: number, t: Tuning = TUNING): number {
  return (lane - (t.lanes.count - 1) / 2) * t.lanes.width;
}

/** Track distance of checkpoint gate `k` (0-based). */
export function gateS(k: number, t: Tuning = TUNING): number {
  return t.gate.first + k * t.gate.every;
}

/** Zone look/content index for a zone count that keeps climbing each gate. */
export function zoneLook(zone: number, t: Tuning = TUNING): number {
  return zone % t.gate.zones;
}
