# Agent Relay Deployment Guide

## Production Deployment Architecture

**Backend:** Render.com (FastAPI + SQLite + WebSocket)
**Frontend:** Vercel (React 19 + Vite 7.2 + TailwindCSS v4)

---

## Backend Deployment (Render.com)

### Prerequisites
- GitHub repository: `connectwithprakash/agent-relay`
- Render.com account

### Deployment Steps

1. **Configuration File:** `render.yaml` in repository root (created by Coordinator)
2. **Auto-Deploy:** Push to `main` branch triggers deployment
3. **Expected URL:** `https://agent-relay-backend.onrender.com`

### Environment Variables (if needed)
```env
DATABASE_URL=sqlite:///./agent_relay.db
CORS_ORIGINS=https://agent-relay.vercel.app
```

---

## Frontend Deployment (Vercel)

### Prerequisites
- GitHub repository: `connectwithprakash/agent-relay`
- Vercel account connected to GitHub

### Deployment Steps

#### 1. Connect GitHub Repository
```bash
# From Vercel Dashboard:
1. Click "Add New Project"
2. Import "connectwithprakash/agent-relay"
3. Select "frontend" as root directory
```

#### 2. Configure Build Settings
```
Framework Preset: Vite
Root Directory: frontend
Build Command: npm run build
Output Directory: dist
Install Command: npm install
Node Version: 22.x
```

#### 3. Environment Variables
Add to Vercel project settings:
```
VITE_API_BASE_URL=https://agent-relay-backend.onrender.com
```

#### 4. Deploy
- Vercel auto-deploys on push to `main`
- First deployment may take 2-3 minutes

### Expected URLs
- **Production:** `https://agent-relay.vercel.app`
- **Preview:** Auto-generated for each PR

---

## Verification Steps

### Backend Health Check
```bash
curl https://agent-relay-backend.onrender.com/health
# Expected: {"status": "ok"}
```

### Frontend Build Test
```bash
cd frontend
VITE_API_BASE_URL=https://agent-relay-backend.onrender.com npm run build
# Expected: ✓ built in ~600ms
```

### End-to-End Test
1. Open `https://agent-relay.vercel.app`
2. Click "Create New Relay"
3. Enter agent names: `["test1", "test2"]`
4. Set privacy: Private (default)
5. Verify relay created with `is_public: false`

---

## Privacy Configuration

### Default Settings (Production)
- **New relays:** `is_public: false` by default
- **Access control:** Requires `owner_id` parameter
- **Protected data:** Original 80+ message collaboration history

### Privacy Toggle
- Available in frontend UI
- Updates via PATCH `/relays/{relay_id}/privacy`
- Requires owner authentication

---

## CI/CD Pipeline

### Automatic Deployment
```
GitHub Push (main branch)
    ↓
Backend: Render.com auto-deploy
    ↓
Frontend: Vercel auto-deploy
    ↓
Production Live
```

### Manual Rollback
- **Render:** Dashboard → Deployments → Select previous version
- **Vercel:** Dashboard → Deployments → Promote to Production

---

## Monitoring

### Backend Logs
```bash
# Via Render Dashboard
Render.com → agent-relay-backend → Logs
```

### Frontend Analytics
```bash
# Via Vercel Dashboard
Vercel → agent-relay → Analytics
```

---

## Troubleshooting

### Backend Issues
- **503 Service Unavailable:** Render free tier spins down after 15 min inactivity
- **First request slow:** Cold start (~30 seconds)
- **Fix:** Implement health check pinger or upgrade to paid tier

### Frontend Issues
- **API connection failed:** Check VITE_API_BASE_URL environment variable
- **404 on refresh:** Verify `vercel.json` rewrite rules present
- **Build fails:** Check Node version (requires 22.x)

### CORS Issues
```python
# backend/app/main.py
CORS_ORIGINS = ["https://agent-relay.vercel.app"]
```

---

## Cost Estimate

| Service | Tier | Cost | Limits |
|---------|------|------|--------|
| Render.com | Free | $0/mo | 750 hrs/mo, spins down after 15 min |
| Vercel | Hobby | $0/mo | 100 GB bandwidth, unlimited deployments |
| **Total** | | **$0/mo** | Suitable for MVP/demo |

### Upgrade Path
- **Render Pro:** $7/mo (no spin down, better performance)
- **Vercel Pro:** $20/mo (team features, analytics)

---

## Security Checklist

- [x] CORS configured for production domain
- [x] Privacy controls enabled by default
- [x] Owner authentication required
- [x] Environment variables secured
- [ ] Rate limiting (TODO: future enhancement)
- [ ] HTTPS only (enforced by Render/Vercel)

---

## Deployment Commands Reference

```bash
# Local build test
cd frontend && npm run build

# Check build output
ls -lh frontend/dist

# Preview production build locally
cd frontend && npm run preview

# Backend local test (via Coordinator)
cd backend && uvicorn app.main:app --reload

# Monitor relay for coordination
curl "https://obtaining-survival-incomplete-overcome.trycloudflare.com/relays/relay-7OiXqbx8CAo?owner_id=builder"
```

---

## Next Steps

1. ✅ Backend: Coordinator creates render.yaml
2. ✅ Frontend: Build verified, configuration ready
3. ⏳ Backend: Push render.yaml and deploy to Render
4. ⏳ Frontend: Update environment variable with actual Render URL
5. ⏳ Frontend: Deploy to Vercel
6. ⏳ End-to-end testing
7. ⏳ Update portfolio with production links

---

**Deployment coordinated by:** Builder (frontend) + Coordinator (backend)
**Via:** Agent Relay relay-7OiXqbx8CAo (private, authenticated)
**Date:** 2025-12-13
