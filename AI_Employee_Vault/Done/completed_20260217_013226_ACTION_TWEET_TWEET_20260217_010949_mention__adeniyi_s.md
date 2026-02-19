---
type: tweet_action
actions: ["like", "reply"]
tweet_id: "2022607328319602800"
author_username: "_adeniyi_s"
conversation_id: ""
source_task: "TWEET_20260217_010949_mention__adeniyi_s.md"
status: pending_approval
---

# Original Tweet

**Author:** @_adeniyi_s (Adeniyi Oluwasegun)
**Tweet ID:** 2022607328319602800
**Type:** mention
**Created:** 2026-02-14T09:42:19.000Z

Exactly — that's where most automations fail.

I'm using Google Sheets as the state layer.
The workflow writes back LastEmailType + timestamp after each send, and the next run validates against it before triggering emails.

So every run is state-aware, not stateless.

# Proposed Actions

## Action 1: like
Will like this tweet.

## Action 2: reply
Solid pattern — basically a write-ahead log for your automation. Do you overwrite the last row or append per run? Curious how you handle concurrent triggers firing close together.
