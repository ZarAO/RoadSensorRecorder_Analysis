import { Component, computed, input } from '@angular/core';

import { RecordingMeta } from '../api/dto';

@Component({
  selector: 'app-vehicle-chip',
  template: `<span class="chip" [class.empty]="!hasProfile()">{{ label() }}</span>`,
  styles: `
    .chip {
      display: inline-block;
      padding: 0.15rem 0.5rem;
      border-radius: 999px;
      background: #dbeafe;
      color: #1e40af;
      font-size: 0.85rem;
      white-space: nowrap;
    }
    .chip.empty { background: #f3f4f6; color: #6b7280; }
  `,
})
export class VehicleChip {
  readonly meta = input<RecordingMeta | null>(null);

  readonly hasProfile = computed(() =>
    Object.keys(this.meta()?.vehicle ?? {}).length > 0);

  readonly label = computed(() => {
    const vehicle = this.meta()?.vehicle ?? {};
    if (!this.hasProfile()) return 'без профілю';
    const type = vehicle['vehicle_type'] ?? '';
    const makeModel = vehicle['vehicle_make_model'] ?? '';
    return [type, makeModel].filter(Boolean).join(' · ');
  });
}
