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
  /** Static posts: length of the stairs up to the roof, in front of `s` (0 = none). */
  ramp: number;
  /** Overhangs: one of three `high`s spanning every lane (drawn as one piece). */
  wide: boolean;
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
  /** Sim time the For You Magnet grabbed it (it flies to you), -1 if not pulled. */
  pullAt: number;
}

/** Power-ups on the track: Screen Protector (absorbs a crash), For You Magnet
 *  (pulls in content from every lane), Going Viral (a jetpack flight over a sky
 *  line of content), Main Character (score x2) and Delulu Kicks (higher jumps,
 *  high enough for the reel roofs). Each kind lasts a little less every time
 *  you take it (tolerance, like everything else). */
export type PowerKind = 'protector' | 'magnet' | 'viral' | 'mainchar' | 'kicks';
export const POWER_KINDS: readonly PowerKind[] = ['protector', 'magnet', 'viral', 'mainchar', 'kicks'];

export interface PowerUp {
  id: number;
  kind: PowerKind;
  lane: number;
  s: number;
  y: number;
  taken: boolean;
  /** Pre-rolled seed for anything taking it spawns (the viral sky line), so
   *  taking it or not never shifts the rest of the generation. */
  seed: number;
}

/** A grind rail (a giant charger cable) along one lane. Its sloped start runs
 *  up from the track over [s - rail.ramp, s]; full height from s to s + length. */
export interface Rail {
  id: number;
  lane: number;
  s: number;
  length: number;
}

/** A covered stretch of track: a ceiling you can bump your head on. */
export interface Tunnel {
  id: number;
  s: number;
  length: number;
}

/** What the runner is standing on. */
export type Surface = 'ground' | 'stairs' | 'roof' | 'rail';

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
  /** Surface under the runner while grounded. */
  on: Surface;
  /** Height of the highest surface under the runner (for the shadow). */
  floor: number;
  /** Height the runner last left a surface from: a runner who came off a roof
   *  can still catch the next roof's edge (mantle). */
  perch: number;
  /** Seconds left of standing on air after the surface ended. */
  coyoteT: number;
}

export type SimEvent =
  | { type: 'start' }
  | { type: 'jump' }
  | { type: 'land'; on: Surface }
  | { type: 'roll' }
  | { type: 'lane'; dir: -1 | 1 }
  | { type: 'edge'; dir: -1 | 1 }
  | { type: 'stumble' }
  | { type: 'pickup'; id: number; content: number; gain: number; tolerance: number; pulled?: boolean }
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
  | { type: 'scroll'; combo: number; gain: number }
  /** Took a power-up. `duration` is seconds (Going Viral: metres of flight). */
  | { type: 'power'; kind: PowerKind; duration: number; tolerance: number }
  | { type: 'powerEnd'; kind: PowerKind }
  /** The Screen Protector took a crash for you (and broke). */
  | { type: 'shield'; id: number; kind: ObstacleKind; lane: number }
  /** Going Viral: lift-off, the descent starts, touchdown. */
  | { type: 'fly'; stage: 'up' | 'down' | 'land' }
  | { type: 'grind'; on: boolean; lane: number }
  /** Walked off a roof or rail (or it went away under you). */
  | { type: 'fall' }
  /** Came off a roof, fell short and caught the next roof's edge. */
  | { type: 'mantle' }
  /** Hit a tunnel's ceiling. */
  | { type: 'bonk' };

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
