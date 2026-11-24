# API 地図 — Jira Data Center（v2）／ Cloud（v3）

ヘルパー `scripts/jira.py` が使うエンドポイントの一覧。パスは版ごとに異なり、ヘルパーが吸収する。利用側は版を意識せずコマンドを使う。

## 共通

- URL は `{JIRA_BASE_URL}/rest/api/2/...`（DC）または `{JIRA_BASE_URL}/rest/api/3/...`（Cloud）。`JIRA_BASE_URL` にはコンテキストパスを含んでよい。末尾に `/rest` は付けない。
- 認証は DC が `Authorization: Bearer <PAT>`、Cloud が Basic 認証（メールアドレスと API トークン）。値は環境変数からのみ読み、表示しない。
- 応答は `Accept: application/json` で JSON を受け取る。使うのは HTTP GET のみ。
- 課題の取得フィールドは `summary,status,assignee,reporter,priority,duedate,created,updated,issuetype,resolutiondate,labels,components` に絞る。課題詳細ではこれに `comment,description` を加える。

## 接続確認

| 目的 | エンドポイント（版共通の相対パス） |
|---|---|
| 認証ユーザー自身 | `GET /myself` |
| サーバー情報（版数など） | `GET /serverInfo` |

## 検索とページング

| 版 | エンドポイント | ページング |
|---|---|---|
| DC（v2） | `GET /search`（`jql`、`startAt`、`maxResults`、`fields`） | 応答の `total` を見て `startAt` を進める。1 ページは 100 件で要求するが、サーバー側の上限で短く返る場合も、返った件数だけ進めるため正しく集められる |
| Cloud（v3） | `GET /search/jql`（`jql`、`maxResults`、`fields`、継続時は `nextPageToken`） | 旧 `/search` は廃止済みのため使わない。応答の `isLast` が真、または `nextPageToken` が無くなるまで継続トークンを渡す。応答に `total` は無い |

- コマンド側の打ち切りは `--limit N`（既定はコマンドごとに 100 など）。打ち切ったかどうかは報告に明記する。
- 対象のキー限定（任意）: 一覧系コマンドの `--keys ABC-1,ABC-2` または環境変数 `JIRA_ISSUE_KEYS` で、`key in (ABC-1, ABC-2)` を各コマンドの JQL に AND で足す（`search` では利用者の JQL を括弧で包み、ORDER BY は末尾に残す）。キーは形式検証（プロジェクトキー＋番号）を通ったものだけを使う。
- 件数だけを数える場合、DC は `maxResults=0` の検索で `total` を読む。Cloud には総数がないためページングで数え上げ、1000 件で打ち切って「以上」として扱う。

## コマンドとエンドポイントの対応

| コマンド | 主なエンドポイント | JQL の骨格 |
|---|---|---|
| `check` | `/myself`、`/serverInfo` | — |
| `my-issues` | 検索 | `assignee = currentUser()`（未完了のみは `resolution = Unresolved` を追加）。期日順 |
| `search` | 検索 | 利用者が渡した JQL をそのまま使う |
| `issue KEY` | `GET /issue/{key}`（`fields` にコメントと説明を含む） | — |
| `project KEY` | `GET /project/{key}`、検索（件数と期限超過） | `project = "KEY"` にステータス区分や期限超過の条件を組み合わせる |
| `overdue` | 検索 | `resolution = Unresolved AND duedate < "今日"`。期日順。範囲は既定で自分の担当、`--project`／`--all` で変更 |
| `stale` | 検索 | `resolution = Unresolved AND updated < -Nd`。更新日の古い順 |
| `standup` | 検索 ×3 | 自分の担当で「`resolved >= -1d`」「ステータス区分が In Progress で未完了」「未完了で `duedate <= "今日"`」 |
| `weekly` | 検索 ×3 | 「`resolved >= -7d`」「`created >= -7d`」「未完了の期限超過」。範囲は既定で自分の担当、`--project` でプロジェクト全体 |

## 課題詳細

| 目的 | エンドポイント | 備考 |
|---|---|---|
| 課題詳細 | `GET /issue/{key}` | ステータス、期日、担当、優先度、作成／更新／完了日、ラベル等を正規化して表示する |
| コメント | 課題詳細の `comment.comments` | 直近 `--comments` 件（既定 5 件）を新しい順ではなく時系列の末尾から取る。本文の形式は版で異なる（DC は平文、Cloud は ADF。`cloud-differences.md` 参照） |
| プロジェクト情報 | `GET /project/{key}` | キーと名前の確認に使う。概況の件数は検索で数える |
