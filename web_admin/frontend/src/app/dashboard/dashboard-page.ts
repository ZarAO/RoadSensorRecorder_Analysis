import { DecimalPipe } from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { ApiService } from '../api/api.service';
import { DashboardOut, IriHistogramBin } from '../api/dto';
import { CountUp } from '../shared/count-up';

const UNKNOWN_VEHICLE_TYPE = 'невідомо';

/** The subset of DashboardOut/VehicleTypeStats the KPI cards + histogram bind
 *  to; «Всі» reads it straight off DashboardOut, unchanged. */
interface DashboardView {
  files_total: number;
  runs_done: number;
  km_total: number;
  low_speed_total: number;
  iri_histogram: IriHistogramBin[];
}

@Component({
  selector: 'app-dashboard-page',
  imports: [DecimalPipe, RouterLink, CountUp],
  templateUrl: './dashboard-page.html',
  styleUrl: './dashboard-page.css',
})
export class DashboardPage {
  private readonly api = inject(ApiService);

  readonly data = signal<DashboardOut | null>(null);
  readonly loading = signal(true);
  /** null = «Всі» (the global totals); otherwise a by_vehicle_type key. */
  readonly selectedType = signal<string | null>(null);

  readonly vehicleTypeKeys = computed(() => Object.keys(this.data()?.by_vehicle_type ?? {}));

  /** One key that is 'невідомо' is a trivial breakdown (nothing to compare
   *  against) — not worth a chips row. */
  readonly showTypeChips = computed(() => {
    const keys = this.vehicleTypeKeys();
    return !(keys.length === 0 || (keys.length === 1 && keys[0] === UNKNOWN_VEHICLE_TYPE));
  });

  readonly view = computed<DashboardView | null>(() => {
    const d = this.data();
    if (!d) return null;
    const type = this.selectedType();
    if (type === null) return d;
    return d.by_vehicle_type[type] ?? null;
  });

  readonly maxBinCount = computed(() => {
    const bins = this.view()?.iri_histogram ?? [];
    return Math.max(1, ...bins.map(b => b.count));
  });

  readonly maxWorstIri = computed(() => {
    const worst = this.data()?.worst_segments ?? [];
    return Math.max(1e-9, ...worst.map(s => s.iri_psd));
  });

  readonly totalBinned = computed(() =>
    (this.view()?.iri_histogram ?? []).reduce((sum, b) => sum + b.count, 0));

  constructor() {
    this.api.getDashboard().subscribe({
      next: d => { this.data.set(d); this.loading.set(false); },
      error: () => this.loading.set(false),
    });
  }

  selectType(type: string | null): void {
    this.selectedType.set(type);
  }
}
