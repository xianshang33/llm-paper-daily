# Feishu Robot Notification Research

Do not implement the notification module in the current roadmap slice. This note defines the future module boundary so implementation can happen later without mixing operational alerts into daily report delivery.

## Current State

- `FeishuClient.deliver_report()` sends the daily report through a webhook-style adapter.
- It does not model notification events.
- It does not support webhook signing.
- It does not distinguish reports from operational alerts.

## Future Module Boundary

Create a separate `FeishuNotificationClient` or `NotificationClient`.

Inputs:

- event type
- short title
- short body
- links
- stage
- date
- severity

Environment:

- `FEISHU_WEBHOOK_URL`
- `FEISHU_WEBHOOK_SECRET`

Events:

- `daily_ready`: daily report generated, with candidate count and Notion link.
- `deep_reading_confirmation_required`: selected papers resolved and waiting for confirmation.
- `deep_reading_done`: deep notes created, with count and links.
- `pipeline_failed`: stage failed, with error summary and recovery action.

## Message Format

Start with text messages. Use interactive cards only after the event model is stable.

Text payload shape:

```json
{
  "msg_type": "text",
  "content": {
    "text": "[paper-learning] daily_ready 2026-05-26\n候选论文: 20\n下一步: review Notion Paper Inbox"
  }
}
```

Signed webhook payloads should include `timestamp` and `sign` according to Feishu custom bot documentation.

## References

- Feishu custom bot: https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot
- Feishu message cards: https://open.feishu.cn/document/common-capabilities/message-card/getting-started/send-message-cards-with-a-custom-bot
