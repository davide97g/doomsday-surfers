// The sounds the UI layer is allowed to trigger (implemented by GameAudio).
export interface Sfx {
  chime(): void;
  /** The system voice says the death line's last word ("Disgusting."). */
  voice(phonemes?: readonly string[]): void;
  jingle(notes: readonly number[]): void;
  tick(): void;
  click(): void;
  reward(): void;
  /** Work mode card arrival (chat, mail, calendar, ticket, humbl). */
  notify(kind: string): void;
  /** Work mode incoming call: loop the ring while `on`. */
  ring(on: boolean): void;
}
