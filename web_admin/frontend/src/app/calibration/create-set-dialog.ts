import { Component, computed, inject, input, linkedSignal, output, signal } from '@angular/core';

import { ApiService } from '../api/api.service';
import { CoefficientSetOut } from '../api/dto';

export type SetModel = 'eq3' | 'eq6_bias';

/** Which artifact the draft's params are read from — exactly one, never both
 *  (the backend answers 422 for a payload carrying two provenances). */
export interface SetProvenance {
  kind: 'comparison' | 'aggregate';
  id: number;
}

export interface PhoneOption {
  label: string;
  /** null = the set applies to any phone (phone_model IS NULL resolution tier) */
  value: string | null;
}

/** The single «Створити набір коефіцієнтів» dialog, shared by the comparison and
 *  the aggregate detail pages. The parent owns the open flag and renders the
 *  component only while open, so every reopen starts from a clean state. */
@Component({
  selector: 'app-create-set-dialog',
  styleUrl: './create-set-dialog.css',
  template: `
    <div class="dialog-backdrop" (click)="closed.emit()">
      <div class="dialog card" id="set-dialog" role="dialog" aria-modal="true"
           aria-labelledby="set-title" (click)="$event.stopPropagation()">
        <h3 id="set-title">Створити набір коефіцієнтів</h3>

        <fieldset class="field models">
          <legend>Модель</legend>
          <label class="radio">
            <input type="radio" name="model" value="eq6_bias"
                   [checked]="model() === 'eq6_bias'" (change)="selectModel('eq6_bias')" />
            <span>Eq.6 — корекція зсуву <small>рекомендовано</small></span>
          </label>
          <label class="radio" [class.disabled]="eq3Disabled()">
            <input type="radio" name="model" value="eq3" [checked]="model() === 'eq3'"
                   [disabled]="eq3Disabled()" (change)="selectModel('eq3')" />
            <span>Eq.3 — <i>A</i> · √PSD + <i>B</i>
              @if (eq3Disabled() && eq3DisabledReason()) {
                <small>{{ eq3DisabledReason() }}</small>
              }
            </span>
          </label>
        </fieldset>

        <label class="field">
          Назва
          <input type="text" [value]="name()" (input)="onNameInput($event)" />
        </label>
        <label class="field">
          Тип авто
          <input type="text" [value]="vehicle()" (input)="onVehicleInput($event)" />
        </label>
        <label class="field">
          Модель телефону
          <!-- A select once the caller knows the recorded phones; free text while it
               does not (the value must match phone_model_from_meta exactly). -->
          @if (phoneOptions().length) {
            <select [value]="phone() ?? ''" (change)="onPhoneSelect($event)">
              @for (option of phoneOptions(); track option.label) {
                <option [value]="option.value ?? ''">{{ option.label }}</option>
              }
            </select>
          } @else {
            <input type="text" [value]="phone() ?? ''" (input)="onPhoneInput($event)"
                   placeholder="(необов'язково)" />
          }
        </label>

        <p class="hint">
          Набір створюється як чернетка — на рани він впливає лише після підтвердження.
        </p>
        @if (error(); as message) {
          <p class="error-banner" id="set-error" role="alert">{{ message }}</p>
        }
        <div class="dialog-actions">
          <button (click)="closed.emit()">Скасувати</button>
          <button class="primary" (click)="submit()" [disabled]="!canCreate()">Створити</button>
        </div>
      </div>
    </div>
  `,
})
export class CreateSetDialog {
  private readonly api = inject(ApiService);

  readonly provenance = input.required<SetProvenance>();
  readonly defaultModel = input<SetModel>('eq6_bias');
  readonly eq3Disabled = input(false);
  /** Shown next to the disabled Eq.3 radio — the reason differs per provenance */
  readonly eq3DisabledReason = input('');
  readonly vehicleType = input('');
  readonly phoneOptions = input<PhoneOption[]>([]);
  /** yyyy-MM-dd of the source's created_at: the suggested name stays reproducible
   *  instead of drifting with the wall clock. */
  readonly nameDate = input('');

  readonly created = output<CoefficientSetOut>();
  readonly closed = output<void>();

  protected readonly model = linkedSignal<SetModel>(() => this.defaultModel());
  protected readonly vehicle = linkedSignal(() => this.vehicleType());
  protected readonly phone = linkedSignal<string | null>(
    () => this.phoneOptions()[0]?.value ?? null);
  protected readonly submitting = signal(false);
  /** Creation errors live inside the dialog — the page banner sits under the backdrop */
  protected readonly error = signal<string | null>(null);
  /** null while the operator has not typed a name: the suggestion then keeps
   *  tracking the model and the vehicle type. */
  private readonly typedName = signal<string | null>(null);

  protected readonly name = computed(() => this.typedName() ?? this.defaultName());

  protected readonly canCreate = computed(
    () => !!this.name().trim() && !!this.vehicle().trim() && !this.submitting());

  protected selectModel(model: SetModel): void {
    if (model === 'eq3' && this.eq3Disabled()) return;
    this.model.set(model);
  }

  protected onNameInput(event: Event): void {
    this.typedName.set((event.target as HTMLInputElement).value);
  }

  protected onVehicleInput(event: Event): void {
    this.vehicle.set((event.target as HTMLInputElement).value);
  }

  protected onPhoneInput(event: Event): void {
    this.phone.set((event.target as HTMLInputElement).value);
  }

  protected onPhoneSelect(event: Event): void {
    this.phone.set((event.target as HTMLSelectElement).value || null);
  }

  protected submit(): void {
    if (!this.canCreate()) return;
    const provenance = this.provenance();
    this.submitting.set(true);
    this.error.set(null);
    this.api.createCoefficientSet({
      ...(provenance.kind === 'aggregate'
        ? { aggregate_comparison_id: provenance.id }
        : { comparison_id: provenance.id }),
      model: this.model(),
      name: this.name().trim(),
      vehicle_type: this.vehicle().trim(),
      phone_model: (this.phone() ?? '').trim() || null,
    }).subscribe({
      next: set => {
        this.submitting.set(false);
        this.created.emit(set);
      },
      // The dialog stays open so the operator can fix the name (a same-day repeat
      // collides with the deterministic default) and retry.
      error: err => {
        this.submitting.set(false);
        this.error.set(err?.error?.detail ?? err?.message ?? 'Невідома помилка');
      },
    });
  }

  /** `{{model}}_{{vehicle_type}}_{{yyyy-MM-dd}}` */
  private defaultName(): string {
    const vehicle = this.vehicle().trim() || 'unknown';
    return [this.model(), vehicle, this.nameDate()].filter(part => part).join('_');
  }
}
