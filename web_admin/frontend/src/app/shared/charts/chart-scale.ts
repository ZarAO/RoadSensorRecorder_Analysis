/** Pure scale/tick helpers shared by the comparison SVG charts.
 *  No DOM, no Angular — unit-testable on their own. */

export interface Scale {
  domain: [number, number];
  range: [number, number];
}

/** Geometry every comparison chart shares (viewBox units). */
export const CHART = {
  width: 640,
  height: 400,
  top: 16,
  right: 16,
  bottom: 40,
  left: 48,
} as const;

/** Plot rectangle derived from CHART: x0/y0 top-left, x1/y1 bottom-right. */
export const PLOT = {
  x0: CHART.left,
  x1: CHART.width - CHART.right,
  y0: CHART.top,
  y1: CHART.height - CHART.bottom,
} as const;

/** domain → range mapper; a zero-width domain maps everything to range start. */
export function linearScale(domain: [number, number], range: [number, number]) {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  const k = (r1 - r0) / (d1 - d0 || 1);
  return (v: number) => r0 + (v - d0) * k;
}

/** Inverse of linearScale — pixel back to data value. */
export function invertScale(domain: [number, number], range: [number, number], px: number): number {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  const k = (r1 - r0) / (d1 - d0 || 1);
  return d0 + (px - r0) / (k || 1);
}

/** Round tick values on a 1-2-5 step, all inside [min, max]. */
export function niceTicks(min: number, max: number, count = 5): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max) || count < 1) return [];
  let lo = Math.min(min, max);
  const hi = Math.max(min, max);
  if (lo === hi) return [lo];

  const raw = (hi - lo) / count;
  const magnitude = Math.pow(10, Math.floor(Math.log10(raw)));
  const normalized = raw / magnitude;
  const step = (normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10) * magnitude;

  const ticks: number[] = [];
  const epsilon = step * 1e-9;
  for (lo = Math.ceil(lo / step) * step; lo <= hi + epsilon; lo += step) {
    // Re-snap on every step: accumulating a float step drifts off the grid.
    ticks.push(Math.round(lo / step) * step);
  }
  return ticks;
}

/** Data extent with a relative pad; [0, 1] for empty data, ±0.5 for flat data. */
export function extent(values: number[], pad = 0.05): [number, number] {
  const finite = values.filter(value => Number.isFinite(value));
  if (!finite.length) return [0, 1];
  let lo = finite[0];
  let hi = finite[0];
  for (const value of finite) {
    if (value < lo) lo = value;
    if (value > hi) hi = value;
  }
  if (lo === hi) return [lo - 0.5, hi + 0.5];
  const margin = (hi - lo) * pad;
  return [lo - margin, hi + margin];
}

/** Tick label with a digit count that suits the axis span. */
export function tickLabel(value: number, span: number): string {
  const digits = span >= 20 ? 0 : span >= 2 ? 1 : span >= 0.2 ? 2 : 3;
  return value.toFixed(digits);
}
