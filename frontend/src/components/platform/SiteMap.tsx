import 'leaflet/dist/leaflet.css';
import { CircleMarker, MapContainer, Popup, TileLayer } from 'react-leaflet';
import { formatCoordinate } from '../../lib/format';

/** One site on an OpenStreetMap base layer. Only rendered for real coordinates. */
export default function SiteMap({
  latitude,
  longitude,
  name,
  className = 'h-64',
}: {
  latitude: number;
  longitude: number;
  name: string;
  /** Height classes; the map fills them. */
  className?: string;
}) {
  return (
    <div
      className={`relative isolate overflow-hidden rounded-xl ring-1 ring-black/10 dark:ring-white/10 ${className}`}
      data-testid="site-map"
    >
      <MapContainer
        center={[latitude, longitude]}
        zoom={14}
        scrollWheelZoom={false}
        className="h-full w-full"
        aria-label={`Map centered on ${name} at ${formatCoordinate(latitude, 'lat')}, ${formatCoordinate(longitude, 'lon')}`}
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
            <div className="text-sm">
              <p className="font-semibold">{name}</p>
              <p className="num text-xs opacity-80">
                {formatCoordinate(latitude, 'lat')}, {formatCoordinate(longitude, 'lon')}
              </p>
            </div>
          </Popup>
        </CircleMarker>
      </MapContainer>
    </div>
  );
}
