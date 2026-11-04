# BhojanChain Belagavi 🍲
Market vendors, wedding venues and restaurants list leftover **cooked and raw food**, free or at a low price.
NGOs and people in need find it **near them**, reserve it, and see **how long it stays safe to eat**.

## Run
    pip install -r requirements.txt
    cd backend && python -m uvicorn main:app --host 0.0.0.0 --port 8000
Open http://localhost:8000 (the web app is served by the same server; no build step).
Demo data around Mumbai loads on first run (set BHOJAN_SEED=0 to disable). Tests: `cd backend && python -m pytest`.

## How it works
- **Sign up** as market vendor / wedding venue / restaurant (donor) or NGO / person in need (receiver).
- **Share food**: pick the food type, quantity, price (0 = free), when it was cooked/bought, and room or cold storage.
- **Shelf life**: `backend/shelf_life.py` holds conservative safe-hours per food (rice 4h room / 24h cold, leafy greens 12h / 72h, milk 2h / 2 days ...).
  Safe-until = prepared time + limit. Donors may shorten the limit, never extend it. Reserving is blocked once it expires.
- **Nearby**: listings and organisations are sorted by distance from your location (GPS or city preset), with a radius filter.
- **Reserve**: atomic stock decrement, a 4-digit pickup code, pickup/cancel flow; donors see incoming reservations.

Shelf-life values are guidance only. Always check smell, look and texture before eating.

## Belagavi (Belgaum) setup
- `backend/belagavi_areas.json` lists 24 Belagavi areas (Camp, Tilakwadi, Shahapur, Udyambag, Khade Bazaar, Mahantesh Nagar ...).
  **The coordinates are approximate area centres (about 1 km), not surveyed points.** Fix or add areas in that file; the server and the web app both read it.
- **Address checks** (`backend/areas.py`): area must be one of the list; donors must give a street/shop/landmark (5+ characters);
  pincode, if given, must be 6 digits starting 590 or 591; an optional exact map pin must be inside Belagavi and within 6 km of the chosen area.
  The saved address is built as `street, area, Belagavi pincode`.
- **Ride cost** (`RIDE` table at the top of `frontend/app.js`): Rapido Bike, Rapido Auto, Uber Auto, Uber Go.
  fare = base (covers first 2 km) + per-km beyond it + booking fee, shown as a range (-10% / +20%), using road distance = straight line x 1.35.
  These are estimates from typical Karnataka city fares, **not live prices**. Rapido and Uber publish no rate cards or free fare API.
  Edit the numbers to match what you see in the apps in Belagavi. Shown on each listing, in the reserve dialog, on the pickup code screen, and in the Ride cost tab.
- Demo data uses invented names and placeholder phone numbers.

## Accounts and sharing data between phones
Accounts use mobile number + password (stored hashed). Data lives on the server, so all phones share it and the app refreshes itself every 15 seconds.
See `DEPLOY.md` to put the server online (free laptop tunnel, PythonAnywhere, or a host with a persistent disk).
