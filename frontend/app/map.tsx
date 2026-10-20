type Point = { lat: number; lng: number };

export default function RideMap({
  pickup,
  drop,
  driver,
}: {
  pickup: Point;
  drop: Point;
  driver?: Point;
}) {
  const points = driver ? [pickup, drop, driver] : [pickup, drop];
  const padding = 0.01;
  const minLat = Math.min(...points.map((point) => point.lat));
  const maxLat = Math.max(...points.map((point) => point.lat));
  const minLng = Math.min(...points.map((point) => point.lng));
  const maxLng = Math.max(...points.map((point) => point.lng));
  const bbox = `${minLng - padding},${minLat - padding},${maxLng + padding},${maxLat + padding}`;
  return (
    <iframe
      title="OpenStreetMap view of your ride"
      className="fallback-map"
      src={`https://www.openstreetmap.org/export/embed.html?bbox=${bbox}&layer=mapnik&marker=${pickup.lat}%2C${pickup.lng}`}
      loading="lazy"
      referrerPolicy="no-referrer-when-downgrade"
    />
  );
}
