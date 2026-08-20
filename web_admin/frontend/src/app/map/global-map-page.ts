import { Component, DestroyRef, ElementRef, effect, inject, signal,
         viewChild, afterNextRender } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import * as L from 'leaflet';

import { ApiService } from '../api/api.service';
import { DashboardOut, GeoJsonFeatureCollection } from '../api/dto';
import { CountUp } from '../shared/count-up';
import { ThemeService } from '../theme.service';

/** IRI_multi color scale; magenta overrides for class-1/2 survey segments */
function segmentColor(props: Record<string, unknown>): string {
  if (props['needs_class12_survey']) return '#FF00FF';
  const iri = props['iri_multi'];
  if (typeof iri !== 'number') return '#8b93a3';
  if (iri < 2.5) return '#2fbf71';
  if (iri < 4) return '#e8c231';
  if (iri < 6) return '#f28c33';
  return '#e5484d';
}

// Theme-matched basemaps (CARTO, free with attribution)
const TILES = {
  dark: 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
  light: 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
};
const TILE_ATTR = '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> © <a href="https://carto.com/attributions">CARTO</a>';

@Component({
  selector: 'app-global-map-page',
  imports: [CountUp, RouterLink],
  templateUrl: './global-map-page.html',
  styleUrl: './global-map-page.css',
})
export class GlobalMapPage {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  private readonly themeService = inject(ThemeService);

  private readonly mapHost = viewChild.required<ElementRef<HTMLDivElement>>('map');
  private map: L.Map | null = null;
  private layer: L.GeoJSON | null = null;
  private tiles: L.TileLayer | null = null;

  readonly busy = signal(false);
  readonly loading = signal(true);
  readonly featureCount = signal<number | null>(null);
  readonly stats = signal<DashboardOut | null>(null);

  constructor() {
    afterNextRender(() => this.initMap());
    this.destroyRef.onDestroy(() => this.map?.remove());
    this.api.getDashboard().subscribe({ next: d => this.stats.set(d) });

    // Swap the basemap when the theme flips
    effect(() => {
      const theme = this.themeService.theme();
      if (!this.map) return;
      this.tiles?.remove();
      this.tiles = L.tileLayer(TILES[theme], { attribution: TILE_ATTR }).addTo(this.map);
    });
  }

  rebuild(): void {
    this.busy.set(true);
    this.api.rebuildGlobalMap().subscribe({
      next: fc => { this.busy.set(false); this.render(fc); },
      error: () => this.busy.set(false),
    });
  }

  private initMap(): void {
    this.map = L.map(this.mapHost().nativeElement, { zoomControl: false })
      .setView([50.45, 30.52], 11);
    L.control.zoom({ position: 'bottomleft' }).addTo(this.map);
    this.tiles = L.tileLayer(TILES[this.themeService.theme()],
      { attribution: TILE_ATTR }).addTo(this.map);
    this.api.getGlobalMap().subscribe({
      next: fc => { this.loading.set(false); this.render(fc); },
      error: () => this.loading.set(false),
    });
  }

  private render(fc: GeoJsonFeatureCollection): void {
    if (!this.map) return;
    this.layer?.remove();
    this.featureCount.set(fc.features.length);
    this.layer = L.geoJSON(fc as never, {
      style: feature => ({
        color: segmentColor(feature?.properties ?? {}),
        weight: 5,
        opacity: 0.9,
      }),
      onEachFeature: (feature, layer) => {
        const props = feature.properties ?? {};
        const iri = typeof props['iri_multi'] === 'number'
          ? (props['iri_multi'] as number).toFixed(2)
          : '—';
        (layer as L.Path).on('mouseover', () =>
          (layer as L.Path).setStyle({ weight: 8, opacity: 1 }));
        (layer as L.Path).on('mouseout', () =>
          (layer as L.Path).setStyle({ weight: 5, opacity: 0.9 }));
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
    if (bounds.isValid()) this.map.fitBounds(bounds, { padding: [40, 40] });
  }
}
