import './style.css';
import { GameAudio } from './audio/audio';
import { Bot } from './dev/bot';
import { GameHaptics } from './fx/haptics';
import { Input } from './input/input';
import { GameRenderer } from './render/renderer';
import { TUNING } from './sim/types';
import { World } from './sim/world';
import { Death } from './ui/death';
import { GateScan } from './ui/gate';
import { Hud } from './ui/hud';
import { KeepGoing } from './ui/keepGoing';
import { Nags } from './ui/nags';
import { Reel } from './ui/reel';
import { Select } from './ui/select';
import type { Sfx } from './ui/sfx';
import { Title } from './ui/title';

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
});
const audio = new GameAudio();
const haptics = new GameHaptics();
// UI sounds, plus the phone buzz that makes a fake notification feel real.
const sfx: Sfx = {
  chime: () => {
    audio.chime();
    haptics.buzz();
  },
  jingle: (notes) => audio.jingle(notes),
  tick: () => audio.tick(),
  click: () => audio.click(),
  reward: () => audio.reward(),
};
const title = new Title(hud.root, sfx);
const select = new Select(title.slot, sfx);
select.onChange = (i) => {
  world.setCharacter(i);
  view.setCharacter(i);
};
world.setCharacter(select.index);
view.setCharacter(select.index);
const reel = new Reel(hud.root);
const nags = new Nags(hud.root, sfx);
nags.onArrive = () => world.notificationArrived();
nags.onOpen = (share) => {
  world.openNotification();
  if (share) reel.play(share.clip, share.friend);
};
// A swipe that starts on a notification still steers the runner.
nags.onSwipe = (a) => input.push(a);
const keepGoing = new KeepGoing(hud.root, sfx);
const death = new Death(hud.root, sfx);
const gateScan = new GateScan(hud.root, sfx);
death.onRevive = () => world.revive();
death.onRestart = () => world.reset(seedParam ? Number(seedParam) : Date.now());
hud.onPerfChange = (p) => {
  view.post.settings.bloom = p.bloom;
  view.post.settings.grade = p.grade;
  if (p.pixelRatio !== view.settings.pixelRatio) {
    view.settings.pixelRatio = p.pixelRatio;
    view.resize();
  }
};

// Expose for automated tests / debugging in the console.
(window as unknown as { game: unknown }).game = { world, view, input, audio, nags, reel, keepGoing, death };

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
  // On the title screen left/right pick a character instead of starting the run.
  if (world.phase === 'ready') actions = select.filter(actions);
  // The keep-going prompt freezes the run; swipes made meanwhile are dropped.
  acc = keepGoing.paused ? 0 : acc + dt;
  while (acc >= STEP) {
    if (bot) actions = actions.concat(bot.think(world, STEP));
    world.step(STEP, actions);
    actions = [];
    acc -= STEP;
  }
  const events = world.drainEvents();
  view.handleEvents(events, world);
  audio.handle(events);
  haptics.handle(events);
  hud.handle(events);
  gateScan.handle(events, world);
  if (events.some((e) => e.type === 'gate')) {
    nags.hideAll();
    reel.hide();
  }
  if (events.some((e) => e.type === 'start')) title.onRunStart();

  view.renderer.info.reset();
  view.render(world, dt);
  audio.update(world, dt);
  haptics.update(world, dt);
  hud.update(world, dt);
  title.update(world.phase);
  // The gate scan owns the screen: no nags, and the keep-going prompt waits.
  nags.topBlocked = reel.playing;
  nags.update(world, dt, keepGoing.paused || world.gateT >= 0);
  reel.update(world, dt, keepGoing.paused);
  gateScan.update(world, dt);
  if (!bot) keepGoing.update(world, dt);
  death.update(world, dt, nags);

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
