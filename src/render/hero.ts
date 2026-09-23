// A doomscroller hero asset (built by assets/blender/runner.py). Picks and
// crossfades its animation clips from sim state; the renderer still owns
// position, lean and the crash faceplant.

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import type { World } from '../sim/world';

type Clip = 'idle' | 'run' | 'jump' | 'roll' | 'present';

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
  private current: Clip | null = null;

  private constructor(gltf: { scene: THREE.Object3D; animations: THREE.AnimationClip[] }) {
    this.root = gltf.scene;
    this.mixer = new THREE.AnimationMixer(this.root);
    for (const clip of gltf.animations) {
      const action = this.mixer.clipAction(clip);
      if (clip.name === 'jump' || clip.name === 'roll' || clip.name === 'present') {
        action.setLoop(THREE.LoopOnce, 1);
        action.clampWhenFinished = true;
      }
      this.actions.set(clip.name as Clip, action);
    }
    this.root.traverse((o) => {
      const mesh = o as THREE.SkinnedMesh;
      if (!mesh.isMesh) return;
      mesh.frustumCulled = false;
      const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
      for (const m of mats as THREE.MeshStandardMaterial[]) {
        if (m.name.startsWith('Screen') && !this.screens.some((s) => s.mat === m)) this.screens.push({ mat: m, glow: m.emissiveIntensity });
        // A little self-light so the hoodie reads against the dark feed.
        if (m.name === 'Hoodie' || m.name === 'HoodieDark') {
          m.emissive = m.color.clone().multiplyScalar(0.15);
        }
      }
    });
    this.play('idle', 0);
  }

  static load(url: string): Promise<Hero> {
    return new Promise((resolve, reject) => {
      new GLTFLoader().load(url, (gltf) => resolve(new Hero(gltf)), undefined, reject);
    });
  }

  update(w: World, dt: number): void {
    const p = w.player;
    let clip: Clip;
    if (w.phase === 'ready') clip = 'idle';
    else if (w.cause === 'empty') clip = 'present';
    else if (p.rollT > 0) clip = 'roll';
    else if (!p.grounded) clip = 'jump';
    else clip = 'run';

    const run = this.actions.get('run');
    if (run) {
      const cadence = (6 + 0.32 * w.runSpeed) / (Math.PI * 2);
      run.timeScale = w.cause === 'crash' ? 0 : cadence * RUN_CLIP_SECONDS;
    }
    // Stop mid-stride as the fade to grey brings the run to a halt.
    this.play(clip, FADE);

    const present = w.cause === 'empty' ? Math.min(1, w.fadeT / w.t.reality.fadeTime) : 0;
    for (const s of this.screens) s.mat.emissiveIntensity = s.glow * (1 - 0.97 * present);
    this.mixer.update(dt);
  }

  private play(clip: Clip, fade: number): void {
    if (clip === this.current) return;
    const next = this.actions.get(clip);
    if (!next) return;
    const prev = this.current ? this.actions.get(this.current) : undefined;
    next.reset().play();
    if (prev) next.crossFadeFrom(prev, fade, false);
    this.current = clip;
  }
}
