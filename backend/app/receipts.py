from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from xml.sax.saxutils import escape

def build_receipt_pdf(ride) -> bytes:
    amount=(ride.fare_actual or ride.fare_estimate)/100
    pdf=BytesIO(); doc=SimpleDocTemplate(pdf,pagesize=letter,rightMargin=.8*inch,leftMargin=.8*inch,topMargin=.75*inch,bottomMargin=.75*inch)
    styles=getSampleStyleSheet(); styles.add(ParagraphStyle(name="CablyGreen",parent=styles["Title"],textColor=colors.HexColor("#087e5b"),alignment=0,fontSize=26,spaceAfter=18))
    story=[Paragraph("Cably",styles["CablyGreen"]),Paragraph("Your ride receipt",styles["Heading1"]),Paragraph(f"Ride {ride.id[:8]} · {ride.created_at.strftime('%b %d, %Y')}",styles["Normal"]),Spacer(1,24)]
    rows=[["Pickup",escape(ride.pickup)],["Drop-off",escape(ride.dropoff)],["Distance",f"{ride.distance_meters/1000:.1f} km"],["Duration",f"{ride.duration_secs//60} min"],["Total paid",f"${amount:.2f}"]]
    table=Table(rows,colWidths=[1.7*inch,4.7*inch],rowHeights=39)
    table.setStyle(TableStyle([("TEXTCOLOR",(0,0),(-1,-1),colors.HexColor("#34443a")),("FONTNAME",(0,0),(-1,-1),"Helvetica"),("FONTSIZE",(0,0),(-1,-1),11),("LINEBELOW",(0,0),(-1,-2),.5,colors.HexColor("#dce5df")),("BACKGROUND",(0,-1),(-1,-1),colors.HexColor("#edf6f0")),("FONTNAME",(0,-1),(-1,-1),"Helvetica-Bold"),("FONTSIZE",(0,-1),(-1,-1),14),("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LEFTPADDING",(0,0),(-1,-1),12)]))
    story.extend([table,Spacer(1,28),Paragraph("Thank you for riding with Cably.",styles["Normal"])]); doc.build(story); return pdf.getvalue()
