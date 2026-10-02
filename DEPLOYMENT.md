# 🚀 Free Deployment Guide - FinGraphRAG

Complete guide to deploy FinGraphRAG for **FREE** using Streamlit Cloud and free-tier external services.

## 📋 Prerequisites

- GitHub account
- Google account (for Gemini API)
- Email addresses for service signups

## 🆓 Free Services Stack

| Service | Free Tier | Limit | Cost |
|---------|-----------|-------|------|
| **Streamlit Cloud** | ✅ Free | Community apps | $0 |
| **Neo4j Aura** | ✅ Free | 1 instance, 50k nodes | $0 |
| **Qdrant Cloud** | ✅ Free | 1GB storage | $0 |
| **Upstash Vector** | ✅ Free | 10k vectors | $0 |
| **Google Gemini** | Pay-as-you-go | Free quota available | ~$0-5/mo |
| **Total** | | | **$0-5/mo** |

---

## 🛠️ Step 1: Set Up External Services (15 minutes)

### 1.1 Neo4j Aura (Free Tier)

1. Go to [https://neo4j.com/cloud/aura/](https://neo4j.com/cloud/aura/)
2. Sign up for free account
3. Create a new instance:
   - **Plan**: Free (AuraDB Free)
   - **Region**: Choose closest to you
   - **Database name**: `neo4j` (default)
4. Save credentials:
   - Connection URI: `bolt+s://xxxxx.neo4j.io`
   - Username: `neo4j`
   - Password: (save this!)

### 1.2 Qdrant Cloud (Free Tier)

1. Go to [https://cloud.qdrant.io/](https://cloud.qdrant.io/)
2. Sign up for free account
3. Create a new cluster:
   - **Plan**: Free (1GB)
   - **Region**: Choose closest to you
4. Create a collection:
   - Collection name: `finrag`
   - Vector size: `3072` (for gemini-embedding-001)
   - Distance: `Cosine`
5. Save credentials:
   - URL: `https://xxxxx.qdrant.io`
   - API Key: (save this!)

### 1.3 Upstash Vector (Free Tier)

1. Go to [https://upstash.com/](https://upstash.com/)
2. Sign up for free account
3. Create a new Vector index:
   - **Plan**: Free
   - **Index name**: `finrag-cache`
   - **Dimension**: `768` (or match your embedding model)
   - **Distance**: `Cosine`
4. Save credentials:
   - REST URL: `https://xxxxx.upstash.io`
   - REST Token: (save this!)

### 1.4 Google Gemini API

1. Go to [https://ai.google.dev/](https://ai.google.dev/)
2. Sign in with Google account
3. Create a new project or use existing
4. Enable Gemini API:
   - Go to [https://console.cloud.google.com/apis/library/generativelanguage.googleapis.com](https://console.cloud.google.com/apis/library/generativelanguage.googleapis.com)
   - Click "Enable"
5. Create API key:
   - Go to [https://console.cloud.google.com/apis/credentials](https://console.cloud.google.com/apis/credentials)
   - Click "Create Credentials" → "API Key"
   - Copy the API key
6. **Note**: Gemini has generous free quota (15 requests/minute for free tier)

---

## 📦 Step 2: Prepare Your Code (5 minutes)

### 2.1 Push to GitHub

```bash
# Initialize git if not already done
git init
git add .
git commit -m "Initial commit"

# Create repository on GitHub first, then:
git remote add origin https://github.com/YOUR_USERNAME/fingraphrag.git
git branch -M main
git push -u origin main
```

### 2.2 Verify Files

Ensure these files exist in your repo:
- ✅ `requirements.txt` (already created)
- ✅ `.streamlit/config.toml` (already created)
- ✅ `src/streamlit_app.py` (your main app)

### 2.3 Data Ingestion (First Time Only)

You need to ingest your CSV data into Neo4j and Qdrant. Run this locally first:

```bash
# Install dependencies
pip install -r requirements.txt

# Copy .env.example to .env and fill in your credentials
cp .env.example .env
# Edit .env with your actual credentials

# Ingest data
python scripts/ingest_pdf.py
# or your ingestion script
```

---

## 🌐 Step 3: Deploy to Streamlit Cloud (5 minutes)

### 3.1 Create Streamlit Cloud Account

1. Go to [https://share.streamlit.io](https://share.streamlit.io)
2. Click "Sign up" (use GitHub account)
3. Authorize Streamlit to access your GitHub

### 3.2 Deploy Your App

1. Click "New app" button
2. Fill in the form:
   - **Repository**: `YOUR_USERNAME/fingraphrag`
   - **Branch**: `main`
   - **Main file**: `src/streamlit_app.py`
   - **Working directory**: `/` (root of repo)
3. Click "Deploy"

### 3.3 Configure Secrets in Streamlit Cloud

1. After deployment, go to your app settings
2. Click "Secrets" (or "⋮" → "Settings" → "Secrets")
3. Add the following secrets (copy from your .env):

```toml
# Neo4j
NEO4J_URI = "bolt+s://your-instance.neo4j.io"
NEO4J_USERNAME = "neo4j"
NEO4J_PASSWORD = "your-neo4j-password"
NEO4J_DATABASE = "neo4j"

# Qdrant
QDRANT_URL = "https://your-instance.qdrant.io"
QDRANT_API_KEY = "your-qdrant-api-key"
QDRANT_COLLECTION = "finrag"

# Gemini
GEMINI_API_KEY = "your-gemini-api-key"
GEMINI_MODEL = "gemini-1.5-flash"

# Upstash Vector
UPSTASH_VECTOR_REST_URL = "https://your-instance.upstash.io"
UPSTASH_VECTOR_REST_TOKEN = "your-upstash-token"

# Optional: LangSmith
LANGSMITH_API_KEY = "your-langsmith-api-key"
LANGSMITH_PROJECT = "finrag"
```

4. Click "Save"
5. Click "Rerun" to restart your app with new secrets

---

## ✅ Step 4: Verify Deployment

1. Wait for Streamlit Cloud to finish building (1-2 minutes)
2. Open your app URL: `https://your-app-name.streamlit.app`
3. Check the sidebar "System Status":
   - ✅ Neo4j: Should show "ok"
   - ✅ Qdrant: Should show "ok"
   - ✅ Gemini: Should show "ok"
   - ✅ Guardrails: Should show "enabled"
4. Try a test query:
   - "What is the relationship between JSW Group and Chery Automobile?"

---

## 🔧 Troubleshooting

### Issue: "Connection failed to Neo4j"
**Solution**:
- Check NEO4J_URI format (should be `bolt+s://` for Aura)
- Verify password is correct
- Ensure Neo4j instance is running (check Aura dashboard)

### Issue: "Qdrant collection not found"
**Solution**:
- Create collection `finrag` in Qdrant Cloud first
- Run ingestion script locally to populate data
- Verify QDRANT_API_KEY is correct

### Issue: "Gemini API quota exceeded"
**Solution**:
- Check Gemini usage at [https://console.cloud.google.com/apis/api/generativelanguage.googleapis.com](https://console.cloud.google.com/apis/api/generativelanguage.googleapis.com)
- Free tier: 15 requests/minute
- Wait or upgrade to paid tier (~$0.001/1k characters)

### Issue: "App won't start on Streamlit Cloud"
**Solution**:
- Check "Manage app" → "Logs" for errors
- Ensure all dependencies are in `requirements.txt`
- Verify `src/streamlit_app.py` path is correct

### Issue: "Upstash Vector not connected"
**Solution**:
- Check UPSTASH_VECTOR_REST_URL and REST_TOKEN
- App will fall back to local cache if Upstash fails
- This is not critical - app will still work

---

## 📊 Cost Monitoring

### Free Tier Limits to Watch:

**Neo4j Aura Free**:
- 50k nodes ✅ (You have 629)
- 100k relationships ✅ (You have 105)
- No expiration

**Qdrant Cloud Free**:
- 1GB storage ✅ (You have ~532 vectors)
- 1 QPS (queries per second)

**Upstash Vector Free**:
- 10k vectors ✅
- 10k requests/day

**Gemini**:
- Free: 15 requests/minute
- If exceeded: ~$0.001/1k characters
- Your app uses semantic caching to reduce API calls

**Streamlit Cloud**:
- Community apps: Free
- No explicit limits for personal projects

---

## 🔄 Updating Your App

### To update code:

```bash
# Make changes locally
git add .
git commit -m "Update feature"
git push
```

Streamlit Cloud will automatically redeploy on push to main branch.

### To update secrets:

1. Go to Streamlit Cloud app settings
2. Edit secrets
3. Click "Save" and "Rerun"

---

## 🚀 Advanced: Custom Domain (Optional)

Streamlit Cloud supports custom domains on paid plans ($20/mo). For free deployment, use the default `your-app.streamlit.app` URL.

---

## 📝 Checklist Before Deploying

- [ ] All external services set up (Neo4j, Qdrant, Upstash, Gemini)
- [ ] Data ingested into Neo4j and Qdrant
- [ ] Code pushed to GitHub
- [ ] `requirements.txt` exists
- [ ] `.streamlit/config.toml` exists
- [ ] Secrets configured in Streamlit Cloud
- [ ] App builds successfully
- [ ] System status shows all services connected
- [ ] Test query works

---

## 🎉 You're Live!

Your FinGraphRAG is now deployed for free at:
`https://your-app-name.streamlit.app`

Share the URL and let users explore Indian-Chinese company partnerships!

---

## 💡 Pro Tips

1. **Use caching**: Your app has 3-layer caching to reduce API costs
2. **Monitor usage**: Check service dashboards monthly
3. **Backup data**: Export Neo4j data periodically
4. **Log queries**: Streamlit Cloud logs can help debug issues
5. **Optimize prompts**: Better prompts = fewer retries = lower costs

---

## 🆘 Need Help?

- **Streamlit Cloud docs**: [https://docs.streamlit.io/streamlit-cloud](https://docs.streamlit.io/streamlit-cloud)
- **Neo4j Aura docs**: [https://neo4j.com/docs/aura/](https://neo4j.com/docs/aura/)
- **Qdrant Cloud docs**: [https://qdrant.tech/documentation/cloud/](https://qdrant.tech/documentation/cloud/)
- **Gemini API docs**: [https://ai.google.dev/docs](https://ai.google.dev/docs)

---

**Total deployment time**: ~30 minutes
**Total cost**: $0-5/month (depending on Gemini usage)
**Maintenance**: Minimal (auto-deploys on git push)
