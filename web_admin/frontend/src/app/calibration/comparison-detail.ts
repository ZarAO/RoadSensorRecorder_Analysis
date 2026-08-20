import { DatePipe } from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { ApiService } from '../api/api.service';
import { ChartData, CoefficientSetOut, ComparisonOut } from '../api/dto';
import { BaChart } from '../shared/charts/ba-chart';
import { ProfileChart } from '../shared/charts/profile-chart';
import { ScatterChart } from '../shared/charts/scatter-chart';
import { CountUp } from '../shared/count-up';

/** Human-facing indicators, mirroring GATE_R2_MIN / GATE_MAE_MAX in the backend */
const GATE_R2_MIN = 0.85;
const GATE_MAE_MAX = 0.5;
/** Share of the largest |diff| rows highlighted in the pairs table */
const HOT_SHARE = 0.1;

/** Figures with a stable filename. fig3_chainage_<slug> carries the road name in
 *  its filename, so it has no fixed URL and stays a directory artifact. */
const FIGURES = [
  { name: 'fig1_scatter_eq3_fit', label: 'Рис. 1 — розсіювання та фіт Eq.3' },
  { name: 'fig2a_bland_altman_before', label: 'Рис. 2a — Бленд-Альтман до корекції' },
  { name: 'fig2b_bland_altman_corrected', label: 'Рис. 2b — Бленд-Альтман після корекції' },
] as const;

interface PairRow {
  seg_id: number;
  chainage_km: number;
  iri_ref: number;
  iri_multi: number;
  diff: number;
  /** Top-10% |diff| row — highlighted, computed over the whole table */
  hot: boolean;
}

@Component({
  selector: 'app-comparison-detail',
  imports: [DatePipe, RouterLink, CountUp, ScatterChart, ProfileChart, BaChart],
  templateUrl: './comparison-detail.html',
  styleUrl: './comparison-detail.css',
})
export class ComparisonDetail {
  private readonly api = inject(ApiService);
  private readonly route = inject(ActivatedRoute);

  readonly comparisonId = Number(this.route.snapshot.paramMap.get('id'));
  readonly comparison = signal<ComparisonOut | null>(null);
  readonly chart = signal<ChartData | null>(null);
  readonly error = signal<string | null>(null);
  readonly loading = signal(true);
  readonly figures = FIGURES;

  /** Cross-chart selection: scatter dot ↔ pairs-table row */
  readonly selectedSegId = signal<number | null>(null);
  /** Chainage range in km from the profile brush; null = whole run */
  readonly brushRange = signal<[number, number] | null>(null);

  /** «Створити набір коефіцієнтів» dialog */
  readonly setOpen = signal(false);
  readonly setModel = signal<'eq3' | 'eq6_bias'>('eq6_bias');
  readonly setName = signal('');
  readonly vehicleType = signal('');
  readonly phoneModel = signal('');
  readonly submitting = signal(false);
  readonly createdSet = signal<CoefficientSetOut | null>(null);
  /** Creation errors live inside the dialog — the page banner sits under the backdrop */
  readonly createError = signal<string | null>(null);
  private readonly nameTouched = signal(false);

  readonly summary = computed(() => this.comparison()?.summary ?? null);

  /** A degenerate Eq.3 fit (null A/B) blocks the fit line, the formula and the eq3 model */
  readonly fitDegenerate = computed(() => {
    const fit = this.chart()?.eq3_fit;
    return !fit || fit.A == null || fit.B == null;
  });

  readonly r2 = computed(() => this.summary()?.eq3_r2 ?? this.chart()?.eq3_fit.r2 ?? null);
  readonly r2Pass = computed(() => (this.r2() ?? 0) >= GATE_R2_MIN);

  /** MAE of the bias-corrected IRI: |diff − bias| straight off the Bland-Altman points */
  readonly correctedMae = computed(() => {
    const chart = this.chart();
    if (!chart?.bland_altman.length) return null;
    const total = chart.bland_altman.reduce(
      (sum, point) => sum + Math.abs(point.diff - chart.bias), 0);
    return total / chart.bland_altman.length;
  });
  readonly maePass = computed(() => (this.correctedMae() ?? Infinity) <= GATE_MAE_MAX);

  /** 95% limits of agreement — bias ± 1.96·sd(diff), computed here to keep the DTO thin */
  readonly loa = computed<[number, number]>(() => {
    const chart = this.chart();
    const bias = chart?.bias ?? 0;
    const diffs = chart?.bland_altman.map(point => point.diff) ?? [];
    if (diffs.length < 2) return [bias, bias];
    const mean = diffs.reduce((sum, value) => sum + value, 0) / diffs.length;
    const variance = diffs.reduce(
      (sum, value) => sum + (value - mean) ** 2, 0) / (diffs.length - 1);
    const sd = Math.sqrt(variance);
    return [bias - 1.96 * sd, bias + 1.96 * sd];
  });

  readonly pairs = computed<PairRow[]>(() => {
    const chart = this.chart();
    if (!chart) return [];
    const chainage = new Map(chart.profile.map(point => [point.seg_id, point.chainage_m]));
    const rows = chart.scatter.map(point => ({
      seg_id: point.seg_id,
      chainage_km: (chainage.get(point.seg_id) ?? point.chainage_m) / 1000,
      iri_ref: point.iri_ref,
      iri_multi: point.iri_multi,
      diff: point.iri_multi - point.iri_ref,
      hot: false,
    })).sort((a, b) => Math.abs(b.diff) - Math.abs(a.diff));
    const hotCount = Math.ceil(rows.length * HOT_SHARE);
    return rows.map((row, index) => ({ ...row, hot: index < hotCount }));
  });

  readonly visiblePairs = computed(() => {
    const range = this.brushRange();
    if (!range) return this.pairs();
    return this.pairs().filter(
      row => row.chainage_km >= range[0] && row.chainage_km <= range[1]);
  });

  /** Substituted Eq.3 formula parts, or null when the fit is degenerate */
  readonly eq3Formula = computed(() => {
    const fit = this.chart()?.eq3_fit;
    if (!fit || fit.A == null || fit.B == null) return null;
    return { a: fit.A.toFixed(2), sign: fit.B < 0 ? '−' : '+', b: Math.abs(fit.B).toFixed(2) };
  });

  readonly biasText = computed(() => {
    const bias = this.chart()?.bias;
    return bias == null ? '—' : this.signed(bias);
  });

  readonly canCreate = computed(
    () => !!this.setName().trim() && !!this.vehicleType().trim() && !this.submitting());

  constructor() {
    this.api.getComparison(this.comparisonId).subscribe({
      next: comparison => {
        this.loading.set(false);
        this.comparison.set(comparison);
        if (comparison.status === 'done') this.loadChart();
        this.loadVehicleType(comparison.run_id);
      },
      error: err => { this.loading.set(false); this.error.set(this.describe(err)); },
    });
  }

  private loadChart(): void {
    this.api.getComparisonChartData(this.comparisonId).subscribe({
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

  // --- interaction ---------------------------------------------------------

  selectSeg(segId: number): void {
    this.selectedSegId.update(current => (current === segId ? null : segId));
  }

  onRange(range: [number, number] | null): void {
    this.brushRange.set(range);
  }

  figureUrl(name: string, extension: 'png' | 'pdf'): string {
    return this.api.comparisonArtifactUrl(this.comparisonId, `figures/${name}.${extension}`);
  }

  // --- coefficient-set dialog ---------------------------------------------

  openSetDialog(): void {
    this.setModel.set('eq6_bias');
    this.nameTouched.set(false);
    this.setName.set(this.defaultName('eq6_bias'));
    this.phoneModel.set('');
    this.createdSet.set(null);
    this.createError.set(null);
    this.setOpen.set(true);
  }

  selectModel(model: 'eq3' | 'eq6_bias'): void {
    if (model === 'eq3' && this.fitDegenerate()) return;
    this.setModel.set(model);
    if (!this.nameTouched()) this.setName.set(this.defaultName(model));
  }

  onNameInput(event: Event): void {
    this.nameTouched.set(true);
    this.setName.set((event.target as HTMLInputElement).value);
  }

  onVehicleInput(event: Event): void {
    this.vehicleType.set((event.target as HTMLInputElement).value);
    if (!this.nameTouched()) this.setName.set(this.defaultName(this.setModel()));
  }

  onPhoneInput(event: Event): void {
    this.phoneModel.set((event.target as HTMLInputElement).value);
  }

  submitCreate(): void {
    const comparison = this.comparison();
    if (!comparison || !this.canCreate()) return;
    this.submitting.set(true);
    this.createError.set(null);
    this.api.createCoefficientSet({
      comparison_id: comparison.id,
      model: this.setModel(),
      name: this.setName().trim(),
      vehicle_type: this.vehicleType().trim(),
      phone_model: this.phoneModel().trim() || null,
    }).subscribe({
      next: set => {
        this.submitting.set(false);
        this.setOpen.set(false);
        this.createdSet.set(set);
      },
      // The dialog stays open so the operator can fix the name (a same-day repeat
      // collides with the deterministic default) and retry.
      error: err => { this.submitting.set(false); this.createError.set(this.describe(err)); },
    });
  }

  /** `{{model}}_{{vehicle_type}}_{{yyyy-MM-dd}}`, dated from created_at so the
   *  suggestion is reproducible instead of drifting with the wall clock. */
  private defaultName(model: string): string {
    const vehicle = this.vehicleType().trim() || 'unknown';
    const parts = [model, vehicle, this.createdDate()].filter(part => part);
    return parts.join('_');
  }

  private createdDate(): string {
    const created = this.comparison()?.created_at;
    const parsed = created ? new Date(created) : null;
    return parsed && !Number.isNaN(parsed.getTime()) ? parsed.toISOString().slice(0, 10) : '';
  }

  fmt(value: number | null | undefined, digits = 2): string {
    return value == null ? '—' : value.toFixed(digits);
  }

  signed(value: number, digits = 2): string {
    return (value < 0 ? '−' : '') + Math.abs(value).toFixed(digits);
  }

  private describe(err: { error?: { detail?: string }; message?: string }): string {
    return err?.error?.detail ?? err?.message ?? 'Невідома помилка';
  }
}
