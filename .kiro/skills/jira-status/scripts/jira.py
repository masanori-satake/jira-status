#!/usr/bin/env python3
"""Jira（Data Center / Cloud）を読み取り専用で使う 課題確認 CLI。

Python 標準ライブラリのみ。HTTP は GET だけを使う。

接続情報は環境変数からのみ読む（値は表示しない）:
  JIRA_BASE_URL    Jira のルート URL（コンテキストパス可。末尾に /rest は付けない）
  JIRA_PAT         Data Center の Personal Access Token（Bearer 認証）
  JIRA_EMAIL       Cloud のログイン メールアドレス（JIRA_API_TOKEN と組で使う）
  JIRA_API_TOKEN   Cloud の API トークン（Basic 認証）
  JIRA_EDITION     dc | cloud（任意。未指定なら接続先と認証情報から判定する）
  JIRA_ISSUE_KEYS  対象を課題キーで限定（カンマ区切り、任意。--keys が優先する）

使い方:
  python scripts/jira.py check
  python scripts/jira.py my-issues [--all] [--limit N] [--keys ABC-1,ABC-2] [--json]
  python scripts/jira.py search --jql "project = ABC AND resolution = Unresolved"
  python scripts/jira.py issue ABC-123 [--comments 5]
  python scripts/jira.py project ABC [--keys ABC-1,ABC-2]
  python scripts/jira.py overdue [--project ABC | --all]
  python scripts/jira.py stale --days 14 [--project ABC | --all]
  python scripts/jira.py standup
  python scripts/jira.py weekly [--project ABC]
  python scripts/jira.py fields [--all] [--json]
"""

import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

MAX_BODY_BYTES = 32 * 1024 * 1024  # 応答本文の上限
ERROR_EXCERPT_BYTES = 8 * 1024  # エラー表示に使う抜粋の上限
MAX_REDIRECTS = 5
PAGE_SIZE = 100
COUNT_CAP = 1000  # 件数数え上げの打ち切り（Cloud のページング用）

ISSUE_FIELDS = (
    "summary,status,assignee,reporter,priority,duedate,created,updated,issuetype,resolutiondate,labels,components"
)


class ConfigError(Exception):
    """環境変数などの設定不備。"""


class ApiError(Exception):
    """API 呼び出しの失敗。"""


# ---------------------------------------------------------------- 接続設定


class Config:
    def __init__(self):
        base = os.environ.get("JIRA_BASE_URL", "").strip()
        if not base:
            raise ConfigError("JIRA_BASE_URL が設定されていません。")
        self.base_url = base.rstrip("/")
        parsed = urllib.parse.urlparse(self.base_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ConfigError("JIRA_BASE_URL が URL として解釈できません。")
        if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
            print("警告: JIRA_BASE_URL が http:// です。認証情報が平文で流れます。", file=sys.stderr)

        self.pat = os.environ.get("JIRA_PAT", "").strip()
        self.email = os.environ.get("JIRA_EMAIL", "").strip()
        self.api_token = os.environ.get("JIRA_API_TOKEN", "").strip()

        edition = os.environ.get("JIRA_EDITION", "").strip().lower()
        if edition in ("dc", "cloud"):
            self.edition = edition
        elif parsed.hostname and parsed.hostname.endswith(".atlassian.net"):
            self.edition = "cloud"
        elif self.pat:
            self.edition = "dc"
        elif self.email and self.api_token:
            self.edition = "cloud"
        else:
            raise ConfigError(
                "版（DC / Cloud）を判定できません。JIRA_EDITION=dc|cloud を指定するか、"
                "DC なら JIRA_PAT、Cloud なら JIRA_EMAIL と JIRA_API_TOKEN を設定してください。"
            )

        if self.edition == "dc":
            if not self.pat:
                raise ConfigError("Data Center には JIRA_PAT が必要です。")
            self.api_prefix = "/rest/api/2"
            self.auth_header = "Bearer " + self.pat
            self._secrets = [self.pat]
        else:
            if not (self.email and self.api_token):
                raise ConfigError("Cloud には JIRA_EMAIL と JIRA_API_TOKEN が必要です。")
            self.api_prefix = "/rest/api/3"
            raw = ("%s:%s" % (self.email, self.api_token)).encode("utf-8")
            self.auth_header = "Basic " + base64.b64encode(raw).decode("ascii")
            self._secrets = [self.api_token]

    def redact(self, text):
        """エラー抜粋などから秘密の値を取り除く。"""
        for secret in self._secrets:
            if secret:
                text = text.replace(secret, "***")
        return text


# ---------------------------------------------------------------- HTTP 層


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """自動リダイレクトを止め、呼び出し側で1つずつ検証しながらたどる。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _read_bounded(resp, cfg):
    """本文を上限つきで読み、宣言長との不一致（切断）を検出する。"""
    declared = resp.headers.get("Content-Length")
    chunks = []
    total = 0
    while True:
        chunk = resp.read(min(65536, MAX_BODY_BYTES + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > MAX_BODY_BYTES:
            raise ApiError("応答が上限（%d バイト）を超えました。" % MAX_BODY_BYTES)
    body = b"".join(chunks)
    if declared is not None:
        try:
            if int(declared) != len(body):
                raise ApiError("応答が途中で切断されました（宣言 %s バイト、実績 %d バイト）。" % (declared, len(body)))
        except ValueError:
            pass
    return body


def api_get(cfg, path, params=None):
    """GET して JSON を返す。リダイレクトでは認証情報の扱いに注意する。"""
    url = cfg.base_url + cfg.api_prefix + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    opener = urllib.request.build_opener(_NoRedirect)
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        req = urllib.request.Request(current, method="GET")
        req.add_header("Accept", "application/json")
        req.add_header("Authorization", cfg.auth_header)
        try:
            resp = opener.open(req, timeout=30)
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                location = e.headers.get("Location") if e.headers else None
                e.read()
                if not location:
                    raise ApiError("リダイレクト先が示されませんでした（HTTP %d）。" % e.code)
                target = urllib.parse.urljoin(current, location)
                t = urllib.parse.urlparse(target)
                if t.scheme not in ("http", "https"):
                    raise ApiError("http(s) 以外へのリダイレクトはたどりません: %s" % t.scheme)
                cur = urllib.parse.urlparse(current)
                if t.netloc != cur.netloc or (cur.scheme == "https" and t.scheme == "http"):
                    # 別ホスト／https→http 降格では認証情報を送らない。
                    # この CLI は同一インスタンス前提なので、ここで打ち切る。
                    raise ApiError("リダイレクト先が接続先と異なるため中断しました（認証情報を送りません）。")
                current = target
                continue
            excerpt = e.read(ERROR_EXCERPT_BYTES).decode("utf-8", "replace")
            raise ApiError("HTTP %d: %s" % (e.code, cfg.redact(excerpt).strip()[:500]))
        except urllib.error.URLError as e:
            raise ApiError("接続できませんでした: %s" % cfg.redact(str(e.reason)))
        body = _read_bounded(resp, cfg)
        if not body:
            return {}
        try:
            return json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ApiError("応答を JSON として解釈できませんでした。")
    raise ApiError("リダイレクトが多すぎます。")


# ---------------------------------------------------------------- データ整形


def adf_to_text(node):
    """Cloud の ADF（Atlassian Document Format）から平文を取り出す。"""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(adf_to_text(n) for n in node)
    if isinstance(node, dict):
        if node.get("type") == "text":
            return node.get("text", "")
        if node.get("type") in ("hardBreak",):
            return "\n"
        inner = adf_to_text(node.get("content", []))
        if node.get("type") in ("paragraph", "heading", "listItem", "blockquote", "codeBlock"):
            return inner + "\n"
        return inner
    return ""


def body_to_text(body):
    """コメント本文（DC は文字列、Cloud は ADF）を平文にする。"""
    if body is None:
        return ""
    if isinstance(body, str):
        return body
    return adf_to_text(body).strip()


def _person(fields, name):
    p = fields.get(name)
    if not p:
        return "（未割り当て）" if name == "assignee" else ""
    return p.get("displayName") or p.get("name") or p.get("accountId") or ""


def normalise_issue(raw):
    f = raw.get("fields", {}) or {}
    status = f.get("status") or {}
    category = (status.get("statusCategory") or {}).get("name", "")
    itype = f.get("issuetype") or {}
    priority = f.get("priority") or {}
    return {
        "key": raw.get("key", ""),
        "summary": f.get("summary", ""),
        "type": itype.get("name", ""),
        "status": status.get("name", ""),
        "statusCategory": category,
        "assignee": _person(f, "assignee"),
        "reporter": _person(f, "reporter"),
        "priority": priority.get("name", ""),
        "duedate": f.get("duedate") or "",
        "created": (f.get("created") or "")[:10],
        "updated": (f.get("updated") or "")[:10],
        "resolved": (f.get("resolutiondate") or "")[:10],
        "labels": f.get("labels") or [],
    }


def search_all(cfg, jql, fields=ISSUE_FIELDS, limit=None):
    """JQL 検索をページングしながら集める。DC と Cloud の方式差を吸収する。"""
    out = []
    if cfg.edition == "dc":
        start = 0
        while True:
            page = api_get(cfg, "/search", {"jql": jql, "startAt": start, "maxResults": PAGE_SIZE, "fields": fields})
            issues = page.get("issues", [])
            out.extend(normalise_issue(i) for i in issues)
            start += len(issues)
            if not issues or start >= page.get("total", 0):
                break
            if limit and len(out) >= limit:
                break
    else:
        token = None
        while True:
            params = {"jql": jql, "maxResults": PAGE_SIZE, "fields": fields}
            if token:
                params["nextPageToken"] = token
            page = api_get(cfg, "/search/jql", params)
            issues = page.get("issues", [])
            out.extend(normalise_issue(i) for i in issues)
            if page.get("isLast", True) or not issues:
                break
            token = page.get("nextPageToken")
            if not token:
                break
            if limit and len(out) >= limit:
                break
    return out[:limit] if limit else out


def count_jql(cfg, jql):
    """件数だけを数える。打ち切り時は (COUNT_CAP, True) を返す。"""
    if cfg.edition == "dc":
        page = api_get(cfg, "/search", {"jql": jql, "startAt": 0, "maxResults": 0, "fields": "key"})
        return page.get("total", 0), False
    total = 0
    token = None
    while total < COUNT_CAP:
        params = {"jql": jql, "maxResults": PAGE_SIZE, "fields": "key"}
        if token:
            params["nextPageToken"] = token
        page = api_get(cfg, "/search/jql", params)
        total += len(page.get("issues", []))
        if page.get("isLast", True):
            return total, False
        token = page.get("nextPageToken")
        if not token:
            return total, False
    return COUNT_CAP, True


# ---------------------------------------------------------------- 表示


def print_issues(issues, as_json):
    if as_json:
        print(json.dumps(issues, ensure_ascii=False, indent=2))
        return
    if not issues:
        print("（該当なし）")
        return
    for i in issues:
        due = i["duedate"] or "—"
        print("%-14s %-10s 期日:%-10s 担当:%-12s %s" % (i["key"], i["status"], due, i["assignee"], i["summary"]))


def _scope(args, mine_default=True):
    """overdue / stale の対象範囲を JQL 断片にする。"""
    if getattr(args, "project", None):
        return 'project = "%s"' % args.project.replace('"', '\\"')
    if getattr(args, "all", False):
        return ""
    return "assignee = currentUser()"


def _join(*parts):
    return " AND ".join(p for p in parts if p)


_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*-\d+$")


def resolve_keys(args):
    """対象キーの限定を解決する。--keys ＞ JIRA_ISSUE_KEYS ＞ 限定なし。

    形式が不正なキーが混ざっていたら ApiError で止める（検証を通った
    キーだけを JQL に入れるため、JQL への混入は起きない）。
    """
    raw = getattr(args, "keys", None) or os.environ.get("JIRA_ISSUE_KEYS", "")
    if not raw or not raw.strip():
        return None
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    bad = [k for k in keys if not _KEY_RE.match(k)]
    if bad:
        raise ApiError("課題キーの形式が不正です: %s" % ", ".join(bad))
    return keys


def key_clause(keys):
    if not keys:
        return ""
    return "key in (%s)" % ", ".join(keys)


# ---------------------------------------------------------------- フィールド

CUSTOM_TYPE_LABELS = {
    "com.atlassian.jira.plugin.system.customfieldtypes:textfield": "テキスト（単一行）",
    "com.atlassian.jira.plugin.system.customfieldtypes:textarea": "テキスト（複数行）",
    "com.atlassian.jira.plugin.system.customfieldtypes:float": "数値",
    "com.atlassian.jira.plugin.system.customfieldtypes:datepicker": "日付ピッカー",
    "com.atlassian.jira.plugin.system.customfieldtypes:datetime": "日時ピッカー",
    "com.atlassian.jira.plugin.system.customfieldtypes:select": "単一選択リスト",
    "com.atlassian.jira.plugin.system.customfieldtypes:multiselect": "複数選択リスト",
    "com.atlassian.jira.plugin.system.customfieldtypes:radiobuttons": "ラジオボタン",
    "com.atlassian.jira.plugin.system.customfieldtypes:multicheckboxes": "チェックボックス（複数）",
    "com.atlassian.jira.plugin.system.customfieldtypes:cascadingselect": "カスケード選択",
    "com.atlassian.jira.plugin.system.customfieldtypes:userpicker": "ユーザー（単一）",
    "com.atlassian.jira.plugin.system.customfieldtypes:multiuserpicker": "ユーザー（複数）",
    "com.atlassian.jira.plugin.system.customfieldtypes:grouppicker": "グループ（単一）",
    "com.atlassian.jira.plugin.system.customfieldtypes:multigrouppicker": "グループ（複数）",
    "com.atlassian.jira.plugin.system.customfieldtypes:labels": "ラベル",
    "com.atlassian.jira.plugin.system.customfieldtypes:url": "URL",
    "com.atlassian.jira.plugin.system.customfieldtypes:version": "バージョン（単一）",
    "com.atlassian.jira.plugin.system.customfieldtypes:multiversion": "バージョン（複数）",
    "com.atlassian.jira.plugin.system.customfieldtypes:project": "プロジェクト",
    "com.atlassian.jira.plugin.system.customfieldtypes:readonlyfield": "読み取り専用テキスト",
}

_SCHEMA_TYPE_LABELS = {
    "string": "文字列",
    "number": "数値",
    "date": "日付",
    "datetime": "日時",
    "array": "配列",
    "option": "選択肢",
    "user": "ユーザー",
}


def _type_label(schema):
    ctype = schema.get("custom") or ""
    if ctype in CUSTOM_TYPE_LABELS:
        return CUSTOM_TYPE_LABELS[ctype]
    if ctype:
        # 未知のカスタム種別はプラグインキーの末尾で示す
        return ctype.rsplit(":", 1)[-1]
    t = schema.get("type", "")
    base = _SCHEMA_TYPE_LABELS.get(t, t)
    if t == "array" and schema.get("items"):
        base += "（要素: %s）" % schema["items"]
    return base


def normalise_field(raw):
    schema = raw.get("schema") or {}
    return {
        "id": raw.get("id", ""),
        "name": raw.get("name", ""),
        "custom": bool(raw.get("custom")),
        "type": schema.get("type", ""),
        "items": schema.get("items", ""),
        "customType": schema.get("custom", ""),
        "typeLabel": _type_label(schema),
        "customId": schema.get("customId"),
        "clauseNames": raw.get("clauseNames") or [],
        "searchable": bool(raw.get("searchable")),
        "orderable": bool(raw.get("orderable")),
    }


def cmd_fields(cfg, args):
    raw = api_get(cfg, "/field")
    fields = [normalise_field(f) for f in raw if isinstance(f, dict)]
    if not args.all:
        fields = [f for f in fields if f["custom"]]
    fields.sort(key=lambda f: f["name"])
    if args.json:
        print(json.dumps(fields, ensure_ascii=False, indent=2))
        return 0
    if not fields:
        print("（該当なし）")
        return 0
    for f in fields:
        jql = ", ".join(f["clauseNames"])
        print("%-18s %-24s %-16s JQL: %s" % (f["id"], f["name"], f["typeLabel"], jql))
    return 0


# ---------------------------------------------------------------- コマンド


def cmd_check(cfg, args):
    me = api_get(cfg, "/myself")
    info = api_get(cfg, "/serverInfo")
    print("接続先: %s" % cfg.base_url)
    print(
        "版: %s（API %s）"
        % ("Cloud" if cfg.edition == "cloud" else "Data Center", "v3" if cfg.edition == "cloud" else "v2")
    )
    print("サーバー版数: %s" % (info.get("version", "不明")))
    print("ログイン: %s" % (me.get("displayName") or me.get("name") or me.get("accountId", "")))
    return 0


def cmd_my_issues(cfg, args):
    parts = ["assignee = currentUser()", key_clause(resolve_keys(args))]
    if not args.all:
        parts.append("resolution = Unresolved")
    jql = _join(*parts) + " ORDER BY duedate ASC, updated DESC"
    print_issues(search_all(cfg, jql, limit=args.limit), args.json)
    return 0


def cmd_search(cfg, args):
    jql = args.jql
    kc = key_clause(resolve_keys(args))
    if kc:
        # 利用者の JQL を括弧で包んでからキー条件を AND する。
        # ORDER BY があれば、その手前で包む。
        m = re.search(r"\border\s+by\b", jql, re.I)
        if m:
            jql = "(%s) AND %s %s" % (jql[: m.start()].strip(), kc, jql[m.start() :].strip())
        else:
            jql = "(%s) AND %s" % (jql, kc)
    print_issues(search_all(cfg, jql, limit=args.limit), args.json)
    return 0


def cmd_issue(cfg, args):
    raw = api_get(
        cfg, "/issue/" + urllib.parse.quote(args.key, safe=""), {"fields": ISSUE_FIELDS + ",comment,description"}
    )
    issue = normalise_issue(raw)
    f = raw.get("fields", {}) or {}
    if args.json:
        comments = (f.get("comment") or {}).get("comments", [])
        issue["comments"] = (
            [
                {
                    "author": (c.get("author") or {}).get("displayName", ""),
                    "created": (c.get("created") or "")[:16].replace("T", " "),
                    "body": body_to_text(c.get("body")),
                }
                for c in comments[-args.comments :]
            ]
            if args.comments > 0
            else []
        )
        print(json.dumps(issue, ensure_ascii=False, indent=2))
        return 0
    print("%s  %s" % (issue["key"], issue["summary"]))
    print(
        "種別: %s / ステータス: %s（%s）/ 優先度: %s"
        % (issue["type"], issue["status"], issue["statusCategory"], issue["priority"])
    )
    print("担当: %s / 報告者: %s" % (issue["assignee"], issue["reporter"]))
    print(
        "期日: %s / 作成: %s / 更新: %s / 完了: %s"
        % (issue["duedate"] or "—", issue["created"], issue["updated"], issue["resolved"] or "—")
    )
    desc = body_to_text(f.get("description"))
    if desc:
        print("\n説明:\n%s" % desc[:1000])
    comments = (f.get("comment") or {}).get("comments", [])
    if comments and args.comments > 0:
        print("\nコメント（直近 %d 件 / 全 %d 件）:" % (min(args.comments, len(comments)), len(comments)))
        for c in comments[-args.comments :]:
            author = (c.get("author") or {}).get("displayName", "")
            when = (c.get("created") or "")[:16].replace("T", " ")
            print("\n[%s] %s\n%s" % (when, author, body_to_text(c.get("body"))[:800]))
    return 0


def cmd_project(cfg, args):
    key = args.key
    proj = api_get(cfg, "/project/" + urllib.parse.quote(key, safe=""))
    print("%s  %s" % (proj.get("key", key), proj.get("name", "")))
    base = _join('project = "%s"' % key.replace('"', '\\"'), key_clause(resolve_keys(args)))
    for label, cat in (("未着手", "To Do"), ("進行中", "In Progress"), ("完了", "Done")):
        n, capped = count_jql(cfg, _join(base, 'statusCategory = "%s"' % cat))
        print("%s: %s%s 件" % (label, n, " 以上" if capped else ""))
    today = date.today().isoformat()
    overdue = search_all(
        cfg, _join(base, "resolution = Unresolved", 'duedate < "%s"' % today) + " ORDER BY duedate ASC", limit=20
    )
    n_over, capped = count_jql(cfg, _join(base, "resolution = Unresolved", 'duedate < "%s"' % today))
    print("期限超過（未完了）: %s%s 件" % (n_over, " 以上" if capped else ""))
    print_issues(overdue, False)
    return 0


def cmd_overdue(cfg, args):
    today = date.today().isoformat()
    jql = (
        _join(_scope(args), key_clause(resolve_keys(args)), "resolution = Unresolved", 'duedate < "%s"' % today)
        + " ORDER BY duedate ASC"
    )
    print_issues(search_all(cfg, jql, limit=args.limit), args.json)
    return 0


def cmd_stale(cfg, args):
    jql = (
        _join(_scope(args), key_clause(resolve_keys(args)), "resolution = Unresolved", "updated < -%dd" % args.days)
        + " ORDER BY updated ASC"
    )
    print_issues(search_all(cfg, jql, limit=args.limit), args.json)
    return 0


def _section(title, issues, as_json):
    if as_json:
        return {title: issues}
    print("\n■ %s（%d 件）" % (title, len(issues)))
    print_issues(issues, False)
    return None


def cmd_standup(cfg, args):
    today = date.today().isoformat()
    me = "assignee = currentUser()"
    kc = key_clause(resolve_keys(args))
    result = {}
    sections = [
        ("完了（直近24時間）", _join(me, kc, "resolved >= -1d")),
        ("進行中", _join(me, kc, 'statusCategory = "In Progress"', "resolution = Unresolved")),
        ("期限超過・今日が期限", _join(me, kc, "resolution = Unresolved", 'duedate <= "%s"' % today)),
    ]
    for title, jql in sections:
        issues = search_all(cfg, jql + " ORDER BY duedate ASC", limit=args.limit)
        r = _section(title, issues, args.json)
        if r:
            result.update(r)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_weekly(cfg, args):
    if args.project:
        base = 'project = "%s"' % args.project.replace('"', '\\"')
        who = base
    else:
        who = "assignee = currentUser()"
    today = date.today().isoformat()
    kc = key_clause(resolve_keys(args))
    result = {}
    sections = [
        ("完了（直近7日）", _join(who, kc, "resolved >= -7d")),
        ("新規（直近7日）", _join(who, kc, "created >= -7d")),
        ("期限超過（未完了）", _join(who, kc, "resolution = Unresolved", 'duedate < "%s"' % today)),
    ]
    for title, jql in sections:
        issues = search_all(cfg, jql + " ORDER BY duedate ASC", limit=args.limit)
        r = _section(title, issues, args.json)
        if r:
            result.update(r)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


# ---------------------------------------------------------------- 入口


def _force_utf8_stdio():
    """標準出力・標準エラーを UTF-8 に固定する。

    Windows では Python の標準出力がコンソールのコードページ（cp932）に
    なり、日本語が文字化けしたり、cp932 に無い文字で落ちたりする。
    出力は常に UTF-8 とし、表示側（ターミナル）の都合と切り離す。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv=None):
    _force_utf8_stdio()
    parser = argparse.ArgumentParser(description="Jira 課題確認（読み取り専用）")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="接続確認")

    keys_help = "対象を課題キーで限定（カンマ区切り。環境変数 JIRA_ISSUE_KEYS でも指定可）"

    p = sub.add_parser("my-issues", help="自分の担当課題")
    p.add_argument("--all", action="store_true", help="完了も含む")
    p.add_argument("--keys", help=keys_help)
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("search", help="JQL 自由検索")
    p.add_argument("--jql", required=True)
    p.add_argument("--keys", help=keys_help)
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("issue", help="課題の詳細と直近コメント")
    p.add_argument("key")
    p.add_argument("--comments", type=int, default=5)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("project", help="プロジェクトの概況")
    p.add_argument("key")
    p.add_argument("--keys", help=keys_help)

    p = sub.add_parser("overdue", help="期限超過の未完了課題")
    p.add_argument("--project")
    p.add_argument("--all", action="store_true", help="見える範囲すべて（既定は自分の担当）")
    p.add_argument("--keys", help=keys_help)
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("stale", help="長く更新のない未完了課題")
    p.add_argument("--days", type=int, default=14)
    p.add_argument("--project")
    p.add_argument("--all", action="store_true")
    p.add_argument("--keys", help=keys_help)
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("standup", help="朝会の材料（自分の分）")
    p.add_argument("--keys", help=keys_help)
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("weekly", help="週次報告の材料")
    p.add_argument("--project", help="プロジェクト全体で集める（既定は自分の担当）")
    p.add_argument("--keys", help=keys_help)
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("fields", help="フィールド定義の一覧（既定はカスタムのみ）")
    p.add_argument("--all", action="store_true", help="システムフィールドも含む")
    p.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    try:
        cfg = Config()
    except ConfigError as e:
        print("設定エラー: %s" % e, file=sys.stderr)
        return 2
    handlers = {
        "check": cmd_check,
        "my-issues": cmd_my_issues,
        "search": cmd_search,
        "issue": cmd_issue,
        "project": cmd_project,
        "overdue": cmd_overdue,
        "stale": cmd_stale,
        "standup": cmd_standup,
        "weekly": cmd_weekly,
        "fields": cmd_fields,
    }
    try:
        return handlers[args.command](cfg, args)
    except ApiError as e:
        print("API エラー: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
