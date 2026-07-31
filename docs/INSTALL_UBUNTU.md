# Ubuntu Install Guide

Deploy RadIMO Cortex on a fresh Ubuntu server for intranet use.

This guide assumes:
- a single Ubuntu host
- the application code will be deployed to `/opt/radimo`
- users access the service inside a closed intranet
- current runtime state should be copied from the existing instance

---

## What This App Needs

From the current repository:
- Flask app entrypoint: `app.py`
- Gunicorn entrypoint: `app:app`
- Gunicorn config: `gunicorn_config.py`
- Config template: `config.demo.yaml`
- Runtime config: local, ignored `config.yaml` created from the template
- Persistent runtime folders: `data/`, `uploads/`, `logs/`
- Health endpoints: `/healthz`, `/readyz`, `/status`

Important:
- `gunicorn_config.py` uses `worker_class = "gevent"`
- `gevent` must be installed together with `requirements.txt`

---

## Recommended Directory Layout

```text
/opt/radimo                 application code
/opt/radimo/.venv           Python virtual environment
/etc/radimo                 deployment-specific config backups or env files
/var/log/radimo             optional central service logs
```

The application itself expects to read and write relative paths from its working directory, so `data/`, `uploads/`, and `logs/` should remain inside `/opt/radimo`.

---

## 1. Prepare Ubuntu

Install base packages during the allowed online window:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git curl
```

Create a dedicated service user:

```bash
sudo adduser --system --group --home /opt/radimo svc-radimo
sudo mkdir -p /opt/radimo /etc/radimo /var/log/radimo
sudo chown -R svc-radimo:svc-radimo /opt/radimo /var/log/radimo
```

---

## 2. Copy the Application

Copy the full `radimo_dev` folder to the target host:

```bash
sudo rsync -a /path/to/radimo_dev/ /opt/radimo/
sudo chown -R svc-radimo:svc-radimo /opt/radimo
```

Do not rely on a developer home directory for the live service.

Create the deployment-local configuration if it was not supplied separately:

```bash
sudo -u svc-radimo cp /opt/radimo/config.demo.yaml /opt/radimo/config.yaml
sudo chmod 600 /opt/radimo/config.yaml
```

`config.yaml` is intentionally ignored by Git. Do not add the live file or its credentials to the repository.

---

## 3. Create the Python Environment

```bash
sudo -u svc-radimo python3 -m venv /opt/radimo/.venv
sudo -u svc-radimo /opt/radimo/.venv/bin/pip install -r /opt/radimo/requirements.txt
```

If you install packages individually for troubleshooting, make sure `gevent` is present:

```bash
sudo -u svc-radimo /opt/radimo/.venv/bin/python -c "import flask, pandas, yaml, pytz, apscheduler, gevent"
```

---

## 4. Copy Current Runtime State

If the new server should start with the current live data, stop the source service
or make a consistent backup first, then copy these paths from the existing instance:

```text
data/worker_skill_roster.json
data/button_weights.json
data/fairness_state.json
uploads/master_medweb.csv
uploads/backups/
```

Copy the deployment-local `config.yaml` separately and keep its permissions at
`600`. Do not replace it with the tracked demo template during a normal update.

Usually you do **not** need to copy:
- `logs/`
- `.pytest_cache/`
- `__pycache__/`
- test fixtures under `test_data/`

---

## 5. Replace Demo Credentials Before Go-Live

The tracked demo file uses the intentionally public password `radimo`. Edit the local `config.yaml` on the new server and change:
- `secret_key`
- `admin_password`
- `access_password` if basic access should be enabled

Generate a Flask secret key with:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Current repo defaults should not be kept for production-like intranet use.

---

## 6. Option 1: Run Gunicorn Directly

This is the simplest deployment and the default choice when the service is accessed only by intranet IP and port.

Create `/etc/systemd/system/radimo-cortex.service`:

```ini
[Unit]
Description=RadIMO Cortex
After=network.target

[Service]
User=svc-radimo
Group=svc-radimo
WorkingDirectory=/opt/radimo
ExecStart=/opt/radimo/.venv/bin/gunicorn -c gunicorn_config.py app:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now radimo-cortex
```

Verify:

```bash
curl -sS http://127.0.0.1:5035/healthz
curl -sS http://127.0.0.1:5035/readyz
sudo journalctl -u radimo-cortex -n 100 --no-pager
```

---

## 7. Option 2: Put nginx in Front

Use this when you want a stable intranet URL, cleaner public ports, or reverse-proxy control. Gunicorn stays local, nginx becomes the public entrypoint.

Install nginx:

```bash
sudo apt install -y nginx
```

The checked-in Gunicorn configuration listens on `0.0.0.0:5035`. For nginx, make
Gunicorn listen only on localhost in the deployment copy (or override it in the
systemd `ExecStart` command):

```text
127.0.0.1:5035
```

Create `/etc/nginx/sites-available/radimo-cortex`:

```nginx
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:5035;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable the site:

```bash
sudo ln -s /etc/nginx/sites-available/radimo-cortex /etc/nginx/sites-enabled/radimo-cortex
sudo nginx -t
sudo systemctl reload nginx
```

Verify through nginx:

```bash
curl -sS http://127.0.0.1/healthz
curl -sS http://127.0.0.1/readyz
```

If you later receive a real hostname, replace `server_name _;` with that intranet DNS name.

---

## 8. First Validation Checklist

- `systemctl status radimo-cortex` shows the service as running
- `/healthz` returns HTTP `200`
- `/readyz` returns HTTP `200`
- `/status` renders correctly
- admin login works with the rotated password
- current roster and weights are visible in the Tools menu
- current uploaded Master CSV is recognized
- live or staged backups load as expected

---

## 9. Operational Notes

- The app reads and writes local state from `data/`, `uploads/`, and `logs/`; keep regular backups of `data/` and `uploads/`, including the local `config.yaml` through your secure configuration backup process.
- `readyz` is the correct probe for operational readiness because it runs the built-in checks.
- If `readyz` fails, inspect the returned JSON and the application log in `logs/selection.log`.
- If you later want TLS, SSO, or a stable hostname, extend the nginx option rather than exposing Gunicorn directly.
