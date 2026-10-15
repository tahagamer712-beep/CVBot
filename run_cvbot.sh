#!/data/data/com.termux/files/usr/bin/bash
# run_cvbot.sh — supervisor for the CV bot.
# Restarts bot.py on crash with 5s backoff + circuit breaker
# (stops after 5 crashes within 60s to avoid a hot crash loop).
cd "$HOME/bots/cvbot" || { echo "cannot cd to ~/bots/cvbot"; exit 1; }
CRASH_TIMES=""
while true; do
  NOW=$(date +%s)
  NEW=""
  for t in $CRASH_TIMES; do
    if [ $((NOW - t)) -lt 60 ]; then NEW="$NEW $t"; fi
  done
  CRASH_TIMES="$NEW"
  COUNT=$(echo "$CRASH_TIMES" | wc -w)
  if [ "$COUNT" -ge 5 ]; then
    echo "[$(date '+%F %T')] CIRCUIT BREAKER: 5 crashes within 60s — supervisor stopping. Manual fix needed."
    break
  fi
  echo "[$(date '+%F %T')] supervisor: starting bot.py (recent crashes in 60s: $COUNT)"
  python bot.py
  CODE=$?
  CRASH_TIMES="$CRASH_TIMES $(date +%s)"
  echo "[$(date '+%F %T')] supervisor: bot.py exited code=$CODE — restarting in 5s"
  sleep 5
done
