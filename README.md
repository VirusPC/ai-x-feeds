# x-feeds

自建的 X（Twitter）账号 RSS 订阅源。数据来自 Grok Bot 的免费公开读取额度，由例程每天刷新一次，再提交到本仓库。阅读器和 [weekly-ai-blogs-digest](https://github.com/VirusPC/edges) 技能都可以订这里的固定地址，不必再依赖时不时会挂的 Nitter 镜像。

## 订阅地址

单个账号：

```
https://raw.githubusercontent.com/VirusPC/ai-x-feeds/main/feeds/<username>.xml
```

例如 @DeepSeekHarness：

- Feed：https://raw.githubusercontent.com/VirusPC/ai-x-feeds/main/feeds/DeepSeekHarness.xml
- 主页：https://x.com/DeepSeekHarness
- 全部源的 OPML：https://raw.githubusercontent.com/VirusPC/ai-x-feeds/main/feeds/index.opml

## 仓库结构

- `accounts.json`：要跟踪的账号列表（`username`、数字 `id`、`title`）。
- `data/<username>.json`：累计帖子，按 id 去重，最新在前，最多保留约 200 条。
- `feeds/<username>.xml`：由 `data/` 生成的 RSS 2.0。
- `feeds/index.opml`：列出全部 feed 的 raw 地址，可直接导入阅读器。
- `scripts/update.py`：合并一次拉取的帖子并重新生成 feed。

## 每天怎么更新

在本仓库根目录操作。先用 Grok Bot 的 X 工具按 `accounts.json` 里的数字 id 拉帖子（`get_users_posts`，`max_results` 建议 25，单次上限就是 25；`post.fields` 用 `created_at,text,article,article_title,conversation_id,entities`，并展开 `referenced_posts`），把工具返回的 JSON 存成文件，然后：

```bash
python3 scripts/update.py DeepSeekHarness /path/to/posts.json
git add accounts.json data feeds
git status
# 有变更再提交推送
git commit -m "Update DeepSeekHarness feed"
git push origin main
```

脚本是幂等的：同一批帖子再跑一次，生成的 `data/` 和 `feeds/` 不会变。没有新帖子时不必提交。

## 怎么加一个账号

1. 用 `get_users_by_username` 查到该账号的数字 id。
2. 在 `accounts.json` 里追加一条，例如：

   ```json
   {
     "username": "ExampleUser",
     "id": "1234567890",
     "title": "Example User"
   }
   ```

3. 拉该账号的帖子，运行 `python3 scripts/update.py ExampleUser posts.json`。
4. 提交并推送到 `main`。订阅地址即为 `https://raw.githubusercontent.com/VirusPC/ai-x-feeds/main/feeds/ExampleUser.xml`。

## 条目规则

- 长文（X Articles）用 `article.title` 做标题，正文用文章全文；没有文章标题时，用帖子正文前约 80 个字符，标题不会为空。
- `link` 为 `https://x.com/<username>/status/<id>`，`guid` 为帖子 id，`pubDate` 为 RFC 822。
- 回复和转帖会写入 feed，并在 `data/` 里用 `is_reply` / `is_retweet` 标记。
