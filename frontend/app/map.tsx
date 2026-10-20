"use client";

import { useEffect } from "react";
import L from "leaflet";
import { MapContainer, Marker, Polyline, TileLayer, Tooltip, useMap, useMapEvents } from "react-leaflet";

export type MapPoint = { lat: number; lng: number; address?: string };

const CHENNAI: [number, number] = [13.0827, 80.2707];
const pickupIcon = L.divIcon({ className: "leaflet-pin-shell", html: '<span class="leaflet-pin pickup-pin"><b>P</b></span>', iconSize: [34, 42], iconAnchor: [17, 38] });
const dropIcon = L.divIcon({ className: "leaflet-pin-shell", html: '<span class="leaflet-pin drop-pin"><b>D</b></span>', iconSize: [34, 42], iconAnchor: [17, 38] });
const previewIcon = L.divIcon({ className: "leaflet-pin-shell", html: '<span class="leaflet-pin preview-pin"><i></i></span>', iconSize: [30, 38], iconAnchor: [15, 34] });
const driverIcon = L.divIcon({ className: "leaflet-pin-shell", html: '<span class="leaflet-pin driver-pin">●</span>', iconSize: [30, 38], iconAnchor: [15, 34] });

function Viewport({ pickup, drop, preview, route, focus }: { pickup?: MapPoint; drop?: MapPoint; preview?: MapPoint; route?: [number, number][]; focus?: MapPoint }) {
  const map = useMap();
  useEffect(() => {
    if (route && route.length > 1) {
      const points: L.LatLngExpression[] = [...route, ...(pickup ? [[pickup.lat, pickup.lng] as [number, number]] : []), ...(drop ? [[drop.lat, drop.lng] as [number, number]] : [])];
      map.fitBounds(L.latLngBounds(points), { padding: [44, 44], maxZoom: 15, animate: true });
      return;
    }
    const point = preview ?? focus ?? drop ?? pickup;
    if (point) map.flyTo([point.lat, point.lng], 15, { duration: 0.6 });
  }, [map, pickup?.lat, pickup?.lng, drop?.lat, drop?.lng, preview?.lat, preview?.lng, focus?.lat, focus?.lng, route]);
  return null;
}

function ClickHandler({ active, onPick }: { active: boolean; onPick?: (point: MapPoint) => void }) {
  useMapEvents({ click(event) { if (active) onPick?.({ lat: event.latlng.lat, lng: event.latlng.lng }); } });
  return null;
}

export default function RideMap({
  pickup,
  drop,
  driver,
  preview,
  previewStatus = "resolving",
  route,
  focus,
  interactive = false,
  activeLocation = "pickup",
  onMapPick,
}: {
  pickup?: MapPoint;
  drop?: MapPoint;
  driver?: MapPoint;
  preview?: MapPoint;
  previewStatus?: "resolving" | "unconfirmed";
  route?: [number, number][];
  focus?: MapPoint;
  interactive?: boolean;
  activeLocation?: "pickup" | "dropoff";
  onMapPick?: (point: MapPoint) => void;
}) {
  return (
    <MapContainer className="cably-leaflet-map" center={CHENNAI} zoom={12} scrollWheelZoom keyboard>
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      <Viewport pickup={pickup} drop={drop} preview={preview} route={route} focus={focus} />
      <ClickHandler active={interactive} onPick={onMapPick} />
      {route && route.length > 1 && <Polyline positions={route} pathOptions={{ color: "#07835f", weight: 5, opacity: 0.86 }} />}
      {pickup && <Marker position={[pickup.lat, pickup.lng]} icon={pickupIcon} title={`Pickup${pickup.address ? `: ${pickup.address}` : " location"}`}><Tooltip permanent direction="top" offset={[0, -30]}>Pickup{pickup.address ? ` · ${pickup.address}` : ""}</Tooltip></Marker>}
      {drop && <Marker position={[drop.lat, drop.lng]} icon={dropIcon} title={`Drop-off${drop.address ? `: ${drop.address}` : " location"}`}><Tooltip permanent direction="top" offset={[0, -30]}>Drop-off{drop.address ? ` · ${drop.address}` : ""}</Tooltip></Marker>}
      {driver && <Marker position={[driver.lat, driver.lng]} icon={driverIcon} title="Your driver"><Tooltip direction="top">Your driver</Tooltip></Marker>}
      {preview && <Marker position={[preview.lat, preview.lng]} icon={previewIcon} title={previewStatus === "resolving" ? "Resolving selected location" : "Location not confirmed"}><Tooltip permanent direction="top" offset={[0, -28]}>{previewStatus === "resolving" ? `Resolving ${activeLocation === "pickup" ? "pickup" : "drop-off"}…` : "Location not confirmed"}</Tooltip></Marker>}
    </MapContainer>
  );
}
