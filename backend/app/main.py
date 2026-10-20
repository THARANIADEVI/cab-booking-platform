import asyncio, json, math, os, time, uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Literal
from urllib.request import Request as URLRequest, urlopen

import stripe
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from starlette.middleware.base import BaseHTTPMiddleware
from jose import jwt
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from dotenv import load_dotenv

load_dotenv()

from .database import Base, engine, get_db, SessionLocal
from .models import Driver, Payment, Promo, Review, Ride, RideDecline, User, WalletTransaction
from .receipts import build_receipt_pdf

APP_ENV = os.getenv("APP_ENV", "development")
# This environment may expose a dead local proxy (127.0.0.1:9). Keep Stripe
# API requests direct when configured proxy variables point there.
for proxy_name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
    proxy_value = os.getenv(proxy_name, "")
    if "127.0.0.1:9" in proxy_value or "localhost:9" in proxy_value:
        for no_proxy_name in ("NO_PROXY", "no_proxy"):
            existing = [host.strip() for host in os.getenv(no_proxy_name, "").split(",") if host.strip()]
            if "api.stripe.com" not in existing:
                existing.append("api.stripe.com")
            os.environ[no_proxy_name] = ",".join(existing)
STRIPE_KEY = os.getenv("STRIPE_SECRET_KEY", "")
stripe.api_key = STRIPE_KEY
app = FastAPI(title="Cably API", version="1.0.0", description="Ride booking, dispatch, payments and live trip updates")
Base.metadata.create_all(bind=engine)
if engine.dialect.name == "postgresql":
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS postgis")
        connection.exec_driver_sql("ALTER TABLE drivers ADD COLUMN IF NOT EXISTS current_location geometry(Point,4326) GENERATED ALWAYS AS (ST_SetSRID(ST_MakePoint(longitude,latitude),4326)) STORED")
        connection.exec_driver_sql("ALTER TABLE rides ADD COLUMN IF NOT EXISTS pickup_point geometry(Point,4326) GENERATED ALWAYS AS (ST_SetSRID(ST_MakePoint(pickup_lng,pickup_lat),4326)) STORED")
        connection.exec_driver_sql("ALTER TABLE rides ADD COLUMN IF NOT EXISTS drop_point geometry(Point,4326) GENERATED ALWAYS AS (ST_SetSRID(ST_MakePoint(drop_lng,drop_lat),4326)) STORED")
        connection.exec_driver_sql("DROP INDEX IF EXISTS ix_drivers_location_gist")
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_drivers_current_location_gist ON drivers USING GIST ((current_location::geography))")
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_rides_pickup_gist ON rides USING GIST ((pickup_point::geography))")

def seed():
    with SessionLocal() as db:
        # Seed parent users first. Keep each record independently idempotent so
        # a partial seed from an earlier failed startup can be repaired safely.
        if not db.get(User, "demo-rider"):
            db.add(User(id="demo-rider", name="Alex Morgan", email="alex@example.com", phone="+1 212 555 0142", role="rider", wallet_cents=2500))
        if not db.get(User, "demo-driver"):
            db.add(User(id="demo-driver", name="Jordan Lee", email="jordan@example.com", phone="+1 917 555 0198", role="driver"))
        db.commit()

        if not db.get(Driver, "demo-driver"):
            db.add(Driver(user_id="demo-driver", vehicle_info="Tesla Model 3 · Black", verified=True, latitude=40.7211, longitude=-73.9981, status="active"))
        if not db.get(Promo, "WELCOME20"):
            db.add(Promo(code="WELCOME20", percent_off=20))
        if not db.get(Promo, "CITY10"):
            db.add(Promo(code="CITY10", percent_off=10))
        db.commit()
seed()

class Hub:
    def __init__(self): self.rooms: dict[str, set[WebSocket]] = defaultdict(set); self.redis=None; self.listener=None
    async def join(self, room, ws): self.rooms[room].add(ws)
    def leave(self, room, ws): self.rooms[room].discard(ws)
    async def cache_location(self, driver_id: str, latitude: float, longitude: float, status: str | None = None):
        if not self.redis: return
        try:
            await self.redis.set(f"cably:driver:{driver_id}:location",json.dumps({"latitude":latitude,"longitude":longitude}),ex=45)
            presence=f"cably:driver:{driver_id}:presence"
            if status=="offline": await self.redis.delete(presence)
            elif status=="active" or status is None: await self.redis.set(presence,"online",ex=45)
        except Exception: pass
    async def send(self, room, data):
        if self.redis:
            await self.redis.publish("cably:realtime", json.dumps({"room":room,"data":data}))
            return
        await self.deliver(room,data)
    async def deliver(self, room, data):
        dead=[]
        for ws in list(self.rooms[room]):
            try: await ws.send_json(data)
            except Exception: dead.append(ws)
        for ws in dead: self.leave(room, ws)
hub=Hub()

@app.on_event("startup")
async def start_services():
    redis_url=os.getenv("REDIS_URL", "")
    if redis_url:
        try:
            from redis.asyncio import Redis
            hub.redis=Redis.from_url(redis_url,decode_responses=True,socket_connect_timeout=2)
            await hub.redis.ping()
            async def listen():
                pubsub=hub.redis.pubsub(); await pubsub.subscribe("cably:realtime")
                async for message in pubsub.listen():
                    if message.get("type")=="message":
                        event=json.loads(message["data"]); await hub.deliver(event["room"],event["data"])
            hub.listener=asyncio.create_task(listen())
        except Exception:
            if hub.redis:
                try: await hub.redis.aclose()
                except Exception: pass
            hub.redis=None

@app.on_event("shutdown")
async def stop_services():
    if hub.listener: hub.listener.cancel()
    if hub.redis: await hub.redis.aclose()

_rate_windows=defaultdict(deque)
_rate_window_minute=-1
class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path.startswith(("/health","/docs","/openapi")): return await call_next(request)
        global _rate_window_minute
        minute=int(time.time()//60)
        key=f"rate:{request.client.host if request.client else 'unknown'}:{minute}"
        redis_limited=False
        if hub.redis:
            try:
                count=await hub.redis.incr(key)
                if count==1: await hub.redis.expire(key,65)
                redis_limited=True
                if count>120: return Response('{"detail":"Too many requests. Please try again shortly."}',status_code=429,media_type="application/json")
            except Exception: pass
        if not redis_limited:
            if minute!=_rate_window_minute:
                for stale in [item for item in _rate_windows if int(item.rsplit(":",1)[-1])<minute]: _rate_windows.pop(stale,None)
                _rate_window_minute=minute
            now=time.time(); window=_rate_windows[key]
            while window and now-window[0]>60: window.popleft()
            window.append(now)
            if len(window)>120: return Response('{"detail":"Too many requests. Please try again shortly."}',status_code=429,media_type="application/json")
        return await call_next(request)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("FRONTEND_ORIGIN", "http://localhost:3000").split(","), allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

def _decode(token: str):
    if APP_ENV == "development" and token in ("dev-rider", "dev-driver"):
        return {"sub": "demo-rider" if token == "dev-rider" else "demo-driver", "role": "rider" if token == "dev-rider" else "driver", "email": "alex@example.com" if token == "dev-rider" else "jordan@example.com", "name": "Alex Morgan" if token == "dev-rider" else "Jordan Lee"}
    jwks_url=os.getenv("CLERK_JWKS_URL", "")
    if not jwks_url: raise HTTPException(401, "Configure Clerk or use a development token in local mode")
    try:
        header=jwt.get_unverified_header(token)
        jwks=json.loads(urlopen(jwks_url, timeout=5).read())
        jwk=next(k for k in jwks["keys"] if k.get("kid")==header.get("kid"))
        verify_options={"verify_aud":False}
        issuer=os.getenv("CLERK_ISSUER")
        if issuer: verify_options["verify_iss"]=True
        else: verify_options["verify_iss"]=False
        claims=jwt.decode(token,jwk,algorithms=["RS256"],issuer=issuer,options=verify_options)
        return claims
    except Exception as exc: raise HTTPException(401, f"Invalid or expired auth token: {exc}")

def current_user(authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    if not authorization or not authorization.lower().startswith("bearer "): raise HTTPException(401, "Bearer token required")
    claims=_decode(authorization.split(" ",1)[1])
    sub=claims.get("sub")
    if not sub: raise HTTPException(401,"Token has no subject")
    user=db.get(User, sub)
    if not user:
        meta=claims.get("public_metadata", {})
        role=claims.get("role") or meta.get("role", "rider")
        if role not in ("rider", "driver"): role="rider"
        user=User(id=sub, name=claims.get("name") or claims.get("first_name") or "Cably member", email=claims.get("email") or claims.get("email_address") or f"{sub}@users.local", role=role)
        db.add(user); db.commit(); db.refresh(user)
        if role=="driver": db.add(Driver(user_id=sub)); db.commit()
    return user

def require_role(role):
    def check(user: User=Depends(current_user)):
        if user.role != role: raise HTTPException(403, f"{role.title()} account required")
        return user
    return check

class EstimateIn(BaseModel):
    pickup: str = Field(min_length=2, max_length=240); dropoff: str = Field(min_length=2, max_length=240)
    pickup_lat: float = Field(ge=-90, le=90); pickup_lng: float = Field(ge=-180, le=180)
    drop_lat: float = Field(ge=-90, le=90); drop_lng: float = Field(ge=-180, le=180)
    promo_code: str | None = None
class RideIn(EstimateIn): pass
class DriverLocation(BaseModel): latitude: float = Field(ge=-90,le=90); longitude: float = Field(ge=-180,le=180); status: Literal["active","offline"] | None = None
class ReviewIn(BaseModel): rating: int = Field(ge=1,le=5); comment: str = Field(default="",max_length=1000)
class TopupIn(BaseModel): amount_cents: int = Field(ge=500,le=100000)
class PaymentConfirmIn(BaseModel): payment_intent_id: str = Field(pattern=r"^pi_[A-Za-z0-9_]+$", max_length=100)
class SessionIn(BaseModel): token: str

def distance_meters(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance used by SQLite dispatch and the fare fallback."""
    dlat=math.radians(lat2-lat1); dlng=math.radians(lng2-lng1)
    arc=2*math.asin(math.sqrt(math.sin(dlat/2)**2+math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlng/2)**2))
    return 6371000*arc

def pickup_eta_minutes(driver_lat: float, driver_lng: float, ride: Ride) -> int:
    # Road routing is provider-dependent; this is a conservative local fallback.
    return max(1, math.ceil(distance_meters(driver_lat,driver_lng,ride.pickup_lat,ride.pickup_lng)*1.3/500))

def fare(payload: EstimateIn):
    distance=distance_meters(payload.pickup_lat,payload.pickup_lng,payload.drop_lat,payload.drop_lng)
    duration=int(distance/7.5)
    estimate_source="haversine"
    maps_key=os.getenv("GOOGLE_MAPS_API_KEY")
    if maps_key:
        try:
            import googlemaps
            result=googlemaps.Client(key=maps_key).distance_matrix((payload.pickup_lat,payload.pickup_lng),(payload.drop_lat,payload.drop_lng),mode="driving")["rows"][0]["elements"][0]
            if result["status"]=="OK": distance=result["distance"]["value"]; duration=result["duration"]["value"]; estimate_source="google_maps"
        except Exception: pass
    cents=max(550, int(325 + distance*1.45 + duration*0.34))
    db=SessionLocal(); code=(payload.promo_code or "").strip().upper(); promo=db.get(Promo,code) if code else None
    if code and (not promo or not promo.active):
        db.close()
        raise HTTPException(400,"That promo code is invalid or expired")
    if promo and promo.active: cents=max(400,int(cents*(100-promo.percent_off)/100))
    db.close()
    return {"distance_meters":int(distance),"duration_secs":duration,"fare_cents":cents,"currency":"usd","fare":round(cents/100,2),"estimate_source":estimate_source,"promo_applied":bool(promo and promo.active)}

def route_coordinates(payload: EstimateIn):
    """Fetch a real driving route from OSRM; never fabricate a path."""
    url=(
        "https://router.project-osrm.org/route/v1/driving/"
        f"{payload.pickup_lng},{payload.pickup_lat};{payload.drop_lng},{payload.drop_lat}"
        "?overview=full&geometries=geojson"
    )
    try:
        request=URLRequest(url,headers={"User-Agent":"Cably/1.0 (ride route estimate)"})
        with urlopen(request,timeout=8) as response:
            result=json.loads(response.read().decode("utf-8"))
        coordinates=result["routes"][0]["geometry"]["coordinates"]
        return [[float(lat),float(lng)] for lng,lat in coordinates]
    except Exception:
        return []

def serialize_ride(ride: Ride, db: Session):
    driver=db.get(User,ride.driver_id) if ride.driver_id else None
    vehicle=db.get(Driver,ride.driver_id) if ride.driver_id else None
    return {"id":ride.id,"rider_id":ride.rider_id,"driver_id":ride.driver_id,"driver_name":driver.name if driver else None,"vehicle_info":vehicle.vehicle_info if vehicle else None,"pickup":ride.pickup,"dropoff":ride.dropoff,"pickup_lat":ride.pickup_lat,"pickup_lng":ride.pickup_lng,"drop_lat":ride.drop_lat,"drop_lng":ride.drop_lng,"status":ride.status,"fare_estimate":ride.fare_estimate,"fare_actual":ride.fare_actual,"distance_meters":ride.distance_meters,"duration_secs":ride.duration_secs,"promo_code":ride.promo_code,"created_at":ride.created_at.isoformat()}

@app.get("/health")
def health(): return {"status":"ok","service":"cably-api","environment":APP_ENV}
@app.post("/api/auth/session")
def auth_session(data: SessionIn, db: Session=Depends(get_db)):
    claims=_decode(data.token); sub=claims.get("sub")
    if not sub: raise HTTPException(401,"Invalid token")
    return {"user_id":sub,"role":claims.get("role") or claims.get("public_metadata",{}).get("role","rider"),"authenticated":True}
@app.get("/api/auth/me")
def me(user: User=Depends(current_user), db: Session=Depends(get_db)):
    driver=db.get(Driver,user.id)
    return {"id":user.id,"name":user.name,"email":user.email,"phone":user.phone,"role":user.role,"rating_avg":user.rating_avg,"wallet_cents":user.wallet_cents,"driver":({"vehicle_info":driver.vehicle_info,"verified":driver.verified,"status":driver.status} if driver else None)}
@app.get("/api/locations/geocode")
def geocode_location(q: str=Query(min_length=3,max_length=240),suggest: bool=False,place_id: str | None=None,user: User=Depends(current_user)):
    maps_key=os.getenv("GOOGLE_MAPS_API_KEY","")
    if not maps_key: raise HTTPException(503,"Address search and reverse geocoding require GOOGLE_MAPS_API_KEY")
    try:
        import googlemaps
        client=googlemaps.Client(key=maps_key)
        if suggest:
            predictions=client.places_autocomplete(q)
            return {"suggestions":[{"address":item["description"],"place_id":item["place_id"]} for item in predictions]}
        coordinate_parts=q.split(",")
        reverse_point=None
        if len(coordinate_parts)==2:
            try:
                lat,lng=(float(part.strip()) for part in coordinate_parts)
                if -90<=lat<=90 and -180<=lng<=180: reverse_point=(lat,lng)
            except ValueError:
                pass
        if place_id:
            results=client.geocode(place_id=place_id)
        elif reverse_point:
            results=client.reverse_geocode(reverse_point)
        else:
            results=client.geocode(q)
    except Exception as exc: raise HTTPException(502,f"Address lookup failed: {exc}")
    if not results: raise HTTPException(404,"We could not find that address. Try a nearby landmark.")
    result=results[0]
    return {"address":result["formatted_address"],"latitude":result["geometry"]["location"]["lat"],"longitude":result["geometry"]["location"]["lng"]}
@app.get("/api/rides/estimate")
def estimate(pickup: str, dropoff: str, pickup_lat: float, pickup_lng: float, drop_lat: float, drop_lng: float, promo_code: str | None=None,user: User=Depends(current_user)):
    return fare(EstimateIn(pickup=pickup,dropoff=dropoff,pickup_lat=pickup_lat,pickup_lng=pickup_lng,drop_lat=drop_lat,drop_lng=drop_lng,promo_code=promo_code))
@app.post("/api/rides/estimate")
def estimate_body(data: EstimateIn,user: User=Depends(current_user)):
    return {**fare(data),"route_coordinates":route_coordinates(data)}
@app.post("/api/rides/request")
async def request_ride(data: RideIn, db: Session=Depends(get_db), user: User=Depends(require_role("rider"))):
    existing=db.scalar(select(Ride).where(Ride.rider_id==user.id,Ride.status.in_(["requested","accepted","arrived","in_progress"])))
    if existing: raise HTTPException(409,"Finish or cancel your current ride before booking another")
    quote=await asyncio.to_thread(fare,data); ride=Ride(id=str(uuid.uuid4()),rider_id=user.id,pickup=data.pickup,dropoff=data.dropoff,pickup_lat=data.pickup_lat,pickup_lng=data.pickup_lng,drop_lat=data.drop_lat,drop_lng=data.drop_lng,status="requested",fare_estimate=quote["fare_cents"],distance_meters=quote["distance_meters"],duration_secs=quote["duration_secs"],promo_code=data.promo_code.upper() if data.promo_code else None)
    db.add(ride); db.commit(); db.refresh(ride)
    query=select(Driver).where(Driver.status=="active",Driver.verified==True)
    if db.bind.dialect.name=="postgresql":
        ids=db.execute(text("SELECT user_id FROM drivers WHERE status='active' AND verified=true AND ST_DWithin(current_location::geography,ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography,15000) ORDER BY ST_DistanceSphere(current_location,ST_SetSRID(ST_MakePoint(:lng,:lat),4326)) LIMIT 5"),{"lng":data.pickup_lng,"lat":data.pickup_lat}).scalars().all()
        drivers=db.scalars(select(Driver).where(Driver.user_id.in_(ids))).all() if ids else []
    else:
        drivers=db.scalars(query).all()
        drivers=[d for d in drivers if distance_meters(d.latitude,d.longitude,data.pickup_lat,data.pickup_lng)<=15000]
        drivers.sort(key=lambda d:distance_meters(d.latitude,d.longitude,data.pickup_lat,data.pickup_lng))
    for driver in drivers[:5]: await hub.send(f"driver:{driver.user_id}", {"type":"ride_offer","ride":serialize_ride(ride,db)})
    return {"ride":serialize_ride(ride,db),"message":"Ride requested. Finding your nearest driver."}
@app.get("/api/rides")
def rides(db: Session=Depends(get_db),user: User=Depends(current_user)):
    query=select(Ride).order_by(Ride.created_at.desc()).limit(100)
    if user.role=="driver": query=query.where(Ride.driver_id==user.id)
    else: query=query.where(Ride.rider_id==user.id)
    rows=db.scalars(query).all()
    ids=[ride.id for ride in rows]
    reviewed=set(db.scalars(select(Review.ride_id).where(Review.rater_id==user.id,Review.ride_id.in_(ids))).all()) if ids else set()
    paid=set(db.scalars(select(Payment.ride_id).where(Payment.ride_id.in_(ids),Payment.status=="succeeded",Payment.kind.in_(["ride","wallet_ride"]))).all()) if ids else set()
    return [{**serialize_ride(ride,db),"reviewed_by_me":ride.id in reviewed,"payment_status":"paid" if ride.id in paid else "unpaid"} for ride in rows]
@app.get("/api/rides/{ride_id}/status")
def ride_status(ride_id: str,db: Session=Depends(get_db),user: User=Depends(current_user)):
    ride=db.get(Ride,ride_id)
    if not ride: raise HTTPException(404,"Ride not found")
    if user.id not in (ride.rider_id,ride.driver_id): raise HTTPException(403,"This ride belongs to another account")
    return serialize_ride(ride,db)
@app.post("/api/rides/{ride_id}/accept")
async def accept_ride(ride_id: str,db: Session=Depends(get_db),user: User=Depends(require_role("driver"))):
    ride=db.get(Ride,ride_id)
    if not ride or ride.status!="requested": raise HTTPException(409,"Ride is no longer available")
    if db.get(RideDecline,(ride_id,user.id)): raise HTTPException(409,"You already declined this ride")
    driver=db.get(Driver,user.id)
    if not driver or driver.status!="active" or not driver.verified: raise HTTPException(403,"Go online and complete verification before accepting rides")
    active_driver_ride=db.scalar(select(Ride).where(Ride.driver_id==user.id,Ride.status.in_(["accepted","arrived","in_progress"])))
    if active_driver_ride: raise HTTPException(409,"Complete your current ride before accepting another")
    result=db.query(Ride).filter(Ride.id==ride_id,Ride.status=="requested").update({"driver_id":user.id,"status":"accepted"},synchronize_session=False)
    if not result: raise HTTPException(409,"Ride is no longer available")
    db.commit(); db.refresh(ride); data=serialize_ride(ride,db)
    await hub.send(f"rider:{ride.rider_id}",{"type":"ride_update","ride":data})
    await hub.send(f"rider:{ride.rider_id}",{"type":"driver_location","latitude":driver.latitude,"longitude":driver.longitude,"ride_id":ride.id,"eta_minutes":pickup_eta_minutes(driver.latitude,driver.longitude,ride)})
    return data
@app.post("/api/rides/{ride_id}/decline")
def decline_ride(ride_id: str,db: Session=Depends(get_db),user: User=Depends(require_role("driver"))):
    driver=db.get(Driver,user.id)
    if not driver or driver.status!="active" or not driver.verified: raise HTTPException(403,"Go online and complete verification before declining ride offers")
    ride=db.get(Ride,ride_id)
    if not ride or ride.status!="requested": raise HTTPException(409,"Ride is no longer available")
    decline=db.get(RideDecline,(ride_id,user.id))
    if not decline:
        db.add(RideDecline(ride_id=ride_id,driver_id=user.id)); db.commit()
    return {"declined":True,"ride_id":ride_id}
@app.post("/api/rides/{ride_id}/status/{status}")
async def update_ride(ride_id: str,status: Literal["arrived","in_progress","completed","cancelled"],db: Session=Depends(get_db),user: User=Depends(current_user)):
    ride=db.get(Ride,ride_id)
    if not ride: raise HTTPException(404,"Ride not found")
    allowed={"arrived":"accepted","in_progress":"arrived","completed":"in_progress"}
    if status=="cancelled":
        if user.id not in (ride.rider_id,ride.driver_id) or ride.status in ("completed","cancelled"): raise HTTPException(409,"Ride cannot be cancelled")
    elif user.id!=ride.driver_id or ride.status!=allowed[status]: raise HTTPException(409,"Invalid ride status transition")
    ride.status=status
    if status=="completed": ride.fare_actual=ride.fare_estimate
    db.commit(); data=serialize_ride(ride,db); await hub.send(f"rider:{ride.rider_id}",{"type":"ride_update","ride":data})
    if ride.driver_id: await hub.send(f"driver:{ride.driver_id}",{"type":"ride_update","ride":data})
    if status=="completed" and os.getenv("CELERY_BROKER_URL"):
        try:
            from .tasks import email_ride_receipt
            email_ride_receipt.delay(ride.id)
        except Exception: pass
    return data
@app.post("/api/drivers/location")
async def driver_location(data: DriverLocation,db: Session=Depends(get_db),user: User=Depends(require_role("driver"))):
    driver=db.get(Driver,user.id)
    if not driver: driver=Driver(user_id=user.id); db.add(driver)
    driver.latitude=data.latitude; driver.longitude=data.longitude
    if data.status: driver.status=data.status
    db.commit()
    await hub.cache_location(user.id,data.latitude,data.longitude,driver.status)
    ride=db.scalar(select(Ride).where(Ride.driver_id==user.id,Ride.status.in_(["accepted","arrived","in_progress"])).order_by(Ride.created_at.desc()))
    if ride: await hub.send(f"rider:{ride.rider_id}",{"type":"driver_location","latitude":data.latitude,"longitude":data.longitude,"ride_id":ride.id,"eta_minutes":pickup_eta_minutes(data.latitude,data.longitude,ride)})
    return {"status":driver.status,"latitude":driver.latitude,"longitude":driver.longitude}
@app.get("/api/drivers/offers")
def offers(db: Session=Depends(get_db),user: User=Depends(require_role("driver"))):
    driver=db.get(Driver,user.id)
    if not driver or driver.status!="active" or not driver.verified: return []
    active=db.scalar(select(Ride.id).where(Ride.driver_id==user.id,Ride.status.in_(["accepted","arrived","in_progress"])))
    if active: return []
    if db.bind.dialect.name=="postgresql":
        rows=db.execute(text("SELECT id FROM rides WHERE status='requested' AND ST_DWithin(pickup_point::geography,ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography,15000) ORDER BY created_at DESC LIMIT 20"),{"lng":driver.longitude,"lat":driver.latitude}).scalars().all()
        found=db.scalars(select(Ride).where(Ride.id.in_(rows))).all() if rows else []; by_id={r.id:r for r in found}; selected=[by_id[i] for i in rows]
    else:
        candidates=db.scalars(select(Ride).where(Ride.status=="requested").order_by(Ride.created_at.desc()).limit(100)).all()
        selected=[r for r in candidates if distance_meters(driver.latitude,driver.longitude,r.pickup_lat,r.pickup_lng)<=15000][:20]
    declined=set(db.scalars(select(RideDecline.ride_id).where(RideDecline.driver_id==user.id)).all())
    return [serialize_ride(r,db) for r in selected if r.id not in declined]
@app.get("/api/reviews/{ride_id}")
def get_reviews(ride_id: str,db: Session=Depends(get_db),user: User=Depends(current_user)):
    ride=db.get(Ride,ride_id)
    if not ride or user.id not in (ride.rider_id,ride.driver_id): raise HTTPException(404,"Ride reviews not found")
    rows=db.scalars(select(Review).where(Review.ride_id==ride_id).order_by(Review.created_at.desc())).all()
    return {"average":round(sum(r.rating for r in rows)/len(rows),2) if rows else None,"count":len(rows),"reviewed_by_me":any(r.rater_id==user.id for r in rows),"reviews":[{"rating":r.rating,"comment":r.comment,"created_at":r.created_at.isoformat()} for r in rows]}
@app.post("/api/rides/{ride_id}/reviews")
def post_review(ride_id: str,data: ReviewIn,db: Session=Depends(get_db),user: User=Depends(current_user)):
    ride=db.get(Ride,ride_id)
    if not ride or ride.status!="completed": raise HTTPException(409,"Reviews are available after a completed ride")
    if user.id not in (ride.rider_id,ride.driver_id): raise HTTPException(403,"You did not take part in this ride")
    rated=ride.driver_id if user.id==ride.rider_id else ride.rider_id
    if db.scalar(select(Review).where(Review.ride_id==ride_id,Review.rater_id==user.id)): raise HTTPException(409,"You already reviewed this ride")
    review=Review(id=str(uuid.uuid4()),ride_id=ride_id,rater_id=user.id,rated_id=rated,rating=data.rating,comment=data.comment); db.add(review); db.flush()
    avg=db.scalar(select(func.avg(Review.rating)).where(Review.rated_id==rated)); person=db.get(User,rated); person.rating_avg=round(float(avg),2); db.commit()
    return {"id":review.id,"rating":review.rating,"comment":review.comment}
@app.get("/api/promos/{code}")
def promo(code: str,db: Session=Depends(get_db),user: User=Depends(current_user)):
    result=db.get(Promo,code.upper())
    if not result or not result.active: raise HTTPException(404,"Promo code is not active")
    return {"code":result.code,"percent_off":result.percent_off,"valid":True}
@app.get("/api/wallet")
def wallet(db: Session=Depends(get_db),user: User=Depends(current_user)):
    tx=db.scalars(select(WalletTransaction).where(WalletTransaction.user_id==user.id).order_by(WalletTransaction.created_at.desc()).limit(30)).all()
    return {"balance_cents":user.wallet_cents,"transactions":[{"id":t.id,"amount":t.amount,"description":t.description,"created_at":t.created_at.isoformat()} for t in tx]}
@app.post("/api/wallet/top-up")
def wallet_topup(data: TopupIn,db: Session=Depends(get_db),user: User=Depends(current_user)):
    payment=Payment(id=str(uuid.uuid4()),user_id=user.id,amount=data.amount_cents,kind="wallet",status="pending")
    if STRIPE_KEY:
        try:
            intent=stripe.PaymentIntent.create(amount=data.amount_cents,currency="usd",metadata={"payment_id":payment.id,"user_id":user.id,"kind":"wallet"},automatic_payment_methods={"enabled":True})
            payment.stripe_payment_intent_id=intent.id; db.add(payment); db.commit(); return {"payment_id":payment.id,"client_secret":intent.client_secret,"amount_cents":data.amount_cents,"status":"requires_payment_method"}
        except Exception as exc: raise HTTPException(502,f"Payment provider error: {exc}")
    payment.status="succeeded"; user.wallet_cents+=data.amount_cents; db.add(payment); db.add(WalletTransaction(id=str(uuid.uuid4()),user_id=user.id,amount=data.amount_cents,description="Wallet top-up (demo)")); db.commit()
    return {"payment_id":payment.id,"amount_cents":data.amount_cents,"status":"succeeded","demo":True}
@app.post("/api/payments/intent/{ride_id}")
def payment_intent(ride_id: str,db: Session=Depends(get_db),user: User=Depends(current_user)):
    ride=db.get(Ride,ride_id)
    if not ride or ride.rider_id!=user.id or ride.status!="completed": raise HTTPException(409,"Payment is available for your completed ride")
    existing=db.scalar(select(Payment).where(Payment.ride_id==ride.id,Payment.status=="succeeded"))
    if existing: return {"payment_id":existing.id,"status":"succeeded"}
    payment=Payment(id=str(uuid.uuid4()),ride_id=ride.id,user_id=user.id,amount=ride.fare_actual or ride.fare_estimate)
    if STRIPE_KEY:
        try:
            intent=stripe.PaymentIntent.create(amount=payment.amount,currency="usd",metadata={"payment_id":payment.id,"ride_id":ride.id,"user_id":user.id},automatic_payment_methods={"enabled":True})
            payment.stripe_payment_intent_id=intent.id; db.add(payment); db.commit(); return {"payment_id":payment.id,"client_secret":intent.client_secret,"amount_cents":payment.amount,"status":intent.status}
        except Exception as exc: raise HTTPException(502,f"Payment provider error: {exc}")
    payment.status="succeeded"; db.add(payment); db.commit(); return {"payment_id":payment.id,"amount_cents":payment.amount,"status":"succeeded","demo":True}

def complete_stripe_payment(db: Session, payment: Payment):
    """Atomically mark a verified intent paid and credit a wallet top-up once."""
    changed=db.execute(update(Payment).where(Payment.id==payment.id,Payment.status!="succeeded").values(status="succeeded"))
    if changed.rowcount:
        if payment.kind=="wallet":
            db.execute(update(User).where(User.id==payment.user_id).values(wallet_cents=User.wallet_cents+payment.amount))
            db.add(WalletTransaction(id=str(uuid.uuid4()),user_id=payment.user_id,amount=payment.amount,description="Wallet top-up"))
        db.commit()
    else:
        db.rollback()
    db.refresh(payment)
    return payment

@app.post("/api/payments/confirm")
def confirm_payment(data: PaymentConfirmIn,db: Session=Depends(get_db),user: User=Depends(current_user)):
    if not STRIPE_KEY: raise HTTPException(503,"Stripe is not configured on the backend")
    payment=db.scalar(select(Payment).where(Payment.stripe_payment_intent_id==data.payment_intent_id,Payment.user_id==user.id))
    if not payment: raise HTTPException(404,"Payment not found")
    try:
        intent=stripe.PaymentIntent.retrieve(data.payment_intent_id)
    except Exception as exc:
        raise HTTPException(502,f"Could not verify payment with Stripe: {exc}")
    metadata=intent.get("metadata",{})
    if metadata.get("payment_id")!=payment.id or metadata.get("user_id")!=user.id:
        raise HTTPException(403,"Payment details did not match this account")
    if int(intent.get("amount",0))!=payment.amount or intent.get("currency")!="usd":
        raise HTTPException(409,"Payment amount does not match the booking")
    if intent.get("status")!="succeeded":
        raise HTTPException(409,f"Payment is not complete (Stripe status: {intent.get('status','unknown')})")
    payment=complete_stripe_payment(db,payment)
    return {"payment_id":payment.id,"status":payment.status,"kind":payment.kind,"amount_cents":payment.amount}

@app.post("/api/payments/wallet/{ride_id}")
def pay_ride_with_wallet(ride_id: str,db: Session=Depends(get_db),user: User=Depends(require_role("rider"))):
    ride=db.get(Ride,ride_id)
    if not ride or ride.rider_id!=user.id or ride.status!="completed": raise HTTPException(409,"Payment is available for your completed ride")
    existing=db.scalar(select(Payment).where(Payment.ride_id==ride.id,Payment.status=="succeeded",Payment.kind.in_(["ride","wallet_ride"])))
    if existing: return {"payment_id":existing.id,"status":"succeeded","already_paid":True}
    amount=ride.fare_actual or ride.fare_estimate
    result=db.execute(update(User).where(User.id==user.id,User.wallet_cents>=amount).values(wallet_cents=User.wallet_cents-amount))
    if result.rowcount!=1: raise HTTPException(402,"Your wallet balance is too low. Add funds or use a card.")
    payment=Payment(id=str(uuid.uuid4()),ride_id=ride.id,user_id=user.id,amount=amount,status="succeeded",kind="wallet_ride")
    db.add(payment)
    db.add(WalletTransaction(id=str(uuid.uuid4()),user_id=user.id,amount=-amount,description=f"Ride payment · {ride.id[:8]}"))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing=db.scalar(select(Payment).where(Payment.ride_id==ride.id,Payment.status=="succeeded",Payment.kind.in_(["ride","wallet_ride"])))
        if existing: return {"payment_id":existing.id,"status":"succeeded","already_paid":True}
        raise
    return {"payment_id":payment.id,"amount_cents":amount,"status":"succeeded","method":"wallet"}
@app.post("/api/webhooks/stripe")
async def stripe_webhook(request: Request,db: Session=Depends(get_db)):
    payload=await request.body(); signature=request.headers.get("stripe-signature", ""); secret=os.getenv("STRIPE_WEBHOOK_SECRET", "")
    if not secret: raise HTTPException(503,"Stripe webhook is not configured")
    try: event=stripe.Webhook.construct_event(payload,signature,secret)
    except Exception as exc: raise HTTPException(400,f"Invalid webhook signature: {exc}")
    if event["type"] in ("payment_intent.succeeded","payment_intent.payment_failed"):
        obj=event["data"]["object"]; payment=db.scalar(select(Payment).where(Payment.stripe_payment_intent_id==obj["id"]))
        if payment:
            if event["type"]=="payment_intent.succeeded":
                complete_stripe_payment(db,payment)
            else:
                db.execute(update(Payment).where(Payment.id==payment.id,Payment.status!="succeeded").values(status="failed"))
                db.commit()
    return {"received":True}
@app.get("/api/rides/{ride_id}/receipt")
def receipt(ride_id: str,db: Session=Depends(get_db),user: User=Depends(current_user)):
    ride=db.get(Ride,ride_id)
    if not ride or user.id not in (ride.rider_id,ride.driver_id): raise HTTPException(404,"Receipt not found")
    if ride.status!="completed": raise HTTPException(409,"Receipt is available after your ride")
    pdf=build_receipt_pdf(ride)
    return Response(pdf,media_type="application/pdf",headers={"Content-Disposition":f"attachment; filename=cably-{ride.id[:8]}-receipt.pdf"})

async def websocket_auth(ws: WebSocket, role: str):
    token=ws.query_params.get("token", "")
    try:
        claims=_decode(token)
        if claims.get("role")!=role and claims.get("public_metadata",{}).get("role")!=role: await ws.close(code=1008); return None
        await ws.accept(); return claims.get("sub")
    except Exception: await ws.close(code=1008); return None
async def socket_loop(ws: WebSocket, participant_id: str, role: str):
    uid=await websocket_auth(ws,role)
    if not uid: return
    if uid!=participant_id:
        await ws.close(code=1008); return
    room=f"{role}:{uid}"
    await hub.join(room,ws)
    try:
        while True:
            message=await ws.receive_json()
            if not isinstance(message,dict): continue
            if role=="driver" and message.get("type")=="location":
                try: position=DriverLocation.model_validate(message)
                except ValidationError: continue
                db=SessionLocal(); driver=db.get(Driver,uid)
                if driver:
                    driver.latitude=position.latitude; driver.longitude=position.longitude; db.commit()
                    await hub.cache_location(uid,driver.latitude,driver.longitude,driver.status)
                    ride=db.scalar(select(Ride).where(Ride.driver_id==uid,Ride.status.in_(["accepted","arrived","in_progress"])).order_by(Ride.created_at.desc()))
                    if ride: await hub.send(f"rider:{ride.rider_id}",{"type":"driver_location","latitude":driver.latitude,"longitude":driver.longitude,"ride_id":ride.id,"eta_minutes":pickup_eta_minutes(driver.latitude,driver.longitude,ride)})
                db.close()
            elif role=="rider": await ws.send_json({"type":"ack"})
    except WebSocketDisconnect: hub.leave(room,ws)
@app.websocket("/ws/driver/{driver_id}")
async def driver_ws(ws: WebSocket,driver_id: str): await socket_loop(ws,driver_id,"driver")
@app.websocket("/ws/rider/{rider_id}")
async def rider_ws(ws: WebSocket,rider_id: str): await socket_loop(ws,rider_id,"rider")
