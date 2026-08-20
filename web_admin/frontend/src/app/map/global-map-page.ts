import { Component, DestroyRef, ElementRef, inject, signal, viewChild,
         afterNextRender } from '@angular/core';
import { Router } from '@angular/router';
import * as L from 'leaflet';

import { ApiService } from '../api/api.service';
import { GeoJsonFeatureCollection } from '../api/dto';

/** IRI_multi color scale; magenta overrides for class-1/2 survey segments */
function segmentColor(props: Record<string, unknown>): string {
  if (props['needs_class12_survey']) return '#FF00FF';
  const iri = props['iri_multi'];
  if (typeof iri !== 'number') return '#9ca3af';
  if (iri < 2.5) return '#16a34a';
  if (iri < 4) return '#eab308';
  if (iri < 6) return '#f97316';
  return '#dc2626';
}

@Component({
  selector: 'app-global-map-page',
  templateUrl: './global-map-page.html',
  styleUrl: './global-map-page.css',
})
export class GlobalMapPage {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);

  private readonly mapHost = viewChild.required<ElementRef<HTMLDivElement>>('map');
  private map: L.Map | null = null;
  private layer: L.GeoJSON | null = null;

  readonly busy = signal(false);
  readonly featureCount = signal(0);

  constructor() {
    afterNextRender(() => this.initMap());
    this.destroyRef.onDestroy(() => this.map?.remove());
  }

  rebuild(): void {
    this.busy.set(true);
    this.api.rebuildGlobalMap().subscribe({
      next: fc => { this.busy.set(false); this.render(fc); },
      error: () => this.busy.set(false),
    });
  }

  private initMap(): void {
    this.map = L.map(this.mapHost().nativeElement).setView([50.45, 30.52], 11);
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '© OpenStreetMap contributors',
    }).addTo(this.map);
    this.api.getGlobalMap().subscribe({ next: fc => this.render(fc) });
  }

  private render(fc: GeoJsonFeatureCollection): void {
    if (!this.map) return;
    this.layer?.remove();
    this.featureCount.set(fc.features.length);
    this.layer = L.geoJSON(fc as never, {
      style: feature => ({
        color: segmentColor(feature?.properties ?? {}),
        weight: 5,
        opacity: 0.85,
      }),
      onEachFeature: (feature, layer) => {
        const props = feature.properties ?? {};
        const iri = typeof props['iri_multi'] === 'number'
          ? (props['iri_multi'] as number).toFixed(2)
          : '—';
        layer.bindPopup(
          `<b>${props['filename'] ?? ''}</b><br>` +
          `Сегмент ${props['seg_id']}, IRI_multi: ${iri}<br>` +
          `<a href="#" data-run="${props['run_id']}">До рану #${props['run_id']}</a>`);
        layer.on('popupopen', event => {
          const link = event.popup.getElement()?.querySelector('a[data-run]');
          link?.addEventListener('click', clickEvent => {
            clickEvent.preventDefault();
            this.router.navigate(['/runs', props['run_id']]);
          });
        });
      },
    }).addTo(this.map);
    const bounds = this.layer.getBounds();
    if (bounds.isValid()) this.map.fitBounds(bounds, { padding: [20, 20] });
  }
}
