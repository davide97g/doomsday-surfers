// Power-ups: the pickups on the track (each with a light beam so you can read
// it from far off) and what you wear while one is on: the Screen Protector's
// glass bubble, the For You Magnet's ring, the Going Viral jetpack, the Main
// Character halo and spotlight, and glowing Delulu Kicks. Kit models
// (`power_*`, `att_jetpack` in kits/common.glb) replace the stand-ins when loaded.

import * as THREE from 'three';
import { POWER_KINDS, laneX, type PowerKind } from '../sim/types';
import type { World } from '../sim/world';
import type { Kit } from './assets';
import type { Bend } from './bend';
import type { Particles } from './particles';

export const POWER_COLOURS: Record<PowerKind, string> = {
  protector: '#8ff0ff',
  magnet: '#ff2e88',
  viral: '#ffb300',
  mainchar: '#ffd54a',
  kicks: '#7dff5a',
};

const glowMat = (hex: string, k = 2.2, extra: THREE.MeshBasicMaterialParameters = {}) =>
  new THREE.MeshBasicMaterial({ color: new THREE.Color(hex).multiplyScalar(k), ...extra });

/** Fresnel glass: bright at the rim, clear in the middle (additive). */
function fresnelMaterial(hex: string): THREE.ShaderMaterial {
  return new THREE.ShaderMaterial({
    uniforms: { colour: { value: new THREE.Color(hex).multiplyScalar(0.75) }, strength: { value: 1 }, time: { value: 0 } },
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    vertexShader: /* glsl */ `
      varying vec3 vN;
      varying vec3 vV;
      varying vec3 vP;
      void main() {
        vec4 mv = modelViewMatrix * vec4(position, 1.0);
        vN = normalize(normalMatrix * normal);
        vV = normalize(-mv.xyz);
        vP = position;
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: /* glsl */ `
      uniform vec3 colour;
      uniform float strength;
      uniform float time;
      varying vec3 vN;
      varying vec3 vV;
      varying vec3 vP;
      void main() {
        float f = pow(1.0 - abs(dot(vN, vV)), 3.2);
        // Faint hex grid, like tempered glass catching the light.
        vec2 g = abs(fract(vP.xy * 3.0 + vec2(0.0, time * 0.2)) - 0.5);
        float grid = smoothstep(0.47, 0.5, max(g.x, g.y)) * 0.08;
        gl_FragColor = vec4(colour * (f + grid) * strength, 1.0);
      }`,
  });
}

/** Stand-in models for the track pickups, about 1 m across. */
function standIn(kind: PowerKind): THREE.Object3D {
  const g = new THREE.Group();
  const c = POWER_COLOURS[kind];
  const shiny = new THREE.MeshStandardMaterial({ color: c, roughness: 0.25, metalness: 0.6, emissive: new THREE.Color(c), emissiveIntensity: 0.6 });
  switch (kind) {
    case 'protector': {
      const glass = new THREE.MeshStandardMaterial({ color: '#dff9ff', roughness: 0.05, metalness: 0.2, transparent: true, opacity: 0.45, emissive: new THREE.Color('#8ff0ff'), emissiveIntensity: 0.5 });
      const pane = new THREE.Mesh(new THREE.BoxGeometry(0.6, 1.0, 0.04), glass);
      const edge = new THREE.Mesh(new THREE.BoxGeometry(0.64, 1.04, 0.02), glowMat(c, 1.6, { wireframe: true }));
      g.add(pane, edge);
      break;
    }
    case 'magnet': {
      const arc = new THREE.Mesh(new THREE.TorusGeometry(0.34, 0.11, 10, 24, Math.PI), shiny);
      arc.rotation.z = Math.PI;
      const tipMat = new THREE.MeshStandardMaterial({ color: '#e8e8f0', roughness: 0.3, metalness: 0.9 });
      for (const sx of [-1, 1]) {
        const tip = new THREE.Mesh(new THREE.BoxGeometry(0.22, 0.22, 0.22), tipMat);
        tip.position.set(sx * 0.34, 0.11, 0);
        g.add(tip);
      }
      g.add(arc);
      break;
    }
    case 'viral': {
      const can = new THREE.CylinderGeometry(0.14, 0.14, 0.62, 16);
      for (const sx of [-1, 1]) {
        const body = new THREE.Mesh(can, shiny);
        body.position.x = sx * 0.17;
        const nose = new THREE.Mesh(new THREE.ConeGeometry(0.14, 0.24, 16), shiny);
        nose.position.set(sx * 0.17, 0.43, 0);
        const flame = new THREE.Mesh(new THREE.ConeGeometry(0.1, 0.3, 12).rotateX(Math.PI), glowMat('#ff7a1f', 2.6));
        flame.position.set(sx * 0.17, -0.46, 0);
        g.add(body, nose, flame);
      }
      break;
    }
    case 'mainchar': {
      const ring = new THREE.Mesh(new THREE.TorusGeometry(0.4, 0.07, 12, 40), shiny);
      const light = new THREE.Mesh(new THREE.TorusGeometry(0.4, 0.035, 8, 40), glowMat('#fff3c0', 2.4));
      light.position.z = 0.05;
      g.add(ring, light);
      break;
    }
    case 'kicks': {
      const sole = new THREE.Mesh(new THREE.BoxGeometry(0.34, 0.14, 0.8), new THREE.MeshStandardMaterial({ color: '#ffffff', roughness: 0.6 }));
      const upper = new THREE.Mesh(new THREE.BoxGeometry(0.32, 0.3, 0.5), shiny);
      upper.position.set(0, 0.2, 0.08);
      const toe = new THREE.Mesh(new THREE.SphereGeometry(0.16, 12, 8), shiny);
      toe.scale.set(1, 0.7, 1.2);
      toe.position.set(0, 0.12, -0.26);
      g.add(sole, upper, toe);
      g.rotation.y = 0.6;
      break;
    }
  }
  return g;
}

interface Pickup {
  kind: PowerKind;
  obj: THREE.Object3D;
  spin: THREE.Object3D;
}

export class PowerView {
  private readonly pool = new Map<PowerKind, Pickup[]>();
  private readonly active = new Map<number, Pickup>();
  private kit: Kit | null = null;
  private readonly beamGeo = new THREE.CylinderGeometry(0.25, 0.55, 9, 16, 1, true).translate(0, 4.5, 0);
  private readonly beamMats = new Map<PowerKind, THREE.MeshBasicMaterial>();

  // Worn effects (children of the unbent player group).
  private readonly bubble: THREE.Mesh;
  private readonly bubbleMat: THREE.ShaderMaterial;
  private readonly jetpack = new THREE.Group();
  private jetpackModel: THREE.Object3D;
  private readonly flames: THREE.Mesh[] = [];
  private readonly halo: THREE.Mesh;
  private readonly spot: THREE.Mesh;
  private readonly magnetRing: THREE.Group;
  private readonly kicksGlow: THREE.Mesh;
  private shieldFlash = 0;
  private jetT = 0;

  constructor(
    private readonly scene: THREE.Scene,
    private readonly bend: Bend,
    player: THREE.Object3D,
    private readonly fx: Particles,
    private readonly visibleAhead: number,
  ) {
    for (const k of POWER_KINDS) {
      this.beamMats.set(k, new THREE.MeshBasicMaterial({ color: new THREE.Color(POWER_COLOURS[k]).multiplyScalar(0.55), transparent: true, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide }));
    }
    this.bubbleMat = fresnelMaterial(POWER_COLOURS.protector);
    this.bubble = new THREE.Mesh(new THREE.SphereGeometry(1.15, 32, 20), this.bubbleMat);
    this.bubble.scale.set(0.9, 1.05, 0.9);
    this.bubble.position.y = 0.95;
    this.bubble.visible = false;
    this.bubble.renderOrder = 5;

    this.jetpackModel = this.standInJetpack();
    this.jetpack.add(this.jetpackModel);
    this.jetpack.position.set(0, 1.15, 0.26);
    this.jetpack.visible = false;

    const gold = POWER_COLOURS.mainchar;
    this.halo = new THREE.Mesh(new THREE.TorusGeometry(0.26, 0.03, 8, 32).rotateX(Math.PI / 2), glowMat(gold, 2.6));
    this.halo.position.y = 2.05;
    this.halo.visible = false;
    this.spot = new THREE.Mesh(
      new THREE.CylinderGeometry(0.35, 1.3, 6, 24, 1, true).translate(0, 3, 0),
      new THREE.MeshBasicMaterial({ color: new THREE.Color(gold).multiplyScalar(0.25), transparent: true, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide }),
    );
    this.spot.visible = false;

    this.magnetRing = new THREE.Group();
    const dash = new THREE.BoxGeometry(0.22, 0.05, 0.05);
    const mm = glowMat(POWER_COLOURS.magnet, 2.4);
    for (let i = 0; i < 10; i++) {
      const a = (i / 10) * Math.PI * 2;
      const b = new THREE.Mesh(dash, mm);
      b.position.set(Math.cos(a) * 0.85, 0, Math.sin(a) * 0.85);
      b.rotation.y = -a;
      this.magnetRing.add(b);
    }
    this.magnetRing.position.y = 1.0;
    this.magnetRing.visible = false;

    this.kicksGlow = new THREE.Mesh(
      new THREE.CircleGeometry(0.55, 24).rotateX(-Math.PI / 2),
      new THREE.MeshBasicMaterial({ color: new THREE.Color(POWER_COLOURS.kicks).multiplyScalar(1.4), transparent: true, opacity: 0.8, blending: THREE.AdditiveBlending, depthWrite: false }),
    );
    this.kicksGlow.position.y = 0.03;
    this.kicksGlow.visible = false;
    player.add(this.bubble, this.jetpack, this.halo, this.spot, this.magnetRing, this.kicksGlow);
  }

  /** Swap in the kit's models (pools rebuild as pickups come and go). */
  useKit(kit: Kit): void {
    this.kit = kit;
    for (const list of this.pool.values()) for (const p of list) this.scene.remove(p.obj);
    this.pool.clear();
    const jet = kit.clone('att_jetpack');
    if (jet) {
      this.jetpack.remove(this.jetpackModel);
      this.jetpackModel = jet;
      this.jetpack.add(jet);
    }
  }

  /** The Screen Protector just took a hit. */
  shatter(x: number, y: number): void {
    this.shieldFlash = 1;
    this.fx.burst(x, y + 1, -0.3, 60, '#dff9ff', { speed: 7, size: 0.14, life: 0.9, gravity: 12, bright: 2.4, up: 2.5 });
  }

  private build(kind: PowerKind): Pickup {
    const obj = new THREE.Group();
    const spin = new THREE.Group();
    const model = this.kit?.clone(`power_${kind}`) ?? standIn(kind);
    spin.add(model);
    const beam = new THREE.Mesh(this.beamGeo, this.beamMats.get(kind)!);
    const base = new THREE.Mesh(new THREE.RingGeometry(0.5, 0.62, 32).rotateX(-Math.PI / 2), glowMat(POWER_COLOURS[kind], 2));
    base.position.y = 0.03;
    obj.add(spin, beam, base);
    this.bend.patchTree(obj);
    this.scene.add(obj);
    return { kind, obj, spin };
  }

  update(w: World, dt: number, time: number, hasShoeGlow: (k: number) => boolean): void {
    // Track pickups.
    const seen = new Set<number>();
    for (const pu of w.powerUps) {
      if (pu.taken || pu.s - w.d > this.visibleAhead) continue;
      seen.add(pu.id);
      let p = this.active.get(pu.id);
      if (!p) {
        p = this.pool.get(pu.kind)?.pop() ?? this.build(pu.kind);
        p.obj.visible = true;
        this.active.set(pu.id, p);
      }
      p.obj.position.set(laneX(pu.lane), pu.y - 0.9, -(pu.s - w.d));
      p.spin.position.y = 0.9 + Math.sin(time * 3 + pu.s) * 0.12;
      p.spin.rotation.y = time * 2.2;
    }
    for (const [id, p] of this.active) {
      if (seen.has(id)) continue;
      p.obj.visible = false;
      const list = this.pool.get(p.kind) ?? [];
      list.push(p);
      this.pool.set(p.kind, list);
      this.active.delete(id);
    }

    // What you're wearing.
    const pw = w.power;
    const t = w.t.power;
    const ending = (left: number) => (left > 2 ? 1 : Math.floor(time * 8) % 2 === 0 ? 1 : 0.3);
    this.bubble.visible = pw.protector > 0 || this.shieldFlash > 0.02;
    this.bubbleMat.uniforms.time.value = time;
    this.bubbleMat.uniforms.strength.value = pw.protector > 0 ? ending(pw.protector) : this.shieldFlash * 3;
    this.shieldFlash = Math.max(0, this.shieldFlash - dt * 3);

    this.magnetRing.visible = pw.magnet > 0;
    if (this.magnetRing.visible) {
      this.magnetRing.rotation.y += dt * 5;
      this.magnetRing.scale.setScalar(1 + 0.08 * Math.sin(time * 9));
      this.magnetRing.visible = ending(pw.magnet) > 0.5;
    }

    this.halo.visible = this.spot.visible = pw.mainchar > 0 && ending(pw.mainchar) > 0.5;
    this.halo.rotation.y += dt * 1.5;

    const kicks = pw.kicks > 0;
    this.kicksGlow.visible = kicks && !hasShoeGlow(kicks ? ending(pw.kicks) : 0) && ending(pw.kicks) > 0.5;
    if (kicks && w.player.grounded && Math.random() < dt * 30) this.fx.burst(w.player.x + (Math.random() - 0.5) * 0.3, 0.1, 0.3, 1, POWER_COLOURS.kicks, { speed: 0.6, size: 0.14, life: 0.4, gravity: 0, bright: 1.6, up: 0.3 });
    if (!kicks) hasShoeGlow(0);

    // Going Viral: the jetpack roars.
    this.jetpack.visible = w.flying;
    if (w.flying) {
      this.jetT += dt;
      const flick = 0.8 + 0.4 * Math.random();
      for (const f of this.flames) f.scale.set(1, flick, 1);
      if (Math.random() < dt * 60) this.fx.burst(w.player.x + (Math.random() < 0.5 ? -0.18 : 0.18), w.player.y + 0.75, 0.45, 1, Math.random() < 0.5 ? '#ffb300' : '#ff5a1f', { speed: 2, size: 0.3, life: 0.35, gravity: -2, bright: 2.6, up: -1.5 });
    } else this.jetT = 0;
    void t;
  }

  private standInJetpack(): THREE.Object3D {
    const g = new THREE.Group();
    const metal = new THREE.MeshStandardMaterial({ color: '#d9d4e6', roughness: 0.25, metalness: 0.85 });
    const accent = new THREE.MeshStandardMaterial({ color: POWER_COLOURS.viral, roughness: 0.3, metalness: 0.5, emissive: new THREE.Color(POWER_COLOURS.viral), emissiveIntensity: 0.4 });
    for (const sx of [-1, 1]) {
      const can = new THREE.Mesh(new THREE.CylinderGeometry(0.1, 0.11, 0.5, 16), metal);
      can.position.x = sx * 0.13;
      const cap = new THREE.Mesh(new THREE.ConeGeometry(0.1, 0.16, 16), accent);
      cap.position.set(sx * 0.13, 0.33, 0);
      const nozzle = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.09, 0.1, 12), metal);
      nozzle.position.set(sx * 0.13, -0.3, 0);
      const flame = new THREE.Mesh(new THREE.ConeGeometry(0.08, 0.55, 12).rotateX(Math.PI).translate(0, -0.27, 0), glowMat('#ffb300', 3.2, { transparent: true, blending: THREE.AdditiveBlending, depthWrite: false }));
      flame.position.set(sx * 0.13, -0.35, 0);
      this.flames.push(flame);
      g.add(can, cap, nozzle, flame);
    }
    const strap = new THREE.Mesh(new THREE.BoxGeometry(0.44, 0.1, 0.06), accent);
    strap.position.y = 0.1;
    g.add(strap);
    return g;
  }
}
