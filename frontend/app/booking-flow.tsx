"use client";

import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { ArrowLeft, ArrowRight, CarFront, Check, Crosshair, LoaderCircle, MapPin, Navigation, Search, ShieldCheck } from "lucide-react";
import type { MapPoint } from "./map";

const RideMap = dynamic(() => import("./map"), { ssr: false, loading: () => <div className="booking-map-loading"><LoaderCircle className="spin"/><span>Loading map…</span></div> });

export type BookingLocation = MapPoint & { address: string };
type Location = BookingLocation;
type Suggestion = { address: string; place_id: string };
type Estimate = { fare_cents: number; distance_meters: number; duration_secs: number; promo_applied: boolean; route_coordinates: [number, number][] };
type Api = (path: string, init?: RequestInit) => Promise<any>;

function readableGeolocationError(error: GeolocationPositionError) {
  if (error.code === error.PERMISSION_DENIED) return "Location permission was denied. Search for your pickup address instead.";
  if (error.code === error.POSITION_UNAVAILABLE) return "Your current location is unavailable. Search for your pickup address instead.";
  return "Finding your location took too long. Search for your pickup address instead.";
}

export default function BookingFlow({ auth, onBook, onWallet, walletCents, active, onCancel }: {
  auth: Api;
  onBook: (pickup: Location, dropoff: Location, promo: string) => Promise<void>;
  onWallet: () => void;
  walletCents: number;
  active?: { status: string; pickup: string; dropoff: string };
  onCancel?: () => void;
}) {
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [pickup, setPickup] = useState<Location | null>(null);
  const [dropoff, setDropoff] = useState<Location | null>(null);
  const [query, setQuery] = useState("");
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [suggestionsLoading, setSuggestionsLoading] = useState(false);
  const [listOpen, setListOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [locating, setLocating] = useState(false);
  const [preview, setPreview] = useState<MapPoint | undefined>();
  const [previewStatus, setPreviewStatus] = useState<"resolving" | "unconfirmed">("resolving");
  const [estimate, setEstimate] = useState<Estimate | null>(null);
  const [error, setError] = useState("");
  const [promo, setPromo] = useState("");
  const [promoBusy, setPromoBusy] = useState(false);

  const activeLocation = step === 1 ? "pickup" : "dropoff";
  const selected = activeLocation === "pickup" ? pickup : dropoff;

  useEffect(() => {
    const term = query.trim();
    if (term.length < 3 || (step !== 1 && step !== 2)) {
      setSuggestions([]);
      setSuggestionsLoading(false);
      return;
    }
    const controller = new AbortController();
    setSuggestionsLoading(true);
    const timeout = window.setTimeout(async () => {
      try {
        const result = await auth(`/api/locations/geocode?q=${encodeURIComponent(term)}&suggest=true`, { signal: controller.signal });
        setSuggestions(Array.isArray(result.suggestions) ? result.suggestions : []);
        setListOpen(true);
        setError("");
      } catch (reason: any) {
        if (reason?.name !== "AbortError") {
          setSuggestions([]);
          setError(reason?.message || "Address suggestions are unavailable. Try a different search.");
        }
      } finally {
        if (!controller.signal.aborted) setSuggestionsLoading(false);
      }
    }, 450);
    return () => { window.clearTimeout(timeout); controller.abort(); };
  }, [auth, query, step]);

  async function resolvePoint(point: MapPoint) {
    const result = await auth(`/api/locations/geocode?q=${encodeURIComponent(`${point.lat},${point.lng}`)}`);
    if (typeof result.address !== "string" || !result.address.trim() || !Number.isFinite(result.latitude) || !Number.isFinite(result.longitude)) {
      throw new Error("We couldn't identify this point. Try another spot or search for an address.");
    }
    return { address: result.address, lat: point.lat, lng: point.lng } satisfies Location;
  }

  async function requestEstimate(origin: Location, destination: Location, promoCode = "") {
    const result = await auth("/api/rides/estimate", {
      method: "POST",
      body: JSON.stringify({
        pickup: origin.address,
        dropoff: destination.address,
        pickup_lat: origin.lat,
        pickup_lng: origin.lng,
        drop_lat: destination.lat,
        drop_lng: destination.lng,
        promo_code: promoCode.trim() || null,
      }),
    });
    if (!Array.isArray(result.route_coordinates) || result.route_coordinates.length < 2) {
      throw new Error("We couldn't load a driving route for these locations. Please try again or choose a nearby point.");
    }
    return result as Estimate;
  }

  async function confirmLocation(location: Location, target: "pickup" | "dropoff") {
    setError("");
    setPreview(undefined);
    setPreviewStatus("resolving");
    setQuery("");
    setListOpen(false);
    setSuggestions([]);
    if (target === "pickup") {
      setPickup(location);
      setDropoff(null);
      setEstimate(null);
      return;
    }
    setDropoff(location);
    if (!pickup) {
      setError("Choose a pickup location first.");
      setStep(1);
      return;
    }
    setBusy(true);
    try {
      const result = await requestEstimate(pickup, location);
      setEstimate(result);
      setStep(3);
    } catch (reason: any) {
      setEstimate(null);
      setError(reason?.message || "We couldn't estimate this ride. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  async function selectSuggestion(suggestion: Suggestion) {
    setListOpen(false);
    setBusy(true);
    setError("");
    try {
      const result = await auth(`/api/locations/geocode?q=${encodeURIComponent(suggestion.address)}&place_id=${encodeURIComponent(suggestion.place_id)}`);
      if (typeof result.address !== "string" || !Number.isFinite(result.latitude) || !Number.isFinite(result.longitude)) throw new Error("That address couldn't be resolved. Choose another suggestion.");
      await confirmLocation({ address: result.address, lat: result.latitude, lng: result.longitude }, activeLocation);
    } catch (reason: any) {
      setError(reason?.message || "That address couldn't be resolved. Try another search.");
    } finally {
      setBusy(false);
    }
  }

  async function chooseMapPoint(point: MapPoint) {
    setPreview(point);
    setPreviewStatus("resolving");
    setError("");
    setBusy(true);
    try {
      const location = await resolvePoint(point);
      await confirmLocation(location, activeLocation);
    } catch (reason: any) {
      setPreviewStatus("unconfirmed");
      setError(reason?.message || "We couldn't identify this point. Try another spot or search for an address.");
    } finally {
      setBusy(false);
    }
  }

  function useCurrentLocation() {
    setError("");
    if (!navigator.geolocation) {
      setError("This browser doesn't support location access. Search for your pickup address instead.");
      return;
    }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(async position => {
      const point = { lat: position.coords.latitude, lng: position.coords.longitude };
      setPreview(point);
      setPreviewStatus("resolving");
      try {
        const location = await resolvePoint(point);
        await confirmLocation(location, "pickup");
      } catch (reason: any) {
        setPreviewStatus("unconfirmed");
        setError(reason?.message || "We couldn't identify your current location. Search for your pickup address instead.");
      } finally {
        setLocating(false);
      }
    }, error => {
      setError(readableGeolocationError(error));
      setLocating(false);
    }, { enableHighAccuracy: true, timeout: 12000, maximumAge: 0 });
  }

  async function retryEstimate() {
    if (!pickup || !dropoff) return;
    setBusy(true);
    setError("");
    try {
      const result = await requestEstimate(pickup, dropoff, promo);
      setEstimate(result);
      setStep(3);
    } catch (reason: any) {
      setError(reason?.message || "We couldn't estimate this ride. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  async function applyPromo() {
    if (!pickup || !dropoff) return;
    setPromoBusy(true);
    setError("");
    try {
      const result = await requestEstimate(pickup, dropoff, promo);
      setEstimate(result);
    } catch (reason: any) {
      setError(reason?.message || "We couldn't apply that promo code.");
    } finally {
      setPromoBusy(false);
    }
  }

  async function submitBooking() {
    if (!pickup || !dropoff || !estimate || submitting) return;
    setSubmitting(true);
    try { await onBook(pickup, dropoff, promo); }
    finally { setSubmitting(false); }
  }

  const statusMessage = busy || locating ? "Resolving location and route…" : "";

  return (
    <section className="booking-experience" aria-labelledby="booking-title">
      <header className="booking-heading">
        <div>
          <span className="eyebrow"><Navigation size={14}/> YOUR NEXT RIDE</span>
          <h1 id="booking-title">Where would you like to go?</h1>
          <p className="page-subtitle">Choose your pickup and destination on the map or search an address.</p>
        </div>
        <span className="booking-secure"><ShieldCheck size={15}/> Secure, upfront pricing</span>
      </header>

      {active && <section className="active-banner"><div className="active-indicator"><span/></div><div className="active-text"><b>{active.status === "requested" ? "Finding your driver" : "Your ride is in progress"}</b><span>{active.pickup} <ArrowRight size={12}/> {active.dropoff}</span></div><span className="ride-state">{active.status.replace("_", " ")}</span>{onCancel && <button className="cancel-ride" onClick={onCancel}>Cancel</button>}</section>}

      <ol className="booking-steps" aria-label="Booking steps">
        {["Pickup", "Drop-off", "Ride"].map((label, index) => {
          const number = (index + 1) as 1 | 2 | 3;
          return <li key={label} className={step === number ? "current" : step > number ? "complete" : ""} aria-current={step === number ? "step" : undefined}>
            <span className="step-number">{step > number ? <Check size={15}/> : number}</span><span>{label}</span>
          </li>;
        })}
      </ol>

      <div className="booking-flow-grid">
        <section className="booking-card booking-step-card" aria-live="polite">
          {step === 1 && <>
            <div className="flow-step-heading"><span className="section-kicker">STEP 1 OF 3</span><h2>Where should we pick you up?</h2><p>Search for an address or choose a point on the map.</p></div>
            <SearchBox query={query} setQuery={value => { setQuery(value); setSuggestions([]); setListOpen(true); setError(""); }} suggestions={suggestions} loading={suggestionsLoading} open={listOpen} onSelect={selectSuggestion} onDismiss={() => setListOpen(false)} disabled={busy || locating}/>
            <button className="location-action" onClick={useCurrentLocation} disabled={locating || busy}><Crosshair size={17}/>{locating ? "Finding your location…" : "Use my current location"}</button>
            {pickup && <div className="selected-location pickup-summary"><span className="location-dot pickup-dot"/><span><small>CONFIRMED PICKUP</small><b>{pickup.address}</b></span><Check size={17}/></div>}
            <div className="step-actions"><span className="step-helper">{pickup ? "Pickup confirmed. Continue to choose a destination." : "Choose a suggestion or click the map to continue."}</span><button className="primary-button" disabled={!pickup || busy} onClick={() => { setStep(2); setQuery(""); setSuggestions([]); setError(""); }}>Choose drop-off <ArrowRight size={16}/></button></div>
          </>}

          {step === 2 && <>
            <div className="flow-step-heading"><span className="section-kicker">STEP 2 OF 3</span><h2>Where are you going?</h2><p>Choose a destination. We’ll show the route and estimate next.</p></div>
            {pickup && <div className="selected-location pickup-summary"><span className="location-dot pickup-dot"/><span><small>PICKUP</small><b>{pickup.address}</b></span><button className="text-link" onClick={() => { setStep(1); setQuery(""); setError(""); }}>Change</button></div>}
            <SearchBox query={query} setQuery={value => { setQuery(value); setSuggestions([]); setListOpen(true); setError(""); }} suggestions={suggestions} loading={suggestionsLoading} open={listOpen} onSelect={selectSuggestion} onDismiss={() => setListOpen(false)} disabled={busy}/>
            {dropoff && <div className="selected-location"><span className="location-dot drop-dot"/><span><small>DESTINATION</small><b>{dropoff.address}</b></span><Check size={17}/></div>}
            {dropoff && <button className="primary-button full-button" disabled={busy} onClick={retryEstimate}>{busy ? <><LoaderCircle className="spin"/> Finding route…</> : <>Show route and fare <ArrowRight size={16}/></>}</button>}
            <p className="step-helper map-click-hint"><MapPin size={14}/> Click the map to set your drop-off. Only the active point will move.</p>
          </>}

          {step === 3 && pickup && dropoff && estimate && <>
            <div className="flow-step-heading"><span className="section-kicker">STEP 3 OF 3</span><h2>Your route is ready</h2><p>Review both locations and choose your ride.</p></div>
            <div className="route-summary">
              <div className="summary-location"><span className="location-dot pickup-dot"/><span><small>PICKUP</small><b>{pickup.address}</b></span><button aria-label="Change pickup" onClick={() => { setStep(1); setQuery(""); setEstimate(null); setError(""); }}>Edit</button></div>
              <div className="summary-location"><span className="location-dot drop-dot"/><span><small>DROP-OFF</small><b>{dropoff.address}</b></span><button aria-label="Change drop-off" onClick={() => { setStep(2); setQuery(""); setEstimate(null); setError(""); }}>Edit</button></div>
            </div>
            <div className="ride-choice" aria-label="Selected ride type"><span className="ride-choice-icon"><CarFront size={22}/></span><span><b>Cably Go</b><small>Everyday rides · {Math.max(1, Math.round(estimate.duration_secs / 60))} min · {(estimate.distance_meters / 1000).toFixed(1)} km</small></span><strong>${(estimate.fare_cents / 100).toFixed(2)}</strong></div>
            <form className="flow-promo" onSubmit={event => { event.preventDefault(); void applyPromo(); }}><label htmlFor="booking-promo">Promo code</label><div><input id="booking-promo" value={promo} onChange={event => setPromo(event.target.value.toUpperCase())} placeholder="Enter code"/><button type="submit" disabled={promoBusy || !promo.trim()}>{promoBusy ? "Applying…" : "Apply"}</button></div></form>
            {estimate.promo_applied && <p className="promo-applied-note"><Check size={14}/> Promo applied to this estimate.</p>}
            <button className="primary-button full-button book-confirm-button" onClick={() => void submitBooking()} disabled={submitting}>{submitting ? <><LoaderCircle className="spin"/> Booking ride…</> : <><CarFront size={18}/> Confirm ride <span className="button-price">${(estimate.fare_cents / 100).toFixed(2)}</span><ArrowRight size={17}/></>}</button>
            <button className="back-link" onClick={() => { setStep(2); setQuery(""); setError(""); }}><ArrowLeft size={15}/> Back to drop-off</button>
          </>}

          {statusMessage && <p className="flow-status" role="status"><LoaderCircle className="spin"/>{statusMessage}</p>}
          {error && <p className="flow-error" role="alert">{error}</p>}
        </section>

        <section className="booking-map-card" aria-label="Choose your ride locations on the map">
          <div className="booking-map-topline"><span><span className="map-live-dot"/> OPENSTREETMAP</span><span>{step === 3 ? "ROUTE PREVIEW" : `${activeLocation === "pickup" ? "PICKUP" : "DROP-OFF"} SELECTION`}</span></div>
          <div className="booking-map-surface"><RideMap pickup={pickup ?? undefined} drop={dropoff ?? undefined} preview={preview} previewStatus={previewStatus} route={step === 3 ? estimate?.route_coordinates : undefined} focus={selected ?? undefined} interactive={step < 3 && !busy && !locating} activeLocation={activeLocation} onMapPick={chooseMapPoint}/></div>
          <div className="booking-map-footer"><p>{step < 3 ? <>Click the map to place the <b>{activeLocation === "pickup" ? "pickup" : "drop-off"}</b> pin. The other pin stays in place.</> : <>Showing the estimated driving route. Edit either location to make a change.</>}</p><div className="pin-legend"><span><i className="legend-pickup"/>Pickup</span><span><i className="legend-drop"/>Drop-off</span>{preview && <span><i className="legend-preview"/>Resolving</span>}</div></div>
        </section>
      </div>

      <div className="booking-wallet-summary"><span className="wallet-summary-icon"><CarFront size={17}/></span><span><small>YOUR CAbly WALLET</small><b>${(walletCents / 100).toFixed(2)} available</b></span><button className="text-link" onClick={onWallet}>Add funds <ArrowRight size={14}/></button></div>
    </section>
  );
}

function SearchBox({ query, setQuery, suggestions, loading, open, onSelect, onDismiss, disabled }: {
  query: string; setQuery: (value: string) => void; suggestions: Suggestion[]; loading: boolean; open: boolean; onSelect: (suggestion: Suggestion) => void; onDismiss: () => void; disabled: boolean;
}) {
  return <div className="address-search">
    <label htmlFor="booking-address">{query.length > 0 ? "Address, street, or landmark" : "Search for an address or landmark"}</label>
    <div className="address-search-input"><Search size={17}/><input id="booking-address" value={query} onChange={event => setQuery(event.target.value)} onKeyDown={event => { if (event.key === "Escape") onDismiss(); if (event.key === "ArrowDown" && open && suggestions.length) { event.preventDefault(); document.querySelector<HTMLElement>("#address-suggestions [role='option']")?.focus(); } }} placeholder="Start typing an address…" autoComplete="off" role="combobox" aria-autocomplete="list" aria-haspopup="listbox" aria-expanded={open && suggestions.length > 0} aria-controls="address-suggestions" disabled={disabled}/>{loading && <LoaderCircle className="spin" aria-label="Searching"/>}</div>
    {query.trim().length > 0 && query.trim().length < 3 && <p className="search-help">Enter at least 3 characters to search.</p>}
    {open && suggestions.length > 0 && <ul id="address-suggestions" className="address-suggestions" role="listbox" aria-label="Address suggestions">{suggestions.map((item, index) => <li key={item.place_id} role="option" aria-selected="false" tabIndex={disabled ? -1 : 0} aria-label={`Select ${item.address}`} onMouseDown={event => event.preventDefault()} onClick={() => onSelect(item)} onKeyDown={event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onSelect(item); } if (event.key === "ArrowDown") { event.preventDefault(); document.querySelectorAll<HTMLElement>("#address-suggestions [role='option']")[index + 1]?.focus(); } if (event.key === "ArrowUp") { event.preventDefault(); if (index === 0) document.getElementById("booking-address")?.focus(); else document.querySelectorAll<HTMLElement>("#address-suggestions [role='option']")[index - 1]?.focus(); } }}><MapPin size={16}/><span>{item.address}</span><ArrowRight size={14}/></li>)}</ul>}
    {open && !loading && query.trim().length >= 3 && suggestions.length === 0 && <p className="search-help" role="status">No matching places. Try a nearby street or landmark.</p>}
  </div>;
}
