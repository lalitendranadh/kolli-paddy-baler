# Kolli Satyanarayana Earth Work & Paddy Baler Services — MVP

Mobile-first Flask web app backed by SQLite SQL database.

## Run locally
1. Install Python 3.10+.
2. In this folder: `python -m venv .venv`
3. Activate it, then `pip install -r requirements.txt`
4. Run: `python app.py`
5. Open `http://localhost:5000` on your computer.

For access from phones on the same Wi-Fi, open `http://YOUR-COMPUTER-LAN-IP:5000`.

## Demo logins (change these before hosting)
- Owner: `owner` / `owner123`
- Driver: `driver` / `driver123`

## SMS
SMS sending is off by default. To enable one normal SMS per saved baling entry, configure a Twilio account and set:
- `TWILIO_ACCOUNT_SID`
- `TWILIO_AUTH_TOKEN`
- `TWILIO_PHONE_NUMBER`

SMS costs and Indian sender-ID/route requirements depend on provider and local regulatory setup. Check an India-supported provider and compliant transactional SMS setup before going live. The app will clearly report if SMS is not configured.

## Hosting
Deploy the Flask app on a Python hosting service that supports persistent storage. Set environment variables:
- `SECRET_KEY` to a long random value
- `OWNER_PASSWORD`
- `DRIVER_PASSWORD`
- `DATABASE_PATH` to persistent disk location (if available)
- SMS credentials if configured

Do not deploy with demo passwords. Enable HTTPS and persistent backups.

## Current MVP features
- Driver/owner logins
- Farmer saved by mobile number; repeat visits link to existing profile
- Rolling entries with timestamp, roll count, rate ₹30–₹40, automatic total
- SMS receipt integration (optional provider configuration)
- Billing and payment status, partial payment support
- Owner-only expense entry: diesel, wages, repairs, spare parts, other
- Owner-only profit/loss summary
- Audit log for job creation and payment updates

## Important limits of this first version
- No public hosting/deployment has been performed yet.
- Driver can record payments, but saved baling details are not editable from the interface.
- SMS is not active until provider credentials are configured.
- For production, add stronger deployment hardening, automated backup, payment audit refinements and testing.

## Deploy using Render Blueprint (recommended for this SQLite MVP)
1. Create a GitHub repository and upload the extracted project files, including `render.yaml`.
2. In Render, choose **New > Blueprint**, connect the GitHub repo, and review the Blueprint.
3. Set `OWNER_PASSWORD` and `DRIVER_PASSWORD` when prompted to strong unique passwords.
4. Confirm deployment. This configuration uses a paid web service and persistent disk so the SQLite database is retained.
5. Once deployed, open the generated `onrender.com` URL and log in. Change the business contact under Owner Settings.

Do not enter real farmer data until you have tested login, entries, payments, SMS provider, and backup/recovery.
