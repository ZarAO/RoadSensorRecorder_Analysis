import { Component, computed, input } from '@angular/core';

import { RecordingMeta } from '../api/dto';

type Kind = 'clean' | 'truncated' | 'legacy';

@Component({
  selector: 'app-recording-badge',
  template: `<span class="badge" [class]="'badge ' + kind()">{{ label() }}</span>`,
  styles: `
    .badge {
      display: inline-block;
      padding: 0.15rem 0.5rem;
      border-radius: 4px;
      font-size: 0.8rem;
      white-space: nowrap;
    }
    .badge.clean { background: #dcfce7; color: #166534; }
    .badge.truncated { background: #fee2e2; color: #991b1b; }
    .badge.legacy { background: #f3f4f6; color: #6b7280; }
  `,
})
export class RecordingBadge {
  readonly meta = input<RecordingMeta | null>(null);

  readonly kind = computed<Kind>(() => {
    const meta = this.meta();
    if (meta?.clean_stop) return 'clean';
    // No schema and no footer: recorded before the v2.1 contract
    if (meta == null || (meta.schema == null && !meta.footer)) return 'legacy';
    return 'truncated';
  });

  readonly label = computed(() => ({
    clean: 'чиста зупинка',
    truncated: 'обірваний',
    legacy: 'pre-v2.1',
  }[this.kind()]));
}
