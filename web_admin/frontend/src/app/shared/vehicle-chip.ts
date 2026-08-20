import { Component, computed, input } from '@angular/core';

import { RecordingMeta } from '../api/dto';

@Component({
  selector: 'app-vehicle-chip',
  template: `<span class="chip" [class.accent]="hasProfile()">
    @if (hasProfile()) {
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="M4 15l1.6-5.2A2 2 0 0 1 7.5 8h9a2 2 0 0 1 1.9 1.8L20 15v4h-2.5v-1.5h-11V19H4v-4Z"
              stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
        <circle cx="8" cy="14.5" r="0.8" fill="currentColor"/>
        <circle cx="16" cy="14.5" r="0.8" fill="currentColor"/>
      </svg>
    }
    {{ label() }}
  </span>`,
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
