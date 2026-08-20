import { DecimalPipe } from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { ApiService } from '../api/api.service';
import { DashboardOut } from '../api/dto';

@Component({
  selector: 'app-dashboard-page',
  imports: [DecimalPipe, RouterLink],
  templateUrl: './dashboard-page.html',
  styleUrl: './dashboard-page.css',
})
export class DashboardPage {
  private readonly api = inject(ApiService);

  readonly data = signal<DashboardOut | null>(null);

  readonly maxBinCount = computed(() => {
    const bins = this.data()?.iri_histogram ?? [];
    return Math.max(1, ...bins.map(b => b.count));
  });

  constructor() {
    this.api.getDashboard().subscribe({ next: d => this.data.set(d) });
  }
}
