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

## Option B: no-card hosting with PythonAnywhere
PythonAnywhere's free Beginner account can keep the SQLite database on its persistent home directory and serves the app over HTTPS. Its free plan has limited daily CPU and storage, so it is best for a small demo rather than a high-traffic production service.

1. Create a free Beginner account at [pythonanywhere.com](https://www.pythonanywhere.com/registration/register/beginner/), then open a Bash console.
2. Clone this repository into your home directory (or upload the project files). In the console:
   ```
   git clone https://github.com/tanayasugatekar/bhojanchain.git
   cd ~/bhojanchain
   mkvirtualenv --python=/usr/bin/python3.13 bhojanchain
   pip install -r requirements.txt
   ```
   If the repository is private, use PythonAnywhere's GitHub authentication to clone it, or upload the files from the private repository.
3. In the **Web** tab, add a web app using **Manual configuration** and the same Python version as the virtualenv.
4. Set the web app's virtualenv to `/home/<your-username>/.virtualenvs/bhojanchain`.
5. Edit the WSGI configuration file linked in the Web tab. Replace its contents with:
   ```
   import os
   import sys

   project = "/home/<your-username>/bhojanchain/backend"
   if project not in sys.path:
       sys.path.insert(0, project)

   os.environ["BHOJAN_SEED"] = "0"
   from wsgi import application
   ```
   Replace `<your-username>` with your PythonAnywhere username.
   The supplied WSGI adapter creates its event loop inside each uWSGI worker.
6. Click **Reload** in the Web tab and open `https://<your-username>.pythonanywhere.com/api/health`. A healthy service returns `{"status":"ok"}`. Then open the same address without `/api/health` to install the app on phones.

The SQLite database is stored at `backend/bhojanchain.db` in your home directory and persists across app reloads. Back it up regularly. PythonAnywhere free accounts have a daily CPU allowance and restricted outbound access; this app serves its frontend and API from one address and does not require server-side calls to third-party APIs.

## Option C: paid always-on hosting with auto-deploy (Render, Railway or Fly.io)
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
- Passwords are stored hashed (scrypt). "Forgot password" can be handled through OTP login until a dedicated reset flow is added.
- Using only the web files on Netlify or similar: edit `frontend/config.js` and set `window.BHOJAN_API` to the server's address.

## OTP and admin configuration
Set these environment variables in the PythonAnywhere web app configuration for real OTP and admin access:

- `BHOJAN_OTP_REQUIRED=1` requires an OTP when creating an account or logging in with OTP.
- `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` enable SMS delivery through Twilio.
- `BHOJAN_ADMIN_USERNAME` and `BHOJAN_ADMIN_PASSWORD` protect the admin account-management screen.

For local testing only, set `BHOJAN_OTP_DEV=1`; the OTP request response includes the test OTP.
