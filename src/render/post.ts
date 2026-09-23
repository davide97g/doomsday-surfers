// Post-processing: half-res bloom + a colour-grade pass.
// The grade's `dopamine` uniform is the day-2 hook: 1 = oversaturated neon,
// 0 = grey silent reality.

import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { ShaderPass } from 'three/addons/postprocessing/ShaderPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';

const GradeShader = {
  name: 'GradeShader',
  uniforms: {
    tDiffuse: { value: null as THREE.Texture | null },
    dopamine: { value: 1.0 },
    vignette: { value: 0.35 },
    time: { value: 0 },
    shake: { value: 0 },
  },
  vertexShader: /* glsl */ `
    varying vec2 vUv;
    void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }
  `,
  fragmentShader: /* glsl */ `
    uniform sampler2D tDiffuse;
    uniform float dopamine;
    uniform float vignette;
    uniform float time;
    uniform float shake;
    varying vec2 vUv;

    void main() {
      // Chromatic split grows with shake (hits, stumbles).
      vec2 off = vec2(0.004 * shake, 0.0);
      vec3 col;
      col.r = texture2D(tDiffuse, vUv + off).r;
      col.g = texture2D(tDiffuse, vUv).g;
      col.b = texture2D(tDiffuse, vUv - off).b;

      float luma = dot(col, vec3(0.2126, 0.7152, 0.0722));
      float sat = mix(0.0, 1.35, dopamine);
      col = mix(vec3(luma), col, sat);
      // Low dopamine: flatten contrast, cool/grey tint.
      float contrast = mix(0.82, 1.08, dopamine);
      col = (col - 0.5) * contrast + 0.5;
      col = mix(col * vec3(0.92, 0.95, 1.0), col, dopamine);

      vec2 d = vUv - 0.5;
      float v = 1.0 - dot(d, d) * vignette * 2.2;
      col *= v;
      gl_FragColor = vec4(col, 1.0);
    }
  `,
};

export interface PostSettings {
  bloom: boolean;
  grade: boolean;
}

export class Post {
  readonly composer: EffectComposer;
  readonly bloom: UnrealBloomPass;
  readonly grade: ShaderPass;
  settings: PostSettings = { bloom: true, grade: true };
  enabled = true;

  constructor(renderer: THREE.WebGLRenderer, scene: THREE.Scene, camera: THREE.Camera) {
    this.composer = new EffectComposer(renderer);
    this.composer.addPass(new RenderPass(scene, camera));
    this.bloom = new UnrealBloomPass(new THREE.Vector2(256, 256), 0.6, 0.5, 0.82);
    this.composer.addPass(this.bloom);
    this.grade = new ShaderPass(GradeShader);
    this.composer.addPass(this.grade);
    this.composer.addPass(new OutputPass());
  }

  setSize(w: number, h: number, pixelRatio: number): void {
    this.composer.setPixelRatio(pixelRatio);
    // UnrealBloomPass already starts its blur chain at half resolution.
    this.composer.setSize(w, h);
  }

  apply(): void {
    this.bloom.enabled = this.settings.bloom;
    this.grade.enabled = this.settings.grade;
  }

  render(dt: number): void {
    this.composer.render(dt);
  }
}
