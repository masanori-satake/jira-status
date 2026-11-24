# 変更履歴

## 1.0.0 — 2026-11-25

- 初版。Jira（Data Center／Cloud）を REST API で読み取り専用に使う 課題確認スキル。担当課題の一覧、プロジェクト概況、期限超過・停滞の検出、JQL 検索、課題詳細と直近コメントの確認、朝会（standup）・週次（weekly）の材料集めと、標準ライブラリのみのヘルパー `scripts/jira.py` を収録。確認の中心は期日・ステータス・コメント。
- スクリプト1本で DC／Cloud 両対応。DC は REST API v2（`startAt` ページング、コメント・説明は平文）、Cloud は REST API v3（検索は新しい `/search/jql` の `nextPageToken` ページング、コメント・説明は ADF からテキスト抽出）。版は `JIRA_EDITION` の任意指定、未指定なら URL と認証情報から自動判定する。
- 接続情報は環境変数からのみ読む（`JIRA_BASE_URL`、DC は `JIRA_PAT` の Bearer 認証、Cloud は `JIRA_EMAIL`＋`JIRA_API_TOKEN` の Basic 認証）。値は表示しない。
- 安全策は bamboo-dc-analysis 1.2.4 と同じ水準。リダイレクト先が別ホスト／https→http 降格のときは認証情報を送らずに中断し、http(s) 以外へは転送しない。応答本文の上限 32 MB、宣言長に満たない切断応答は成功と扱わない。エラー抜粋からは秘密の値を取り除き、`JIRA_BASE_URL` が http://（localhost を除く）なら平文警告を出す。
- リポジトリをチェックアウトした途端に使える構成。正本は `.agents/skills/jira-status/`（Copilot がそのまま発見する）に置き、Kiro の発見先である `.kiro/skills/jira-status/` にはバイト同一のミラーを配置。`tools/sync_mirror.py` で再生成と同一性検証を行い、同期とリリースは GitHub Actions（sync-and-release）で自動化する。
- `scripts/install.py` を同梱。別のワークスペースへ、正本から Kiro の配置先へディレクトリリンク（Windows はジャンクション、POSIX はシンボリックリンク）で配置し、コピー方式への切替と `--check` による同一性検証も備える。
- `tests/` にフィクスチャテストを同梱。DC v2 の `startAt` ページング、Cloud v3 の `nextPageToken` ページング、ADF 抽出、認証ヘッダー（Bearer／Basic）、リダイレクト時の認証情報ドロップ、本文上限・切断検出・エラー抜粋の redaction を、実サーバーに接続せず検証する。`JIRA_SKILL_DIR` で任意の配置先を指定して実行できる。
