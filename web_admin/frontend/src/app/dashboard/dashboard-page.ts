import { DecimalPipe } from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { ApiService } from '../api/api.service';
import { DashboardOut } from '../api/dto';
import { CountUp } from '../shared/count-up';

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

  readonly maxBinCount = computed(() => {
    const bins = this.data()?.iri_histogram ?? [];
    return Math.max(1, ...bins.map(b => b.count));
  });

  readonly maxWorstIri = computed(() => {
    const worst = this.data()?.worst_segments ?? [];
    return Math.max(1e-9, ...worst.map(s => s.iri_psd));
  });

  readonly totalBinned = computed(() =>
    (this.data()?.iri_histogram ?? []).reduce((sum, b) => sum + b.count, 0));

  constructor() {
    this.api.getDashboard().subscribe({
      next: d => { this.data.set(d); this.loading.set(false); },
      error: () => this.loading.set(false),
    });
  }
}
