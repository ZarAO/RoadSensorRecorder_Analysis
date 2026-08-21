import { Component, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { ApiService } from '../api/api.service';
import { CompareSegmentRow, FileCompareOut } from '../api/dto';

/** |delta_iri_multi| above this highlights the row (spec Task 7) */
const DELTA_WARN_THRESHOLD = 0.5;

@Component({
  selector: 'app-run-compare',
  imports: [RouterLink],
  templateUrl: './run-compare.html',
  styleUrl: './run-compare.css',
})
export class RunCompare {
  private readonly api = inject(ApiService);
  private readonly route = inject(ActivatedRoute);

  readonly runAId = Number(this.route.snapshot.paramMap.get('id'));
  readonly runBId = Number(this.route.snapshot.paramMap.get('other'));
  readonly data = signal<FileCompareOut | null>(null);
  readonly error = signal<string | null>(null);

  constructor() {
    this.api.getRun(this.runAId).subscribe({
      next: run => {
        this.api.compareRuns(run.file_id, this.runAId, this.runBId).subscribe({
          next: result => this.data.set(result),
          error: err => this.error.set(this.describe(err)),
        });
      },
      error: err => this.error.set(this.describe(err)),
    });
  }

  /** Coefficient chips for one side — reuses the run-detail chip idiom. */
  coefficientChips(side: 'run_a' | 'run_b'):
      Array<{ model: string; name: string; label: string }> {
    const coefficients = this.data()?.[side]?.params?.coefficients;
    const chips: Array<{ model: string; name: string; label: string }> = [];
    if (coefficients?.eq3) {
      chips.push({
        model: 'eq3', name: coefficients.eq3.name,
        label: this.formatCoefficientParams(coefficients.eq3.params),
      });
    }
    if (coefficients?.eq6_bias) {
      chips.push({
        model: 'eq6_bias', name: coefficients.eq6_bias.name,
        label: this.formatCoefficientParams(coefficients.eq6_bias.params),
      });
    }
    return chips;
  }

  policyFor(side: 'run_a' | 'run_b'): string {
    return this.data()?.[side]?.params?.low_speed_policy ?? 'invalid';
  }

  /** |delta| > 0.5 -> highlight the row (var(--color-warn-bg)) */
  isHot(row: CompareSegmentRow): boolean {
    return row.delta_iri_multi != null && Math.abs(row.delta_iri_multi) > DELTA_WARN_THRESHOLD;
  }

  fmt(value: number | null | undefined, digits = 2): string {
    return value == null ? '—' : value.toFixed(digits);
  }

  private formatCoefficientParams(params: { A?: number; B?: number; bias?: number }): string {
    if (params.bias != null) return `bias=${params.bias.toFixed(3)}`;
    if (params.A != null && params.B != null) {
      return `A=${params.A.toFixed(3)}, B=${params.B.toFixed(3)}`;
    }
    return '';
  }

  private describe(err: { error?: { detail?: string }; message?: string }): string {
    return err?.error?.detail ?? err?.message ?? 'Невідома помилка';
  }
}
