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
  /** Contract v3.1: both set = the exact «this phone in this car» tier, which no
   *  other phone and no other car can ever match. Both null on the other tiers. */
  deviceId?: string | null;
  vehicleId?: string | null;
}

const ANY_PHONE: PhoneOption = {
  label: 'Будь-який телефон цього типу авто', value: null, deviceId: null, vehicleId: null,
};

/** The resolution tiers a set can target, built from what the run actually
 *  recorded — nothing here is ever typed by hand:
 *   - contract v3.1 (device_id + vehicle_id): the exact phone-and-car identity;
 *   - a device line only (pre-v3.1): the exact phone of that vehicle type;
 *   - neither: the «any phone» tier alone.
 *  A hand-typed device string would never match `phone_model_from_meta`, so it is
 *  not offered at all. */
export function phoneOptionsFor(phoneModel: string | null | undefined,
                                deviceId: string | null = null,
                                vehicleId: string | null = null): PhoneOption[] {
  if (deviceId && vehicleId) {
    return [{
      label: `Цей телефон і авто (${phoneModel ?? deviceId})`,
      value: phoneModel ?? null, deviceId, vehicleId,
    }, ANY_PHONE];
  }
  return phoneModel
    ? [{ label: `Точний телефон (${phoneModel})`, value: phoneModel,
         deviceId: null, vehicleId: null }, ANY_PHONE]
    : [ANY_PHONE];
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
          Ключ калібрування
          <!-- Machine keys only: every option comes from phoneOptionsFor(), built
               from what the run recorded. No free-text entry exists, because a
               typed value must match the parsed metadata exactly and a wrong one
               would silently never resolve. The option value is the label, which
               is unique per tier: two tiers may share the same phone string (or
               none at all), and the posted key comes from the option object. -->
          <select [value]="selected().label" (change)="onPhoneSelect($event)">
            @for (option of phoneOptions(); track option.label) {
              <option [value]="option.label">{{ option.label }}</option>
            }
          </select>
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
  /** Required: an empty list would leave the operator with no key at all, and a
   *  silent default would guess a resolution tier the run never recorded. */
  readonly phoneOptions = input.required<PhoneOption[]>();
  /** yyyy-MM-dd of the source's created_at: the suggested name stays reproducible
   *  instead of drifting with the wall clock. */
  readonly nameDate = input('');

  readonly created = output<CoefficientSetOut>();
  readonly closed = output<void>();

  protected readonly model = linkedSignal<SetModel>(() => this.defaultModel());
  /** The chosen resolution tier as a whole option: the select's value alone
   *  cannot carry the identity keys of the v3.1 tier. Most specific first, so
   *  option 0 is the default. */
  protected readonly selected = linkedSignal<PhoneOption>(
    () => this.phoneOptions()[0] ?? ANY_PHONE);
  protected readonly submitting = signal(false);
  /** Creation errors live inside the dialog — the page banner sits under the backdrop */
  protected readonly error = signal<string | null>(null);
  /** null while the operator has not typed a name: the suggestion then keeps
   *  tracking the model and the vehicle type. */
  private readonly typedName = signal<string | null>(null);
  /** null while the operator has not edited the vehicle type: it then keeps
   *  tracking the input (e.g. a run's vehicle_type arriving after an async fetch)
   *  instead of overwriting whatever the operator already typed. */
  private readonly typedVehicle = signal<string | null>(null);

  protected readonly name = computed(() => this.typedName() ?? this.defaultName());
  protected readonly vehicle = computed(() => this.typedVehicle() ?? this.vehicleType());

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
    this.typedVehicle.set((event.target as HTMLInputElement).value);
  }

  /** Read back by index, not by phone string: two tiers may carry the same phone
   *  while keying differently. Nothing selected falls back to the widest tier. */
  protected onPhoneSelect(event: Event): void {
    const index = (event.target as HTMLSelectElement).selectedIndex;
    this.selected.set(this.phoneOptions()[index] ?? ANY_PHONE);
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
      phone_model: this.selected().value,
      device_id: this.selected().deviceId ?? null,
      vehicle_id: this.selected().vehicleId ?? null,
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
