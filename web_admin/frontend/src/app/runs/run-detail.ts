import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { marked } from 'marked';

import { ApiService } from '../api/api.service';
import {
  ArtifactEntry, ComparisonOut, GeoJsonFeatureCollection, RunOut, SegmentRow,
} from '../api/dto';
import { CountUp } from '../shared/count-up';
import { SegmentMap } from '../shared/segment-map';

const PLOTS = [
  'speed_vs_distance', 'accel_vs_distance', 'metrics_vs_distance',
  'iri_psd_vs_distance',
];
const REFRESH_MS = 2000;

/** Older runs may have no roughness.geojson artifact — then there is no map */
function parseFeatureCollection(text: string): GeoJsonFeatureCollection | null {
  try {
    const parsed = JSON.parse(text) as GeoJsonFeatureCollection;
    return Array.isArray(parsed?.features) ? parsed : null;
  } catch {
    return null;
  }
}

@Component({
  selector: 'app-run-detail',
  imports: [DatePipe, DecimalPipe, RouterLink, CountUp, SegmentMap],
  templateUrl: './run-detail.html',
  styleUrl: './run-detail.css',
})
export class RunDetail {
  private readonly api = inject(ApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly sanitizer = inject(DomSanitizer);
  private readonly destroyRef = inject(DestroyRef);

  private eventSource: EventSource | null = null;
  private timer: ReturnType<typeof setInterval> | null = null;

  readonly runId = Number(this.route.snapshot.paramMap.get('id'));
  readonly run = signal<RunOut | null>(null);
  readonly segments = signal<SegmentRow[]>([]);
  readonly reportHtml = signal<SafeHtml | null>(null);
  readonly mapData = signal<GeoJsonFeatureCollection | null>(null);
  readonly logLines = signal<string[]>([]);
  readonly artifacts = signal<ArtifactEntry[]>([]);
  readonly comparisons = signal<ComparisonOut[]>([]);
  readonly plots = PLOTS;

  /** Every done run of the same file (including this one) — feeds the
   *  «Порівняти з іншим раном» button and its dialog's run list. */
  readonly siblingDoneRuns = signal<RunOut[]>([]);
  readonly compareOpen = signal(false);
  readonly compareTargetId = signal<number | null>(null);

  readonly otherDoneRuns = computed(
    () => this.siblingDoneRuns().filter(run => run.id !== this.runId));
  /** The button needs the CURRENT run done too -- a queued/running/failed run
   *  has no artifacts to compare and would 409 at the endpoint. */
  readonly canCompare = computed(
    () => this.run()?.status === 'done' && this.otherDoneRuns().length > 0);

  /** Whether any segment carries a corrected IRI — gates the extra table column */
  readonly hasCorrectedIri = computed(() =>
    this.segments().some(row => row.iri_multi_corrected != null));

  /** Coefficient sets applied to this run, for the header chip row. Empty when
   *  the run used book constants (no confirmed calibration set). */
  readonly coefficientChips = computed(() => {
    const coefficients = this.run()?.params?.coefficients;
    const chips: Array<{ model: string; name: string; label: string }> = [];
    if (coefficients?.eq3) {
      chips.push({
        model: 'eq3',
        name: coefficients.eq3.name,
        label: this.formatCoefficientParams(coefficients.eq3.params),
      });
    }
    if (coefficients?.eq6_bias) {
      chips.push({
        model: 'eq6_bias',
        name: coefficients.eq6_bias.name,
        label: this.formatCoefficientParams(coefficients.eq6_bias.params),
      });
    }
    return chips;
  });

  constructor() {
    this.load();
    this.destroyRef.onDestroy(() => this.cleanup());
  }

  artifactUrl(name: string): string {
    return this.api.artifactUrl(this.runId, name);
  }

  formatSize(bytes: number): string {
    const kb = bytes / 1024;
    if (kb < 1024) return `${kb.toFixed(2)} KB`;
    return `${(kb / 1024).toFixed(2)} MB`;
  }

  /** Low-speed invariant: never render a number where the metric is not defined */
  iriMultiLabel(row: SegmentRow): string {
    if (row.iri_multi != null) return row.iri_multi.toFixed(2);
    if (row.needs_class12_survey) return '— (невалідна швидкість)';
    return '—';
  }

  private load(): void {
    this.api.getRun(this.runId).subscribe({
      next: run => {
        this.run.set(run);
        this.api.listRuns(run.file_id).subscribe({
          next: runs => this.siblingDoneRuns.set(runs.filter(r => r.status === 'done')),
        });
        if (run.status === 'queued' || run.status === 'running') {
          this.followLog();
          this.pollStatus();
        } else {
          this.cleanup();
          if (run.status === 'done') this.loadResults();
        }
      },
    });
  }

  openCompare(): void {
    this.compareTargetId.set(this.otherDoneRuns()[0]?.id ?? null);
    this.compareOpen.set(true);
  }

  onCompareTargetSelect(event: Event): void {
    this.compareTargetId.set(Number((event.target as HTMLSelectElement).value));
  }

  submitCompare(): void {
    const otherId = this.compareTargetId();
    if (otherId == null) return;
    this.compareOpen.set(false);
    this.router.navigate(['/runs', this.runId, 'compare', otherId]);
  }

  private loadResults(): void {
    this.api.getSegments(this.runId).subscribe({
      next: rows => this.segments.set(rows),
    });
    this.api.getArtifactText(this.runId, 'report.md').subscribe({
      next: md => {
        // Our own backend's file: rendering, not untrusted input
        const html = marked.parse(md, { async: false });
        this.reportHtml.set(this.sanitizer.bypassSecurityTrustHtml(html));
      },
    });
    this.api.getArtifactText(this.runId, 'roughness.geojson').subscribe({
      next: text => this.mapData.set(parseFeatureCollection(text)),
      error: () => this.mapData.set(null),
    });
    this.api.listRunArtifacts(this.runId).subscribe({
      next: entries => this.artifacts.set(entries),
    });
    this.api.listComparisons(this.runId).subscribe({
      next: comparisons => this.comparisons.set(comparisons),
    });
  }

  /** Same 3-decimal rounding as the calibration table — raw floats print as
   *  -1.5499999999999998 in a chip. */
  private formatCoefficientParams(params: { A?: number; B?: number; bias?: number }): string {
    if (params.bias != null) return `bias=${params.bias.toFixed(3)}`;
    if (params.A != null && params.B != null) {
      return `A=${params.A.toFixed(3)}, B=${params.B.toFixed(3)}`;
    }
    return '';
  }

  private followLog(): void {
    if (this.eventSource) return;
    this.eventSource = new EventSource(this.api.logUrl(this.runId));
    this.eventSource.onmessage = event =>
      this.logLines.update(lines => [...lines, event.data as string]);
    this.eventSource.addEventListener('done', () => this.cleanup());
  }

  private pollStatus(): void {
    if (this.timer) return;
    this.timer = setInterval(() => {
      this.api.getRun(this.runId).subscribe({
        next: run => {
          this.run.set(run);
          if (run.status === 'done' || run.status === 'failed') {
            this.cleanup();
            if (run.status === 'done') this.loadResults();
          }
        },
      });
    }, REFRESH_MS);
  }

  private cleanup(): void {
    this.eventSource?.close();
    this.eventSource = null;
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }
}
