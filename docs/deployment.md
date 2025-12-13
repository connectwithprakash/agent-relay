# Agent Relay v2 - Production Deployment Guide

This guide covers deploying Agent Relay v2 to production with PostgreSQL, environment configuration, and CI/CD setup.

## Deployment Overview

```mermaid
graph LR
    A[GitHub Repository] -->|Push| B[CI/CD Pipeline]
    B -->|Deploy Backend| C[Fly.io / Railway]
    B -->|Deploy Frontend| D[Vercel / Netlify]
    C -->|Connect| E[(PostgreSQL)]
    D -->|API Calls| C
    F[Cloudflare DNS] -->|Route| D
    G[Users] -->|HTTPS| F
```

## Prerequisites

- GitHub account with repository access
- Fly.io or Railway account (for backend)
- Vercel or Netlify account (for frontend)
- PostgreSQL database (managed or self-hosted)
- Custom domain (optional but recommended)

## Backend Deployment

### Option 1: Deploy to Fly.io

Fly.io provides excellent support for Python applications with built-in PostgreSQL.

#### 1. Install Fly CLI

```bash
# macOS
brew install flyctl

# Linux
curl -L https://fly.io/install.sh | sh

# Windows
powershell -Command "iwr https://fly.io/install.ps1 -useb | iex"
```

#### 2. Login to Fly.io

```bash
flyctl auth login
```

#### 3. Create Fly.io Application

```bash
cd backend

# Initialize Fly.io app
flyctl launch

# Select options:
# - App name: agent-relay-api (or your choice)
# - Region: Choose closest to your users
# - PostgreSQL: Yes
# - Redis: No (not needed)
```

#### 4. Create fly.toml Configuration

```toml
# backend/fly.toml
app = "agent-relay-api"
primary_region = "sjc"

[build]
  builder = "paketobuildpacks/builder:base"
  buildpacks = ["gcr.io/paketo-buildpacks/python"]

[env]
  PORT = "8000"
  DATABASE_URL = "postgresql://user:password@host:5432/dbname"

[http_service]
  internal_port = 8000
  force_https = true
  auto_stop_machines = true
  auto_start_machines = true
  min_machines_running = 1
  processes = ["app"]

[[services]]
  protocol = "tcp"
  internal_port = 8000
  processes = ["app"]

  [[services.ports]]
    port = 80
    handlers = ["http"]
    force_https = true

  [[services.ports]]
    port = 443
    handlers = ["tls", "http"]

[services.concurrency]
  type = "connections"
  hard_limit = 25
  soft_limit = 20
```

#### 5. Create Procfile

```bash
# backend/Procfile
web: uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

#### 6. Update Dependencies for PostgreSQL

```bash
# Add to backend/requirements.txt
psycopg2-binary>=2.9.9
```

#### 7. Update Database Configuration

```python
# backend/app/main.py
import os
from sqlalchemy import create_engine

# Use DATABASE_URL from environment (Fly.io provides this)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./agent_relay.db")

# Fly.io uses postgres:// but SQLAlchemy needs postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
```

#### 8. Set Environment Variables

```bash
# Set CORS origins for production
flyctl secrets set CORS_ORIGINS="https://agent-relay.vercel.app,https://yourdomain.com"

# Set other secrets as needed
flyctl secrets set SECRET_KEY="your-secret-key-here"
```

#### 9. Deploy to Fly.io

```bash
flyctl deploy

# Monitor deployment
flyctl logs

# Check status
flyctl status

# Your API will be available at:
# https://agent-relay-api.fly.dev
```

#### 10. Run Database Migrations

```bash
# SSH into Fly.io machine
flyctl ssh console

# Inside the machine, run migrations
python -c "from app.models import Base; from app.main import engine; Base.metadata.create_all(bind=engine)"
```

### Option 2: Deploy to Railway

Railway offers a simpler deployment experience with built-in PostgreSQL.

#### 1. Install Railway CLI

```bash
npm i -g @railway/cli
```

#### 2. Login and Initialize

```bash
railway login
cd backend
railway init
```

#### 3. Add PostgreSQL Database

```bash
# Add PostgreSQL plugin from Railway dashboard
# Or via CLI:
railway add postgresql
```

#### 4. Configure Environment Variables

Create `railway.json`:

```json
{
  "$schema": "https://railway.app/railway.schema.json",
  "build": {
    "builder": "NIXPACKS"
  },
  "deploy": {
    "startCommand": "uvicorn app.main:app --host 0.0.0.0 --port $PORT",
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 10
  }
}
```

#### 5. Set Environment Variables in Railway Dashboard

```bash
# Add in Railway dashboard or via CLI:
railway variables set CORS_ORIGINS="https://agent-relay.vercel.app"
railway variables set DATABASE_URL=${{Postgres.DATABASE_URL}}
```

#### 6. Deploy

```bash
railway up

# Your API will be available at:
# https://agent-relay-production.up.railway.app
```

## Frontend Deployment

### Option 1: Deploy to Vercel

Vercel is optimized for React and Vite applications.

#### 1. Install Vercel CLI

```bash
npm i -g vercel
```

#### 2. Login and Deploy

```bash
cd frontend

# Login to Vercel
vercel login

# Deploy (first time)
vercel

# Follow prompts:
# - Project name: agent-relay
# - Framework preset: Vite
# - Build command: npm run build
# - Output directory: dist
```

#### 3. Configure Environment Variables

Add in Vercel dashboard or via CLI:

```bash
vercel env add VITE_API_BASE_URL production
# Enter: https://agent-relay-api.fly.dev

# For WebSocket connections, use wss:// protocol:
vercel env add VITE_WS_BASE_URL production
# Enter: wss://agent-relay-api.fly.dev
```

#### 4. Create vercel.json Configuration

```json
{
  "buildCommand": "npm run build",
  "outputDirectory": "dist",
  "framework": "vite",
  "rewrites": [
    {
      "source": "/(.*)",
      "destination": "/index.html"
    }
  ],
  "headers": [
    {
      "source": "/assets/(.*)",
      "headers": [
        {
          "key": "Cache-Control",
          "value": "public, max-age=31536000, immutable"
        }
      ]
    }
  ]
}
```

#### 5. Deploy to Production

```bash
# Deploy to production
vercel --prod

# Your frontend will be available at:
# https://agent-relay.vercel.app
```

### Option 2: Deploy to Netlify

#### 1. Install Netlify CLI

```bash
npm i -g netlify-cli
```

#### 2. Login and Initialize

```bash
cd frontend
netlify login
netlify init
```

#### 3. Configure netlify.toml

```toml
[build]
  command = "npm run build"
  publish = "dist"

[[redirects]]
  from = "/*"
  to = "/index.html"
  status = 200

[build.environment]
  NODE_VERSION = "18"

[[headers]]
  for = "/assets/*"
  [headers.values]
    Cache-Control = "public, max-age=31536000, immutable"
```

#### 4. Set Environment Variables

```bash
# Add in Netlify dashboard or via CLI:
netlify env:set VITE_API_BASE_URL "https://agent-relay-api.fly.dev"
netlify env:set VITE_WS_BASE_URL "wss://agent-relay-api.fly.dev"
```

#### 5. Deploy

```bash
netlify deploy --prod

# Your frontend will be available at:
# https://agent-relay.netlify.app
```

## Database Migration from SQLite to PostgreSQL

### 1. Export SQLite Data

```bash
cd backend

# Export to SQL dump
sqlite3 agent_relay.db .dump > data_dump.sql

# Or use Python script to export JSON:
python3 << EOF
import sqlite3
import json
from app.models import Relay, Message, Webhook

conn = sqlite3.connect('agent_relay.db')
cursor = conn.cursor()

# Export relays
cursor.execute("SELECT * FROM relays")
relays = cursor.fetchall()
with open('relays.json', 'w') as f:
    json.dump(relays, f)

# Export messages
cursor.execute("SELECT * FROM messages")
messages = cursor.fetchall()
with open('messages.json', 'w') as f:
    json.dump(messages, f)

conn.close()
EOF
```

### 2. Import to PostgreSQL

```python
# migration_script.py
import os
import json
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models import Base, Relay, Message, Webhook

# Production PostgreSQL URL
DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)

# Create tables
Base.metadata.create_all(bind=engine)

# Import data
Session = sessionmaker(bind=engine)
session = Session()

# Import relays
with open('relays.json', 'r') as f:
    relays = json.load(f)
    for relay_data in relays:
        relay = Relay(**relay_data)
        session.add(relay)

# Import messages
with open('messages.json', 'r') as f:
    messages = json.load(f)
    for message_data in messages:
        message = Message(**message_data)
        session.add(message)

session.commit()
session.close()
```

## CORS Configuration for Production

Update backend CORS settings for production domains:

```python
# backend/app/main.py
import os

CORS_ORIGINS = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:5173,http://localhost:3000"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Set production CORS origins:

```bash
# Fly.io
flyctl secrets set CORS_ORIGINS="https://agent-relay.vercel.app,https://yourdomain.com"

# Railway
railway variables set CORS_ORIGINS="https://agent-relay.vercel.app,https://yourdomain.com"
```

## WebSocket Configuration

### Backend WebSocket Endpoint

Ensure WebSocket endpoint supports WSS (WebSocket Secure):

```python
# backend/app/main.py
@app.websocket("/relays/{relay_id}/ws")
async def websocket_endpoint(websocket: WebSocket, relay_id: str, agent: str):
    # WebSocket will automatically upgrade to WSS in production
    # when accessed via HTTPS
    await manager.connect(relay_id, agent, websocket)
    # ... rest of implementation
```

### Frontend WebSocket Configuration

Update API client to use WSS in production:

```javascript
// frontend/src/utils/api.js
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

export const connectWebSocket = (relayId, agent, onMessage) => {
  // Convert HTTPS to WSS, HTTP to WS
  const wsUrl = API_BASE_URL
    .replace('https://', 'wss://')
    .replace('http://', 'ws://');

  const ws = new WebSocket(`${wsUrl}/relays/${relayId}/ws?agent=${agent}`);

  ws.onopen = () => console.log(`WebSocket connected: ${agent}`);
  ws.onmessage = (event) => {
    const message = JSON.parse(event.data);
    onMessage(message);
  };

  return ws;
};
```

## CI/CD with GitHub Actions

Create automated deployment pipeline:

```yaml
# .github/workflows/deploy.yml
name: Deploy to Production

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test-backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install dependencies
        working-directory: ./backend
        run: |
          pip install -r requirements.txt
          pip install pytest pytest-cov

      - name: Run tests
        working-directory: ./backend
        run: pytest --cov=app

  test-frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Set up Node.js
        uses: actions/setup-node@v3
        with:
          node-version: '18'

      - name: Install dependencies
        working-directory: ./frontend
        run: npm ci

      - name: Build frontend
        working-directory: ./frontend
        run: npm run build

  deploy-backend:
    needs: [test-backend, test-frontend]
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v3

      - name: Deploy to Fly.io
        uses: superfly/flyctl-actions/setup-flyctl@master

      - run: flyctl deploy --remote-only
        working-directory: ./backend
        env:
          FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}

  deploy-frontend:
    needs: [test-backend, test-frontend]
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v3

      - name: Deploy to Vercel
        uses: amondnet/vercel-action@v20
        with:
          vercel-token: ${{ secrets.VERCEL_TOKEN }}
          vercel-org-id: ${{ secrets.VERCEL_ORG_ID }}
          vercel-project-id: ${{ secrets.VERCEL_PROJECT_ID }}
          working-directory: ./frontend
```

## Environment Variables Summary

### Backend Environment Variables

```bash
# Required
DATABASE_URL=postgresql://user:password@host:5432/dbname
CORS_ORIGINS=https://agent-relay.vercel.app,https://yourdomain.com

# Optional
PORT=8000
LOG_LEVEL=INFO
SECRET_KEY=your-secret-key-here
```

### Frontend Environment Variables

```bash
# Required
VITE_API_BASE_URL=https://agent-relay-api.fly.dev

# Optional
VITE_WS_BASE_URL=wss://agent-relay-api.fly.dev
```

## Monitoring and Logging

### Backend Monitoring

#### Fly.io Monitoring

```bash
# View logs
flyctl logs

# Monitor metrics
flyctl dashboard

# Scale machines
flyctl scale count 2
flyctl scale vm shared-cpu-1x
```

#### Railway Monitoring

```bash
# View logs
railway logs

# Open dashboard
railway open
```

### Frontend Monitoring

#### Vercel Analytics

Add Vercel Analytics to your frontend:

```bash
npm install @vercel/analytics
```

```javascript
// frontend/src/main.jsx
import { Analytics } from '@vercel/analytics/react';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
    <Analytics />
  </React.StrictMode>
);
```

## Custom Domain Configuration

### Backend Domain

#### Fly.io Custom Domain

```bash
# Add custom domain
flyctl certs create api.yourdomain.com

# Get DNS records to add
flyctl certs show api.yourdomain.com

# Add these DNS records to your domain:
# CNAME api.yourdomain.com -> agent-relay-api.fly.dev
```

#### Railway Custom Domain

```bash
# Add in Railway dashboard:
# Settings > Domains > Add Custom Domain
# Enter: api.yourdomain.com
# Add CNAME record pointing to provided Railway domain
```

### Frontend Domain

#### Vercel Custom Domain

```bash
# Add in Vercel dashboard:
# Project Settings > Domains > Add Domain
# Enter: yourdomain.com
# Add DNS records as instructed:
# A record: @ -> 76.76.21.21
# CNAME record: www -> cname.vercel-dns.com
```

## Health Checks and Uptime Monitoring

Add health check endpoint to backend:

```python
# backend/app/main.py
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "database": "connected"  # Add actual DB check
    }
```

Use services like:
- **UptimeRobot** - Free monitoring with 5-minute intervals
- **Pingdom** - Comprehensive monitoring and alerting
- **Statuspage** - Public status page for your users

## Security Best Practices

### Backend Security

1. **Environment Variables**: Never commit secrets to Git
2. **CORS**: Restrict to specific production domains
3. **Rate Limiting**: Add rate limiting middleware
4. **Input Validation**: Use Pydantic schemas for all inputs
5. **HTTPS Only**: Force HTTPS in production

### Frontend Security

1. **Environment Variables**: Prefix with VITE_ for exposure
2. **Content Security Policy**: Add CSP headers
3. **Dependency Updates**: Regularly update npm packages
4. **Build Optimization**: Enable code splitting and minification

## Rollback Strategy

### Backend Rollback

```bash
# Fly.io - rollback to previous release
flyctl releases list
flyctl releases rollback <version>

# Railway - rollback from dashboard
# Deployments > Previous Deployment > Redeploy
```

### Frontend Rollback

```bash
# Vercel - rollback to previous deployment
vercel rollback <deployment-url>

# Netlify - rollback from dashboard
# Deploys > Previous Deploy > Publish deploy
```

## Performance Optimization

### Backend Optimization

1. **Database Connection Pooling**: Configure SQLAlchemy pool size
2. **Caching**: Add Redis for session/response caching
3. **Async Operations**: Ensure all I/O is async
4. **Compression**: Enable gzip compression

### Frontend Optimization

1. **Code Splitting**: Use React.lazy() for route-based splitting
2. **Image Optimization**: Use WebP format and lazy loading
3. **Bundle Analysis**: Run `npm run build` and check bundle size
4. **CDN**: Leverage Vercel/Netlify CDN for static assets

## Troubleshooting

### Common Issues

#### WebSocket Connection Failed

- Ensure WSS protocol is used in production
- Check CORS configuration allows WebSocket origin
- Verify backend WebSocket endpoint is accessible

#### Database Connection Error

- Verify DATABASE_URL format (postgresql://, not postgres://)
- Check database credentials and network access
- Ensure database exists and migrations are run

#### CORS Error in Production

- Add frontend domain to CORS_ORIGINS
- Verify CORS middleware is properly configured
- Check browser console for specific CORS error

#### Build Fails on Deployment

- Check logs for specific error messages
- Verify all dependencies are in requirements.txt/package.json
- Test build locally before deploying

## Cost Estimation

### Fly.io
- Free tier: 3 shared-cpu-1x VMs + 3GB persistent storage
- Estimated cost: $0-10/month for small projects

### Railway
- Free tier: $5 credit/month
- Estimated cost: $5-20/month depending on usage

### Vercel
- Free tier: Unlimited personal projects
- Estimated cost: $0 for personal use, $20/month for pro

### PostgreSQL
- Fly.io: Included in free tier
- Railway: Included in free tier
- Managed (Supabase/Neon): Free tier available

## Next Steps

After deployment:

1. Test all endpoints in production
2. Verify WebSocket connections work over WSS
3. Monitor logs for errors
4. Set up uptime monitoring
5. Configure custom domains
6. Add SSL certificates (automatic on Fly.io/Vercel)
7. Set up CI/CD pipeline
8. Create backup strategy for database

## Support

For deployment issues:
- Fly.io: https://fly.io/docs
- Railway: https://docs.railway.app
- Vercel: https://vercel.com/docs
- Netlify: https://docs.netlify.com

For application issues:
- Check GitHub issues: https://github.com/connectwithprakash/agent-relay/issues
- Review application logs in deployment platform
- Test locally to isolate production-specific issues
