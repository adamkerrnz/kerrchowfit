# KerrChow Fit in Docker (Portainer)

This branch (`docker-version`) runs KerrChow Fit on your own Docker host instead of claude.ai. It uses the same
`index.html`, with a small server standing in for the claude.ai pieces it relied on.

| On claude.ai | In the container |
|---|---|
| Artifact storage (check-offs, plan start, weather, Garmin snapshot) | SQLite file on the `kerrchowfit-data` volume |
| Strava connector | Strava's own API, through your own Strava API app (no Strava subscription needed) |
| Garmin Connect MCP server on your PC | The `garminconnect` library inside the container, signed in with your Garmin account |
| AccuWeather connector + scheduled Claude task | Open-Meteo forecast (free, no key), refreshed every 3 hours |
| Scheduled Claude task for Garmin at 5:45 am | Built-in job at `GARMIN_REFRESH_TIME` |
| claude.ai sign-in | Optional username and password for the whole site |

## How it fits together

```
browser ──> kerrchowfit container (port 8000, published as HOST_PORT)
              ├─ /                 index.html + claude-shim.js (provides window.claude)
              ├─ /api/db/*         page data in /data/kerrchowfit.db
              ├─ /api/mcp/call     Strava + Garmin "connector" calls
              ├─ /strava/connect   one-time Strava sign-in
              └─ scheduler         Garmin snapshot each morning, weather every 3 h, Strava best efforts hourly
volume kerrchowfit-data → /data   database, Strava tokens, Garmin tokens
```

Files on this branch:
- `docker-compose.yml`: the stack Portainer deploys.
- `docker/Dockerfile`: builds the image from this repository.
- `docker/app/`: the server (FastAPI). `main.py` routes, `store.py` SQLite, `strava.py`, `garmin.py`, `weather.py`, `jobs.py`.
- `docker/web/claude-shim.js`: makes the page's `window.claude.use("db" | "mcp" | "user" | "permissions")` calls go to the server.
- `.env.example`: every setting, with examples.

`index.html` itself is unchanged. When serving it, the server adds the shim script and swaps a few claude.ai-specific
messages (for example "Add it in claude.ai Settings" becomes "Connect it at /strava/connect").

---

## Before you start

You need:
1. A Docker host with **Portainer CE 2.19 or later** (Docker Standalone environment).
2. Your **Garmin Connect** email and password.
3. A **Strava API application** (free, 2 minutes):
   1. Go to https://www.strava.com/settings/api and create an app.
   2. **Application name:** KerrChow Fit. **Category:** Training. **Website:** anything, e.g. `http://localhost`.
   3. **Authorization Callback Domain:** the host name you will open the app at, **without** `http://` or the port.
      For example `192.168.1.50` (your Docker host's LAN address) or `kerrchowfit.example.com`.
   4. Note the **Client ID** and **Client Secret**.
4. Decide the address you'll use, e.g. `http://192.168.1.50:8088`. That's your `PUBLIC_URL`.

> The repository is on GitHub. If it's private, also create a GitHub **fine-grained personal access token** with
> read-only **Contents** access to `adamkerrnz/kerrchowfit` so Portainer can clone it.

---

## Deploy with Portainer Stacks

Portainer builds the image from the repository, so use the **Repository** build method. The Web editor method
can't build (it has no source code to build from).

1. In Portainer, open your Docker environment and go to **Stacks → + Add stack**.
2. **Name:** `kerrchowfit`
3. **Build method:** **Repository**
4. Repository settings:
   - **Authentication:** turn on only if the repo is private. Username `adamkerrnz`, password = the personal access token.
   - **Repository URL:** `https://github.com/adamkerrnz/kerrchowfit`
   - **Repository reference:** `refs/heads/docker-version`
   - **Compose path:** `docker-compose.yml`
   - **GitOps updates:** optional. Turn it on with **Polling** (e.g. every `24h`) if you want new commits on the branch to redeploy automatically.
5. **Environment variables:** click **Advanced mode** and paste this, filled in with your values:

   ```
   HOST_PORT=8088
   TZ=Pacific/Auckland
   BASIC_AUTH_USER=adam
   BASIC_AUTH_PASSWORD=pick-a-long-password
   PUBLIC_URL=http://192.168.1.50:8088
   STRAVA_CLIENT_ID=12345
   STRAVA_CLIENT_SECRET=your-strava-client-secret
   GARMIN_EMAIL=you@example.com
   GARMIN_PASSWORD=your-garmin-password
   GARMIN_REFRESH_TIME=05:45
   WEATHER_LAT=-36.8485
   WEATHER_LON=174.7633
   ```

   | Variable | What it does |
   |---|---|
   | `HOST_PORT` | Port on the Docker host. Open the app at `http://<host>:<HOST_PORT>`. |
   | `TZ` | Your time zone. Drives "today", the week view and the job times. |
   | `BASIC_AUTH_USER` / `BASIC_AUTH_PASSWORD` | Browser login for the whole site. Leave both empty only if the host is unreachable from outside your network. |
   | `PUBLIC_URL` | The exact address you open the app at. Used for the Strava sign-in redirect. |
   | `STRAVA_CLIENT_ID` / `STRAVA_CLIENT_SECRET` | From your Strava API app. |
   | `STRAVA_REFRESH_TOKEN` | Optional. Only if you'd rather paste a token than use `/strava/connect`. |
   | `GARMIN_EMAIL` / `GARMIN_PASSWORD` | Used once to sign in; the tokens are then saved on the volume. |
   | `GARMIN_REFRESH_TIME` | When the daily Garmin snapshot runs (24-hour `HH:MM`). |
   | `WEATHER_LAT` / `WEATHER_LON` | Forecast location. Default is Auckland Central. |

6. Click **Deploy the stack**. The first build takes a few minutes (it installs Python packages).
7. Go to **Containers → kerrchowfit**. Status should become **healthy** within a minute. If not, open **Logs**.

### Connect Strava (once)

1. Open `http://<host>:8088/strava/connect` (your `PUBLIC_URL` plus `/strava/connect`) and sign in with your site login.
2. Strava asks you to authorise KerrChow Fit. Leave **View data about your activities** ticked and click **Authorize**.
3. You land back on the app. The Strava section loads after a few seconds.

The Strava tokens are saved on the volume and refresh themselves.

### Garmin sign-in

On first start the container signs in with `GARMIN_EMAIL` / `GARMIN_PASSWORD` and saves tokens to `/data/garmin-tokens`.
Check **Logs** for `Garmin snapshot saved for <date>`.

If your Garmin account uses **2-step verification**, the log says Garmin asked for a code. Then:
1. **Containers → kerrchowfit → Console**, command `/bin/sh`, user `app`, click **Connect**.
2. Run `python -m app.garmin_login`, and enter the code Garmin sends you.
3. Back in Portainer, **restart** the container.

Once tokens are saved you can delete `GARMIN_PASSWORD` from the stack's environment variables and click
**Update the stack**. The tokens last months; if Garmin expires them, put the password back or run the login command again.

### Check it

- `http://<host>:8088/` shows the tracker, weather on each day, the Garmin section and Strava.
- The Garmin chip reads **Live** when the page fetched it just now, or **Saved** for the morning snapshot.
- To run a job now: `curl -u adam:password -X POST http://<host>:8088/api/jobs/garmin` (or `/weather`).
- If a Garmin panel says "No data", compare with the raw response at
  `http://<host>:8088/api/debug/garmin/status` (also `summary`, `readiness`, `hrv`, `sleep`, `maxmetrics`).
  Garmin's field names aren't documented, so `docker/app/garmin.py` may need a tweak.

---

## Updating

- **With GitOps polling on:** push to `docker-version` and Portainer redeploys on its next poll.
- **By hand:** **Stacks → kerrchowfit → Pull and redeploy**. If Portainer offers **Re-pull image and redeploy**
  or a rebuild option, turn it on so the image is rebuilt from the new code.

Your data stays on the `kerrchowfit-data` volume across updates.

## Backups

Everything worth keeping is in the `kerrchowfit-data` volume: `kerrchowfit.db` (check-offs, plan start date,
snapshots) and the Strava and Garmin tokens. Back up that volume, or the file
`/var/lib/docker/volumes/kerrchowfit_kerrchowfit-data/_data/kerrchowfit.db` on the host.

## Using it away from home

Don't publish the port to the internet as-is. Use one of:
- **Tailscale** on the Docker host and your phone (simplest), then open `http://<tailscale-name>:8088`.
- A **reverse proxy** with HTTPS (Nginx Proxy Manager, Traefik or Caddy) in front of the container, keeping the site login on.
  Set `PUBLIC_URL` to the HTTPS address and update the Strava app's callback domain to match.

## Without Portainer

```bash
cp .env.example .env   # fill it in
docker compose up -d --build
```

## Known differences from the claude.ai version

- **Strava best efforts** cover the last 12 months, worked out from your activities, not Strava's all-time records.
  The first time, they fill in over a few hours to stay inside Strava's rate limit (100 requests per 15 minutes).
- **Garmin** goes through the unofficial `garminconnect` library. Garmin can change its sign-in or data and break it
  without notice; updating the library (`docker/requirements.txt`) usually fixes it.
- **VO2 max trend:** the first Garmin run fetches about 8 weeks of daily values (one request per day), so it takes a minute.
- **Weather** comes from Open-Meteo, not AccuWeather, and has no MetService warnings.
- **Check-offs** start empty. Progress saved on claude.ai stays there; it isn't copied across.
- There's one user: whoever has the site login can tick sessions off.
