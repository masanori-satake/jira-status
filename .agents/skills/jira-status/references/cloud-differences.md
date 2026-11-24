# DC と Cloud の差 — スクリプトが吸収するもの

`scripts/jira.py` は1本で Data Center と Cloud の両方に対応する。このファイルは、版ごとに異なる点と、ヘルパーがどう吸収しているかをまとめたもの。利用側は版を意識しないが、結果を解釈するときの前提として残す。

## 版の判定

`JIRA_EDITION=dc|cloud` が指定されていればそれに従う。未指定の場合は次の順で判定する。

1. URL のホスト名が `*.atlassian.net` なら Cloud。
2. `JIRA_PAT` があれば DC。
3. `JIRA_EMAIL` と `JIRA_API_TOKEN` の両方があれば Cloud。
4. どれにも当てはまらなければ設定エラーとして止まる（推測で進めない）。

版が決まったあと、DC なら PAT が、Cloud ならメール＋トークンが無ければ設定エラーになる。

## 差の一覧

| 項目 | Data Center | Cloud |
|---|---|---|
| REST API の世代 | v2（`/rest/api/2/`） | v3（`/rest/api/3/`） |
| 認証 | PAT を `Authorization: Bearer` | メール＋API トークンを Basic 認証 |
| 検索エンドポイント | `/search` | `/search/jql`（旧 `/search` は廃止済み） |
| 検索のページング | `startAt`／`maxResults`、応答に `total` あり | `nextPageToken`、応答に `isLast` と継続トークン。`total` は無い |
| 件数の取得 | `maxResults=0` で `total` を読む | ページングで数え上げ（1000 件で打ち切り、「以上」として表示） |
| 説明・コメントの本文 | 平文の文字列 | ADF（Atlassian Document Format）の JSON |
| ユーザーの識別 | `name`（ユーザー名）を持つことが多い | `accountId` が中心。担当者の表示名はどちらも `displayName` を優先する |

## ADF のテキスト抽出

Cloud では課題の説明とコメント本文が ADF で返る。ヘルパーは次の規則で平文に直す。

- `text` ノードはその文字列を取る。
- `hardBreak` は改行にする。
- `paragraph`、`heading`、`listItem`、`blockquote`、`codeBlock` は中身の末尾に改行を付ける。
- それ以外のノード（リンク、メンション、絵文字など）は中身をたどる。属性（リンク先 URL など）はテキストに含めない。

このため、Cloud のコメントをそのまま読んでも DC と同じ形で報告できる。ただし ADF の装飾（太字、表、リンク先）は失われる。表やリンクが本質的なコメントでは、Web 画面で原文を確認する。

## 解釈上の注意

- Cloud の検索には `total` が無いため、「全 N 件」という言い方は数え上げの結果に基づく。打ち切り時は下限として扱う。
- DC の実バージョンは環境ごとに異なり、このスキルの前提は「最新寄りの DC（REST API v2 系）」である。`check` の `serverInfo` で実バージョンを確認し、前提と大きく違う場合はその旨を報告する。
- Cloud の実機検証はドキュメント準拠が中心である。無料サイト等で実機確認した場合は、その日付と結果を CHANGELOG 側ではなく報告に残す。
