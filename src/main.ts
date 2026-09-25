import './style.css';
import { GameAudio } from './audio/audio';
import { renderSound, schedulePing, scheduleWord } from './audio/voice';
import { ClipRecorder } from './clip/clip';
import { content, mode, realBrands, switchMode } from './content/content';
import { Bot } from './dev/bot';
import { GameHaptics } from './fx/haptics';
import { Input } from './input/input';
import { GameRenderer } from './render/renderer';
import { fill } from './content/templates';
import { GhostRecorder, type GhostTrack } from './sim/ghost';
import { TUNING } from './sim/types';
import { World } from './sim/world';
import { distanceText, killerEmoji, loadToday, saveDaily, seedFor, shareLine, today } from './ui/daily';
import { Death } from './ui/death';
import { clearGhostFromUrl, ghostFromUrl, ghostUrl } from './ui/ghostLink';
import { loadHandle } from './ui/handle';
import { Race } from './ui/race';
import { killerText } from './ui/receipt';
import { GateScan } from './ui/gate';
import { Hud } from './ui/hud';
import { KeepGoing } from './ui/keepGoing';
import { Desk } from './ui/desk';
import { Nags } from './ui/nags';
import { Reel } from './ui/reel';
import { Select } from './ui/select';
import { SetPieceUi } from './ui/setpieces';
import { shareText } from './ui/share';
import type { Sfx } from './ui/sfx';
import { Title } from './ui/title';

const STEP = 1 / 120;
const params = new URLSearchParams(location.search);
const useBot = params.has('bot');
const seedParam = params.get('seed');

document.documentElement.dataset.mode = mode;
if (realBrands) {
  // Meet's UI font stand-in (Google Sans isn't public). Teams/Outlook fall back to Segoe UI or the system font.
  const font = document.createElement('link');
  font.rel = 'stylesheet';
  font.href = 'https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap';
  document.head.append(font);
}
const app = document.getElementById('app')!;
const endlessSeed = () => (seedParam ? Number(seedParam) : Date.now());
const world = new World(endlessSeed());
/** Today's feed number while the Daily is being played, else null (an endless run). */
let dailyDay: number | null = null;
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
  voice: () => audio.voice(),
  chime: () => {
    audio.chime();
    haptics.buzz();
  },
  jingle: (notes) => audio.jingle(notes),
  tick: () => audio.tick(),
  click: () => audio.click(),
  reward: () => audio.reward(),
  notify: (kind) => {
    audio.notify(kind);
    haptics.buzz();
  },
  ring: (on) => {
    audio.ring(on);
    if (on) haptics.buzz();
  },
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
// Work mode: opened cards dock their app here, under the notification layer.
const desk = new Desk(hud.root);
desk.onChange = (n) => world.setOpenWindows(n);
const nags = new Nags(hud.root, sfx);
nags.onArrive = () => world.notificationArrived();
nags.onOpen = (share, app) => {
  world.openNotification();
  if (share) reel.play(share.clip, share.friend);
  if (app) {
    desk.open(app.kind, app.who, app.text);
    world.windowOpened();
  }
};
// A swipe that starts on a notification still steers the runner.
nags.onSwipe = (a) => input.push(a);
const keepGoing = new KeepGoing(hud.root, sfx);
const death = new Death(hud.root, sfx);
const gateScan = new GateScan(hud.root, sfx);
const setPieceUi = new SetPieceUi(hud.root);
const race = new Race(hud.root, sfx);
death.race = race;
// Auto-clip: every run is encoded as it plays; death cuts the montage.
const clip = new ClipRecorder();
death.clip = clip;
clip.slateSounds = async (sr) => {
  const [voice, ping] = await Promise.all([
    renderSound(sr, (c, o) => scheduleWord(c, o, 0.02, content.death.voice, 0.8), 1.8),
    renderSound(sr, (c, o) => schedulePing(c, o, 0.01, 0.2), 0.7),
  ]);
  return { voice, ping };
};
race.onMoment = () => clip.mark('ghost');
// Every run is recorded as a ghost, so any death can be shared as a challenge.
const recorder = new GhostRecorder();
/** A friend's ghost from the link this page was opened with (see ghostLink.ts). */
let challenge: GhostTrack | null = null;

/** A fresh run on `seed`, racing `ghost` if given. */
function newRun(seed: number, ghost: GhostTrack | null = null): void {
  world.reset(seed);
  recorder.reset();
  death.link = null;
  if (ghost) race.start(ghost);
  else race.clear();
  view.setGhost(ghost);
}

/** Pack this run into a challenge link (async; the share button uses it once ready). */
function buildLink(): void {
  death.handle = loadHandle(world.character);
  const day = dailyDay;
  const header = { v: 1 as const, seed: world.seed, ch: world.character, name: death.handle, mode, day: day ?? 0, dist: Math.round(world.d), killer: killerText(world).toLowerCase() };
  const result = day !== null ? { distance: distanceText(world.d), emoji: killerEmoji(world), line: shareLine(world, day) } : null;
  void ghostUrl(recorder, header).then((url) => {
    if (header.seed !== world.seed) return; // a new run already started
    death.link = url;
    if (result && url) saveDaily({ day: day!, result: { ...result, line: `${result.line}\n${fill(content.share.link, { url })}` } });
  });
}

death.onRevive = () => {
  world.revive();
  clip.resume();
};
death.onRename = buildLink;
death.ending.onAmbience = (m) => audio.setEnding(m);
death.onRestart = () => {
  dailyDay = death.daily = null;
  newRun(endlessSeed());
};
// Tapping the "Time to Doom" notification: swap in today's course and go. One shot a day.
title.onDaily = () => {
  if (world.phase !== 'ready' || loadToday()) return;
  dailyDay = death.daily = today();
  newRun(seedFor(dailyDay));
  input.push('up');
};
// A challenge link: their course, their ghost, as many tries as you want. If it
// is today's feed and you haven't played it yet, this *is* your Daily.
title.onChallenge = () => {
  if (world.phase !== 'ready' || !challenge) return;
  const h = challenge.header;
  const asDaily = h.day > 0 && h.day === today() && !loadToday();
  dailyDay = death.daily = asDaily ? h.day : null;
  newRun(h.seed, challenge);
  // Only the first go at today's feed is the Daily; the card says so next time.
  if (asDaily) title.setChallenge({ name: h.name, distance: distanceText(h.dist), daily: false });
  input.push('up');
};
title.onChallengeDecline = () => {
  challenge = null;
  clearGhostFromUrl();
  title.setChallenge(null);
};
// First launch: no menu, no widgets. The lock screen says "Swipe up to scroll" and
// the run starts by itself a moment later. The character select comes back after.
const firstLaunch = (() => {
  try {
    return !localStorage.getItem('ds.launched');
  } catch {
    return false;
  }
})();
if (firstLaunch && !location.hash.includes('g=')) {
  title.firstLaunch();
  setTimeout(() => {
    if (world.phase === 'ready' && !challenge) input.push('up');
  }, TUNING.ui.firstStart * 1000);
}
void ghostFromUrl().then((track) => {
  if (!track) return;
  // The course plays the same in both modes, but the ghost's world should match theirs.
  if (track.header.mode !== mode) {
    switchMode(track.header.mode);
    return;
  }
  challenge = track;
  const h = track.header;
  title.setChallenge({ name: h.name, distance: distanceText(h.dist), daily: h.day > 0 && h.day === today() && !loadToday() });
});
title.onShare = (text) => void shareText(content.report.shareTitle, text);
hud.onPerfChange = (p) => {
  view.post.settings.bloom = p.bloom;
  view.post.settings.grade = p.grade;
  if (p.pixelRatio !== view.settings.pixelRatio) {
    view.settings.pixelRatio = p.pixelRatio;
    view.resize();
  }
};

// Expose for automated tests / debugging in the console.
(window as unknown as { game: unknown }).game = { world, view, input, audio, nags, reel, desk, keepGoing, death, race, recorder, clip };

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
    recorder.update(world);
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
    desk.clear();
  }
  for (const e of events) {
    if (e.type === 'start') {
      clip.startRun(loadHandle(world.character));
      try {
        localStorage.setItem('ds.launched', '1');
      } catch {
        // Every launch is the first one, then.
      }
    }
    else if (e.type === 'dead') {
      clip.stop();
      buildLink();
    } else if (e.type === 'gate') clip.mark('gate');
    else if (e.type === 'thrill') clip.mark(e.kind);
  }
  if (dailyDay !== null) {
    // The Daily locks as soon as it starts (quitting mid-run doesn't buy a retry).
    // Each death (a revive can bring you back) overwrites the result.
    if (events.some((e) => e.type === 'start')) {
      saveDaily({ day: dailyDay });
      title.onRunStart();
    }
    if (events.some((e) => e.type === 'dead')) {
      saveDaily({ day: dailyDay, result: { distance: distanceText(world.d), emoji: killerEmoji(world), line: shareLine(world, dailyDay) } });
    }
  }

  view.renderer.info.reset();
  view.render(world, dt);
  clip.listen(audio.output);
  clip.capture(view.renderer.domElement, world);
  audio.update(world, dt);
  haptics.update(world, dt);
  hud.update(world, dt);
  title.update(world.phase);
  // The gate scan owns the screen: no nags, and the keep-going prompt waits.
  // Work cards land over the docked windows; a reel keeps the top slot to itself.
  nags.topBlocked = reel.playing;
  nags.update(world, dt, keepGoing.paused || world.gateT >= 0);
  reel.update(world, dt, keepGoing.paused);
  desk.update(world, dt, keepGoing.paused);
  gateScan.update(world, dt);
  if (!bot) keepGoing.update(world, dt);
  death.update(world, dt, nags);
  race.update(world, dt, view.ghostTag);
  setPieceUi.update(world);

  cpuAcc += performance.now() - cpuStart;
  fpsFrames++;
  fpsTime += dt;
  if (fpsTime >= 0.5) {
    // Recording must never cost the run its frame rate.
    if (world.phase === 'running' && fpsFrames / fpsTime < TUNING.clip.minFps) clip.lowPower = true;
    const s = view.stats();
    hud.setFps(fpsFrames / fpsTime, cpuAcc / fpsFrames, s.calls, s.tris);
    fpsFrames = 0;
    fpsTime = 0;
    cpuAcc = 0;
  }
}
requestAnimationFrame(frame);
