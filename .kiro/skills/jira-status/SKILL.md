---
name: jira-status
description: Jira（Data Center / Cloud）を REST API で読み取り専用に使い、担当課題の一覧、プロジェクトの概況、期限超過・停滞課題の検出、JQL 検索、課題詳細とコメントの確認、朝会（standup）と週次報告の材料集めを行うときに使う。期日・ステータス・コメントを中心に課題の確認を、Web 画面を行ったり来たりせずに済ませたいときに使う。
metadata:
  version: "1.1.1"
---

# Jira 課題確認

Jira（Data Center は REST API v2、Cloud は REST API v3）に対して読み取り専用（HTTP GET のみ）で日常の確認を行う手順。同梱の `scripts/jira.py`（Python 標準ライブラリのみ）を使う。

確認の中心は期日・ステータス・コメントである。スクラム／スプリント／ストーリーポイントは前面に出さない。

## 安全と前提

- 書き込みは一切しない。使うのは HTTP GET のみ。課題の作成・遷移・コメント追加・担当者変更はこのスキルの対象外（将来スコープ）。
- 接続情報は環境変数からのみ読む。値は表示しない。
  - 共通: `JIRA_BASE_URL`（Jira のルート URL。コンテキストパスを含んでよい。末尾に `/rest` は付けない。末尾のスラッシュはあってもなくてもよい）
  - Data Center: `JIRA_PAT`（Personal Access Token。`Authorization: Bearer` で送る）
  - Cloud: `JIRA_EMAIL` ＋ `JIRA_API_TOKEN`（Basic 認証）
  - 版の指定: `JIRA_EDITION=dc|cloud`（任意）。未指定なら、URL が `*.atlassian.net` のとき Cloud、それ以外で PAT があれば DC、メール＋トークンがあれば Cloud と判定する。
  - 利用環境は主に Windows 11 を想定する。Windows では、環境変数はユーザー環境変数に設定してエディタを再起動するのが確実である。PowerShell の `$env:` で設定した値は、そのシェルからエディタを起動した場合にだけ渡る（スタートメニューから起動したエディタには渡らない）。「環境変数が設定されていません」と出たら、設定場所とエディタの起動経路を疑う。コマンド例の `python` は、Python ランチャーの `py` でもよい。
- PAT・API トークン・メールアドレスなどの秘密の値を、チャット・ファイル・コミット・チケットに書かない。
- 対象を課題キーで限定できる（任意）。一覧系コマンドの `--keys ABC-1,ABC-2`、または環境変数 `JIRA_ISSUE_KEYS`（カンマ区切り。`--keys` が優先）で、`key in (...)` を条件に AND で足す。指定しなければ限定しない。キーは形式検証を通ったものだけを JQL に入れる（不正なキーが混ざればエラーで止まる）。
- 見える範囲は認証ユーザーの権限の範囲だけである。一覧に出ないことは「存在しない」ことと区別できない。報告ではこの前提を落とさない。キーで限定した場合は、その旨も報告に明記する。
- 安全策: リダイレクト先が別ホスト、または https から http への降格の場合は認証情報を送らずに中断する。http(s) 以外へは転送しない。応答本文の上限は 32 MB で、宣言長に満たない切断応答は成功と扱わない。エラー抜粋からは秘密の値を取り除く。`JIRA_BASE_URL` が http://（localhost を除く）なら平文警告を出す。

## 手順 0: 接続確認（必ず最初に行う）

```bash
python scripts/jira.py check
```

`/myself` と `/serverInfo` を取得し、「どのインスタンスに、誰として」つないだか、版（DC／Cloud）とサーバーの版数を確認してから作業に入る。DC の実バージョンはこの `serverInfo` で判明するので、初回接続時は結果を報告に含める。

## 日常の確認の進め方

1. **自分の担当**（毎朝の入口）: `my-issues` で未完了の担当課題を期日順に見る。完了も含める場合は `--all`。
2. **朝会の材料**: `standup` で自分の「完了（直近24時間）／進行中／期限超過・今日が期限」を集める。
3. **週次の材料**: `weekly` で直近7日の完了・新規と、未完了の期限超過を集める。`--project KEY` でプロジェクト全体に広げられる。
4. **問題の検出**: `overdue` で期限超過の未完了課題、`stale --days N` で N 日以上更新のない未完了課題を抽出する。既定は自分の担当で、`--project KEY`／`--all` で範囲を変える。
5. **プロジェクト概況**: `project KEY` でステータス区分ごとの件数と期限超過の一覧を見る。
6. **個別の確認**: `issue KEY` で課題の詳細（ステータス、期日、担当、優先度、更新日）と直近コメントを確認する。自由な絞り込みは `search --jql "..."` で行う。

コマンドとエンドポイントの対応は `references/api-map.md`、集計の定義と読み方は `references/check-recipes.md`、DC と Cloud の差は `references/cloud-differences.md` を参照。

## 報告の約束

- 一覧には必ず「対象範囲（自分／プロジェクト／全体）、取得できた件数、打ち切りの有無」を添える。`--limit` や件数数え上げの打ち切り（Cloud の件数集計は 1000 件で打ち切り、「以上」と表示する）に当たった場合は、その旨を明記して結論の強さを落とす。
- 期日は Jira の `duedate`、完了は `resolutiondate` とステータス区分（To Do／In Progress／Done）で判定する。判定の定義は `references/check-recipes.md` に従い、レポート間で意味をずらさない。
- コメントは確認の中心の一つである。課題の状況を報告するときは、ステータスと期日だけでなく、直近コメントの要点（いつ、誰が、何を書いたか）も併記する。Cloud のコメントと説明は ADF 形式で返るため、ヘルパーがテキストに抽出したものを読む。
- 「期限超過」「停滞」は事実の抽出であり、担当者への評価ではない。理由や遅れの原因は、課題とコメントに書かれた内容に基づいてだけ触れ、憶測で断定しない。

## ヘルパーのコマンド

```bash
python scripts/jira.py check
python scripts/jira.py my-issues [--all] [--keys ABC-1,ABC-2] [--limit N] [--json]
python scripts/jira.py search --jql "..." [--keys ABC-1,ABC-2] [--limit N] [--json]
python scripts/jira.py issue KEY [--comments 5] [--json]
python scripts/jira.py project KEY [--keys ABC-1,ABC-2]
python scripts/jira.py overdue [--project KEY | --all] [--keys ABC-1,ABC-2] [--limit N] [--json]
python scripts/jira.py stale [--days 14] [--project KEY | --all] [--keys ABC-1,ABC-2] [--limit N] [--json]
python scripts/jira.py standup [--keys ABC-1,ABC-2] [--limit N] [--json]
python scripts/jira.py weekly [--project KEY] [--keys ABC-1,ABC-2] [--limit N] [--json]
```

共通: `--json` で整形済みの JSON を出す。

## References

- `references/api-map.md` — コマンドとエンドポイントの対応、ページング、取得フィールド
- `references/check-recipes.md` — 期限超過・停滞・朝会・週次の判定定義と限界
- `references/cloud-differences.md` — DC（v2）と Cloud（v3）の差、ADF のテキスト抽出、版の自動判定
