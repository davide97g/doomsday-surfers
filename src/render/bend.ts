// Bends the straight track onto the rollercoaster course, on the GPU.
//
// Everything in the scene is still placed in "straight space", as if the track
// were a flat line: x lateral, y up, z = -(s - d) with the runner at the origin.
// A patched vertex shader then moves each vertex onto the course: it looks up
// the track frame (position + rotation) at s = d - z and puts (x, y) on that
// frame's cross-section. So a 24 m reel train really follows a curve, loops
// and corkscrews carry everything round, and none of the gameplay code knows.
//
// Frames are relative to the runner's own frame (identity at the runner), so
// numbers stay small far into a run and the runner and camera rig can stay in
// straight space. `map` does the same bend on the CPU for the camera.
//
// Frames live in a small float texture (row 0: position, row 1: quaternion),
// SAMPLES entries every STEP metres from BACK behind the runner, refreshed
// every frame. Past either end the track carries on straight.

import * as THREE from 'three';
import type { Course, CourseSample } from '../sim/course';

const STEP = 0.5;
const BACK = 60;
const SAMPLES = 540; // BACK + 210 m ahead

const GLSL_COMMON = /* glsl */ `
uniform highp sampler2D uBend;
uniform float uBendS0;
vec3 bendRot(vec4 q, vec3 v) {
  vec3 t = 2.0 * cross(q.xyz, v);
  return v + q.w * t + cross(q.xyz, t);
}
void bendAt(float s, out vec3 P, out vec4 Q) {
  float f = (s - uBendS0) * ${(1 / STEP).toFixed(4)};
  float fc = clamp(f, 0.0, ${(SAMPLES - 1.001).toFixed(3)});
  int i0 = int(floor(fc));
  float k = fc - float(i0);
  P = mix(texelFetch(uBend, ivec2(i0, 0), 0).xyz, texelFetch(uBend, ivec2(i0 + 1, 0), 0).xyz, k);
  Q = normalize(mix(texelFetch(uBend, ivec2(i0, 1), 0), texelFetch(uBend, ivec2(i0 + 1, 1), 0), k));
  P += bendRot(Q, vec3(0.0, 0.0, -(f - fc) * ${STEP.toFixed(4)}));
}
`;

const GLSL_PROJECT = /* glsl */ `
vec4 bendPos = vec4(transformed, 1.0);
#ifdef USE_INSTANCING
  bendPos = instanceMatrix * bendPos;
#endif
bendPos = modelMatrix * bendPos;
vec3 bendP;
vec4 bendQ;
bendAt(-bendPos.z, bendP, bendQ);
bendPos.xyz = bendP + bendRot(bendQ, vec3(bendPos.xy, 0.0));
vec4 mvPosition = viewMatrix * bendPos;
gl_Position = projectionMatrix * mvPosition;
#if defined(BEND_NORMALS) && !defined(FLAT_SHADED)
  vNormal = normalize(mat3(viewMatrix) * bendRot(bendQ, transpose(mat3(viewMatrix)) * vNormal));
#endif
`;

export class Bend {
  private readonly data = new Float32Array(SAMPLES * 2 * 4);
  private readonly tex: THREE.DataTexture;
  private readonly uniforms: { uBend: THREE.IUniform<THREE.Texture>; uBendS0: THREE.IUniform<number> };
  /** CPU copies for `map`, in the same layout as the texture. */
  private readonly pos: THREE.Vector3[] = [];
  private readonly rot: THREE.Quaternion[] = [];
  private readonly smp: CourseSample = { x: 0, y: 0, z: 0, yaw: 0, pitch: 0, roll: 0 };
  private readonly euler = new THREE.Euler(0, 0, 0, 'YXZ');
  private readonly origin = new THREE.Vector3();
  private readonly inv = new THREE.Quaternion();
  /** The runner's frame in course space (inverse of `inv`): for world-fixed things like the sky. */
  readonly runner = new THREE.Quaternion();
  private readonly q = new THREE.Quaternion();
  private readonly tmpQ = new THREE.Quaternion();
  private readonly tmpP = new THREE.Vector3();
  private readonly tmpV = new THREE.Vector3();

  constructor() {
    this.tex = new THREE.DataTexture(this.data, SAMPLES, 2, THREE.RGBAFormat, THREE.FloatType);
    this.tex.minFilter = this.tex.magFilter = THREE.NearestFilter;
    this.tex.generateMipmaps = false;
    this.tex.needsUpdate = true;
    this.uniforms = { uBend: { value: this.tex }, uBendS0: { value: -BACK } };
    for (let i = 0; i < SAMPLES; i++) {
      this.pos.push(new THREE.Vector3());
      this.rot.push(new THREE.Quaternion());
    }
  }

  /** Re-sample the course around the runner at distance `d`. */
  update(course: Course, d: number): void {
    const c = course.sample(d, this.smp);
    this.origin.set(c.x, c.y, c.z);
    this.runner.setFromEuler(this.euler.set(c.pitch, c.yaw, c.roll));
    this.inv.copy(this.runner).invert();
    const data = this.data;
    const row = SAMPLES * 4;
    for (let i = 0; i < SAMPLES; i++) {
      const s = course.sample(d - BACK + i * STEP, this.smp);
      const p = this.pos[i].set(s.x, s.y, s.z).sub(this.origin).applyQuaternion(this.inv);
      const q = this.rot[i].setFromEuler(this.euler.set(s.pitch, s.yaw, s.roll)).premultiply(this.inv);
      // Keep neighbours in the same hemisphere so the shader's lerp takes the short way.
      if (i > 0 && q.dot(this.rot[i - 1]) < 0) q.set(-q.x, -q.y, -q.z, -q.w);
      data[i * 4] = p.x;
      data[i * 4 + 1] = p.y;
      data[i * 4 + 2] = p.z;
      data[row + i * 4] = q.x;
      data[row + i * 4 + 1] = q.y;
      data[row + i * 4 + 2] = q.z;
      data[row + i * 4 + 3] = q.w;
    }
    this.tex.needsUpdate = true;
  }

  /** Frame at straight-space depth z (s = d - z): position and rotation. */
  frame(z: number, outP: THREE.Vector3, outQ: THREE.Quaternion): void {
    const f = (-z + BACK) / STEP;
    const fc = Math.min(SAMPLES - 1.001, Math.max(0, f));
    const i = Math.floor(fc);
    const k = fc - i;
    outP.lerpVectors(this.pos[i], this.pos[i + 1], k);
    const a = this.rot[i];
    const b = this.rot[i + 1];
    outQ.set(a.x + (b.x - a.x) * k, a.y + (b.y - a.y) * k, a.z + (b.z - a.z) * k, a.w + (b.w - a.w) * k).normalize();
    outP.add(this.tmpV.set(0, 0, -(f - fc) * STEP).applyQuaternion(outQ));
  }

  /** Bend a straight-space point in place (same as the shader). */
  map(v: THREE.Vector3): THREE.Vector3 {
    this.frame(v.z, this.tmpP, this.tmpQ);
    return v.set(v.x, v.y, 0).applyQuaternion(this.tmpQ).add(this.tmpP);
  }

  /** The track's up direction at straight-space depth z. */
  up(z: number, out: THREE.Vector3): THREE.Vector3 {
    this.frame(z, this.tmpP, this.q);
    return out.set(0, 1, 0).applyQuaternion(this.q);
  }

  /** Make a material bend. Lit materials get their normals bent too. Idempotent. */
  patch(m: THREE.Material): void {
    if (m.userData.bent) return;
    m.userData.bent = true;
    // Default cache key is the onBeforeCompile source: take it before replacing it.
    const key = m.customProgramCacheKey();
    const prev = m.onBeforeCompile.bind(m);
    const lit = (m as THREE.MeshStandardMaterial).isMeshStandardMaterial === true;
    m.onBeforeCompile = (sh, r) => {
      prev(sh, r);
      Object.assign(sh.uniforms, this.uniforms);
      if (lit) sh.defines = { ...sh.defines, BEND_NORMALS: '' };
      sh.vertexShader = sh.vertexShader.replace('#include <common>', `#include <common>\n${GLSL_COMMON}`).replace('#include <project_vertex>', GLSL_PROJECT);
    };
    m.customProgramCacheKey = () => `${key}|bend`;
    m.needsUpdate = true;
  }

  /** Patch every material under `obj` and stop culling it (its bounds are in straight space). */
  patchTree(obj: THREE.Object3D): void {
    obj.traverse((o) => {
      o.frustumCulled = false;
      const mesh = o as THREE.Mesh;
      if (!mesh.material) return;
      for (const m of Array.isArray(mesh.material) ? mesh.material : [mesh.material]) this.patch(m);
    });
  }
}
