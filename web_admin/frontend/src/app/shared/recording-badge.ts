import { Component, computed, input } from '@angular/core';

import { RecordingMeta } from '../api/dto';

type Kind = 'clean' | 'truncated' | 'legacy';

@Component({
  selector: 'app-recording-badge',
  template: `<span class="chip" [class.ok]="kind() === 'clean'"
                   [class.bad]="kind() === 'truncated'">{{ label() }}</span>`,
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
