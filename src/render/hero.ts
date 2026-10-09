// A doomscroller hero asset (built by assets/blender/human.py; see
// docs/assets-v2.md). Picks and crossfades its animation clips from sim
// state; the renderer still owns position, lean and the crash faceplant.
// Older models without the v2 clips fall back to the closest one they have.

import * as THREE from 'three';
import type { World } from '../sim/world';
import { loadGltf } from './assets';

export type Clip = 'idle' | 'run' | 'jump' | 'roll' | 'present' | 'fall' | 'land' | 'grind' | 'fly' | 'stumble' | 'kicks';

/** One-shot clips (hold their last frame). */
const ONCE: ReadonlySet<string> = new Set(['jump', 'roll', 'present', 'land', 'stumble', 'kicks']);
/** What to play when a model doesn't have a clip. */
const FALLBACK: Partial<Record<Clip, Clip>> = { fall: 'jump', land: 'run', grind: 'run', fly: 'jump', stumble: 'run', kicks: 'jump' };

const FADE = 0.12;
// The run clip is one stride pair (16 frames at 30 fps). Match the old
// procedural cadence: 6 + 0.32 * speed radians per second.
const RUN_CLIP_SECONDS = 16 / 30;

export class Hero {
  readonly root: THREE.Object3D;
  private readonly mixer: THREE.AnimationMixer;
  private readonly actions = new Map<Clip, THREE.AnimationAction>();
  /** Every glowing screen (Screen, ScreenAlt, …) and its built-in glow. */
  private readonly screens: { mat: THREE.MeshStandardMaterial; glow: number }[] = [];
  /** Shoe materials (Delulu Kicks make them glow). */
  private readonly shoes: THREE.MeshStandardMaterial[] = [];
  private current: Clip | null = null;
  private wasGrounded = true;
  private landT = 0;
  /** Named bones and nodes (attachments: the jetpack, the phone light). */
  readonly nodes = new Map<string, THREE.Object3D>();

  private constructor(gltf: { scene: THREE.Object3D; animations: THREE.AnimationClip[] }) {
    this.root = gltf.scene;
    this.mixer = new THREE.AnimationMixer(this.root);
    for (const clip of gltf.animations) {
      const action = this.mixer.clipAction(clip);
      if (ONCE.has(clip.name)) {
        action.setLoop(THREE.LoopOnce, 1);
        action.clampWhenFinished = true;
      }
      this.actions.set(clip.name as Clip, action);
    }
    this.root.traverse((o) => {
      if (o.name) this.nodes.set(o.name, o);
      const mesh = o as THREE.SkinnedMesh;
      if (!mesh.isMesh) return;
      mesh.frustumCulled = false;
      const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
      for (const m of mats as THREE.MeshStandardMaterial[]) {
        if (m.name.startsWith('Screen') && !this.screens.some((s) => s.mat === m)) this.screens.push({ mat: m, glow: m.emissiveIntensity });
        if (m.name.startsWith('Shoes') && !this.shoes.includes(m)) this.shoes.push(m);
        // A little self-light so the hoodie reads against the dark feed.
        if (m.name === 'Hoodie' || m.name === 'HoodieDark') {
          m.emissive = m.color.clone().multiplyScalar(0.15);
        }
      }
    });
    this.play('idle', 0);
  }

  /** `path` under public/, e.g. assets/characters/goblin.glb. */
  static load(path: string): Promise<Hero> {
    return loadGltf(path).then((gltf) => new Hero(gltf));
  }

  /** Delulu Kicks: light up the shoes (0 = off). False if this model has no Shoes material. */
  shoeGlow(k: number): boolean {
    for (const m of this.shoes) {
      if (!m.userData.baseEmissive) m.userData.baseEmissive = { c: m.emissive.clone(), i: m.emissiveIntensity };
      const base = m.userData.baseEmissive as { c: THREE.Color; i: number };
      if (k > 0) {
        m.emissive.set('#7dff5a');
        m.emissiveIntensity = 2.5 * k;
      } else {
        m.emissive.copy(base.c);
        m.emissiveIntensity = base.i;
      }
    }
    return this.shoes.length > 0;
  }

  update(w: World, dt: number): void {
    const p = w.player;
    // Touchdown: a short knee absorb before running on.
    if (p.grounded && !this.wasGrounded) this.landT = this.actions.has('land') ? 0.2 : 0;
    this.wasGrounded = p.grounded;
    this.landT = Math.max(0, this.landT - dt);
    let clip: Clip;
    if (w.phase === 'ready') clip = 'idle';
    else if (w.cause === 'empty') clip = 'present';
    else if (w.flying) clip = 'fly';
    else if (p.rollT > 0) clip = 'roll';
    else if (p.stumbleT > 0) clip = 'stumble';
    else if (!p.grounded) clip = w.power.kicks > 0 && p.vy > 0 ? 'kicks' : p.vy < -6 && w.airT > 0.6 ? 'fall' : 'jump';
    else if (p.on === 'rail') clip = 'grind';
    else if (this.landT > 0) clip = 'land';
    else clip = 'run';

    const run = this.actions.get('run');
    if (run) {
      const cadence = (6 + 0.32 * w.runSpeed) / (Math.PI * 2);
      run.timeScale = w.cause === 'crash' ? 0 : cadence * (run.getClip().duration || RUN_CLIP_SECONDS);
    }
    // Stop mid-stride as the fade to grey brings the run to a halt.
    this.play(clip, FADE);

    const present = w.cause === 'empty' ? Math.min(1, w.fadeT / w.t.reality.fadeTime) : 0;
    for (const s of this.screens) s.mat.emissiveIntensity = s.glow * (1 - 0.97 * present);
    this.mixer.update(dt);
  }

  /** Drive the hero without a World (a challenge ghost): a clip and a speed for the run cadence. */
  animate(clip: Clip, speed: number, dt: number): void {
    const run = this.actions.get('run');
    if (run) run.timeScale = ((6 + 0.32 * speed) / (Math.PI * 2)) * (run.getClip().duration || RUN_CLIP_SECONDS);
    this.play(clip, FADE);
    this.mixer.update(dt);
  }

  /** Every mesh wears `mat` (the ghost's hologram). */
  dress(mat: THREE.Material): void {
    this.screens.length = 0;
    this.root.traverse((o) => {
      const mesh = o as THREE.Mesh;
      if (mesh.isMesh) mesh.material = mat;
    });
  }

  private play(want: Clip, fade: number): void {
    const clip = this.actions.has(want) ? want : (FALLBACK[want] ?? 'run');
    if (clip === this.current) return;
    const next = this.actions.get(clip);
    if (!next) return;
    const prev = this.current ? this.actions.get(this.current) : undefined;
    next.reset().play();
    if (prev) next.crossFadeFrom(prev, fade, false);
    this.current = clip;
  }
}
