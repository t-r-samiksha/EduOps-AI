// 6-hue fixed legend (--chip-1..6 in index.css) so every subject in the school gets
// a stable color regardless of load order — a simple multiplicative hash spreads
// small sequential ids (40, 41, 42, ...) across the full rotation instead of
// clustering on chip-1/chip-2.
const CHIP_COUNT = 6;

export function subjectChipIndex(subjectId: number): number {
  return ((subjectId * 2654435761) >>> 0) % CHIP_COUNT;
}

export function subjectChipVar(subjectId: number): string {
  return `var(--chip-${subjectChipIndex(subjectId) + 1})`;
}
