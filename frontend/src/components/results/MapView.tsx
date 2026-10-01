import 'leaflet/dist/leaflet.css';
import { CircleMarker, MapContainer, Popup, TileLayer } from 'react-leaflet';
import type { Analysis } from '../../api/types';
import { countedSpecies, hasValidCoordinates, topSpeciesNames } from '../../lib/analysis';
import { formatCoordinate, formatDate } from '../../lib/format';
import { thresholdPercent } from '../../lib/threshold';
import { Panel } from '../ui/Panel';

/**
 * Leaflet map of the recording location. Rendered only for real coordinates;
 * there is never a fallback or default point.
 */
export default function MapView({ analysis }: { analysis: Analysis }) {
  const recording = analysis.recording;
  if (!hasValidCoordinates(recording)) return null;
  const { latitude, longitude } = recording;
  const richness = analysis.metrics?.species_richness ?? countedSpecies(analysis).length;
  const top = topSpeciesNames(analysis, 3);

  return (
    <Panel labelledBy="map-heading" className="p-5 sm:p-6">
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <p className="eyebrow mb-1">Map</p>
          <h3 id="map-heading" className="text-base font-semibold tracking-tight text-ink">
            Recording location
          </h3>
        </div>
        <p className="num text-xs text-muted">
          {formatCoordinate(latitude, 'lat')}, {formatCoordinate(longitude, 'lon')}
        </p>
      </div>
      <div
        className="isolate h-[26rem] overflow-hidden rounded-xl ring-1 ring-black/10 dark:ring-white/10"
        data-testid="map"
      >
        <MapContainer
          center={[latitude, longitude]}
          zoom={13}
          scrollWheelZoom={false}
          className="h-full w-full"
          aria-label={`Map centered on the recording location at ${formatCoordinate(latitude, 'lat')}, ${formatCoordinate(longitude, 'lon')}`}
        >
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          <CircleMarker
            center={[latitude, longitude]}
            radius={9}
            pathOptions={{ color: '#ffffff', weight: 2, fillColor: '#377157', fillOpacity: 1 }}
          >
            <Popup>
              <div className="min-w-[12rem] text-sm">
                <p className="font-semibold">{recording.site_name ?? 'Unnamed site'}</p>
                <p className="text-xs opacity-80">
                  {recording.captured_at
                    ? formatDate(recording.captured_at, recording.timezone)
                    : `Analyzed ${formatDate(analysis.created_at)}`}
                </p>
                <p className="mt-2">
                  Species richness: <strong>{richness}</strong>{' '}
                  <span className="text-xs opacity-80">
                    at {thresholdPercent(analysis.settings.decision_threshold)}
                  </span>
                </p>
                {top.length ? <p className="mt-1">Top species: {top.join(', ')}</p> : null}
              </div>
            </Popup>
          </CircleMarker>
        </MapContainer>
      </div>
      <p className="mt-3 text-xs text-muted">
        The point is the location entered for this recording. Map tiles load from OpenStreetMap when
        you are online.
      </p>
    </Panel>
  );
}
