import { Component, ElementRef, computed, input, signal, viewChild } from '@angular/core';

import { ChartBAPoint } from '../../api/dto';
import { CHART, PLOT, extent, linearScale, niceTicks, tickLabel } from './chart-scale';

const HOVER_RADIUS = 14;

interface Dot { point: ChartBAPoint; cx: number; cy: number; }

/** Bland-Altman plot: mean vs difference with the bias line and 95% limits of agreement. */
@Component({
  selector: 'app-ba-chart',
  styleUrl: './chart.css',
  template: `
    <div class="legend">
      <span class="legend-item"><i class="dot accent"></i>Сегменти</span>
      <span class="legend-item"><i class="accent"></i>Зсув (bias)</span>
      <span class="legend-item"><i class="reference dashed"></i>Межі узгодженості ±1.96σ</span>
    </div>

    <div class="chart-wrap">
      <svg #svg viewBox="0 0 640 400" role="img"
           aria-label="Графік Бленда-Альтмана: середнє проти різниці"
           (pointermove)="onMove($event)" (pointerleave)="hover.set(null)">
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
              text-anchor="middle">Середнє (смартфон + еталон) / 2, м/км</text>
        <text class="axis-title" x="0" y="10">Різниця (смартфон − еталон), м/км</text>

        <line class="bias-line" [attr.x1]="plot.x0" [attr.y1]="biasPx()"
              [attr.x2]="plot.x1" [attr.y2]="biasPx()" />
        <text class="axis" [attr.x]="plot.x1 - 2" [attr.y]="biasPx() - 5"
              text-anchor="end">зсув</text>

        @for (line of loaPx(); track line.key) {
          <line class="loa" stroke-dasharray="6 4" [attr.x1]="plot.x0" [attr.y1]="line.px"
                [attr.x2]="plot.x1" [attr.y2]="line.px" />
          <text class="axis" [attr.x]="plot.x1 - 2" [attr.y]="line.px - 5"
                text-anchor="end">±1.96σ</text>
        }

        @for (dot of dots(); track dot.point.seg_id) {
          <circle class="dot" [attr.cx]="dot.cx" [attr.cy]="dot.cy"
                  [attr.r]="hover()?.point.seg_id === dot.point.seg_id ? 6 : 4" />
        }

        <line class="axis-line" [attr.x1]="plot.x0" [attr.y1]="plot.y1"
              [attr.x2]="plot.x1" [attr.y2]="plot.y1" />
        <line class="axis-line" [attr.x1]="plot.x0" [attr.y1]="plot.y0"
              [attr.x2]="plot.x0" [attr.y2]="plot.y1" />
      </svg>

      @if (hover(); as dot) {
        <div class="tip" [style.left.%]="pct(dot.cx, chart.width, 15, 85)"
             [style.top.%]="pct(dot.cy, chart.height, 14, 96)">
          <b>сегмент {{ dot.point.seg_id }}</b>:
          середнє {{ dot.point.mean.toFixed(2) }},
          різниця {{ dot.point.diff.toFixed(2) }} м/км
        </div>
      }
    </div>
  `,
})
export class BaChart {
  readonly points = input<ChartBAPoint[]>([]);
  readonly bias = input(0);
  readonly loa = input<[number, number]>([0, 0]);

  protected readonly chart = CHART;
  protected readonly plot = PLOT;
  protected readonly hover = signal<Dot | null>(null);
  private readonly svgRef = viewChild<ElementRef<SVGSVGElement>>('svg');

  private readonly xDomain = computed(() => extent(this.points().map(p => p.mean)));
  /** The y-domain must hold the LoA lines too, or they fall outside the plot. */
  private readonly yDomain = computed(() => extent(
    [...this.points().map(p => p.diff), this.bias(), ...this.loa()]));
  private readonly xScale = computed(() => linearScale(this.xDomain(), [PLOT.x0, PLOT.x1]));
  private readonly yScale = computed(() => linearScale(this.yDomain(), [PLOT.y1, PLOT.y0]));

  protected readonly xTicks = computed(() => this.ticks(this.xDomain(), this.xScale()));
  protected readonly yTicks = computed(() => this.ticks(this.yDomain(), this.yScale()));

  protected readonly dots = computed<Dot[]>(() => {
    const [sx, sy] = [this.xScale(), this.yScale()];
    return this.points().map(point => ({ point, cx: sx(point.mean), cy: sy(point.diff) }));
  });

  protected readonly biasPx = computed(() => this.yScale()(this.bias()));
  protected readonly loaPx = computed(() => {
    const sy = this.yScale();
    return [
      { key: 'low', px: sy(this.loa()[0]) },
      { key: 'high', px: sy(this.loa()[1]) },
    ];
  });

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
    return {
      x: ((event.clientX - rect.left) / rect.width) * CHART.width,
      y: ((event.clientY - rect.top) / rect.height) * CHART.height,
    };
  }
}
