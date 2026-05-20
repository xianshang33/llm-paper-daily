# Subscribe Agent Setup

This document is for a local coding agent such as OpenClaw, Codex, or Claude Code. Your job is to configure a user's local subscription to `llm-paper-daily` with the `paper-subscribe` skill.

The human should not need to understand cron, Node scripts, state files, or feed formats. Ask only for preferences that are missing.

## Goal

Set up a local scheduled subscription that reads:

```text
https://raw.githubusercontent.com/xianshang33/llm-paper-daily/main/feed-papers.json
```

The subscription must only consume the public feed. Do not run the production paper discovery, summarization, README generation, or GitHub Actions workflow.

## Inputs To Confirm

If the user did not provide these preferences, choose the defaults below and mention them in your final response:

- Language: `zh`
- Timezone: user's local timezone, or `Asia/Shanghai` if unknown
- Schedule: `15 9 * * *`
- Topics: `agent`, `llm`
- Max items per digest: `5`
- Delivery channel: `stdout`

The current subscription implementation supports `stdout` delivery. If the user asks for email, Slack, Feishu, WeChat, or another target, explain that a delivery adapter needs to be added first.

## Files

- Skill entry: `skill/paper-subscribe/SKILL.md`
- Config template: `skill/paper-subscribe/templates/config.example.json`
- Digest builder: `skill/paper-subscribe/scripts/prepare-digest.js`
- Delivery script: `skill/paper-subscribe/scripts/deliver.js`
- Cron installer: `skill/paper-subscribe/scripts/install-cron.sh`
- Runtime wrapper: `skill/paper-subscribe/scripts/run-subscription.sh`
- User config path: `~/.paper-subscribe/config.json`
- User state path: `~/.paper-subscribe/state.json`

## Setup Steps

1. Locate the cloned repository root.

2. Verify Node.js is available and version 18 or newer:

```bash
node --version
```

3. Create the local config directory:

```bash
mkdir -p ~/.paper-subscribe
```

4. Create or update `~/.paper-subscribe/config.json` with this shape:

```json
{
  "feed_url": "https://raw.githubusercontent.com/xianshang33/llm-paper-daily/main/feed-papers.json",
  "state_path": "~/.paper-subscribe/state.json",
  "timezone": "Asia/Shanghai",
  "schedule": "15 9 * * *",
  "filters": {
    "topics": ["agent", "llm"],
    "max_items": 5,
    "language": "zh"
  },
  "delivery": {
    "channel": "stdout"
  }
}
```

Preserve any user-provided preferences when updating an existing config.

5. Preview the digest without consuming the real state.

Create a temporary config whose `state_path` points to a temporary file, then run:

```bash
node skill/paper-subscribe/scripts/prepare-digest.js --config /tmp/paper-subscribe-preview-config.json > /tmp/paper-subscribe-preview.json
node skill/paper-subscribe/scripts/deliver.js --config /tmp/paper-subscribe-preview-config.json --input /tmp/paper-subscribe-preview.json
```

Do not use the real `~/.paper-subscribe/state.json` for preview delivery, because `deliver.js` records delivered item IDs.

6. Install or update the scheduled job:

```bash
bash skill/paper-subscribe/scripts/install-cron.sh --config ~/.paper-subscribe/config.json
```

7. Verify the crontab contains the subscription tag:

```bash
crontab -l | grep 'paper-subscribe:'
```

8. Report back to the user with:

- Config path
- Feed URL
- Timezone
- Schedule
- Language
- Topics
- Max items
- Delivery channel
- Preview status
- Cron verification result

## Failure Handling

- If Node.js is missing or older than 18, ask the user to install or upgrade Node.js.
- If the feed cannot be fetched, report the HTTP or network error and do not install the cron job until the user approves.
- If `crontab` is unavailable, report that scheduled delivery could not be installed and provide the manual command to run the subscription wrapper.
- If preview returns `skipped_no_new_items`, the setup can still be valid; mention that there were no new unseen items in the preview state.

## Manual Wrapper

If cron is unavailable, the subscription can be run manually from the repository root:

```bash
bash skill/paper-subscribe/scripts/run-subscription.sh --config ~/.paper-subscribe/config.json
```
