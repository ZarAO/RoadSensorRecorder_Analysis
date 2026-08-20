import { Component, computed, inject, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';

import { ApiService } from '../api/api.service';
import { DashboardOut, GeoJsonFeatureCollection } from '../api/dto';
import { CountUp } from '../shared/count-up';
import { SegmentMap } from '../shared/segment-map';

@Component({
  selector: 'app-global-map-page',
  imports: [CountUp, RouterLink, SegmentMap],
  templateUrl: './global-map-page.html',
  styleUrl: './global-map-page.css',
})
export class GlobalMapPage {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);

  readonly busy = signal(false);
  readonly loading = signal(true);
  readonly fc = signal<GeoJsonFeatureCollection | null>(null);
  readonly stats = signal<DashboardOut | null>(null);

  readonly featureCount = computed(() => this.fc()?.features.length ?? null);

  constructor() {
    this.api.getDashboard().subscribe({ next: d => this.stats.set(d) });
    this.api.getGlobalMap().subscribe({
      next: fc => { this.loading.set(false); this.fc.set(fc); },
      error: () => this.loading.set(false),
    });
  }

  rebuild(): void {
    this.busy.set(true);
    this.api.rebuildGlobalMap().subscribe({
      next: fc => { this.busy.set(false); this.fc.set(fc); },
      error: () => this.busy.set(false),
    });
  }

  goToRun(runId: number): void {
    this.router.navigate(['/runs', runId]);
  }
}
