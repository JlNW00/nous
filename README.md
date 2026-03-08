# Crypto Investigator — Setup Guide

## What You Need (all free)

You need 5 accounts. Here's exactly where to get them:

| # | Service | URL | What it gives you |
|---|---------|-----|-------------------|
| 1 | **Neon** (Postgres database) | https://neon.tech | `DATABASE_URL` |
| 2 | **Upstash** (Redis queue) | https://upstash.com | `REDIS_URL` |
| 3 | **Neo4j Aura** (Graph database) | https://neo4j.com/cloud/aura-free/ | `NEO4J_URI`, `NEO4J_PASSWORD` |
| 4 | **Helius** (Solana data) | https://helius.dev | `HELIUS_API_KEY` |
| 5 | **Anthropic** (AI reasoning) | https://console.anthropic.com | `ANTHROPIC_API_KEY` |

Python 3.12+ is also required: https://www.python.org/downloads/

---

## Setup Steps

### Step 1 — Sign up for Neon (Postgres)

1. Go to https://neon.tech and sign up
2. Click **"New Project"** → name it `investigator` → click Create
3. You'll see a connection string that looks like:
   ```
   postgresql://neondb_owner:abc123xyz@ep-cool-name-123456.us-east-2.aws.neon.tech/neondb?sslmode=require
   ```
4. Copy that string. You'll paste it in Step 6.

### Step 2 — Sign up for Upstash (Redis)

1. Go to https://upstash.com and sign up
2. Click **"Create Database"**
3. Pick any region, name it anything, click Create
4. On the database page, find **"Redis URL"** — it looks like:
   ```
   rediss://default:Axxxxxxxxxxxxxxxx@usw2-nice-horse-12345.upstash.io:6379
   ```
5. Copy that string.

### Step 3 — Sign up for Neo4j Aura (Graph DB)

1. Go to https://neo4j.com/cloud/aura-free/ and sign up
2. Click **"New Instance"** → pick **Free** → Create
3. **IMPORTANT: It shows you a password ONCE. Save it immediately.**
4. After it's created, copy the **Connection URI** — looks like:
   ```
   neo4j+s://abcd1234.databases.neo4j.io
   ```
5. Save both the URI and the password.

### Step 4 — Sign up for Helius (Solana data)

1. Go to https://helius.dev and sign up
2. Create a project → copy your **API key**

### Step 5 — Get Anthropic API key

1. Go to https://console.anthropic.com
2. Create an API key → copy it

### Step 6 — Configure your .env file

1. In the `crypto-investigator` folder, find the file called `.env.example`
2. **Make a copy** of it and rename the copy to `.env`
   - Right-click → Copy → Paste → Rename to `.env`
3. Open `.env` in Notepad (or any text editor)
4. Replace each placeholder with your real values:

```
DATABASE_URL=postgresql+asyncpg://neondb_owner:abc123xyz@ep-cool-name-123456.us-east-2.aws.neon.tech/neondb?sslmode=require
REDIS_URL=rediss://default:Axxxxxxxxxxxxxxxx@usw2-nice-horse-12345.upstash.io:6379
NEO4J_URI=neo4j+s://abcd1234.databases.neo4j.io
NEO4J_USER=neo4j
NEO4J_PASSWORD=your-saved-password
HELIUS_API_KEY=your-helius-key
ANTHROPIC_API_KEY=sk-ant-your-key-here
```

**IMPORTANT:** For the `DATABASE_URL`, take the Neon string and change `postgresql://` to `postgresql+asyncpg://`

5. Save the file.

### Step 7 — Install and run

Open a terminal/command prompt **inside the `crypto-investigator` folder** and run:

**Windows:**
```
setup.bat
```

**Mac/Linux:**
```
pip install -r requirements.txt
python setup_check.py
```

If setup_check says "All systems go", start the API:
```
uvicorn apps.api.main:app --reload --port 8000
```

Then open http://localhost:8000/health in your browser. You should see:
```json
{"status": "ok"}
```

---

## Security Notes

- **Never commit your `.env` file to git.** It's already in `.gitignore`.
- All database connections use SSL/TLS encryption by default.
- API keys are loaded from environment variables, never hardcoded.
- The Neo4j Aura password is shown only once — store it in a password manager.
- Provider API keys (Helius, Anthropic) can be regenerated if compromised.

---

## Troubleshooting

**"Module not found" errors:**
```
pip install -r requirements.txt
```

**setup_check.py says PostgreSQL FAIL:**
- Make sure you changed `postgresql://` to `postgresql+asyncpg://` in your DATABASE_URL
- Check that `?sslmode=require` is at the end

**setup_check.py says Redis FAIL:**
- Make sure the URL starts with `rediss://` (two s's = SSL)

**setup_check.py says Neo4j FAIL:**
- Double-check the password — it's only shown once during creation
- Make sure the URI starts with `neo4j+s://`

**"uvicorn not found":**
```
pip install uvicorn[standard]
```
