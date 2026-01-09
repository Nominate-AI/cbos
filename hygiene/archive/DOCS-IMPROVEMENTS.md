# API Documentation Standards for Nominate.AI

This document defines the documentation standards for FastAPI/Swagger services across the Nominate.AI platform.

## Gold Standard: models.nominate.ai

The `models.nominate.ai` service represents the ideal NGINX configuration for API documentation exposure.

### Required NGINX Configuration Pattern

```nginx
# [Service Name] - [subdomain].nominate.ai
# [Brief description of what this service does]
# API: [port], Frontend: [port] (if applicable)

upstream [service]_api {
    server 127.0.0.1:[port];
}

server {
    listen 80;
    server_name [subdomain].nominate.ai;

    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl;
    server_name [subdomain].nominate.ai;

    # SSL Configuration
    ssl_certificate /etc/letsencrypt/live/[cert-name]/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/[cert-name]/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

    # PIN Gate Auth (if required)
    include snippets/pin-gate-auth.conf;

    # Logging
    access_log /var/log/nginx/[subdomain].nominate.ai.access.log;
    error_log /var/log/nginx/[subdomain].nominate.ai.error.log;

    # API endpoints
    location /api/ {
        proxy_pass http://[service]_api;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }

    # API docs (Swagger UI)
    location /docs {
        proxy_pass http://[service]_api;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # ReDoc alternative docs
    location /redoc {
        proxy_pass http://[service]_api;
        proxy_set_header Host $host;
    }

    # OpenAPI spec
    location /openapi.json {
        proxy_pass http://[service]_api;
        proxy_set_header Host $host;
    }

    # Health check endpoint
    location = /health {
        proxy_pass http://[service]_api/api/v1/health;
        proxy_set_header Host $host;
    }

    # Root redirect to docs (optional)
    location = / {
        return 302 /docs;
    }
}
```

### Required Header Comments

Every NGINX config file MUST include:

1. **Line 1**: Service name and domain
2. **Line 2**: Brief service description
3. **Line 3**: Port allocation (API and Frontend if applicable)

Example:
```nginx
# Voter Segment Analysis API - models.nominate.ai
# Provides ML model analysis endpoints for voter segmentation
# API (32411), Frontend reserved (32410)
```

---

## Site Inventory and Status

### Compliant Sites (Full Documentation Support)

| Site | /docs | /redoc | /openapi.json | Header Comments | Health Check |
|------|-------|--------|---------------|-----------------|--------------|
| models.nominate.ai | ✅ | ✅ | ✅ | ✅ | ✅ |
| workflow.nominate.ai | ✅ | ✅ | ✅ | ✅ | ✅ |
| districts.nominate.ai | ✅ | ✅ | ✅ | ✅ | ❌ |
| tenant.nominate.ai | ✅ | ✅ | ✅ | ✅ | ❌ |

### Partially Compliant Sites (Need NGINX Updates)

These sites serve /docs via catch-all routes but lack explicit NGINX configuration:

| Site | /docs Status | Missing NGINX Routes | Header Issues |
|------|--------------|---------------------|---------------|
| ai.nominate.ai | 200 | /docs, /redoc, /openapi.json | Missing service description |
| auth.nominate.ai | 200 | /docs, /redoc, /openapi.json | Minimal header |
| cdn.nominate.ai | 200 | /docs, /redoc, /openapi.json | Good header |
| files.nominate.ai | 200 | /docs, /redoc, /openapi.json | Good header |
| intel.nominate.ai | 200 | /docs, /redoc, /openapi.json | Minimal header |
| ky04api.nominate.ai | 200 | /docs, /redoc, /openapi.json | Good header |
| mi20api.nominate.ai | 200 | /docs, /redoc, /openapi.json | Good header |
| ruralamfm.nominate.ai | 200 | /docs, /redoc, /openapi.json | No header |
| surveys.nominate.ai | 200 | /docs, /redoc, /openapi.json | Good header |

### Non-Compliant Sites (Need Immediate Attention)

| Site | Issue | Priority |
|------|-------|----------|
| project.nominate.ai | /docs returns 404, no NGINX docs routes | HIGH |
| testsiteapi.nominate.ai | Connection failed (service down or misconfigured) | HIGH |
| clarion.nominate.ai | /docs route exists but returns 404 | MEDIUM |
| oym.nominate.ai | /docs route exists but returns 404 | MEDIUM |
| os.nominate.ai | /docs returns 302 redirect | LOW |

### Non-API Sites (No /docs Required)

| Site | Purpose |
|------|---------|
| catchall.nominate.ai | Wildcard catchall for teaser page |
| docs.nominate.ai | MkDocs documentation site |
| kentucky.nominate.ai | Legacy frontend |
| ky04.nominate.ai | Tenant frontend |
| lochness.nominate.ai | Observable framework |
| mi20.nominate.ai | Tenant frontend |
| testsite.nominate.ai | Tenant frontend |
| www.nominate.ai | Public website |

---

## Improvement Tasks by Site

### Priority 1: Fix Non-Working /docs

#### project.nominate.ai

Add explicit docs routes to `/etc/nginx/sites-nominate/project.nominate.ai.conf`:

```nginx
# Add after the /api/health location block:

# API docs
location /docs {
    proxy_pass http://127.0.0.1:32403;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

location /redoc {
    proxy_pass http://127.0.0.1:32403;
    proxy_set_header Host $host;
}

location /openapi.json {
    proxy_pass http://127.0.0.1:32403;
    proxy_set_header Host $host;
}
```

#### testsiteapi.nominate.ai

1. Verify service is running: `sudo systemctl status testsite-api`
2. Check port binding: `ss -tlnp | grep 32301`
3. Add explicit /docs routes if missing

### Priority 2: Add Explicit Documentation Routes

For each site listed as "Partially Compliant", add these location blocks:

```nginx
# API docs (Swagger UI)
location /docs {
    proxy_pass http://[upstream];
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

# ReDoc alternative
location /redoc {
    proxy_pass http://[upstream];
    proxy_set_header Host $host;
}

# OpenAPI specification
location /openapi.json {
    proxy_pass http://[upstream];
    proxy_set_header Host $host;
}
```

### Priority 3: Standardize Header Comments

Update configs missing proper headers. Example fix for `ruralamfm.nominate.ai.conf`:

```nginx
# CampaignBrain Tenant - ruralamfm.nominate.ai
# Rural AM/FM radio station campaign management
# Frontend: 32330, Backend: 32331

upstream ruralamfm_frontend {
    server 127.0.0.1:32330;
}
```

---

## FastAPI Application Requirements

### Minimum Documentation Configuration

Every FastAPI application MUST include:

```python
from fastapi import FastAPI

app = FastAPI(
    title="Service Name API",
    description="Brief description of what this API does",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)
```

### Health Check Endpoint

Every API MUST expose a health check:

```python
@app.get("/api/v1/health")
async def health_check():
    return {"status": "healthy", "service": "service-name"}
```

---

## Verification Commands

### Check if /docs is accessible

```bash
curl -s -o /dev/null -w "%{http_code}" https://[site].nominate.ai/docs
```

### Verify all documentation endpoints

```bash
for endpoint in docs redoc openapi.json; do
    echo -n "$endpoint: "
    curl -s -o /dev/null -w "%{http_code}" "https://[site].nominate.ai/$endpoint"
    echo
done
```

### Test NGINX configuration

```bash
sudo nginx -t
sudo systemctl reload nginx
```

---

## Rollout Checklist

- [ ] Fix project.nominate.ai /docs routing
- [ ] Investigate testsiteapi.nominate.ai connectivity
- [ ] Add explicit /docs routes to ai.nominate.ai
- [ ] Add explicit /docs routes to auth.nominate.ai
- [ ] Add explicit /docs routes to cdn.nominate.ai
- [ ] Add explicit /docs routes to files.nominate.ai
- [ ] Add explicit /docs routes to intel.nominate.ai
- [ ] Add explicit /docs routes to ky04api.nominate.ai
- [ ] Add explicit /docs routes to mi20api.nominate.ai
- [ ] Add explicit /docs routes to ruralamfm.nominate.ai
- [ ] Add explicit /docs routes to surveys.nominate.ai
- [ ] Standardize header comments on all configs
- [ ] Verify clarion.nominate.ai FastAPI app serves /docs
- [ ] Verify oym.nominate.ai FastAPI app serves /docs
