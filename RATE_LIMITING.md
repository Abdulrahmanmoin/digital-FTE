# X/Twitter Daily Rate Limiting

**Date:** 2026-02-09
**Feature:** Daily post quota to prevent spam and bot-like behavior

---

## Overview

The X/Twitter watcher now implements a **daily rate limit of 10 posts per 24 hours**. This ensures your AI employee behaves professionally and avoids:

- 🚫 Overwhelming your followers with too many interactions
- 🚫 Looking like a bot (which can trigger X/Twitter bans)
- 🚫 Processing too many mentions/keywords in a short time
- ✅ Professional, measured engagement that appears human

---

## How It Works

### 24-Hour Rolling Window
```
Window Start: 2026-02-09 08:00:00
Window End:   2026-02-09 08:00:00 (next day)

Posts processed: 0/10 ✅ Fetching enabled
Posts processed: 5/10 ✅ Fetching enabled
Posts processed: 10/10 ⛔ Fetching disabled until window resets
```

### Fetch Behavior
1. **Before limit (0-9 posts):** Watcher fetches mentions + keyword searches every 3 minutes as normal
2. **At limit (10 posts):** Watcher stops fetching until the 24-hour window resets
3. **After 24 hours:** Window automatically resets, counter goes to 0, fetching resumes

### What Gets Counted
Each **file created** in `Needs_Action/` counts toward the limit:
- Mentions from X/Twitter
- Keyword search matches
- Both count equally toward the 10-post limit

### What Doesn't Get Counted
- Duplicate tweets (already processed)
- Your own tweets (automatically filtered)
- Tweets fetched but not written to disk (e.g., browser errors)

---

## Configuration

### Current Settings (watchers/x_watcher.py)
```python
DAILY_POST_LIMIT = 10        # Maximum posts per window
QUOTA_WINDOW_HOURS = 24      # Hours in quota window
```

### To Change the Limit
Edit `watchers/x_watcher.py`:

```python
# Increase to 20 posts per day
DAILY_POST_LIMIT = 20

# Or decrease to 5 posts per day
DAILY_POST_LIMIT = 5
```

Then restart PM2:
```bash
pm2 restart ai-employee
```

### To Change the Window Duration
```python
# 12-hour window instead of 24
QUOTA_WINDOW_HOURS = 12

# 48-hour window (2 days)
QUOTA_WINDOW_HOURS = 48
```

---

## Quota Tracking File

**Location:** `credentials/.x_daily_quota.json`

**Structure:**
```json
{
  "window_start_time": "2026-02-09T08:00:00.123456",
  "posts_processed_today": 7
}
```

**Protected:** Already in `.gitignore` (won't be committed to git)

**Persistent:** Survives system restarts, PM2 restarts, etc.

---

## Monitoring Your Quota

### In Logs (logs/x_watcher.log)
```
2026-02-09 08:00:00 [INFO] x_watcher - Loaded daily quota: 7/10 posts processed (window started: 2026-02-09T08:00:00)
2026-02-09 08:05:00 [INFO] x_watcher - Total new tweets to process: 2 (quota: 7/10)
2026-02-09 08:05:05 [INFO] x_watcher - Daily quota updated: 8/10 posts processed
2026-02-09 08:05:10 [INFO] x_watcher - Daily quota updated: 9/10 posts processed
```

### When Limit Reached
```
2026-02-09 08:10:00 [INFO] x_watcher - Daily post limit reached (10/10). Next reset in 23h 50m.
2026-02-09 08:10:00 [DEBUG] x_watcher - Skipping fetch — daily post limit reached.
```

### When Window Resets
```
2026-02-10 08:00:00 [INFO] x_watcher - 24-hour window elapsed — resetting quota.
2026-02-10 08:00:00 [INFO] x_watcher - Reset quota window — new 24h period started at 2026-02-10T08:00:00
```

### Manual Check
```bash
# View quota file
cat credentials/.x_daily_quota.json

# Or with Python
python -c "import json; print(json.load(open('credentials/.x_daily_quota.json')))"
```

---

## Manual Quota Management

### Reset Quota Manually (Fresh 24h Window)
```bash
# Delete the quota file
rm credentials/.x_daily_quota.json

# Restart watcher (PM2 will auto-restart)
pm2 restart ai-employee
```

### Increase/Decrease Counter Manually
```bash
# Edit the quota file
nano credentials/.x_daily_quota.json

# Change "posts_processed_today" to desired value
{
  "window_start_time": "2026-02-09T08:00:00.123456",
  "posts_processed_today": 3  # Changed from 7
}

# Restart to apply
pm2 restart ai-employee
```

---

## Impact on Workflow

### Needs_Action Folder
- Maximum 10 new files per 24 hours from X/Twitter watcher
- Gmail watcher operates independently (no rate limit)
- Files still flow through normal approval process

### Human Approval
- You still need to approve actions by moving files to `Approved/`
- Rate limit only affects **incoming** tweets, not **outgoing** actions
- If you approve 20 actions, the system will execute all 20 (no limit on approved actions)

### Multi-Source Processing
```
Daily breakdown example:
- Mentions: 3 new tweets → 3 files created
- Keyword "AI": 5 matches → 5 files created
- Keyword "hackathon": 4 matches → 2 files created (limit reached at 10)
- Total: 10 files created, 2 skipped
```

---

## Why This Matters

### Professional Behavior
- **Measured engagement** looks more human, less spammy
- **Avoids X/Twitter rate limits** and potential account suspension
- **Manageable approval queue** — you're not overwhelmed with 100 tweets to review

### Safety
- Prevents runaway behavior if keywords match too many tweets
- Limits exposure if account is targeted by spam/trolls
- Gives you control over engagement volume

### Compliance
- Respects X/Twitter's automation guidelines
- Follows best practices for bot accounts
- Reduces risk of being flagged as spam

---

## Troubleshooting

### Problem: No tweets being fetched
**Check:**
1. Are you at the daily limit?
   ```bash
   cat credentials/.x_daily_quota.json
   # If "posts_processed_today": 10, you're at the limit
   ```
2. When does the window reset?
   - Check `window_start_time` + 24 hours
3. Is the browser session still valid?
   ```bash
   tail -f logs/x_watcher.log
   # Look for "Session expired" warnings
   ```

### Problem: Want to process more than 10 posts
**Solution:** Increase `DAILY_POST_LIMIT` in `watchers/x_watcher.py`

### Problem: Window reset timing doesn't match my schedule
**Solution:** Delete quota file at your preferred time to force reset:
```bash
# Delete at 8 AM daily (cron job)
0 8 * * * rm /path/to/credentials/.x_daily_quota.json
```

---

## Recommended Settings

### Conservative (Professional Account)
```python
DAILY_POST_LIMIT = 5
QUOTA_WINDOW_HOURS = 24
```

### Moderate (Default)
```python
DAILY_POST_LIMIT = 10
QUOTA_WINDOW_HOURS = 24
```

### Active (Personal/Test Account)
```python
DAILY_POST_LIMIT = 20
QUOTA_WINDOW_HOURS = 24
```

### High-Volume (Testing Only)
```python
DAILY_POST_LIMIT = 50
QUOTA_WINDOW_HOURS = 24
```

**⚠️ Warning:** Setting limits >20 may trigger X/Twitter anti-spam measures.

---

## Testing the Rate Limit

### Verify It's Working
1. Check current quota:
   ```bash
   cat credentials/.x_daily_quota.json
   ```

2. Watch the logs during a poll cycle:
   ```bash
   tail -f logs/x_watcher.log
   ```

3. Manually set quota to 9 and watch it hit the limit:
   ```bash
   # Edit quota file
   echo '{"window_start_time": "'$(date -Iseconds)'", "posts_processed_today": 9}' > credentials/.x_daily_quota.json

   # Restart and watch logs
   pm2 restart ai-employee
   tail -f logs/x_watcher.log
   ```

---

## Summary

✅ **Rate limit implemented:** 10 posts per 24 hours
✅ **Automatic window reset:** Every 24 hours from window start
✅ **Persistent tracking:** Survives restarts
✅ **Protected in git:** Quota file in `.gitignore`
✅ **Configurable:** Easy to adjust limits in code
✅ **Logged:** Full visibility in `logs/x_watcher.log`

Your AI employee now operates within professional rate limits! 🎯
