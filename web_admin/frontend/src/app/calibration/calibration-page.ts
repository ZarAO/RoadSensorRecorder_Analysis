import { DatePipe } from '@angular/common';
import { Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { ApiService } from '../api/api.service';
import { CoefficientSetOut, ComparisonOut, ReferenceOut, RunOut } from '../api/dto';

const REFRESH_MS = 2000;
/** Only 10 m reference forms are comparable with 100 m analyzer segments */
const COMPARABLE_STEP_M = 10;

interface DeleteTarget {
  kind: 'reference' | 'comparison';
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

  /** Delete confirm dialog (references and comparisons share it) */
  readonly deleteTarget = signal<DeleteTarget | null>(null);

  /** Coefficient-set confirm → reanalyze chain */
  readonly confirmTarget = signal<CoefficientSetOut | null>(null);
  readonly confirmNote = signal('');
  readonly reanalyzeTarget = signal<ReanalyzeTarget | null>(null);
  readonly createdRuns = signal<number | null>(null);

  readonly doneRuns = computed(() => this.runs().filter(run => run.status === 'done'));
  readonly comparableReferences = computed(() => this.references().filter(
    reference => reference.step_m === COMPARABLE_STEP_M && !reference.source_deleted));

  constructor() {
    this.reloadReferences();
    this.reloadComparisons();
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
        // Poll while anything is still moving through the queue
        const active = comparisons.some(
          comparison => comparison.status === 'queued' || comparison.status === 'running');
        if (active && this.timer === null) {
          this.timer = setInterval(() => this.reloadComparisons(), REFRESH_MS);
        } else if (!active) {
          this.stopTimer();
        }
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
    this.error.set(null);
    this.api.createComparison(runId, referenceId).subscribe({
      next: () => { this.comparisonOpen.set(false); this.reloadComparisons(); },
      error: err => { this.comparisonOpen.set(false); this.error.set(this.describe(err)); },
    });
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

  submitDelete(): void {
    const target = this.deleteTarget();
    if (!target) return;
    this.deleteTarget.set(null);
    this.error.set(null);
    const request = target.kind === 'reference'
      ? this.api.deleteReference(target.id)
      : this.api.deleteComparison(target.id);
    request.subscribe({
      next: () => {
        if (target.kind === 'reference') this.reloadReferences();
        else this.reloadComparisons();
      },
      error: err => this.error.set(this.describe(err)),
    });
  }

  // --- coefficient sets ----------------------------------------------------

  openConfirm(set: CoefficientSetOut): void {
    this.confirmNote.set('');
    this.createdRuns.set(null);
    this.confirmTarget.set(set);
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
    if (!target) return;
    this.reanalyzeTarget.set(null);
    this.error.set(null);
    this.api.reanalyzeCoefficientSet(target.set.id).subscribe({
      next: runs => { this.createdRuns.set(runs.length); this.reloadRuns(); },
      error: err => this.error.set(this.describe(err)),
    });
  }

  archive(set: CoefficientSetOut): void {
    this.error.set(null);
    this.api.archiveCoefficientSet(set.id).subscribe({
      next: () => this.reloadSets(),
      error: err => this.error.set(this.describe(err)),
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
