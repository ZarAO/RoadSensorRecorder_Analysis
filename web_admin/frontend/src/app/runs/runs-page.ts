import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, DestroyRef, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { ApiService } from '../api/api.service';
import { RunOut } from '../api/dto';

const REFRESH_MS = 2000;

@Component({
  selector: 'app-runs-page',
  imports: [DatePipe, DecimalPipe, RouterLink],
  templateUrl: './runs-page.html',
  styleUrl: './runs-page.css',
})
export class RunsPage {
  private readonly api = inject(ApiService);
  private readonly destroyRef = inject(DestroyRef);
  private timer: ReturnType<typeof setInterval> | null = null;

  readonly runs = signal<RunOut[]>([]);
  readonly error = signal<string | null>(null);

  constructor() {
    this.reload();
    this.destroyRef.onDestroy(() => this.stopTimer());
  }

  reload(): void {
    this.api.listRuns().subscribe({
      next: runs => {
        this.runs.set(runs);
        // Poll while anything is still moving through the queue
        const active = runs.some(r => r.status === 'queued' || r.status === 'running');
        if (active && this.timer === null) {
          this.timer = setInterval(() => this.reload(), REFRESH_MS);
        } else if (!active) {
          this.stopTimer();
        }
      },
      error: err => this.error.set(err?.message ?? 'Помилка завантаження'),
    });
  }

  remove(run: RunOut): void {
    if (!confirm(`Видалити ран #${run.id} разом з артефактами?`)) return;
    this.api.deleteRun(run.id).subscribe({ next: () => this.reload() });
  }

  private stopTimer(): void {
    if (this.timer !== null) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }
}
