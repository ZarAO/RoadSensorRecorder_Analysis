import { Component, ElementRef, computed, input, output, signal, viewChild } from '@angular/core';

import { ChartScatterPoint } from '../../api/dto';
import { CHART, PLOT, extent, invertScale, linearScale, niceTicks, tickLabel } from './chart-scale';

/** Pointer-to-point hover distance, in viewBox units */
const HOVER_RADIUS = 14;
const ZOOM_FACTOR = 1.2;

interface Dot { point: ChartScatterPoint; cx: number; cy: number; }

/** √PSD vs profilometer IRI with the Eq.3 fit line, hover tooltip and wheel zoom. */
@Component({
  selector: 'app-scatter-chart',
  styleUrl: './chart.css',
  template: `
    <div class="legend">
      <span class="legend-item"><i class="dot accent"></i>Смартфон (сегменти)</span>
      @if (fitLine()) {
        <span class="legend-item"><i class="reference"></i>Фіт Eq.3</span>
      } @else {
        <span class="legend-item">Фіт Eq.3: фіт вироджений — недоступно</span>
      }
      <span class="hint">прокрутка — масштаб, подвійний клік — скидання</span>
    </div>

    <div class="chart-wrap">
      <svg #svg viewBox="0 0 640 400" role="img"
           aria-label="Діаграма розсіювання √PSD проти IRI профілометра"
           (pointermove)="onMove($event)" (pointerleave)="hover.set(null)"
           (wheel)="onWheel($event)" (dblclick)="resetZoom()">
        <defs>
          <clipPath [attr.id]="clipId">
            <rect [attr.x]="plot.x0" [attr.y]="plot.y0"
                  [attr.width]="plot.x1 - plot.x0" [attr.height]="plot.y1 - plot.y0" />
          </clipPath>
        </defs>

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
              text-anchor="middle">√PSD, g/√Гц (0.5–6 Гц)</text>
        <text class="axis-title" x="0" y="10">IRI профілометра, м/км</text>

        <g [attr.clip-path]="clipUrl">
          @if (fitLine(); as line) {
            <line class="fit" [attr.x1]="line.x1" [attr.y1]="line.y1"
                  [attr.x2]="line.x2" [attr.y2]="line.y2" />
          }
          @for (dot of dots(); track dot.point.seg_id) {
            <circle class="dot" [class.selected]="dot.point.seg_id === selectedSegId()"
                    [attr.cx]="dot.cx" [attr.cy]="dot.cy" [attr.r]="radius(dot.point)"
                    (click)="segClick.emit(dot.point.seg_id)" />
          }
        </g>

        <line class="axis-line" [attr.x1]="plot.x0" [attr.y1]="plot.y1"
              [attr.x2]="plot.x1" [attr.y2]="plot.y1" />
        <line class="axis-line" [attr.x1]="plot.x0" [attr.y1]="plot.y0"
              [attr.x2]="plot.x0" [attr.y2]="plot.y1" />
      </svg>

      @if (hover(); as dot) {
        <div class="tip" [style.left.%]="pct(dot.cx, chart.width, 15, 85)"
             [style.top.%]="pct(dot.cy, chart.height, 14, 96)">
          <b>сегмент {{ dot.point.seg_id }}</b>:
          √PSD {{ dot.point.psd_sqrt_scalar.toFixed(4) }},
          IRI_ref {{ dot.point.iri_ref.toFixed(2) }} м/км
        </div>
      }
    </div>
  `,
})
export class ScatterChart {
  private static instances = 0;

  readonly points = input<ChartScatterPoint[]>([]);
  readonly fit = input<{ A: number | null; B: number | null } | null>(null);
  readonly selectedSegId = input<number | null>(null);
  readonly segClick = output<number>();

  protected readonly chart = CHART;
  protected readonly plot = PLOT;
  protected readonly clipId = `scatter-clip-${++ScatterChart.instances}`;
  protected readonly clipUrl = `url(#${this.clipId})`;

  protected readonly hover = signal<Dot | null>(null);
  /** null = full data extent; set by wheel zoom, cleared by dblclick */
  private readonly zoom = signal<{ x: [number, number]; y: [number, number] } | null>(null);
  private readonly svgRef = viewChild<ElementRef<SVGSVGElement>>('svg');

  private readonly dataX = computed(() => extent(this.points().map(p => p.psd_sqrt_scalar)));
  private readonly dataY = computed(() => extent(this.points().map(p => p.iri_ref)));
  private readonly xDomain = computed(() => this.zoom()?.x ?? this.dataX());
  private readonly yDomain = computed(() => this.zoom()?.y ?? this.dataY());
  private readonly xScale = computed(() => linearScale(this.xDomain(), [PLOT.x0, PLOT.x1]));
  private readonly yScale = computed(() => linearScale(this.yDomain(), [PLOT.y1, PLOT.y0]));

  protected readonly xTicks = computed(() => this.ticks(this.xDomain(), this.xScale()));
  protected readonly yTicks = computed(() => this.ticks(this.yDomain(), this.yScale()));

  protected readonly dots = computed<Dot[]>(() => {
    const [sx, sy] = [this.xScale(), this.yScale()];
    return this.points().map(point => ({
      point, cx: sx(point.psd_sqrt_scalar), cy: sy(point.iri_ref),
    }));
  });

  /** Fit line across the whole x-domain — null whenever the fit is degenerate. */
  protected readonly fitLine = computed(() => {
    const fit = this.fit();
    if (!fit || fit.A == null || fit.B == null) return null;
    const [x0, x1] = this.xDomain();
    const [sx, sy] = [this.xScale(), this.yScale()];
    return {
      x1: sx(x0), y1: sy(fit.A * x0 + fit.B),
      x2: sx(x1), y2: sy(fit.A * x1 + fit.B),
    };
  });

  protected radius(point: ChartScatterPoint): number {
    if (point.seg_id === this.selectedSegId()) return 7;
    return this.hover()?.point.seg_id === point.seg_id ? 6 : 4;
  }

  /** viewBox coordinate as a clamped percentage, keeping the tooltip inside the box. */
  protected pct(value: number, span: number, lo: number, hi: number): number {
    return Math.min(hi, Math.max(lo, (value / span) * 100));
  }

  protected onMove(event: PointerEvent): void {
    const at = this.toChart(event);
    if (!at) return;
    let nearest: Dot | null = null;
    let best = HOVER_RADIUS;
    for (const dot of this.dots()) {
      const distance = Math.hypot(dot.cx - at.x, dot.cy - at.y);
      if (distance <= best) {
        best = distance;
        nearest = dot;
      }
    }
    this.hover.set(nearest);
  }

  protected onWheel(event: WheelEvent): void {
    const at = this.toChart(event);
    if (!at) return;
    event.preventDefault();
    const factor = event.deltaY > 0 ? ZOOM_FACTOR : 1 / ZOOM_FACTOR;
    this.zoom.set({
      x: this.zoomDomain(this.xDomain(), this.dataX(), [PLOT.x0, PLOT.x1], at.x, factor),
      y: this.zoomDomain(this.yDomain(), this.dataY(), [PLOT.y1, PLOT.y0], at.y, factor),
    });
  }

  protected resetZoom(): void {
    this.zoom.set(null);
  }

  private ticks(domain: [number, number], scale: (v: number) => number) {
    const span = domain[1] - domain[0];
    return niceTicks(domain[0], domain[1]).map(value => ({
      value, px: scale(value), label: tickLabel(value, span),
    }));
  }

  /** Scale a domain around the cursor, never wider than the full data extent. */
  private zoomDomain(domain: [number, number], full: [number, number],
                     range: [number, number], px: number, factor: number): [number, number] {
    const center = invertScale(domain, range, px);
    const width = Math.min((domain[1] - domain[0]) * factor, full[1] - full[0]);
    const lo = Math.max(full[0], Math.min(center - (center - domain[0]) * factor,
                                          full[1] - width));
    return [lo, lo + width];
  }

  private toChart(event: MouseEvent): { x: number; y: number } | null {
    const svg = this.svgRef()?.nativeElement;
    if (!svg) return null;
    const rect = svg.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    return {
      x: ((event.clientX - rect.left) / rect.width) * CHART.width,
      y: ((event.clientY - rect.top) / rect.height) * CHART.height,
    };
  }
}
