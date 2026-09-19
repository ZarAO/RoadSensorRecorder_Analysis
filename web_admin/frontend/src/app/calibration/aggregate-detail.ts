import { DatePipe } from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { catchError, forkJoin, map, of } from 'rxjs';

import { ApiService } from '../api/api.service';
import { AggregateChartData, AggregateOut, CoefficientSetOut, RunOut } from '../api/dto';
import { BandPoint, LineSeries, MultiLineChart } from '../shared/charts/multi-line-chart';
import { CreateSetDialog, SetProvenance, phoneOptionsFor } from './create-set-dialog';

const MSG_MIXED_IDENTITY = 'Проїзди агрегата записані різними телефонами або '
  + 'конфігураціями авто — набір буде прив’язаний лише до типу авто.';
const MSG_MIXED_VEHICLE_TYPE = 'Проїзди агрегата зроблені різними типами авто — '
  + 'зсув не можна прив’язати до однієї ідентичності.';

/** The identity keys of one pooled pass, as read off its RunOut. */
interface RunKeys {
  vehicleType: string | null;
  phoneModel: string | null;
  deviceId: string | null;
  vehicleId: string | null;
}

const FIGURE_PROFILE = { name: 'fig_agg_profile', label: 'Агрегований профіль IRI' };
const FIGURE_SPEED = { name: 'fig_agg_speed', label: 'Швидкісний ефект (центровані відхилення)' };

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
  /** Device shared by every pooled pass, once cross-pass consistency is
   *  confirmed — a divergent phone/car falls back to the «any phone» tier. */
  readonly phoneModel = signal<string | null>(null);
  /** Contract v3.1 identity shared by every pooled pass — the exact calibration key */
  readonly deviceId = signal<string | null>(null);
  readonly vehicleId = signal<string | null>(null);
  readonly phoneOptions = computed(
    () => phoneOptionsFor(this.phoneModel(), this.deviceId(), this.vehicleId()));

  /** Set when the passes share a vehicle_type but diverge on phone/device/car —
   *  the dialog falls back to the generic tier and shows this Ukrainian warning. */
  readonly identityWarning = signal<string | null>(null);
  /** Set when the passes themselves diverge on vehicle_type — a set from this
   *  aggregate cannot be attributed to one identity at all, so creation is blocked. */
  readonly identityBlocked = signal(false);
  readonly blockedMessage = MSG_MIXED_VEHICLE_TYPE;

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
        // An aggregate has no single run: every pooled pass is fetched so a
        // mixed-vehicle aggregate cannot silently inherit pass #1's identity.
        if (aggregate.run_ids.length) this.loadRunKeys(aggregate.run_ids);
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

  private loadRunKeys(runIds: number[]): void {
    const perRun = runIds.map(id => this.api.getRun(id).pipe(
      map((run: RunOut): RunKeys => ({
        vehicleType: run.summary?.vehicle_type ?? null,
        phoneModel: run.phone_model,
        deviceId: run.device_id,
        vehicleId: run.vehicle_id,
      })),
      // A missing run only costs its own contribution to the prefill — the
      // operator can still type the vehicle type, and a run that fails to load
      // must never look like a false consistency match with the others.
      catchError(() => of(null)),
    ));
    forkJoin(perRun).subscribe(results => {
      const keys = results.filter((k): k is RunKeys => k !== null);
      this.applyRunKeys(keys);
    });
  }

  /** Cross-pass consistency (spec: coefficient sets are attributed to one
   *  identity, never to whichever pass happened to be listed first):
   *   - identical (vehicle_type, phone/device, vehicle) on every pass -> prefill
   *     that one identity, unchanged from the single-pass behavior;
   *   - same vehicle_type but a diverging phone/device/vehicle -> fall back to
   *     the generic (vehicle_type-only) tier and warn;
   *   - vehicle_type itself diverges -> no identity applies at all, block
   *     creation from this aggregate entirely. */
  private applyRunKeys(keys: RunKeys[]): void {
    if (!keys.length) return;
    const vehicleTypes = new Set(keys.map(k => k.vehicleType ?? ''));
    if (vehicleTypes.size > 1) {
      this.identityBlocked.set(true);
      this.identityWarning.set(null);
      this.vehicleType.set('');
      this.phoneModel.set(null);
      this.deviceId.set(null);
      this.vehicleId.set(null);
      return;
    }
    this.identityBlocked.set(false);
    this.vehicleType.set(keys[0].vehicleType ?? '');

    const [first, ...rest] = keys;
    const sameIdentity = rest.every(k => k.phoneModel === first.phoneModel
      && k.deviceId === first.deviceId && k.vehicleId === first.vehicleId);
    if (sameIdentity) {
      this.phoneModel.set(first.phoneModel);
      this.deviceId.set(first.deviceId);
      this.vehicleId.set(first.vehicleId);
      this.identityWarning.set(null);
    } else {
      this.phoneModel.set(null);
      this.deviceId.set(null);
      this.vehicleId.set(null);
      this.identityWarning.set(MSG_MIXED_IDENTITY);
    }
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
