# Deploy (free): Streamlit Community Cloud + Supabase

The app stores each dataset (`real`, `sample`) as a single JSON blob in Supabase Postgres.
With no Supabase credentials set, it transparently falls back to local JSON files, so
local development needs no setup.

## 1. Create a free Supabase project
1. Sign up at <https://supabase.com> → **New project** (free tier).
2. In the project's **SQL Editor**, run:
   ```sql
   create table datasets (
     name       text primary key,        -- 'real' | 'sample'
     data       jsonb not null default '{}'::jsonb,
     updated_at timestamptz default now()
   );
   ```
3. **Project Settings → API**: copy the **Project URL** and the **service_role** key
   (under "Project API keys"). The service-role key is used server-side only — never
   ship it to a browser or commit it.

## 2. Seed your existing data into Supabase
From the **repo root**, with your real `data.json` (and optionally `data_sample.json`)
present. Pick **one** way to supply credentials:

**Option A — a secrets file (easiest; also used by local app runs):**
```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# edit .streamlit/secrets.toml and paste your real URL + service-role key
python scripts/migrate_to_supabase.py
```

**Option B — environment variables (note: NO spaces around `=`):**
```bash
pip install -r requirements.txt
export SUPABASE_URL="https://<project-ref>.supabase.co"
export SUPABASE_KEY="<service-role key>"
python scripts/migrate_to_supabase.py
```

You should see two `datasets` rows in the Supabase Table Editor. (Skip this if you'd
rather start empty and add players in the app.) `.streamlit/secrets.toml` is gitignored,
so your key stays local.

## 3. Deploy on Streamlit Community Cloud
1. Push to GitHub (the repo is already public).
2. Go to <https://share.streamlit.io> → **New app** → repo `timmymatten/ASL-Squad-Tracker`,
   branch `main`, main file **`app.py`** → **Deploy**.
3. In the app's **⋮ → Settings → Secrets**, paste:
   ```toml
   SUPABASE_URL = "https://<project-ref>.supabase.co"
   SUPABASE_KEY = "<service-role key>"
   ```
   Save — the app reboots and now reads/writes Supabase. You get a public
   `https://<name>.streamlit.app` link.

## Local development
- **No secrets** → uses local `data.json` / `data_sample.json` (current behavior).
- **With Supabase** → copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml`
  and fill in the keys (file is gitignored), or `export` the two env vars before running.

## Notes
- **Free-tier pause:** Supabase pauses an inactive free project after ~7 days; your data
  is retained — click **Restore** in the dashboard. Fine for seasonal club use.
- **One writer at a time:** saves overwrite the whole dataset blob. Fine when the organizer
  edits and others view; avoid two people editing simultaneously.
- **Restricting edits:** the public link exposes edit controls. Ask for the optional
  password gate if you want only the organizer to be able to make changes.
