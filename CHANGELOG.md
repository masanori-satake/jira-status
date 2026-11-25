# 変更履歴

## 1.2.1 — 2026-11-25

- `.pre-commit-config.yaml` を追加し、pre-commit.ci で実行できるようにした。設定は他のプロジェクトと統一している（pre-commit-hooks v6.0.0 の基本セット＋Python 健全性チェック、Ruff v0.17.3）。Ruff のルール方針は C2M-Export の `ruff.toml` と同一とし、`ruff.toml` を追加した（対象は Python 3.9、UP031 のみ %-整形の統一使用を理由に対象外）。
- フックの自動修正（ruff-format、import 順序）を全ファイルに適用した。整形のみで、スキルの動作は変わらない。

## 1.2.0 — 2026-11-25

- `fields` コマンドを追加した。`GET /field`（DC／Cloud 共通）で全フィールドの定義を収集し、既定ではカスタムフィールドのみ、`--all` でシステムフィールドも含める。各フィールドについて ID、名前、種類、JQL で使える句名（clauseNames）、検索・並び替え可否を出す。種類は schema から整形し、カスタム種別はプラグインキーを読みやすい表示（テキスト（複数行）、日付ピッカー、複数選択リストなど）に変換する。未知のカスタム種別はプラグインキーの末尾で示す。`--json` では schema の生の値（type、items、custom、customId）も保持する。
- ユースケース集に「フィールドの棚卸しと JQL の下調べ」を追加した。
- プロジェクト×課題タイプごとの必須・表示（createmeta）は対象外のままである。

## 1.1.2 — 2026-11-25

- 環境変数の説明を、版（Data Center／Cloud）ごとに「必須／任意／不要」が分かる表形式にした（README の初期設定と SKILL.md）。設定を案内するときに、相手の版で必要な変数だけを挙げられるようにした。スキルの動作は変わらない。

## 1.1.1 — 2026-11-25

- 初期設定の説明を Windows 11 の利用者優先に書き換えた（README と SKILL.md）。環境変数は Windows のユーザー環境変数への設定を推奨とし、設定後のエディタ再起動が必要なこと、PowerShell の `$env:` で設定した場合はそのシェルからエディタを起動したときにだけ渡ることを明記した。Python の用意（PATH への追加）と、コマンド例の `python` を Python ランチャーの `py` に読み替えられることも案内した。フィクスチャテストの実行例にも PowerShell 形式を併記した。スキルの動作は変わらない。

## 1.1.0 — 2026-11-25

- 対象を課題キーで限定できるようにした。一覧系コマンド（my-issues / search / overdue / stale / standup / weekly / project）に `--keys ABC-1,ABC-2` を追加し、環境変数 `JIRA_ISSUE_KEYS` でも既定の限定を指定できる（優先順位は `--keys` ＞ 環境変数 ＞ 限定なし）。条件は `key in (...)` として JQL に AND で足され、サーバー側で絞り込まれるため取得量も減る。`search` では利用者の JQL を括弧で包んでから足し、ORDER BY は末尾に残す。
- キーは形式検証（プロジェクトキー＋番号）を通ったものだけを JQL に入れる。不正なキーや JQL 混入を狙う文字列が混ざっていたら、検索を実行せずエラーで止める。
- **脆弱性チェックを実施した。** 静的検査 Bandit 1.9.4 で Medium／High は 0 件。Low 3 件はいずれも install.py のジャンクション作成（mklink）に関するもので、引数はリスト形式で渡し、cmd の特殊文字を含むパスは実行前に拒否する対策が入っているため、許容と判断した。あわせて、依存は Python 標準ライブラリのみであること、shell 実行・eval・pickle・TLS 検証の無効化が無いことを確認した。フィクスチャテストには、秘密情報が標準出力・標準エラーに出ないことの常時検証に加え、リダイレクト先が http(s) 以外のスキームの場合はたどらないこと、形式不正なキーが拒否されることを追加した。
- `tools/sync_mirror.py` の同一性チェックを assert から明示的なエラー終了に変えた（`python -O` でも消えないようにするため）。

## 1.0.0 — 2026-11-25

- 初版。Jira（Data Center／Cloud）を REST API で読み取り専用に使う 課題確認スキル。担当課題の一覧、プロジェクト概況、期限超過・停滞の検出、JQL 検索、課題詳細と直近コメントの確認、朝会（standup）・週次（weekly）の材料集めと、標準ライブラリのみのヘルパー `scripts/jira.py` を収録。確認の中心は期日・ステータス・コメント。
- スクリプト1本で DC／Cloud 両対応。DC は REST API v2（`startAt` ページング、コメント・説明は平文）、Cloud は REST API v3（検索は新しい `/search/jql` の `nextPageToken` ページング、コメント・説明は ADF からテキスト抽出）。版は `JIRA_EDITION` の任意指定、未指定なら URL と認証情報から自動判定する。
- 接続情報は環境変数からのみ読む（`JIRA_BASE_URL`、DC は `JIRA_PAT` の Bearer 認証、Cloud は `JIRA_EMAIL`＋`JIRA_API_TOKEN` の Basic 認証）。値は表示しない。
- 安全策は bamboo-dc-analysis 1.2.4 と同じ水準。リダイレクト先が別ホスト／https→http 降格のときは認証情報を送らずに中断し、http(s) 以外へは転送しない。応答本文の上限 32 MB、宣言長に満たない切断応答は成功と扱わない。エラー抜粋からは秘密の値を取り除き、`JIRA_BASE_URL` が http://（localhost を除く）なら平文警告を出す。
- リポジトリをチェックアウトした途端に使える構成。正本は `.agents/skills/jira-status/`（Copilot がそのまま発見する）に置き、Kiro の発見先である `.kiro/skills/jira-status/` にはバイト同一のミラーを配置。`tools/sync_mirror.py` で再生成と同一性検証を行い、同期とリリースは GitHub Actions（sync-and-release）で自動化する。
- `scripts/install.py` を同梱。別のワークスペースへ、正本から Kiro の配置先へディレクトリリンク（Windows はジャンクション、POSIX はシンボリックリンク）で配置し、コピー方式への切替と `--check` による同一性検証も備える。
- `tests/` にフィクスチャテストを同梱。DC v2 の `startAt` ページング、Cloud v3 の `nextPageToken` ページング、ADF 抽出、認証ヘッダー（Bearer／Basic）、リダイレクト時の認証情報ドロップ、本文上限・切断検出・エラー抜粋の redaction を、実サーバーに接続せず検証する。`JIRA_SKILL_DIR` で任意の配置先を指定して実行できる。
