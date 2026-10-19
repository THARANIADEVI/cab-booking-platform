import os
import smtplib
from email.message import EmailMessage
from celery import Celery
from dotenv import load_dotenv
load_dotenv()
from .database import SessionLocal
from .models import Ride, User
from .receipts import build_receipt_pdf

celery_app=Celery("cably",broker=os.getenv("CELERY_BROKER_URL","redis://localhost:6379/1"),backend=os.getenv("CELERY_RESULT_BACKEND","redis://localhost:6379/2"))

@celery_app.task(name="cably.email_ride_receipt",autoretry_for=(OSError,),retry_backoff=True,max_retries=3)
def email_ride_receipt(ride_id: str):
    """Send completed-trip receipt email when SMTP settings are configured."""
    host=os.getenv("SMTP_HOST"); recipient=None
    with SessionLocal() as db:
        ride=db.get(Ride,ride_id)
        if not ride: return "ride not found"
        rider=db.get(User,ride.rider_id)
        if not rider: return "rider not found"
        recipient=rider.email
        summary=(rider.name,ride.id[:8],ride.pickup,ride.dropoff,f"${(ride.fare_actual or ride.fare_estimate)/100:.2f}")
        receipt_pdf=build_receipt_pdf(ride)
    if not host: return "SMTP not configured; receipt remains available in ride history"
    message=EmailMessage(); message["Subject"]=f"Your Cably ride receipt · {summary[1]}"; message["From"]=os.getenv("SMTP_FROM","receipts@cably.app"); message["To"]=recipient
    message.set_content(f"Hi {summary[0]},\n\nThanks for riding with Cably.\n\nTrip: {summary[1]}\nPickup: {summary[2]}\nDrop-off: {summary[3]}\nTotal: {summary[4]}\n\nYour PDF receipt is available in your ride history.")
    message.add_attachment(receipt_pdf,maintype="application",subtype="pdf",filename=f"cably-{summary[1]}-receipt.pdf")
    with smtplib.SMTP(host,int(os.getenv("SMTP_PORT","587")),timeout=15) as smtp:
        smtp.starttls()
        if os.getenv("SMTP_USER"): smtp.login(os.getenv("SMTP_USER"),os.getenv("SMTP_PASSWORD",""))
        smtp.send_message(message)
    return "sent"
