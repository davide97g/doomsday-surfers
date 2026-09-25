// Set pieces: one per zone after the first gate, announced by the gate's
// profiling log. Every block of three zones plays each of them once, in an
// order shuffled from the course seed, so the Daily and ghost races see the
// same ones. Pure: the generator, the world and the renderer all ask here.

export type SetPiece = 'thumb' | 'algorithm' | 'slop';

const ORDERS: SetPiece[][] = [
  ['thumb', 'algorithm', 'slop'],
  ['thumb', 'slop', 'algorithm'],
  ['algorithm', 'thumb', 'slop'],
  ['algorithm', 'slop', 'thumb'],
  ['slop', 'thumb', 'algorithm'],
  ['slop', 'algorithm', 'thumb'],
];

export function setPieceFor(zone: number, seed: number): SetPiece | null {
  if (zone < 1) return null;
  const block = Math.floor((zone - 1) / 3);
  let h = Math.imul((seed ^ Math.imul(block + 1, 0x9e3779b1)) >>> 0, 0x85ebca6b);
  h ^= h >>> 15;
  return ORDERS[(h >>> 0) % ORDERS.length][(zone - 1) % 3];
}
