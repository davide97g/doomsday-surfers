// The sounds the UI layer is allowed to trigger (implemented by GameAudio).
export interface Sfx {
  chime(): void;
  jingle(notes: readonly number[]): void;
  tick(): void;
  click(): void;
  reward(): void;
}
