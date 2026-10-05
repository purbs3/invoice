from flask import Flask, request, send_file, render_template_string, redirect, url_for
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
import io, os, json
from datetime import date, datetime
import redis

app = Flask(__name__)

# ==================== SETTINGS ====================
def get_settings():
    return {
        "company":  os.environ.get("COMPANY_NAME", "Dr. Sharma Home Physiotherapy"),
        "address":  os.environ.get("COMPANY_ADDRESS", "Delhi, India"),
        "phone":    os.environ.get("COMPANY_PHONE", "+91 98765 43210"),
        "msme":     os.environ.get("MSME_NUMBER", "UDYAM-DL-00-0000000"),
        "gst_rate": int(os.environ.get("DEFAULT_GST", "0")),
    }

# ==================== REDIS / KV ====================
KV_URL = os.environ.get("KV_URL") or os.environ.get("REDIS_URL")

def get_redis():
    if not KV_URL:
        return None
    return redis.from_url(KV_URL, decode_responses=True)

def gen_invoice_no():
    """Atomic sequential invoice number (KV se)."""
    r = get_redis()
    year = date.today().year
    if r is None:
        return f"PHY-{year}-{datetime.now().strftime('%H%M%S')}"
    try:
        n = r.incr(f"invoice_counter:{year}")
        return f"PHY-{year}-{n:04d}"
    except Exception as e:
        print("KV error:", e)
        return f"PHY-{year}-{datetime.now().strftime('%H%M%S')}"

def peek_next_invoice_no():
    """Counter badhaye bina agla number dikhaye."""
    r = get_redis()
    year = date.today().year
    if r is None:
        return f"PHY-{year}-????"
    try:
        v = r.get(f"invoice_counter:{year}")
        n = int(v) if v else 0
        return f"PHY-{year}-{n+1:04d}"
    except Exception:
        return f"PHY-{year}-????"

def save_history(data):
    r = get_redis()
    if r is None:
        return
    try:
        r.lpush("invoice_history", json.dumps(data))
        r.ltrim("invoice_history", 0, 999)
    except Exception as e:
        print("history save failed:", e)

def get_history(limit=200):
    r = get_redis()
    if r is None:
        return []
    try:
        rows = r.lrange("invoice_history", 0, limit - 1)
        return [json.loads(x) for x in rows]
    except Exception:
        return []

def get_counter():
    r = get_redis()
    if r is None:
        return 0
    year = date.today().year
    try:
        v = r.get(f"invoice_counter:{year}")
        return int(v) if v else 0
    except Exception:
        return 0

def set_counter(val):
    r = get_redis()
    if r is None:
        return False
    year = date.today().year
    try:
        r.set(f"invoice_counter:{year}", val)
        return True
    except Exception:
        return False

# ==================== LOGO ====================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO = os.path.join(BASE_DIR, "..", "logo.png")
if not os.path.exists(LOGO):
    LOGO = os.path.join(BASE_DIR, "logo.png")

# ==================== PDF ====================
def _draw_page(c, w, h, copy_label, inv_no, patient, age, contact, diagnosis,
               referred_by, inv_date, pf, pt, pay_type, pay_date,
               gst_rate, items, subtotal, gst, total, s):
    # Header — logo + company
    if os.path.exists(LOGO):
        try:
            c.drawImage(LOGO, 20*mm, h-38*mm, width=26*mm, height=26*mm,
                        preserveAspectRatio=True, mask="auto")
        except Exception:
            pass
    c.setFont("Helvetica-Bold", 15)
    c.drawString(54*mm, h-22*mm, s["company"])
    c.setFont("Helvetica", 9)
    c.drawString(54*mm, h-27*mm, s["address"])
    c.drawString(54*mm, h-32*mm, f"Ph: {s['phone']}")
    c.drawString(54*mm, h-37*mm, f"MSME / Udyam No: {s['msme']}")

    c.setFont("Helvetica-Bold", 10)
    c.drawRightString(190*mm, h-22*mm, copy_label)

    c.setFont("Helvetica-Bold", 14)
    c.drawString(20*mm, h-50*mm, "PHYSIOTHERAPY INVOICE")
    c.setFont("Helvetica-Oblique", 8)
    c.drawString(20*mm, h-54*mm, "Not for Government Use")

    # Patient details
    y = h - 65*mm
    c.setFont("Helvetica", 10)
    c.drawString(20*mm, y, f"Invoice No: {inv_no}")
    c.drawString(125*mm, y, f"Date: {inv_date}")
    y -= 6*mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(20*mm, y, f"Patient: {patient}")
    y -= 6*mm
    c.setFont("Helvetica", 10)
    if age:
        c.drawString(20*mm, y, f"Age: {age}"); y -= 6*mm
    if contact:
        c.drawString(20*mm, y, f"Contact: {contact}"); y -= 6*mm
    if diagnosis:
        c.drawString(20*mm, y, f"Diagnosis: {diagnosis}"); y -= 6*mm
    if referred_by:
        c.drawString(20*mm, y, f"Referred By: {referred_by}"); y -= 6*mm
    c.drawString(20*mm, y, f"Treatment Period: {pf} to {pt}")
    y -= 10*mm

    # Items table
    c.setFont("Helvetica-Bold", 10)
    for x, t in [(20,"Treatment / Service"),(105,"Sessions"),(130,"Fee/Session"),(160,"Amount")]:
        c.drawString(x*mm, y, t)
    y -= 2*mm
    c.line(20*mm, y, 190*mm, y)
    y -= 6*mm

    c.setFont("Helvetica", 10)
    for n_, q, r, a in items:
        c.drawString(20*mm, y, str(n_)[:46])
        c.drawString(105*mm, y, f"{q:g}")
        c.drawString(130*mm, y, f"{r:.2f}")
        c.drawString(160*mm, y, f"{a:.2f}")
        y -= 6*mm

    y -= 4*mm
    c.line(125*mm, y, 190*mm, y)
    y -= 6*mm
    c.drawString(125*mm, y, f"Subtotal: Rs {subtotal:.2f}")
    y -= 6*mm
    if gst > 0:
        c.drawString(125*mm, y, f"GST {gst_rate}%: Rs {gst:.2f}")
        y -= 6*mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(125*mm, y, f"Total: Rs {total:.2f}")
    y -= 12*mm

    # Payment
    c.setFont("Helvetica-Bold", 10)
    c.drawString(20*mm, y, "Payment Details")
    y -= 6*mm
    c.setFont("Helvetica", 10)
    c.drawString(20*mm, y, f"Payment Type: {pay_type}")
    y -= 6*mm
    c.drawString(20*mm, y, f"Payment Received On: {pay_date}")
    y -= 14*mm

    c.setFont("Helvetica-Oblique", 9)
    c.drawString(20*mm, y, "Therapist Signature: ____________________")

    c.setFont("Helvetica-Oblique", 7)
    c.drawString(20*mm, 15*mm,
        "This is a commercial invoice and is NOT valid for government / official use.")

def build_pdf_bytes(inv_no, patient, age, contact, diagnosis, referred_by,
                    inv_date, pf, pt, pay_type, pay_date,
                    gst_rate, items, subtotal, gst, total, s):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    for label in ["ORIGINAL FOR PATIENT", "DUPLICATE FOR CLINIC"]:
        _draw_page(c, w, h, label, inv_no, patient, age, contact, diagnosis,
                   referred_by, inv_date, pf, pt, pay_type, pay_date,
                   gst_rate, items, subtotal, gst, total, s)
        c.showPage()
    c.save()
    buf.seek(0)
    return buf

# ==================== HTML — FORM ====================
FORM_HTML = """
<!doctype html><html><head><meta charset="utf-8">
<title>Physiotherapy Invoice</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
 body{font-family:system-ui,Arial;max-width:680px;margin:20px auto;padding:16px;background:#f0f7f4}
 h1{color:#00796b;margin-top:0}
 .card{background:#fff;padding:16px;border-radius:10px;box-shadow:0 1px 4px rgba(0,0,0,.08);margin-bottom:14px}
 label{display:block;font-size:13px;color:#555;margin-top:10px}
 input,select{width:100%;padding:9px;border:1px solid #ccc;border-radius:6px;font-size:15px;box-sizing:border-box}
 button{padding:11px 18px;border:0;border-radius:8px;background:#00796b;color:#fff;font-size:15px;cursor:pointer;margin-top:12px}
 button.green{background:#2e7d32}
 button.small{background:#eee;color:#333;padding:6px 10px;font-size:13px;margin-top:6px}
 .row{display:flex;gap:8px;margin-top:8px}
 .row input{flex:1}
 .top-links{display:flex;justify-content:space-between;margin-bottom:12px}
 .top-links a{color:#00796b;font-size:14px;text-decoration:none;font-weight:500}
</style></head><body>

<div class="top-links">
  <a href="/history">📋 History</a>
  <a href="/admin">⚙ Admin</a>
</div>

<h1>🩺 Physiotherapy Invoice</h1>
<form method="post" action="/preview">

<div class="card">
  <label>Patient Name *</label>
  <input name="patient" required>
  <div class="row">
    <input name="age" placeholder="Age">
    <input name="contact" placeholder="Contact No.">
  </div>
  <label>Diagnosis / Condition</label>
  <input name="diagnosis" placeholder="e.g. Knee pain, Back pain, Post-surgery rehab">
  <label>Referred By (Doctor)</label>
  <input name="referred_by" placeholder="Dr. ...">
</div>

<div class="card">
  <label>Treatment Period — From *</label>
  <input type="date" name="pf" required>
  <label>To *</label>
  <input type="date" name="pt" required>
</div>

<div class="card">
  <label>Treatment / Sessions</label>
  <div id="items">
    <div class="row">
      <input name="item_name" placeholder="Treatment" value="Home Visit Physiotherapy" required>
      <input name="qty" placeholder="Sessions" type="number" step="1" required>
      <input name="rate" placeholder="Fee per session" type="number" step="any" required>
    </div>
  </div>
  <button type="button" class="small" onclick="addRow()">+ Add Row</button>
</div>

<div class="card">
  <label>Payment Type</label>
  <select name="pay_type">
    <option>Cash</option>
    <option>UPI</option>
    <option>Bank Transfer</option>
    <option>Cheque</option>
    <option>Credit</option>
    <option>NEFT/RTGS</option>
  </select>
  <label>Payment Received Date *</label>
  <input type="date" name="pay_date" required>
  <label>GST Rate</label>
  <select name="gst_rate">
    <option value="0" selected>0% (Exempt)</option>
    <option value="5">5%</option>
    <option value="12">12%</option>
    <option value="18">18%</option>
  </select>
</div>

<button class="green" type="submit">👁 Preview Invoice</button>
</form>

<script>
function addRow(){
  const d=document.createElement('div'); d.className='row';
  d.innerHTML=`<input name="item_name" placeholder="Treatment" required>
               <input name="qty" placeholder="Sessions" type="number" step="1" required>
               <input name="rate" placeholder="Fee" type="number" step="any" required>`;
  document.getElementById('items').appendChild(d);
}
</script>
</body></html>
"""

# ==================== HTML — PREVIEW ====================
PREVIEW_HTML = """
<!doctype html><html><head><meta charset="utf-8">
<title>Preview Invoice</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
 body{font-family:system-ui,Arial;max-width:680px;margin:20px auto;padding:16px;background:#f0f7f4}
 h1{color:#00796b;margin-top:0}
 .warn{background:#fff3cd;color:#856404;padding:12px 14px;border-radius:8px;margin-bottom:14px;font-size:14px}
 .card{background:#fff;padding:16px;border-radius:10px;box-shadow:0 1px 4px rgba(0,0,0,.08);margin-bottom:14px}
 .row{display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px dashed #eee;font-size:14px}
 .row:last-child{border-bottom:0}
 .label{color:#666}
 .value{font-weight:500;color:#222;text-align:right}
 table{width:100%;border-collapse:collapse;margin-top:8px}
 th,td{padding:8px 6px;font-size:14px;text-align:left;border-bottom:1px solid #eee}
 th{color:#666;font-weight:500;font-size:13px}
 td.num{text-align:right}
 .totals{margin-top:10px;padding-top:10px;border-top:2px solid #00796b}
 .totals .row{border-bottom:0}
 .grand{font-size:17px;font-weight:700;color:#1b5e20}
 .btns{display:flex;gap:10px;margin-top:16px;flex-wrap:wrap}
 button, .btn{padding:13px 18px;border:0;border-radius:8px;font-size:15px;cursor:pointer;
             text-decoration:none;display:inline-block;text-align:center;flex:1;min-width:130px}
 .confirm{background:#2e7d32;color:#fff}
 .back{background:#eee;color:#333}
 .print-btn{background:#1565c0;color:#fff}
 .badge{display:inline-block;background:#00796b;color:#fff;padding:3px 8px;border-radius:6px;font-size:12px;font-weight:600}
 .copy-tag{text-align:right;font-size:11pt;font-weight:700;color:#00796b;margin-bottom:4mm;letter-spacing:.5px}
 .print-header{display:none}
 .print-only{display:none}
 .screen-only{display:block}

 @media print {
   body{background:#fff;max-width:none;margin:0;padding:0;font-size:11pt;color:#000}
   .warn, .btns, h1, .no-print, .screen-only{display:none !important}
   .print-only{display:block !important}
   .card{box-shadow:none;border:1px solid #ccc;border-radius:0;margin-bottom:6mm;
         padding:5mm;page-break-inside:avoid}
   .row{padding:2px 0;font-size:11pt}
   table{font-size:11pt}
   th,td{padding:3px 4px}
   .totals{border-top:2px solid #000}
   .grand{color:#000;font-size:13pt}
   .copy-tag{color:#000;border-bottom:1px solid #000;padding-bottom:2mm;margin-bottom:4mm}
   .print-header{display:block !important;margin-bottom:6mm;padding-bottom:4mm;
                 border-bottom:2px solid #00796b;text-align:center}
   .print-header h2{margin:0;color:#00796b;font-size:16pt}
   .print-header .sub{color:#555;font-size:10pt;margin-top:2px}
   .page1 { page-break-after: always; break-after: page; }
   @page{margin:15mm}
 }
</style></head><body>

{% macro invoice_body(copy_label=None) %}
  {% if copy_label %}<div class="copy-tag">{{ copy_label }}</div>{% endif %}

  <div class="card">
    <h3 style="margin-top:0;color:#00796b">Patient Details</h3>
    <div class="row"><span class="label">Name</span><span class="value">{{ data.patient }}</span></div>
    {% if data.age %}<div class="row"><span class="label">Age</span><span class="value">{{ data.age }}</span></div>{% endif %}
    {% if data.contact %}<div class="row"><span class="label">Contact</span><span class="value">{{ data.contact }}</span></div>{% endif %}
    {% if data.diagnosis %}<div class="row"><span class="label">Diagnosis</span><span class="value">{{ data.diagnosis }}</span></div>{% endif %}
    {% if data.referred_by %}<div class="row"><span class="label">Referred By</span><span class="value">{{ data.referred_by }}</span></div>{% endif %}
    <div class="row"><span class="label">Treatment Period</span><span class="value">{{ data.pf }} → {{ data.pt }}</span></div>
  </div>

  <div class="card">
    <h3 style="margin-top:0;color:#00796b">Treatment / Services</h3>
    <table>
      <tr>
        <th>Treatment</th>
        <th style="text-align:right">Sessions</th>
        <th style="text-align:right">Fee</th>
        <th style="text-align:right">Amount</th>
      </tr>
      {% for it in items %}
      <tr>
        <td>{{ it.name }}</td>
        <td class="num">{{ "%g"|format(it.qty) }}</td>
        <td class="num">{{ "%.2f"|format(it.rate) }}</td>
        <td class="num">{{ "%.2f"|format(it.qty * it.rate) }}</td>
      </tr>
      {% endfor %}
    </table>
    <div class="totals">
      <div class="row"><span class="label">Subtotal</span><span class="value">Rs {{ "%.2f"|format(subtotal) }}</span></div>
      {% if gst > 0 %}
      <div class="row"><span class="label">GST {{ data.gst_rate }}%</span><span class="value">Rs {{ "%.2f"|format(gst) }}</span></div>
      {% endif %}
      <div class="row grand"><span>Total</span><span>Rs {{ "%.2f"|format(total) }}</span></div>
    </div>
  </div>

  <div class="card">
    <h3 style="margin-top:0;color:#00796b">Payment</h3>
    <div class="row"><span class="label">Payment Type</span><span class="value">{{ data.pay_type }}</span></div>
    <div class="row"><span class="label">Received On</span><span class="value">{{ data.pay_date }}</span></div>
  </div>

  <div style="margin-top:8mm;font-size:10pt;color:#333">
    Therapist Signature: ____________________
  </div>
{% endmacro %}

<div class="screen-only">
  <h1>👁 Preview Invoice</h1>

  <div class="warn">
    ⚠️ Ye sirf preview hai — <b>invoice number abhi generate nahi hua</b>.<br>
    "Confirm & Download" dabane par milega:
    <span class="badge">{{ next_no }}</span>
  </div>

  {{ invoice_body() }}

  <form method="post" action="/api/download">
    <input type="hidden" name="data" value="{{ data_json | e }}">
    <div class="btns">
      <a href="javascript:history.back()" class="btn back">✏️ Edit</a>
      <button type="button" class="print-btn" onclick="window.print()">🖨️ Print (2 copies)</button>
      <button type="submit" class="confirm">✅ Confirm & Download PDF</button>
    </div>
  </form>

  <p style="text-align:center;color:#888;font-size:12px;margin-top:16px">
    🖨️ Print dabane par <b>2 pages</b> print honge — Original (patient) + Duplicate (clinic)
  </p>
</div>

<div class="print-only page1">
  <div class="print-header">
    <h2>{{ company_name }}</h2>
    <div class="sub">{{ company_address }} • {{ company_phone }}</div>
    <div class="sub">MSME: {{ company_msme }}</div>
  </div>
  {{ invoice_body("ORIGINAL FOR PATIENT") }}
  <div style="text-align:center;font-size:9pt;color:#888;margin-top:6mm">
    This is a preview — not a valid tax invoice.
  </div>
</div>

<div class="print-only">
  <div class="print-header">
    <h2>{{ company_name }}</h2>
    <div class="sub">{{ company_address }} • {{ company_phone }}</div>
    <div class="sub">MSME: {{ company_msme }}</div>
  </div>
  {{ invoice_body("DUPLICATE FOR CLINIC") }}
  <div style="text-align:center;font-size:9pt;color:#888;margin-top:6mm">
    This is a preview — not a valid tax invoice.
  </div>
</div>

</body></html>
"""

# ==================== HTML — HISTORY ====================
HISTORY_HTML = """
<!doctype html><html><head><meta charset="utf-8">
<title>Invoice History</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
 body{font-family:system-ui,Arial;max-width:720px;margin:20px auto;padding:16px;background:#f0f7f4}
 h1{color:#00796b}
 .card{background:#fff;padding:12px 14px;border-radius:10px;box-shadow:0 1px 4px rgba(0,0,0,.08);margin-bottom:10px}
 .no{font-weight:600;color:#00796b}
 .meta{font-size:13px;color:#666;margin-top:4px}
 .amt{float:right;font-weight:700;color:#1b5e20}
 .links a{color:#00796b;text-decoration:none;margin-right:14px;font-size:14px}
 .empty{text-align:center;color:#999;padding:40px 0}
</style></head><body>
<h1>📋 Invoice History</h1>
<div class="links">
  <a href="/">← New Invoice</a>
  <a href="/admin">⚙ Admin</a>
</div>
<br>
{% if rows %}
  {% for r in rows %}
  <div class="card">
    <span class="amt">Rs {{ "%.2f"|format(r.total) }}</span>
    <div class="no">{{ r.inv_no }} — {{ r.patient }}</div>
    <div class="meta">{{ r.date }} • {{ r.pay_type }} • {{ r.sessions }} session(s) • {{ r.pf }} → {{ r.pt }}</div>
  </div>
  {% endfor %}
{% else %}
  <div class="empty">Abhi koi invoice nahi bana.</div>
{% endif %}
</body></html>
"""

# ==================== HTML — ADMIN ====================
ADMIN_HTML = """
<!doctype html><html><head><meta charset="utf-8">
<title>Admin</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
 body{font-family:system-ui,Arial;max-width:520px;margin:20px auto;padding:16px;background:#f0f7f4}
 h1{color:#00796b}
 .card{background:#fff;padding:16px;border-radius:10px;box-shadow:0 1px 4px rgba(0,0,0,.08);margin-bottom:14px}
 label{display:block;font-size:13px;color:#555;margin-top:10px}
 input{width:100%;padding:9px;border:1px solid #ccc;border-radius:6px;font-size:15px;box-sizing:border-box}
 button{padding:11px 18px;border:0;border-radius:8px;background:#00796b;color:#fff;font-size:15px;cursor:pointer;margin-top:12px}
 button.red{background:#c62828}
 .msg{background:#e8f5e9;color:#1b5e20;padding:10px;border-radius:6px;margin-bottom:12px}
 .links a{color:#00796b;text-decoration:none;margin-right:14px;font-size:14px}
</style></head><body>
<h1>⚙ Admin Panel</h1>
<div class="links">
  <a href="/">← New Invoice</a>
  <a href="/history">📋 History</a>
</div>
<br>

{% if msg %}<div class="msg">{{ msg }}</div>{% endif %}

<div class="card">
  <h3>Invoice Counter ({{ year }})</h3>
  <p style="color:#666;font-size:14px">Abhi tak ka last number: <b>{{ counter }}</b></p>
  <p style="color:#666;font-size:13px">Agla invoice: <b>PHY-{{ year }}-{{ "%04d"|format(counter+1) }}</b></p>

  <form method="post" action="/admin/set_counter">
    <label>Counter set karein (agle invoice ke liye)</label>
    <input name="counter" type="number" min="0" value="{{ counter }}" required>
    <button type="submit">Save</button>
  </form>
</div>

<div class="card">
  <h3 style="color:#c62828">Danger Zone</h3>
  <p style="color:#666;font-size:13px">History delete kar dega. Counter same rahega.</p>
  <form method="post" action="/admin/clear_history"
        onsubmit="return confirm('Pakka history delete karni hai?');">
    <button class="red" type="submit">🗑 Clear Invoice History</button>
  </form>
</div>

</body></html>
"""

# ==================== ROUTES ====================
@app.route("/")
def index():
    return render_template_string(FORM_HTML)

@app.route("/history")
def history():
    rows = get_history(200)
    return render_template_string(HISTORY_HTML, rows=rows)

@app.route("/admin")
def admin():
    msg = request.args.get("msg", "")
    return render_template_string(
        ADMIN_HTML,
        counter=get_counter(),
        year=date.today().year,
        msg=msg
    )

@app.route("/admin/set_counter", methods=["POST"])
def admin_set_counter():
    try:
        val = int(request.form.get("counter", 0))
        if set_counter(val):
            return redirect(url_for("admin", msg=f"Counter set to {val} ✅"))
        return redirect(url_for("admin", msg="KV connect nahi hai ❌"))
    except Exception as e:
        return redirect(url_for("admin", msg=f"Error: {e}"))

@app.route("/admin/clear_history", methods=["POST"])
def admin_clear_history():
    r = get_redis()
    if r:
        try:
            r.delete("invoice_history")
        except Exception as e:
            return redirect(url_for("admin", msg=f"Error: {e}"))
    return redirect(url_for("admin", msg="History cleared ✅"))

@app.route("/preview", methods=["POST"])
def preview():
    data = {
        "patient":     request.form.get("patient", "").strip(),
        "age":         request.form.get("age", "").strip(),
        "contact":     request.form.get("contact", "").strip(),
        "diagnosis":   request.form.get("diagnosis", "").strip(),
        "referred_by": request.form.get("referred_by", "").strip(),
        "pf":          request.form.get("pf", ""),
        "pt":          request.form.get("pt", ""),
        "pay_type":    request.form.get("pay_type", "Cash"),
        "pay_date":    request.form.get("pay_date", ""),
        "gst_rate":    int(request.form.get("gst_rate", 0)),
    }

    names = request.form.getlist("item_name")
    qtys  = request.form.getlist("qty")
    rates = request.form.getlist("rate")
    items = []
    for n_, q, r in zip(names, qtys, rates):
        try:
            q = float(q)
            r = float(r)
            if n_.strip():
                items.append({"name": n_.strip(), "qty": q, "rate": r})
        except Exception:
            pass

    if not items:
        return "Koi valid treatment nahi mila. <a href='/'>Wapas jaayein</a>.", 400

    data["items"] = items
    subtotal = sum(i["qty"] * i["rate"] for i in items)
    gst = subtotal * data["gst_rate"] / 100
    total = subtotal + gst

    s = get_settings()

    return render_template_string(
        PREVIEW_HTML,
        data=data, items=items,
        subtotal=subtotal, gst=gst, total=total,
        data_json=json.dumps(data),
        next_no=peek_next_invoice_no(),
        company_name=s["company"],
        company_address=s["address"],
        company_phone=s["phone"],
        company_msme=s["msme"],
    )

@app.route("/api/download", methods=["POST"])
def download():
    raw = request.form.get("data")
    if not raw:
        return "Data missing. <a href='/'>Form</a> se dobara try karein.", 400
    try:
        data = json.loads(raw)
    except Exception:
        return "Data invalid.", 400

    s = get_settings()
    patient     = data.get("patient", "").strip()
    age         = data.get("age", "").strip()
    contact     = data.get("contact", "").strip()
    diagnosis   = data.get("diagnosis", "").strip()
    referred_by = data.get("referred_by", "").strip()
    pf          = data.get("pf", "")
    pt          = data.get("pt", "")
    pay_type    = data.get("pay_type", "Cash")
    pay_date    = data.get("pay_date", "")
    gst_rate    = int(data.get("gst_rate", s["gst_rate"]))

    items_raw = data.get("items", [])
    items = []
    total_sessions = 0
    for it in items_raw:
        try:
            n_ = it["name"].strip()
            q  = float(it["qty"])
            r  = float(it["rate"])
            if n_:
                items.append((n_, q, r, q * r))
                total_sessions += int(q)
        except Exception:
            pass

    if not items:
        return "Koi valid treatment nahi mila.", 400

    subtotal = sum(i[3] for i in items)
    gst = subtotal * gst_rate / 100
    total = subtotal + gst

    inv_no = gen_invoice_no()
    today = date.today().strftime("%d-%m-%Y")

    save_history({
        "inv_no": inv_no, "patient": patient, "age": age, "contact": contact,
        "diagnosis": diagnosis, "referred_by": referred_by,
        "date": today, "pf": pf or today, "pt": pt or today,
        "pay_type": pay_type, "pay_date": pay_date or today,
        "sessions": total_sessions, "total": round(total, 2),
    })

    buf = build_pdf_bytes(
        inv_no, patient, age, contact, diagnosis, referred_by,
        today, pf or today, pt or today, pay_type, pay_date or today,
        gst_rate, items, subtotal, gst, total, s
    )

    return send_file(
        buf, as_attachment=True,
        download_name=f"{inv_no}.pdf",
        mimetype="application/pdf"
    )

handler = app
