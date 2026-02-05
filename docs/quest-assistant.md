# Quest Assistant (RPG)

當 GitHub issue 被加上 `quest` label 時，GitHub Actions 會自動：

1. 在 `docs/quests/` 生成一個 quest 記錄檔（Markdown）
2. 自動 commit 並 push 回 repo

## 觸發方式

- 開一個 issue
- 加上 label：`quest`

## 生成檔案格式

路徑：`docs/quests/YYYY-MM-DD-issue-<number>.md`

包含：
- issue 標題 / URL / 作者 / 建檔日期（UTC）
- labels 清單
- issue body 作為「Quest brief」

## 注意

- workflow 只在 `issues: labeled` 事件下運作
- 有 `permissions: contents: write`，用內建 `GITHUB_TOKEN` 就能 push
