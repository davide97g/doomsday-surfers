import './style.css';
import { Bot } from './dev/bot';
import { Input } from './input/input';
import { GameRenderer } from './render/renderer';
import { TUNING } from './sim/types';
import { World } from './sim/world';
import { Hud } from './ui/hud';

const STEP = 1 / 120;
const params = new URLSearchParams(location.search);
const useBot = params.has('bot');
const seedParam = params.get('seed');

const app = document.getElementById('app')!;
const world = new World(seedParam ? Number(seedParam) : Date.now());
const view = new GameRenderer(app, TUNING.spawn.ahead - 10);
view.renderer.info.autoReset = false;
const input = new Input(view.renderer.domElement);
const bot = useBot ? new Bot() : null;

const hud = new Hud(document.body, {
  bloom: true,
  grade: true,
  pixelRatio: view.settings.pixelRatio,
  dopamine: 1,
});
hud.onRestart = () => world.reset(seedParam ? Number(seedParam) : Date.now());
hud.onPerfChange = (p) => {
  view.post.settings.bloom = p.bloom;
  view.post.settings.grade = p.grade;
  view.post.grade.uniforms.dopamine.value = p.dopamine;
  if (p.pixelRatio !== view.settings.pixelRatio) {
    view.settings.pixelRatio = p.pixelRatio;
    view.resize();
  }
};

// Expose for automated tests / debugging in the console.
(window as unknown as { game: unknown }).game = { world, view, input };

let last = performance.now();
let acc = 0;
let fpsFrames = 0;
let fpsTime = 0;
let cpuAcc = 0;

function frame(now: number): void {
  requestAnimationFrame(frame);
  const dt = Math.min(0.1, (now - last) / 1000);
  last = now;
  const cpuStart = performance.now();

  // Restart is button-only, so a panicked swipe on the death screen can't skip it.
  let actions = input.drain();
  acc += dt;
  while (acc >= STEP) {
    if (bot) actions = actions.concat(bot.think(world, STEP));
    world.step(STEP, actions);
    actions = [];
    acc -= STEP;
  }
  view.handleEvents(world.drainEvents());

  view.renderer.info.reset();
  view.render(world, dt);
  hud.update(world.phase, world.d, world.score);

  cpuAcc += performance.now() - cpuStart;
  fpsFrames++;
  fpsTime += dt;
  if (fpsTime >= 0.5) {
    const s = view.stats();
    hud.setFps(fpsFrames / fpsTime, cpuAcc / fpsFrames, s.calls, s.tris);
    fpsFrames = 0;
    fpsTime = 0;
    cpuAcc = 0;
  }
}
requestAnimationFrame(frame);
