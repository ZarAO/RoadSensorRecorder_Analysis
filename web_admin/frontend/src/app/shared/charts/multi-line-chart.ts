import { Component, ElementRef, computed, input, signal, viewChild } from '@angular/core';

import { CHART, PLOT, extent, invertScale, linearScale, niceTicks, tickLabel } from './chart-scale';

export interface LinePoint { x: number; y: number; }
export interface LineSeries { label: string; colorVar: string; points: LinePoint[]; dashed?: boolean; }
export interface BandPoint { x: number; lo: number; hi: number; }

interface HoverRow { label: string; colorVar: string; value: number | null; }

/** Generic multi-series line chart (N series + an optional band), sharing the
 *  same viewBox/margins/scales/tooltip conventions as the other comparison charts. */
@Component({
  selector: 'app-multi-line-chart',
  styleUrl: './chart.css',
  template: `
    <div class="legend">
      @for (s of series(); track s.label) {
        <span class="legend-item">
          <i [class.dashed]="s.dashed" [style.border-top-color]="'var(' + s.colorVar + ')'"></i>
          {{ s.label }}
        </span>
      }
    </div>

    <div class="chart-wrap">
      <svg #svg viewBox="0 0 640 400" role="img" aria-label="Багатолінійний графік"
           (pointermove)="onMove($event)" (pointerleave)="onLeave()">
        @for (tick of xTicks(); track tick.value) {
          <line class="grid" [attr.x1]="tick.px" [attr.y1]="plot.y0"
                [attr.x2]="tick.px" [attr.y2]="plot.y1" />
          <text class="axis" [attr.x]="tick.px" [attr.y]="plot.y1 + 16"
                text-anchor="middle">{{ tick.label }}</text>
        }
        @for (tick of yTicks(); track tick.value) {
          <line class="grid" [attr.x1]="plot.x0" [attr.y1]="tick.px"
                [attr.x2]="plot.x1" [attr.y2]="tick.px" />
          <text class="axis" [attr.x]="plot.x0 - 8" [attr.y]="tick.px + 4"
                text-anchor="end">{{ tick.label }}</text>
        }

        @if (xLabel()) {
          <text class="axis-title" [attr.x]="(plot.x0 + plot.x1) / 2" [attr.y]="chart.height - 6"
                text-anchor="middle">{{ xLabel() }}</text>
        }
        @if (yLabel()) {
          <text class="axis-title" x="0" y="10">{{ yLabel() }}</text>
        }

        @if (bandPath(); as d) {
          <path class="band" [attr.d]="d" />
        }

        @for (s of series(); track s.label; let i = $index) {
          <path class="line" [attr.d]="linePaths()[i]" [style.stroke]="'var(' + s.colorVar + ')'"
                [attr.stroke-dasharray]="s.dashed ? '6 4' : null" />
        }

        @if (hoverX() !== null) {
          <line class="crosshair" [attr.x1]="hoverPx()" [attr.y1]="plot.y0"
                [attr.x2]="hoverPx()" [attr.y2]="plot.y1" />
        }

        <line class="axis-line" [attr.x1]="plot.x0" [attr.y1]="plot.y1"
              [attr.x2]="plot.x1" [attr.y2]="plot.y1" />
        <line class="axis-line" [attr.x1]="plot.x0" [attr.y1]="plot.y0"
              [attr.x2]="plot.x0" [attr.y2]="plot.y1" />
      </svg>

      @if (hoverX() !== null) {
        <div class="tip" [style.left.%]="pct(hoverPx(), chart.width, 15, 85)" style="top: 18%">
          <b>{{ hoverXLabel() }}</b>
          @for (row of hoverRows(); track row.label) {
            <div>{{ row.label }}: {{ row.value != null ? row.value.toFixed(2) : '—' }}</div>
          }
        </div>
      }
    </div>
  `,
})
export class MultiLineChart {
  readonly series = input<LineSeries[]>([]);
  readonly band = input<BandPoint[] | null>(null);
  readonly xLabel = input('');
  readonly yLabel = input('');

  protected readonly chart = CHART;
  protected readonly plot = PLOT;

  /** Hovered x in data space; null while the pointer is outside the chart. */
  protected readonly hoverX = signal<number | null>(null);
  private readonly svgRef = viewChild<ElementRef<SVGSVGElement>>('svg');

  private readonly allPoints = computed(() => this.series().flatMap(s => s.points));
  private readonly xDomain = computed(
    () => extent([...this.allPoints().map(p => p.x), ...(this.band() ?? []).map(b => b.x)], 0));
  private readonly yDomain = computed(() => extent([
    ...this.allPoints().map(p => p.y),
    ...(this.band() ?? []).flatMap(b => [b.lo, b.hi]),
  ]));
  private readonly xScale = computed(() => linearScale(this.xDomain(), [PLOT.x0, PLOT.x1]));
  private readonly yScale = computed(() => linearScale(this.yDomain(), [PLOT.y1, PLOT.y0]));

  protected readonly xTicks = computed(() => this.ticks(this.xDomain(), this.xScale()));
  protected readonly yTicks = computed(() => this.ticks(this.yDomain(), this.yScale()));

  protected readonly hoverPx = computed(() => {
    const x = this.hoverX();
    return x == null ? 0 : this.xScale()(x);
  });

  /** Fixed 3-decimal precision (meter resolution on km-scale chainage), not the
   *  axis-span-scaled tickLabel — that gave 100 m resolution on an 11 km reference,
   *  well above the 10 m interval spacing the data actually carries. */
  protected readonly hoverXLabel = computed(() => {
    const x = this.hoverX();
    return x == null ? '' : x.toFixed(3);
  });

  protected readonly hoverRows = computed<HoverRow[]>(() => {
    const x = this.hoverX();
    if (x == null) return [];
    return this.series().map(s => ({
      label: s.label, colorVar: s.colorVar, value: this.nearestY(s.points, x),
    }));
  });

  /** One path per series, precomputed alongside the scales so pointermove
   *  (which only touches hoverX) never re-sorts/re-renders every series' points. */
  protected readonly linePaths = computed(() => {
    const [sx, sy] = [this.xScale(), this.yScale()];
    return this.series().map(s => {
      const sorted = [...s.points].sort((a, b) => a.x - b.x);
      return sorted.map((point, index) =>
        `${index ? 'L' : 'M'}${sx(point.x).toFixed(2)} ${sy(point.y).toFixed(2)}`).join(' ');
    });
  });

  protected readonly bandPath = computed(() => {
    const band = this.band();
    if (!band || !band.length) return null;
    const sorted = [...band].sort((a, b) => a.x - b.x);
    const [sx, sy] = [this.xScale(), this.yScale()];
    const top = sorted.map((p, index) =>
      `${index ? 'L' : 'M'}${sx(p.x).toFixed(2)} ${sy(p.hi).toFixed(2)}`).join(' ');
    const bottom = [...sorted].reverse()
      .map(p => `L${sx(p.x).toFixed(2)} ${sy(p.lo).toFixed(2)}`).join(' ');
    return `${top} ${bottom} Z`;
  });

  protected pct(value: number, span: number, lo: number, hi: number): number {
    return Math.min(hi, Math.max(lo, (value / span) * 100));
  }

  protected onMove(event: PointerEvent): void {
    const at = this.toChart(event);
    if (!at) return;
    this.hoverX.set(invertScale(this.xDomain(), [PLOT.x0, PLOT.x1], at.x));
  }

  protected onLeave(): void {
    this.hoverX.set(null);
  }

  private nearestY(points: LinePoint[], x: number): number | null {
    if (!points.length) return null;
    return points.reduce((best, point) =>
      Math.abs(point.x - x) < Math.abs(best.x - x) ? point : best).y;
  }

  private ticks(domain: [number, number], scale: (v: number) => number) {
    const span = domain[1] - domain[0];
    return niceTicks(domain[0], domain[1]).map(value => ({
      value, px: scale(value), label: tickLabel(value, span),
    }));
  }

  private toChart(event: MouseEvent): { x: number; y: number } | null {
    const svg = this.svgRef()?.nativeElement;
    if (!svg) return null;
    const rect = svg.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    const x = ((event.clientX - rect.left) / rect.width) * CHART.width;
    return {
      // Clamped to the plot rect: the crosshair must never draw over the axis
      // labels and invertScale must never extrapolate past the data extent.
      x: Math.min(PLOT.x1, Math.max(PLOT.x0, x)),
      y: ((event.clientY - rect.top) / rect.height) * CHART.height,
    };
  }
}
