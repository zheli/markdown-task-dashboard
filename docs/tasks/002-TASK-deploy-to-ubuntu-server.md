# 002 — Deploy dashboard to tasks.z12z.org

**Type:** Task
**Status:** ⏳ Not started
**Created:** 2025-07-15
**Updated:** 2025-07-15

## Goal

Deploy the markdown task dashboard to `ubuntu@89.167.111.224`, accessible at
`https://tasks.z12z.org`, protected by Google SSO via `oauth2-proxy`.

## Architecture

```
Browser → nginx (443, TLS) → oauth2-proxy (4180) → dashboard (8000)
```

All services run as Docker Compose containers on the server. TLS is handled by
Let's Encrypt (certbot). Google OAuth 2.0 protects the entire dashboard —
unauthenticated requests are redirected to Google login.

## Pre-requisites (manual, before running steps)

- [ ] DNS A record: `tasks.z12z.org` → `89.167.111.224`
- [ ] Google Cloud OAuth 2.0 credentials created (client ID + secret)
  - Authorized redirect URI: `https://tasks.z12z.org/oauth2/callback`
- [ ] `GITHUB_TOKEN` available to place in `.env` on server

## Progress

### 1. Server preparation
- [ ] SSH into server: `ssh ubuntu@89.167.111.224`
- [ ] Verify/install Docker and Docker Compose plugin
- [ ] Verify/install nginx and certbot
- [ ] Create project directory: `/home/ubuntu/markdown-task-dashboard`

### 2. Deploy project files
- [ ] Clone repo onto server:
  ```bash
  git clone git@github.com:zheli/markdown-task-dashboard.git /home/ubuntu/markdown-task-dashboard
  ```
  (or `rsync` if SSH key for GitHub is not on server)

### 3. Create `.env` file on server
- [ ] Create `/home/ubuntu/markdown-task-dashboard/.env` with:
  ```
  GITHUB_TOKEN=<secret>
  BACKEND_PORT=8000
  FRONTEND_PORT=8080
  CONFIG_PATH=config.yaml
  MOCK_DATA=false
  OAUTH2_CLIENT_ID=<google-client-id>
  OAUTH2_CLIENT_SECRET=<google-client-secret>
  OAUTH2_COOKIE_SECRET=<random-32-byte-base64>  # generate: openssl rand -base64 32
  OAUTH2_EMAIL_DOMAIN=<your-allowed-domain-or-*>
  ```

### 4. Add oauth2-proxy to docker-compose.yml
- [ ] Add `oauth2-proxy` service to `docker-compose.yml`:
  ```yaml
  oauth2-proxy:
    image: quay.io/oauth2-proxy/oauth2-proxy:v7.6.0
    command:
      - --provider=google
      - --upstream=http://dashboard:8000
      - --http-address=0.0.0.0:4180
      - --redirect-url=https://tasks.z12z.org/oauth2/callback
      - --email-domain=${OAUTH2_EMAIL_DOMAIN:-*}
      - --cookie-secure=true
      - --cookie-domain=tasks.z12z.org
    environment:
      OAUTH2_PROXY_CLIENT_ID: ${OAUTH2_CLIENT_ID}
      OAUTH2_PROXY_CLIENT_SECRET: ${OAUTH2_CLIENT_SECRET}
      OAUTH2_PROXY_COOKIE_SECRET: ${OAUTH2_COOKIE_SECRET}
    ports:
      - "127.0.0.1:4180:4180"
    depends_on:
      - dashboard
  ```
- [ ] Remove public port mapping from `dashboard` service (keep it internal only)

### 5. Obtain TLS certificate
- [ ] Temporarily start nginx with HTTP-only config to pass ACME challenge
- [ ] Run: `sudo certbot certonly --nginx -d tasks.z12z.org`
- [ ] Verify cert files exist at `/etc/letsencrypt/live/tasks.z12z.org/`

### 6. Configure nginx
- [ ] Create `/etc/nginx/sites-available/tasks.z12z.org`:
  ```nginx
  server {
      listen 80;
      server_name tasks.z12z.org;
      return 301 https://$host$request_uri;
  }

  server {
      listen 443 ssl;
      server_name tasks.z12z.org;

      ssl_certificate     /etc/letsencrypt/live/tasks.z12z.org/fullchain.pem;
      ssl_certificate_key /etc/letsencrypt/live/tasks.z12z.org/privkey.pem;

      location / {
          proxy_pass http://127.0.0.1:4180;
          proxy_set_header Host $host;
          proxy_set_header X-Real-IP $remote_addr;
          proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
          proxy_set_header X-Forwarded-Proto $scheme;
      }
  }
  ```
- [ ] Enable site: `sudo ln -s /etc/nginx/sites-available/tasks.z12z.org /etc/nginx/sites-enabled/`
- [ ] Test and reload: `sudo nginx -t && sudo systemctl reload nginx`

### 7. Build and start the stack
- [ ] `docker compose up -d --build`
- [ ] Check logs: `docker compose logs -f`

### 8. Verify
- [ ] Visit `https://tasks.z12z.org` in browser
- [ ] Confirm redirect to Google login
- [ ] Confirm dashboard loads after authentication
- [ ] Confirm TLS certificate is valid

## Notes

- `oauth2-proxy` image is pinned to `v7.6.0` — check for latest stable before deploying.
- `OAUTH2_COOKIE_SECRET` must be exactly 16, 24, or 32 bytes (use `openssl rand -base64 32`).
- Certbot auto-renewal is handled by the default systemd timer installed with certbot.
- The `dashboard` service should NOT have a public port binding after oauth2-proxy is added.
- `oauth2-proxy` port is bound to `127.0.0.1` only so it is not publicly reachable.

## Next Steps

Work through the pre-requisites, then follow the steps in order.
