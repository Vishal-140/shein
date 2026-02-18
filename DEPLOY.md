# User Guide: Deploying to Render (Free Tier)

This guide will help you deploy your Shein Stock Monitor to Render for free 24/7 operation.

## Prerequisite: GitHub
1. Create a **new private repository** on GitHub.
2. Upload all files in this folder (`server.py`, `monitor.py`, `Dockerfile`, `requirements.txt`) to that repository.
   - *Note: Do NOT upload `monitor.log` or `stock_state.json`.*

## Step 1: Create Web Service on Render
1. Go to [dashboard.render.com](https://dashboard.render.com/) and log in.
2. Click **New +** -> **Web Service**.
3. Connect your GitHub repository.
4. Configure the service:
   - **Name**: `shein-monitor` (or similar)
   - **Region**: Any (e.g., Singapore or Frankfurt)
   - **Instance Type**: **Free**
   - **Runtime**: **Docker** (Render should auto-detect the Dockerfile)
5. **Environment Variables** (REQUIRED):
   - You MUST add your Telegram keys here because they are not in the code anymore:
     - `TELEGRAM_BOT_TOKEN`: `your_token_from_env_file`
     - `TELEGRAM_CHAT_ID`: `your_chat_id_from_env_file`

6. Click **Create Web Service**.

## Step 2: Keep It Alive (Critical for Free Tier)
Render's free tier "spins down" (sleeps) after 15 minutes of inactivity. To keep it running 24/7:

1. Sign up for a free account at [UptimeRobot](https://uptimerobot.com/).
2. Click **Add New Monitor**.
   - **Monitor Type**: HTTP(s)
   - **Friendly Name**: Shein Monitor
   - **URL**: Your Render App URL (e.g., `https://shein-monitor.onrender.com/health`)
   - **Monitoring Interval**: 5 minutes
3. Click **Create Monitor**.

## Important Notes
- **Logs**: View logs in the Render Dashboard.
- **State Reset**: On the free tier, the file system is valid only while running. If the app restarts (which happens occasionally), it will **forget** previous stock states and might re-send alerts for items currently in stock. This is normal for ephemeral containers.
