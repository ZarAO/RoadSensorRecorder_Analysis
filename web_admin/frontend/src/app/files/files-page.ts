import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, inject, signal } from '@angular/core';
import { Router } from '@angular/router';

import { ApiService } from '../api/api.service';
import { FileOut } from '../api/dto';
import { RecordingBadge } from '../shared/recording-badge';
import { VehicleChip } from '../shared/vehicle-chip';

const POLICIES = ['invalid', 'very-poor', 'poor', 'ignore'] as const;

@Component({
  selector: 'app-files-page',
  imports: [DatePipe, DecimalPipe, VehicleChip, RecordingBadge],
  templateUrl: './files-page.html',
  styleUrl: './files-page.css',
})
export class FilesPage {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);

  readonly files = signal<FileOut[]>([]);
  readonly error = signal<string | null>(null);
  readonly busy = signal(false);
  readonly dragOver = signal(false);
  /** File picked for the analyze dialog; null = dialog closed */
  readonly analyzeTarget = signal<FileOut | null>(null);
  readonly policy = signal<string>('invalid');
  readonly policies = POLICIES;
  /** Expanded preview row */
  readonly expandedId = signal<number | null>(null);

  constructor() {
    this.reload();
  }

  reload(): void {
    this.api.listFiles().subscribe({
      next: files => this.files.set(files),
      error: err => this.error.set(this.describe(err)),
    });
  }

  onFileInput(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (input.files?.length) this.upload(input.files[0]);
    input.value = '';
  }

  onDrop(event: DragEvent): void {
    event.preventDefault();
    this.dragOver.set(false);
    const file = event.dataTransfer?.files?.[0];
    if (file) this.upload(file);
  }

  onDragOver(event: DragEvent): void {
    event.preventDefault();
    this.dragOver.set(true);
  }

  upload(file: File): void {
    this.busy.set(true);
    this.error.set(null);
    this.api.uploadFile(file).subscribe({
      next: () => { this.busy.set(false); this.reload(); },
      error: err => { this.busy.set(false); this.error.set(this.describe(err)); },
    });
  }

  remove(file: FileOut): void {
    if (!confirm(`Видалити файл «${file.filename}»? Рани залишаться.`)) return;
    this.api.deleteFile(file.id).subscribe({
      next: () => this.reload(),
      error: err => this.error.set(this.describe(err)),
    });
  }

  openAnalyze(file: FileOut): void {
    this.policy.set('invalid');
    this.analyzeTarget.set(file);
  }

  confirmAnalyze(): void {
    const target = this.analyzeTarget();
    if (!target) return;
    this.analyzeTarget.set(null);
    this.api.createRun(target.id, { low_speed_policy: this.policy() }).subscribe({
      next: () => this.router.navigate(['/runs']),
      error: err => this.error.set(this.describe(err)),
    });
  }

  runAll(): void {
    this.busy.set(true);
    this.api.runAllUnanalyzed().subscribe({
      next: created => {
        this.busy.set(false);
        if (created.length) this.router.navigate(['/runs']);
      },
      error: err => { this.busy.set(false); this.error.set(this.describe(err)); },
    });
  }

  toggleExpand(file: FileOut): void {
    this.expandedId.set(this.expandedId() === file.id ? null : file.id);
  }

  onPolicyChange(event: Event): void {
    this.policy.set((event.target as HTMLSelectElement).value);
  }

  vehicleEntries(file: FileOut): Array<[string, string]> {
    return Object.entries(file.recording_meta?.vehicle ?? {});
  }

  private describe(err: { error?: { detail?: string }; message?: string }): string {
    return err?.error?.detail ?? err?.message ?? 'Невідома помилка';
  }
}
