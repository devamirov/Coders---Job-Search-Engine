# Email backend for InfiNet (spectre.guru)

Separate backend for signup verification codes and password-reset links. Deploy to **/var/www/spectre.guru** (do not mix with other backends).

## Endpoints

- `POST /api/send-signup-code` — Body: `{ "email": "..." }`. Sends 6-digit code from admin@infinet.services.
- `POST /api/verify-signup-code` — Body: `{ "email": "...", "code": "123456" }`. Returns `{ "ok": true }` if valid.
- `POST /api/send-reset-link` — Body: `{ "email": "..." }`. Sends reset link to that email.
- `POST /api/verify-reset-token` — Body: `{ "token": "..." }`. Returns `{ "ok": true, "email": "..." }` if valid; invalidates token.

## Env

Copy `.env.example` to `.env` and set `SMTP_*` and `FROM_EMAIL` (admin@infinet.services). Set `BASE_URL=https://spectre.guru` for reset links.

## Run locally

```bash
pip install -r requirements.txt
export $(cat .env | xargs)
python app.py
```

Runs on port 5000. On the server, run under gunicorn or systemd and proxy Apache to this app (e.g. `/api` → `http://127.0.0.1:5000`).

## Deploy to /var/www/spectre.guru

1. Copy this folder to `/var/www/spectre.guru/email-backend` (or similar).
2. Create `/var/www/spectre.guru/data` for SQLite DB.
3. Set `.env` with SMTP and BASE_URL.
4. Run with gunicorn: `gunicorn -w 1 -b 127.0.0.1:5000 app:app`
5. In Apache vhost for spectre.guru, add: `ProxyPass /api http://127.0.0.1:5000/api` (and `ProxyPassReverse /api http://127.0.0.1:5000/api`).

Then the Streamlit app can call `https://spectre.guru/api/send-signup-code` etc.
