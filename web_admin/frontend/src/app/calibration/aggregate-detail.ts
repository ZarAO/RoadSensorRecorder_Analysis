import { DatePipe } from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { ApiService } from '../api/api.service';
import { AggregateChartData, AggregateOut, CoefficientSetOut } from '../api/dto';
import { BandPoint, LineSeries, MultiLineChart } from '../shared/charts/multi-line-chart';
import { CreateSetDialog, PhoneOption, SetProvenance } from './create-set-dialog';

const FIGURE_PROFILE = { name: 'fig_agg_profile', label: 'Агрегований профіль IRI' };
const FIGURE_SPEED = { name: 'fig_agg_speed', label: 'Швидкісний ефект (центровані відхилення)' };

/** An aggregate pools several passes, so it has no single recording to read a
 *  phone model from: only the «any phone» resolution tier is offered here.
 *  (Task 6 introduces the recorded device identity — then a real option list
 *  can replace this one.) */
const PHONE_OPTIONS: PhoneOption[] = [{ label: '(будь-який телефон)', value: null }];

interface BinRow {
  chainage_km: number;
  iri_ref: number;
  mean_iri: number;
  std_iri: number | null;
  n_passes: number;
  diff: number;
}

@Component({
  selector: 'app-aggregate-detail',
  imports: [DatePipe, RouterLink, MultiLineChart, CreateSetDialog],
  templateUrl: './aggregate-detail.html',
  styleUrl: './aggregate-detail.css',
})
export class AggregateDetail {
  private readonly api = inject(ApiService);
  private readonly route = inject(ActivatedRoute);

  readonly aggregateId = Number(this.route.snapshot.paramMap.get('id'));
  readonly aggregate = signal<AggregateOut | null>(null);
  readonly chart = signal<AggregateChartData | null>(null);
  readonly error = signal<string | null>(null);
  readonly loading = signal(true);

  /** «Створити набір коефіцієнтів» dialog (shared component, mounted while open) */
  readonly setOpen = signal(false);
  readonly createdSet = signal<CoefficientSetOut | null>(null);
  readonly vehicleType = signal('');
  readonly phoneOptions = PHONE_OPTIONS;

  readonly summary = computed(() => this.aggregate()?.summary ?? null);

  readonly provenance = computed<SetProvenance>(
    () => ({ kind: 'aggregate', id: this.aggregateId }));

  /** yyyy-MM-dd of created_at — feeds the dialog's reproducible default name */
  readonly createdDate = computed(() => {
    const created = this.aggregate()?.created_at;
    const parsed = created ? new Date(created) : null;
    return parsed && !Number.isNaN(parsed.getTime()) ? parsed.toISOString().slice(0, 10) : '';
  });

  /** «−1.80; −1.42», empty when the job estimated no interval */
  readonly ciText = computed(() => {
    const stats = this.summary();
    if (stats?.bias_ci_low == null || stats.bias_ci_high == null) return '';
    return `${this.signed(stats.bias_ci_low)}; ${this.signed(stats.bias_ci_high)}`;
  });

  readonly profileSeries = computed<LineSeries[]>(() => {
    const profile = this.chart()?.profile ?? [];
    return [
      {
        label: 'Еталон', colorVar: '--color-fg',
        points: profile.map(bin => ({ x: bin.chainage_m / 1000, y: bin.iri_ref })),
      },
      {
        label: 'Смартфон (середнє проїздів)', colorVar: '--color-accent',
        points: profile.map(bin => ({ x: bin.chainage_m / 1000, y: bin.mean_iri })),
      },
    ];
  });

  /** min–max spread of the passes in each bin, drawn under the two lines */
  readonly profileBand = computed<BandPoint[] | null>(() => {
    const profile = this.chart()?.profile ?? [];
    if (!profile.length) return null;
    return profile.map(bin => ({ x: bin.chainage_m / 1000, lo: bin.lo, hi: bin.hi }));
  });

  readonly bins = computed<BinRow[]>(() => (this.chart()?.profile ?? [])
    .map(bin => ({
      chainage_km: bin.chainage_m / 1000,
      iri_ref: bin.iri_ref,
      mean_iri: bin.mean_iri,
      std_iri: bin.std_iri,
      n_passes: bin.n_passes,
      diff: bin.mean_iri - bin.iri_ref,
    }))
    .sort((a, b) => a.chainage_km - b.chainage_km));

  readonly speedEffect = computed(() => this.chart()?.speed_effect ?? null);

  readonly figures = computed(
    () => this.speedEffect() ? [FIGURE_PROFILE, FIGURE_SPEED] : [FIGURE_PROFILE]);

  constructor() {
    this.api.getAggregate(this.aggregateId).subscribe({
      next: aggregate => {
        this.loading.set(false);
        this.aggregate.set(aggregate);
        if (aggregate.status === 'done') this.loadChart();
        // An aggregate has no single run: the vehicle type of the first pass is
        // the prefill (all pooled passes are meant to be the same vehicle).
        if (aggregate.run_ids.length) this.loadVehicleType(aggregate.run_ids[0]);
      },
      error: err => { this.loading.set(false); this.error.set(this.describe(err)); },
    });
  }

  private loadChart(): void {
    this.api.getAggregateChartData(this.aggregateId).subscribe({
      next: chart => this.chart.set(chart),
      error: err => this.error.set(this.describe(err)),
    });
  }

  private loadVehicleType(runId: number): void {
    this.api.getRun(runId).subscribe({
      next: run => this.vehicleType.set(run.summary?.vehicle_type ?? ''),
      // A missing run only costs the prefill — the operator can still type it
      error: () => undefined,
    });
  }

  figureUrl(name: string, extension: 'png' | 'pdf'): string {
    return this.api.aggregateArtifactUrl(this.aggregateId, `figures/${name}.${extension}`);
  }

  // --- coefficient-set dialog ---------------------------------------------

  openSetDialog(): void {
    this.createdSet.set(null);
    this.setOpen.set(true);
  }

  onSetCreated(set: CoefficientSetOut): void {
    this.setOpen.set(false);
    this.createdSet.set(set);
  }

  fmt(value: number | null | undefined, digits = 2): string {
    return value == null ? '—' : value.toFixed(digits);
  }

  signed(value: number | null | undefined, digits = 2): string {
    if (value == null) return '—';
    return (value < 0 ? '−' : '') + Math.abs(value).toFixed(digits);
  }

  /** Explicit sign on both directions — the column is a deviation, not a value */
  diffText(value: number, digits = 2): string {
    return (value < 0 ? '−' : '+') + Math.abs(value).toFixed(digits);
  }

  private describe(err: { error?: { detail?: string }; message?: string }): string {
    return err?.error?.detail ?? err?.message ?? 'Невідома помилка';
  }
}
