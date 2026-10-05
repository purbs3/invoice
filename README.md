# 🩺 Physiotherapy Invoice Generator

Home physiotherapy के लिए simple invoice app — patient details, treatment sessions, GST, 2-copy PDF, history और admin panel के साथ।

## Features
- 🩺 Patient + Diagnosis + Referred By details
- 📅 Treatment period (From → To)
- 💰 Multi-row treatments with sessions & fee
- 👁 Preview first, then confirm (invoice number waste nahi hota)
- 🖨️ Print 2 copies directly (Original for Patient + Duplicate for Clinic)
- 📄 Download PDF (2 pages)
- 🔢 Sequential invoice numbers (PHY-2026-0001, 0002…)
- 📋 Invoice history (last 1000)
- ⚙️ Admin panel — counter set/reset, history clear
- 🚫 No government use — clearly marked

## Tech Stack
- **Backend:** Flask (Python)
- **PDF:** ReportLab
- **Storage:** Vercel KV (Upstash Redis)
- **Hosting:** Vercel (free tier)

## Setup (Local)

```bash
pip install -r requirements.txt
python api/index.py
