import { Component, ElementRef, computed, input, output, signal, viewChild } from '@angular/core';

import { ChartProfilePoint } from '../../api/dto';
import { CHART, PLOT, extent, invertScale, linearScale, niceTicks, tickLabel } from './chart-scale';

/** A drag narrower than this is a click, i.e. «clear the range» */
const MIN_BRUSH_PX = 5;

/** IRI along the chainage: reference, smartphone and bias-corrected profiles. */
@Component({
  selector: 'app-profile-chart',
  styleUrl: './chart.css',
  template: `
    <div class="legend">
      <span class="legend-item"><i class="reference"></i>IRI профілометра</span>
      <span class="legend-item"><i class="accent"></i>IRI смартфона</span>
      <span class="legend-item"><i class="corrected dashed"></i>IRI зі зсувом Eq.6</span>
      <span class="hint">протягніть, щоб виділити ділянку; клік — скинути</span>
    </div>

    <div class="chart-wrap">
      <svg #svg viewBox="0 0 640 400" role="img"
           aria-label="Профіль IRI за пікетажем: еталон, смартфон і скоригований смартфон"
           (pointerdown)="onDown($event)" (pointermove)="onMove($event)"
           (pointerup)="onUp($event)" (pointerleave)="onLeave()">
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

        <text class="axis-title" [attr.x]="(plot.x0 + plot.x1) / 2" [attr.y]="chart.height - 6"
              text-anchor="middle">Пікетаж, км</text>
        <text class="axis-title" x="0" y="10">IRI, м/км</text>

        @if (brush(); as band) {
          <rect class="brush" [attr.x]="band.x0" [attr.y]="plot.y0"
                [attr.width]="band.x1 - band.x0" [attr.height]="plot.y1 - plot.y0" />
        }

        <path class="line-ref" [attr.d]="refPath()" />
        <path class="line-multi" [attr.d]="multiPath()" />
        <path class="line-corrected" stroke-dasharray="6 4" [attr.d]="correctedPath()" />

        @if (hover(); as point) {
          <line class="crosshair" [attr.x1]="hoverPx()" [attr.y1]="plot.y0"
                [attr.x2]="hoverPx()" [attr.y2]="plot.y1" />
        }

        <line class="axis-line" [attr.x1]="plot.x0" [attr.y1]="plot.y1"
              [attr.x2]="plot.x1" [attr.y2]="plot.y1" />
        <line class="axis-line" [attr.x1]="plot.x0" [attr.y1]="plot.y0"
              [attr.x2]="plot.x0" [attr.y2]="plot.y1" />
      </svg>

      @if (hover(); as point) {
        <div class="tip" [style.left.%]="pct(hoverPx(), chart.width, 15, 85)" style="top: 18%">
          <b>{{ (point.chainage_m / 1000).toFixed(2) }} км</b>
          (сегмент {{ point.seg_id }})<br />
          еталон {{ point.iri_ref.toFixed(2) }} ·
          смартфон {{ point.iri_multi.toFixed(2) }} ·
          зі зсувом {{ point.iri_multi_bias_corrected.toFixed(2) }} м/км
        </div>
      }
    </div>
  `,
})
export class ProfileChart {
  readonly points = input<ChartProfilePoint[]>([]);
  /** Selected chainage range in km, or null when the selection is cleared */
  readonly range = output<[number, number] | null>();

  protected readonly chart = CHART;
  protected readonly plot = PLOT;

  protected readonly hover = signal<ChartProfilePoint | null>(null);
  protected readonly brush = signal<{ x0: number; x1: number } | null>(null);
  private dragStart: number | null = null;
  private readonly svgRef = viewChild<ElementRef<SVGSVGElement>>('svg');

  private readonly sorted = computed(
    () => [...this.points()].sort((a, b) => a.chainage_m - b.chainage_m));

  private readonly xDomain = computed(
    () => extent(this.sorted().map(p => p.chainage_m / 1000), 0));
  private readonly yDomain = computed(() => extent(this.sorted().flatMap(
    p => [p.iri_ref, p.iri_multi, p.iri_multi_bias_corrected])));
  private readonly xScale = computed(() => linearScale(this.xDomain(), [PLOT.x0, PLOT.x1]));
  private readonly yScale = computed(() => linearScale(this.yDomain(), [PLOT.y1, PLOT.y0]));

  protected readonly xTicks = computed(() => this.ticks(this.xDomain(), this.xScale()));
  protected readonly yTicks = computed(() => this.ticks(this.yDomain(), this.yScale()));

  protected readonly refPath = computed(() => this.path(p => p.iri_ref));
  protected readonly multiPath = computed(() => this.path(p => p.iri_multi));
  protected readonly correctedPath = computed(
    () => this.path(p => p.iri_multi_bias_corrected));

  protected readonly hoverPx = computed(() => {
    const point = this.hover();
    return point ? this.xScale()(point.chainage_m / 1000) : 0;
  });

  protected pct(value: number, span: number, lo: number, hi: number): number {
    return Math.min(hi, Math.max(lo, (value / span) * 100));
  }

  protected onDown(event: PointerEvent): void {
    const at = this.toChart(event);
    if (!at) return;
    // Capture the pointer: a release outside the SVG must still reach onUp, otherwise
    // the painted band would survive with no range emitted (and vice versa on re-entry).
    this.svgRef()?.nativeElement.setPointerCapture?.(event.pointerId);
    this.dragStart = at.x;
    this.brush.set({ x0: at.x, x1: at.x });
  }

  protected onMove(event: PointerEvent): void {
    const at = this.toChart(event);
    if (!at) return;
    this.hover.set(this.nearest(at.x));
    if (this.dragStart !== null) {
      this.brush.set({
        x0: Math.min(this.dragStart, at.x), x1: Math.max(this.dragStart, at.x),
      });
    }
  }

  protected onUp(event: PointerEvent): void {
    const start = this.dragStart;
    const at = this.toChart(event);
    this.dragStart = null;
    if (start === null || !at) {
      this.brush.set(null);
      return;
    }
    const [lo, hi] = [Math.min(start, at.x), Math.max(start, at.x)];
    if (hi - lo < MIN_BRUSH_PX) {
      this.brush.set(null);
      this.range.emit(null);
      return;
    }
    this.brush.set({ x0: lo, x1: hi });
    const range: [number, number] = [PLOT.x0, PLOT.x1];
    this.range.emit([
      invertScale(this.xDomain(), range, lo), invertScale(this.xDomain(), range, hi),
    ]);
  }

  /** Only the hover crosshair goes: the drag is pointer-captured, so it stays alive
   *  until onUp either commits the range or clears the band — never half of each. */
  protected onLeave(): void {
    this.hover.set(null);
  }

  private nearest(px: number): ChartProfilePoint | null {
    const points = this.sorted();
    if (!points.length) return null;
    const target = invertScale(this.xDomain(), [PLOT.x0, PLOT.x1], px);
    return points.reduce((best, point) =>
      Math.abs(point.chainage_m / 1000 - target) < Math.abs(best.chainage_m / 1000 - target)
        ? point : best);
  }

  private path(pick: (point: ChartProfilePoint) => number): string {
    const [sx, sy] = [this.xScale(), this.yScale()];
    return this.sorted().map((point, index) =>
      `${index ? 'L' : 'M'}${sx(point.chainage_m / 1000).toFixed(2)} ${sy(pick(point)).toFixed(2)}`,
    ).join(' ');
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
      // Clamped to the plot rect: the band must never be painted over the axis labels
      // and invertScale must never extrapolate past the data extent.
      x: Math.min(PLOT.x1, Math.max(PLOT.x0, x)),
      y: ((event.clientY - rect.top) / rect.height) * CHART.height,
    };
  }
}
