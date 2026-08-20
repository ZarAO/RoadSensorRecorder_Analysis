import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, DestroyRef, inject, signal } from '@angular/core';
import { DomSanitizer, SafeHtml, SafeResourceUrl } from '@angular/platform-browser';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { marked } from 'marked';

import { ApiService } from '../api/api.service';
import { RunOut, SegmentRow } from '../api/dto';
import { CountUp } from '../shared/count-up';

const PLOTS = [
  'speed_vs_distance', 'accel_vs_distance', 'metrics_vs_distance',
  'iri_psd_vs_distance',
];
const REFRESH_MS = 2000;

@Component({
  selector: 'app-run-detail',
  imports: [DatePipe, DecimalPipe, RouterLink, CountUp],
  templateUrl: './run-detail.html',
  styleUrl: './run-detail.css',
})
export class RunDetail {
  private readonly api = inject(ApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly sanitizer = inject(DomSanitizer);
  private readonly destroyRef = inject(DestroyRef);

  private eventSource: EventSource | null = null;
  private timer: ReturnType<typeof setInterval> | null = null;

  readonly runId = Number(this.route.snapshot.paramMap.get('id'));
  readonly run = signal<RunOut | null>(null);
  readonly segments = signal<SegmentRow[]>([]);
  readonly reportHtml = signal<SafeHtml | null>(null);
  readonly mapUrl = signal<SafeResourceUrl | null>(null);
  readonly logLines = signal<string[]>([]);
  readonly plots = PLOTS;

  constructor() {
    this.load();
    this.destroyRef.onDestroy(() => this.cleanup());
  }

  artifactUrl(name: string): string {
    return this.api.artifactUrl(this.runId, name);
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
    this.mapUrl.set(this.sanitizer.bypassSecurityTrustResourceUrl(
      this.artifactUrl('segments_map.html')));
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
