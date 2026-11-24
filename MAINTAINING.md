# 保守手順 — 正本1つ、チェックアウトで即利用、両対応を維持する

## リポジトリの構成

このリポジトリは、チェックアウトして開けばスキルがそのまま使える構成です。

- 正本: `.agents/skills/jira-status/`（SKILL.md、references/、scripts/、tests/）
- ミラー: `.kiro/skills/jira-status/`（正本とバイト同一）
- リポジトリ直下: README、CHANGELOG、LICENSE、本書、`tools/sync_mirror.py`

Copilot は `.agents/skills/` をそのまま発見し、Kiro は `.kiro/skills/` を発見します。チェックアウトを開けば、どちらのツールでも配置作業なしでスキルが有効になります。

## 編集のルール

- 編集するのは正本だけです。ミラーを直接編集しません。
- 正本を編集したら、コミット前に必ず次を実行します。

```bash
python tools/sync_mirror.py
python tools/sync_mirror.py --check
```

`sync_mirror.py` は正本からミラーを再生成し、`--check` はファイル集合と SHA-256 で同一性を検証します（ずれがあれば該当ファイルを示して終了コード 1）。

## 他のワークスペースへ入れるとき

このリポジトリ以外のワークスペースで使う場合は、正本フォルダをそのワークスペースの `.agents/skills/` に置き、正本同梱のインストーラで Kiro 向けの配置を作ります。

```bash
python .agents/skills/jira-status/scripts/install.py --workspace .
```

- 既定はリンク方式（Windows はジャンクション、POSIX はシンボリックリンク）で、実体は正本だけです。正本を入れ替えれば、リンク先もそのまま追随します。
- リンクが使えない環境では `--mode copy` を使い、`install.py --check` で同一性を検証します。
- 「同じ動き」の担保は、同一性検証に加えてフィクスチャテストです。任意の配置先を指定して実行できます（PowerShell: `$env:JIRA_SKILL_DIR="<配置先>"; python tests/test_jira.py`／bash: `JIRA_SKILL_DIR=<配置先> python tests/test_jira.py`。tests は正本フォルダ内にあります）。テストはフィクスチャサーバーだけで検証し、実際の Jira には接続しません。

## リリース手順（GitHub Actions で自動化）

`.github/workflows/sync-and-release.yml` が、正本への push を契機に次を自動実行します。

1. **同期ジョブ**: ミラーを再生成し、同一性を検証し、正本とミラーの両方でフィクスチャテストを実行して、ミラーに差分があれば自動コミットします。
2. **リリースジョブ**: `SKILL.md` の `metadata.version` に対応するリリースがまだ無い場合だけ、タグ `v<版>` を打ち、CHANGELOG の該当節をノートとして GitHub Release を作成します。

人がやるのは、これだけです。

1. 正本だけを編集する。
2. 版を上げるときは `SKILL.md` の `metadata.version` と `CHANGELOG.md` を揃えて更新する。
3. コミットして GitHub に push する（ミラーの再生成はワークフローがやるので、ローカルで `sync_mirror.py` を回し忘れてもリリース前に揃います）。
4. 利用側は、このリポジトリを pull するだけです。チェックアウト構成のため、追加の配置作業はありません。

ワークフローを手動実行（workflow_dispatch）すると、その時点の版でタグとリリースが無ければ作成します。ワークフローが使えない場合の手動手順は、従来どおり `tools/sync_mirror.py` の再生成と `--check`、両配置でのテスト、版マーカーと CHANGELOG の更新、タグとリリースの手動作成です。

## やらないこと

- ミラーや配置先の中身を直接編集しない。直したいときは正本を直して再生成・再配置する。
- 版を上げる際、SKILL.md のメタデータと CHANGELOG のどちらか片方だけを更新しない。
- 実際の接続先のホスト名や実データを、ドキュメント・テスト・コミットに書かない。検証はフィクスチャだけで行う。
