# Jira Status

[![Latest release](https://img.shields.io/github/v/release/masanori-satake/jira-status?style=flat)](https://github.com/masanori-satake/jira-status/releases)
[![Sync mirror and release](https://github.com/masanori-satake/jira-status/actions/workflows/sync-and-release.yml/badge.svg)](https://github.com/masanori-satake/jira-status/actions/workflows/sync-and-release.yml)

**Jira（Data Center / Cloud）** を REST API で読み取り専用に使う、課題確認のための Agent Skill です。GitHub Copilot、Amazon Kiro など、Agent Skills 形式に対応したエージェントから使えます。

Jira の Web 画面を何枚も開いて確認していたことを、エージェントへの質問で済ませるためのものです。「私の担当で期限を過ぎている課題はある？」「朝会の材料をそろえて」「このプロジェクトの概況を見せて」と聞けば、API から集めて答えます。確認の中心は期日・ステータス・コメントで、スクラム／スプリント／ストーリーポイントは前面に出しません。

## できること

- **担当課題** — 自分の未完了課題を期日順に一覧（完了も含める指定も可）
- **プロジェクト概況** — ステータス区分ごとの件数と、期限超過の一覧
- **問題の検出** — 期限超過の未完了課題、N 日以上更新のない停滞課題の抽出（自分の担当／プロジェクト／全体で範囲指定可）
- **JQL 検索** — 自由な JQL で課題を検索
- **課題詳細** — ステータス、期日、担当、優先度、更新日と直近コメントの確認
- **朝会・週次の材料** — 朝会向けに「完了（直近24時間）／進行中／期限超過・今日が期限」、週次向けに「直近7日の完了・新規／未完了の期限超過」を集める
- **対象のキー限定（任意）** — 一覧系コマンドは `--keys ABC-1,ABC-2` や環境変数 `JIRA_ISSUE_KEYS` で、対象を特定の課題キーだけに絞れます。絞り込みは JQL でサーバー側にかかるため、取得量も減ります。指定しなければ従来どおり限定しません
- **フィールド収集** — カスタムフィールドを含む全フィールドの定義（ID、名前、種類、JQL で使える句名）を一覧できます。カスタムフィールドの棚卸しや、JQL を書く前の下調べに使えます

Data Center（REST API v2）と Cloud（REST API v3）の世代差は、ヘルパーが吸収します。検索のページング方式（DC は `startAt`、Cloud は新しい `/search/jql` の `nextPageToken`）や、Cloud のコメント・説明の ADF 形式からテキストへの抽出も、ヘルパー側で行います。

## 安全の考え方

- **GET のみ。** 課題の作成・遷移・コメント追加など、Jira の状態変更は一切しません。書き込みは将来スコープで、初版には入れていません。
- **認証情報はファイルに残しません。** ヘルパーは接続情報を環境変数からだけ読みます。スキル、リポジトリ、出力のどこにも書きません。
- **リダイレクトで認証情報が漏れないようにします。** 転送先が別ホスト、または https から http へ落ちる場合は認証情報を送らずに中断し、http(s) 以外へは転送しません。
- **応答本文には 32 MB の上限**を設け、宣言された長さに満たない切断された応答は成功と扱いません。エラー表示の抜粋からは秘密の値を取り除きます。
- **見える範囲は権限の範囲だけ。** その前提を落とさずに報告します。

## 動作環境

- Jira Data Center（最新寄り、REST API v2 系を前提）または Jira Cloud（REST API v3）
- 認証情報: DC は Personal Access Token、Cloud はメールアドレス＋API トークン
- Python 3.9 以降（ヘルパーは標準ライブラリのみ）

## 導入

**このリポジトリを clone して開けば、その場でスキルが有効になります。** リポジトリ自体が、両ツールの発見先にスキルを内蔵しています。

- `.agents/skills/jira-status/` — 正本のスキル（Copilot は `.agents/skills/` を発見する）
- `.kiro/skills/jira-status/` — バイト同一のミラー（Kiro は `.kiro/skills/` を発見する）

```bash
git clone https://github.com/masanori-satake/jira-status.git
```

配置作業もコピーも不要です。更新は `git pull` だけです。

**別のワークスペースで使う場合** は、チェックアウトから正本フォルダ `.agents/skills/jira-status/` を取り出してそのワークスペースの `.agents/skills/` に置き、同梱インストーラを1回実行して、Kiro の配置先を正本へのディレクトリリンク（Windows はジャンクション、POSIX はシンボリックリンク）として作ります。実体は正本だけなので、コピー同士が食い違うことはありません。

```bash
python .agents/skills/jira-status/scripts/install.py --workspace .
python .agents/skills/jira-status/scripts/install.py --workspace . --check
```

リンクが使えない環境向けに `--mode copy` もあり、`--check` がファイル集合と SHA-256 で同一性を検証します。同梱のフィクスチャテストは配置先を指定して実行できるので（PowerShell では `$env:JIRA_SKILL_DIR="<配置先>"; python tests/test_jira.py`、bash では `JIRA_SKILL_DIR=<配置先> python tests/test_jira.py`）、両方で同じ動きになることを実際に確かめられます。保守ルールの全文は [MAINTAINING.md](MAINTAINING.md) にあります。

## 初期設定

利用環境は主に Windows 11 を想定しています。以後のコマンド例の `python` は、Python ランチャーを使う環境では `py` に読み替えてください。

1. Python 3.9 以降を用意します。python.org のインストーラか Microsoft Store から入れられます。python.org のインストーラでは、最初の画面で「Add python.exe to PATH」にチェックを入れてください。
2. 認証情報を用意します。
   - Data Center: プロフィール → Personal access tokens から、この用途専用のトークンを発行します。
   - Cloud: Atlassian アカウントの API トークンを発行し、ログインに使うメールアドレスと組み合わせます。
3. 環境変数を設定します。必要な変数は、利用している Jira が Data Center か Cloud かで違います。

   | 環境変数 | Data Center | Cloud | 設定する値 |
   |---|---|---|---|
   | `JIRA_BASE_URL` | **必須** | **必須** | Jira のルート URL |
   | `JIRA_PAT` | **必須** | 不要 | 発行した Personal Access Token（Bearer 認証） |
   | `JIRA_EMAIL` | 不要 | **必須** | ログインに使うメールアドレス（`JIRA_API_TOKEN` と組で使う） |
   | `JIRA_API_TOKEN` | 不要 | **必須** | 発行した API トークン（Basic 認証） |
   | `JIRA_EDITION` | 任意 | 任意 | `dc` または `cloud`。未指定なら URL と認証情報から自動判定します |
   | `JIRA_ISSUE_KEYS` | 任意 | 任意 | 対象を絞る課題キー（カンマ区切り） |

   **推奨は Windows のユーザー環境変数**への設定です。スタートメニューで「環境変数」と検索して「環境変数を編集」を開き、「（ユーザー名）のユーザー環境変数」に、自分の版で「必須」のものを追加します（「任意」は必要なときだけ）。

   設定したら、エディタ（VS Code / Kiro）を**再起動**してください。再起動後に起動したエディタからは、エージェントも含めて環境変数が読めるようになります。

   一時的に試すだけなら、PowerShell でそのセッションだけに設定することもできます。ただしこの方法では、**その PowerShell からエディタを起動した場合にだけ**エディタ側へ渡ります（スタートメニューから起動したエディタには渡りません）。

```powershell
# Data Center の場合
$env:JIRA_BASE_URL = "https://（JiraのURL）"
$env:JIRA_PAT = "（発行したPAT）"
# Cloud の場合は JIRA_PAT の代わりに次の2つ
$env:JIRA_EMAIL = "（メールアドレス）"
$env:JIRA_API_TOKEN = "（発行したAPIトークン）"
```

   macOS / Linux では、シェルの `export JIRA_BASE_URL=...` のように設定します（変数名は同じです）。

`JIRA_BASE_URL` は Jira のルート URL（コンテキストパスを含む、末尾に `/rest` は付けない）です。**末尾のスラッシュは、あってもなくても構いません。** ヘルパーが末尾のスラッシュを取り除いてから接続します。

4. 疎通確認（スキルフォルダ `.agents/skills/jira-status/` で、PowerShell から実行）:

```powershell
python scripts/jira.py check
```

接続先の版（DC／Cloud）とサーバーの版数、誰として認証されたかが返れば準備完了です。「環境変数が設定されていません」と出る場合は、設定した場所とエディタの再起動（PowerShell 方式なら起動経路）を見直してください。あとはエージェントに頼むだけです。

ユースケースごとの詳細なプロンプト（朝の確認、朝会、週次報告、期限超過の掘り下げなど、そのまま貼って使える形）は [ユースケース別プロンプト集](docs/use-cases.md) にあります。

## ヘルパーのコマンド

スキルフォルダ（`.agents/skills/jira-status/`）で実行します。

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
python scripts/jira.py fields [--all] [--json]
```

## 限界

- 書き込みはしません。課題の更新やコメントの投稿は Web 画面で行ってください。
- 期日が未設定の課題は、期限超過の抽出には現れません。期日未設定を調べる場合は JQL 検索で `duedate is EMPTY` を使います。
- Cloud の件数集計はページングによる数え上げで、1000 件で打ち切ります（その場合は「以上」と表示します）。
- Cloud のコメント・説明は ADF からテキストに抽出するため、表やリンク先などの装飾は失われます。装飾が本質的な場合は Web 画面で原文を確認してください。
- スプリント／ボード（Jira Software の Agile API）は対象外です。期日とステータス中心の運用を前提にしています。

## リポジトリ構成

- `.agents/skills/jira-status/` — 正本のスキル一式（`SKILL.md`、`references/`（API 地図、判定の定義、DC と Cloud の差）、`scripts/`（読み取り専用 REST ヘルパーとインストーラ）、`tests/`（フィクスチャテスト））
- `.kiro/skills/jira-status/` — 正本のバイト同一ミラー。`tools/sync_mirror.py` が生成し、手では編集しない
- `docs/use-cases.md` — ユースケース別プロンプト集
- `tools/sync_mirror.py` — ミラーの再生成と同一性検証
- `MAINTAINING.md` — 正本1つを保つ保守・リリースのルール

## ライセンス

MIT — [LICENSE](LICENSE) を参照してください。
