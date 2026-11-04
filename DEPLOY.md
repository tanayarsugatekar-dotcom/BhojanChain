# Putting BhojanChain online so every phone shares the same data

The server in `backend/` holds the accounts and listings and also serves the web app, so ONE address
is the website, the installable app and the API. Everyone who opens that address sees the same food,
and new listings appear on other phones within about 15 seconds without refreshing.

## Option A: free, from your own laptop (good for a college demo)
1. `pip install -r requirements.txt`
2. `cd backend && python -m uvicorn main:app --host 0.0.0.0 --port 8000`
3. Install Cloudflare's free `cloudflared` and run: `cloudflared tunnel --url http://localhost:8000`
   It prints an https link such as https://something.trycloudflare.com. Open it on any phone.
The laptop must stay on and online. Data is saved in `backend/bhojanchain.db` on the laptop.
(Set `BHOJAN_SEED=0` first if you do not want the demo listings.)

## Option B: always-on hosting with auto-deploy (Render, Railway or Fly.io)
1. Put this folder on GitHub.
2. Create a web service from the repo using the `Dockerfile` (on Render, "New > Blueprint" reads `render.yaml`).
3. Attach a persistent disk/volume mounted at `/data`. Without it the database is wiped on every restart or deploy.
   Free tiers usually have no persistent disk, so check the host's current plans.
4. Open the address the host gives you. Phone: browser menu > "Install app" / "Add to Home Screen".

## How changes reach users automatically
| You change | What happens |
|---|---|
| Listings, reservations, accounts | Stored on the server; every phone sees them within ~15 seconds. |
| Code (`frontend/` or `backend/`) | `git push`; the host redeploys. Installed apps load the new version the next time they open online. |
| Areas (`backend/belagavi_areas.json`) | Same as code. |
| Ride rates (`RIDE` in `frontend/app.js`) | Same as code. |

## Good to know
- Back up by copying the `bhojanchain.db` file (it is the whole database).
- Passwords are stored hashed (scrypt). There is no SMS, so "forgot password" means an admin must reset the account.
- Using only the web files on Netlify or similar: edit `frontend/config.js` and set `window.BHOJAN_API` to the server's address.
