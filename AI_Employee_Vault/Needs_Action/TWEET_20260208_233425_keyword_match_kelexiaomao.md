---
type: tweet
source: x_twitter
tweet_id: "2020566367267872932"
author_username: "kelexiaomao"
author_name: "可乐小猫"
author_id: ""
tweet_type: "keyword_match"
detection_source: "search"
conversation_id: ""
created_at: "2026-02-08T18:32:16.000Z"
received_at: "2026-02-08T23:34:25.193595"
status: pending
---

# Tweet: keyword_match from @kelexiaomao

## Metadata
| Field      | Value |
|------------|-------|
| Author     | @kelexiaomao (可乐小猫) |
| Tweet ID   | 2020566367267872932 |
| Type       | keyword_match |
| Source     | search |
| Created    | 2026-02-08T18:32:16.000Z |
| Conversation ID |  |

## Tweet Content
OpenClaw 切换 Voyage embedding（memorySearch）配置要点：

1) 使用 voyage API key（建议走 auth profile）
2) memorySearch.model 设为 "voyage-4"
3) remote.batch.enabled 建议先关（避免部分环境批处理卡住）
4) 重启 gateway 后再测 memory_search

核心是：model 写在 memorySearch 下，不是

## Referenced Tweets
None

## Matched Keyword
openclaw

## Raw Reference
- Tweet ID: `2020566367267872932`
- Author ID: ``
- Detection source: `search`
