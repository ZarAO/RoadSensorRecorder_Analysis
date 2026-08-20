import { DatePipe } from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { ApiService } from '../api/api.service';
import { GeoJsonFeatureCollection, ReferenceIntervalRow, ReferenceOut } from '../api/dto';
import { LineSeries, MultiLineChart } from '../shared/charts/multi-line-chart';
import { SegmentMap } from '../shared/segment-map';

const PAGE_SIZE = 200;
/** iri_ref (and the table's channel range) is computed from ch1..8 only —
 *  ch9/10 duplicate ch8 (see reference_forms.parse_form_xlsx). */
const RANGE_CHANNELS = [1, 2, 3, 4, 5, 6, 7, 8] as const;

interface IntervalRow {
  interval_id: number;
  chainage_km: number;
  iri_ref: number | null;
  channel_range: string;
}

@Component({
  selector: 'app-reference-detail',
  imports: [DatePipe, RouterLink, SegmentMap, MultiLineChart],
  templateUrl: './reference-detail.html',
  styleUrl: './reference-detail.css',
})
export class ReferenceDetail {
  private readonly api = inject(ApiService);
  private readonly route = inject(ActivatedRoute);

  readonly referenceId = Number(this.route.snapshot.paramMap.get('id'));
  readonly reference = signal<ReferenceOut | null>(null);
  readonly geo = signal<GeoJsonFeatureCollection | null>(null);
  readonly intervals = signal<ReferenceIntervalRow[]>([]);
  readonly error = signal<string | null>(null);
  readonly loading = signal(true);

  readonly page = signal(0);

  readonly rows = computed<IntervalRow[]>(() => this.intervals().map((row, index) => ({
    interval_id: index,
    chainage_km: this.chainageMid(row) / 1000,
    iri_ref: row.iri_ref,
    channel_range: this.channelRange(row),
  })));

  readonly pageCount = computed(() => Math.max(1, Math.ceil(this.rows().length / PAGE_SIZE)));

  readonly pageRows = computed(() => {
    const start = this.page() * PAGE_SIZE;
    return this.rows().slice(start, start + PAGE_SIZE);
  });

  /** «N–M з K», 1-based and inclusive; «0–0 з 0» when there is nothing to page. */
  readonly pageLabel = computed(() => {
    const total = this.rows().length;
    if (!total) return '0–0 з 0';
    const start = this.page() * PAGE_SIZE + 1;
    const end = Math.min(total, start + PAGE_SIZE - 1);
    return `${start}–${end} з ${total}`;
  });

  readonly profileSeries = computed<LineSeries[]>(() => {
    const points = this.intervals()
      .filter(row => row.iri_ref != null)
      .map(row => ({ x: this.chainageMid(row) / 1000, y: row.iri_ref as number }));
    return [{ label: 'IRI профілометра (сер. кан. 1–8)', colorVar: '--color-fg', points }];
  });

  constructor() {
    this.api.getReference(this.referenceId).subscribe({
      next: reference => { this.loading.set(false); this.reference.set(reference); },
      error: err => { this.loading.set(false); this.error.set(this.describe(err)); },
    });
    this.api.getReferenceGeojson(this.referenceId).subscribe({
      next: geo => this.geo.set(geo),
      error: () => this.geo.set(null),
    });
    this.api.getReferenceIntervals(this.referenceId).subscribe({
      next: intervals => this.intervals.set(intervals),
      error: err => this.error.set(this.describe(err)),
    });
  }

  prevPage(): void {
    this.page.update(current => Math.max(0, current - 1));
  }

  nextPage(): void {
    this.page.update(current => Math.min(this.pageCount() - 1, current + 1));
  }

  fmt(value: number | null | undefined, digits = 2): string {
    return value == null ? '—' : value.toFixed(digits);
  }

  /** Chainage midpoint in meters — the same convention build_reference_geojson
   *  uses for chainage_m, so the table and the chart/map agree. */
  private chainageMid(row: ReferenceIntervalRow): number {
    const start = row.km_start * 1000 + row.m_start;
    const end = row.km_end * 1000 + row.m_end;
    return (start + end) / 2;
  }

  private channelRange(row: ReferenceIntervalRow): string {
    const values = RANGE_CHANNELS
      .map(channel => row[`iri_ch${channel}` as keyof ReferenceIntervalRow] as number | null)
      .filter((value): value is number => value != null);
    if (!values.length) return '—';
    return `${Math.min(...values).toFixed(2)}–${Math.max(...values).toFixed(2)}`;
  }

  private describe(err: { error?: { detail?: string }; message?: string }): string {
    return err?.error?.detail ?? err?.message ?? 'Невідома помилка';
  }
}
