import { DatePipe } from '@angular/common';
import { Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { ApiService } from '../api/api.service';
import {
  AggregateOut, AggregateSummary, CoefficientSetOut, ComparisonOut, PreviewResolutionOut,
  ReferenceOut, RunOut,
} from '../api/dto';

const REFRESH_MS = 2000;
/** Only 10 m reference forms are comparable with 100 m analyzer segments */
const COMPARABLE_STEP_M = 10;
/** Server-side guard too (POST /aggregate-comparisons answers 422 below it) */
const MIN_AGGREGATE_RUNS = 2;

interface DeleteTarget {
  kind: 'reference' | 'comparison' | 'aggregate';
  id: number;
  label: string;
}

interface ReanalyzeTarget {
  set: CoefficientSetOut;
  candidates: number;
}

@Component({
  selector: 'app-calibration-page',
  imports: [DatePipe, RouterLink],
  templateUrl: './calibration-page.html',
  styleUrl: './calibration-page.css',
})
export class CalibrationPage {
  private readonly api = inject(ApiService);
  private readonly destroyRef = inject(DestroyRef);
  private timer: ReturnType<typeof setInterval> | null = null;

  readonly references = signal<ReferenceOut[]>([]);
  readonly comparisons = signal<ComparisonOut[]>([]);
  readonly aggregates = signal<AggregateOut[]>([]);
  readonly sets = signal<CoefficientSetOut[]>([]);
  readonly runs = signal<RunOut[]>([]);
  readonly error = signal<string | null>(null);
  readonly busy = signal(false);

  /** Reference upload row */
  readonly pendingFile = signal<File | null>(null);
  readonly measuredAt = signal('');

  /** «Нове порівняння» dialog */
  readonly comparisonOpen = signal(false);
  readonly selectedRunId = signal<number | null>(null);
  readonly selectedReferenceId = signal<number | null>(null);

  /** «Нове мультипроїзне порівняння» dialog */
  readonly aggregateOpen = signal(false);
  readonly aggregateReferenceId = signal<number | null>(null);
  readonly aggregateRunIds = signal<number[]>([]);

  /** Delete confirm dialog (references and comparisons share it) */
  readonly deleteTarget = signal<DeleteTarget | null>(null);

  /** Coefficient-set confirm → reanalyze chain */
  readonly confirmTarget = signal<CoefficientSetOut | null>(null);
  readonly confirmNote = signal('');
  /** Files the set being confirmed would apply to; null while the preview is
   *  in flight or after it failed (the confirm itself never depends on it). */
  readonly confirmPreview = signal<PreviewResolutionOut | null>(null);
  readonly reanalyzeTarget = signal<ReanalyzeTarget | null>(null);
  readonly createdRuns = signal<number | null>(null);
  /** Coefficient set id currently being archived, guarding against a double click */
  readonly archivingId = signal<number | null>(null);
  /** Reanalyze request in flight — a double click would queue 2N real analyzer runs */
  readonly reanalyzing = signal(false);

  /** Queue polling: comparisons and aggregates share ONE interval */
  private readonly comparisonsPending = signal(false);
  private readonly aggregatesPending = signal(false);

  readonly doneRuns = computed(() => this.runs().filter(run => run.status === 'done'));
  readonly comparableReferences = computed(() => this.references().filter(
    reference => reference.step_m === COMPARABLE_STEP_M && !reference.source_deleted));
  readonly canAggregate = computed(
    () => this.aggregateReferenceId() != null
      && this.aggregateRunIds().length >= MIN_AGGREGATE_RUNS);

  constructor() {
    this.reloadReferences();
    this.reloadComparisons();
    this.reloadAggregates();
    this.reloadSets();
    this.reloadRuns();
    this.destroyRef.onDestroy(() => this.stopTimer());
  }

  // --- loading -------------------------------------------------------------

  reloadReferences(): void {
    this.api.listReferences().subscribe({
      next: references => this.references.set(references),
      error: err => this.error.set(this.describe(err)),
    });
  }

  reloadComparisons(): void {
    this.api.listComparisons().subscribe({
      next: comparisons => {
        this.comparisons.set(comparisons);
        this.comparisonsPending.set(comparisons.some(comparison => this.pending(comparison.status)));
        this.syncTimer();
      },
      error: err => this.error.set(this.describe(err)),
    });
  }

  reloadAggregates(): void {
    this.api.listAggregates().subscribe({
      next: aggregates => {
        this.aggregates.set(aggregates);
        this.aggregatesPending.set(aggregates.some(aggregate => this.pending(aggregate.status)));
        this.syncTimer();
      },
      error: err => this.error.set(this.describe(err)),
    });
  }

  reloadSets(): void {
    this.api.listCoefficientSets().subscribe({
      next: sets => this.sets.set(sets),
      error: err => this.error.set(this.describe(err)),
    });
  }

  reloadRuns(): void {
    this.api.listRuns().subscribe({
      next: runs => this.runs.set(runs),
      error: err => this.error.set(this.describe(err)),
    });
  }

  // --- references ----------------------------------------------------------

  onFileInput(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.pendingFile.set(input.files?.length ? input.files[0] : null);
  }

  onMeasuredAtInput(event: Event): void {
    this.measuredAt.set((event.target as HTMLInputElement).value);
  }

  upload(input?: HTMLInputElement): void {
    const file = this.pendingFile();
    if (!file) return;
    const measuredAt = this.measuredAt().trim();
    this.busy.set(true);
    this.error.set(null);
    this.api.uploadReference(file, measuredAt || undefined).subscribe({
      next: () => {
        this.busy.set(false);
        this.pendingFile.set(null);
        this.measuredAt.set('');
        if (input) input.value = '';
        this.reloadReferences();
      },
      error: err => { this.busy.set(false); this.error.set(this.describe(err)); },
    });
  }

  warningsTitle(reference: ReferenceOut): string {
    return reference.parse_warnings.join('\n');
  }

  // --- comparisons ---------------------------------------------------------

  openComparison(): void {
    this.selectedRunId.set(this.doneRuns()[0]?.id ?? null);
    this.selectedReferenceId.set(this.comparableReferences()[0]?.id ?? null);
    this.comparisonOpen.set(true);
  }

  onRunSelect(event: Event): void {
    this.selectedRunId.set(Number((event.target as HTMLSelectElement).value));
  }

  onReferenceSelect(event: Event): void {
    this.selectedReferenceId.set(Number((event.target as HTMLSelectElement).value));
  }

  submitComparison(): void {
    const runId = this.selectedRunId();
    const referenceId = this.selectedReferenceId();
    if (runId == null || referenceId == null) return;
    this.comparisonOpen.set(false);
    this.error.set(null);
    this.api.createComparison(runId, referenceId).subscribe({
      next: () => this.reloadComparisons(),
      error: err => this.error.set(this.describe(err)),
    });
  }

  // --- aggregates ----------------------------------------------------------

  openAggregate(): void {
    this.aggregateReferenceId.set(this.comparableReferences()[0]?.id ?? null);
    this.aggregateRunIds.set([]);
    this.aggregateOpen.set(true);
  }

  onAggregateReferenceSelect(event: Event): void {
    this.aggregateReferenceId.set(Number((event.target as HTMLSelectElement).value));
  }

  toggleAggregateRun(runId: number): void {
    this.aggregateRunIds.update(ids => ids.includes(runId)
      ? ids.filter(id => id !== runId)
      : [...ids, runId]);
  }

  isAggregateRunSelected(runId: number): boolean {
    return this.aggregateRunIds().includes(runId);
  }

  submitAggregate(): void {
    const referenceId = this.aggregateReferenceId();
    const selected = this.aggregateRunIds();
    if (referenceId == null || selected.length < MIN_AGGREGATE_RUNS) return;
    // Submitted in the listing order, so the pooled pass list does not depend on
    // the order the operator happened to tick the boxes.
    const runIds = this.doneRuns().map(run => run.id).filter(id => selected.includes(id));
    this.aggregateOpen.set(false);
    this.error.set(null);
    this.api.createAggregate(referenceId, runIds).subscribe({
      next: () => this.reloadAggregates(),
      error: err => this.error.set(this.describe(err)),
    });
  }

  runFilenamesTitle(aggregate: AggregateOut): string {
    return aggregate.run_filenames.join('\n');
  }

  /** «−1.61 [−1.80; −1.42]», «—» when the job estimated no bias */
  biasWithCi(summary: AggregateSummary | null | undefined): string {
    if (summary?.bias == null) return '—';
    const low = summary.bias_ci_low;
    const high = summary.bias_ci_high;
    if (low == null || high == null) return this.signed(summary.bias);
    return `${this.signed(summary.bias)} [${this.signed(low)}; ${this.signed(high)}]`;
  }

  // --- delete --------------------------------------------------------------

  askDeleteReference(reference: ReferenceOut): void {
    this.deleteTarget.set({
      kind: 'reference', id: reference.id,
      label: `еталон «${reference.road_name}» (${reference.filename})`,
    });
  }

  askDeleteComparison(comparison: ComparisonOut): void {
    this.deleteTarget.set({
      kind: 'comparison', id: comparison.id,
      label: `порівняння #${comparison.id}`,
    });
  }

  askDeleteAggregate(aggregate: AggregateOut): void {
    this.deleteTarget.set({
      kind: 'aggregate', id: aggregate.id,
      label: `мультипроїзне порівняння #${aggregate.id}`,
    });
  }

  submitDelete(): void {
    const target = this.deleteTarget();
    if (!target) return;
    this.deleteTarget.set(null);
    this.error.set(null);
    const request = target.kind === 'reference'
      ? this.api.deleteReference(target.id)
      : target.kind === 'aggregate'
        ? this.api.deleteAggregate(target.id)
        : this.api.deleteComparison(target.id);
    request.subscribe({
      next: () => {
        if (target.kind === 'reference') {
          this.reloadReferences();
        } else if (target.kind === 'aggregate') {
          // Deleting an aggregate detaches its coefficient sets (backend nulls
          // aggregate_comparison_id) — refresh the sets table too.
          this.reloadAggregates();
          this.reloadSets();
        } else {
          // Deleting a comparison detaches any coefficient sets that referenced it
          // (backend nulls comparison_id) — refresh the sets table too.
          this.reloadComparisons();
          this.reloadSets();
        }
      },
      error: err => this.error.set(this.describe(err)),
    });
  }

  // --- coefficient sets ----------------------------------------------------

  openConfirm(set: CoefficientSetOut): void {
    this.confirmNote.set('');
    this.createdRuns.set(null);
    this.confirmPreview.set(null);
    this.confirmTarget.set(set);
    // A set whose key matches no uploaded file resolves for nothing — the count
    // makes that visible before the confirm, without blocking it.
    this.api.previewResolution({
      model: set.model, vehicle_type: set.vehicle_type, phone_model: set.phone_model,
    }).subscribe({
      next: preview => this.confirmPreview.set(preview),
      // A failed preview must not stand in the way of the decision
      error: () => undefined,
    });
  }

  previewFilesTitle(): string {
    return (this.confirmPreview()?.filenames ?? []).join('\n');
  }

  onNoteInput(event: Event): void {
    this.confirmNote.set((event.target as HTMLTextAreaElement).value);
  }

  submitConfirm(): void {
    const target = this.confirmTarget();
    if (!target) return;
    const note = this.confirmNote().trim();
    this.confirmTarget.set(null);
    this.error.set(null);
    this.api.confirmCoefficientSet(target.id, note || undefined).subscribe({
      next: result => {
        this.reloadSets();
        if (result.reanalyze_candidates > 0) {
          this.reanalyzeTarget.set({
            set: result.set, candidates: result.reanalyze_candidates,
          });
        }
      },
      error: err => this.error.set(this.describe(err)),
    });
  }

  submitReanalyze(): void {
    const target = this.reanalyzeTarget();
    if (!target || this.reanalyzing()) return;
    this.reanalyzing.set(true);
    this.error.set(null);
    this.api.reanalyzeCoefficientSet(target.set.id).subscribe({
      next: runs => {
        // Clear only on success — a failed request keeps the dialog open so the
        // operator can retry instead of losing the reanalyze offer.
        this.reanalyzing.set(false);
        this.reanalyzeTarget.set(null);
        this.createdRuns.set(runs.length);
        this.reloadRuns();
      },
      error: err => {
        this.reanalyzing.set(false);
        this.error.set(this.describe(err));
      },
    });
  }

  archive(set: CoefficientSetOut): void {
    if (this.archivingId() !== null) return;
    this.archivingId.set(set.id);
    this.error.set(null);
    this.api.archiveCoefficientSet(set.id).subscribe({
      next: () => { this.archivingId.set(null); this.reloadSets(); },
      error: err => { this.archivingId.set(null); this.error.set(this.describe(err)); },
    });
  }

  paramsText(set: CoefficientSetOut): string {
    const parts: string[] = [];
    for (const key of ['A', 'B', 'bias'] as const) {
      const value = set.params[key];
      if (value != null) parts.push(`${key}=${value.toFixed(3)}`);
    }
    return parts.length ? parts.join(', ') : '—';
  }

  statText(set: CoefficientSetOut, key: string): string {
    return this.fmt(set.stats_snapshot?.[key]);
  }

  fmt(value: number | null | undefined, digits = 2): string {
    return value == null ? '—' : value.toFixed(digits);
  }

  signed(value: number, digits = 2): string {
    return (value < 0 ? '−' : '') + Math.abs(value).toFixed(digits);
  }

  private pending(status: string): boolean {
    return status === 'queued' || status === 'running';
  }

  /** One interval for both queues: started while either has pending work,
   *  stopped as soon as neither does. */
  private syncTimer(): void {
    const active = this.comparisonsPending() || this.aggregatesPending();
    if (active && this.timer === null) {
      this.timer = setInterval(() => this.poll(), REFRESH_MS);
    } else if (!active) {
      this.stopTimer();
    }
  }

  private poll(): void {
    if (this.comparisonsPending()) this.reloadComparisons();
    if (this.aggregatesPending()) this.reloadAggregates();
  }

  private stopTimer(): void {
    if (this.timer !== null) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }

  private describe(err: { error?: { detail?: string }; message?: string }): string {
    return err?.error?.detail ?? err?.message ?? 'Невідома помилка';
  }
}
