import base64
import json
import os
import re
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

DC_TOKEN = "TESTPAT-SECRET-12345"
CLOUD_EMAIL = "test@example.com"
CLOUD_TOKEN = "TESTAPITOKEN-SECRET-67890"
CLOUD_BASIC = "Basic " + base64.b64encode(("%s:%s" % (CLOUD_EMAIL, CLOUD_TOKEN)).encode()).decode()
SECRETS = (DC_TOKEN, CLOUD_TOKEN, CLOUD_BASIC)

SKILL_DIR = os.environ.get(
    "JIRA_SKILL_DIR",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)
HELPER = os.path.join(SKILL_DIR, "scripts", "jira.py")


def make_issue(key, summary, status="進行中", category="In Progress", duedate="2026-12-01"):
    return {
        "key": key,
        "fields": {
            "summary": summary,
            "status": {"name": status, "statusCategory": {"name": category}},
            "assignee": {"displayName": "Test User", "name": "test-user"},
            "reporter": {"displayName": "Reporter", "name": "reporter"},
            "priority": {"name": "High"},
            "duedate": duedate,
            "created": "2026-11-01T09:00:00.000+0900",
            "updated": "2026-11-20T09:00:00.000+0900",
            "issuetype": {"name": "タスク"},
            "resolutiondate": None,
            "labels": [],
            "components": [],
        },
    }


DC_ISSUES = [
    make_issue("ABC-1", "最初の課題", duedate="2026-11-10"),
    make_issue("ABC-2", "二番目の課題", duedate="2026-11-20"),
    make_issue("ABC-3", "三番目の課題", duedate="2026-12-01"),
]

CLOUD_ISSUES = [
    make_issue("XYZ-1", "Cloud 一件目"),
    make_issue("XYZ-2", "Cloud 二件目"),
    make_issue("XYZ-3", "Cloud 三件目"),
]

FIELDS = [
    {
        "id": "summary",
        "key": "summary",
        "name": "Summary",
        "custom": False,
        "orderable": True,
        "navigable": True,
        "searchable": True,
        "clauseNames": ["summary"],
        "schema": {"type": "string", "system": "summary"},
    },
    {
        "id": "customfield_10001",
        "key": "customfield_10001",
        "name": "受入基準",
        "custom": True,
        "orderable": True,
        "navigable": True,
        "searchable": True,
        "clauseNames": ["cf[10001]", "受入基準"],
        "schema": {
            "type": "string",
            "custom": "com.atlassian.jira.plugin.system.customfieldtypes:textarea",
            "customId": 10001,
        },
    },
    {
        "id": "customfield_10002",
        "key": "customfield_10002",
        "name": "見積り日",
        "custom": True,
        "orderable": True,
        "navigable": True,
        "searchable": True,
        "clauseNames": ["cf[10002]", "見積り日"],
        "schema": {
            "type": "date",
            "custom": "com.atlassian.jira.plugin.system.customfieldtypes:datepicker",
            "customId": 10002,
        },
    },
    {
        "id": "customfield_10003",
        "key": "customfield_10003",
        "name": "対象OS",
        "custom": True,
        "orderable": True,
        "navigable": True,
        "searchable": True,
        "clauseNames": ["cf[10003]", "対象OS"],
        "schema": {
            "type": "array",
            "items": "option",
            "custom": "com.atlassian.jira.plugin.system.customfieldtypes:multiselect",
            "customId": 10003,
        },
    },
    {
        "id": "customfield_10004",
        "key": "customfield_10004",
        "name": "外部連携ID",
        "custom": True,
        "orderable": False,
        "navigable": True,
        "searchable": True,
        "clauseNames": ["cf[10004]", "外部連携ID"],
        "schema": {"type": "string", "custom": "com.example.plugin:external-id", "customId": 10004},
    },
]


ADF_BODY = {
    "type": "doc",
    "version": 1,
    "content": [
        {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "進捗は順調です。"},
                {"type": "hardBreak"},
                {"type": "text", "text": "次の確認は来週です。"},
            ],
        },
        {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "以上です。"},
            ],
        },
    ],
}
ADF_TEXT = "進捗は順調です。\n次の確認は来週です。\n以上です。"


def filter_by_keys(issues, jql):
    """Fixture-side filtering: honour the helper's `key in (...)`
    clause the way a real Jira would, so tests prove end-to-end
    narrowing instead of only checking the JQL text."""
    m = re.search(r"key in \(([^)]*)\)", jql)
    if not m:
        return issues
    keys = {k.strip() for k in m.group(1).split(",")}
    return [i for i in issues if i["key"] in keys]


def dc_issue_detail():
    raw = make_issue("ABC-1", "最初の課題", duedate="2026-11-10")
    raw["fields"]["description"] = "DC の平文の説明です。"
    raw["fields"]["comment"] = {
        "total": 2,
        "comments": [
            {"author": {"displayName": "Reporter"}, "created": "2026-11-18T10:00:00.000+0900", "body": "古いコメント"},
            {
                "author": {"displayName": "Test User"},
                "created": "2026-11-20T11:00:00.000+0900",
                "body": "直近のコメントです。",
            },
        ],
    }
    return raw


def cloud_issue_detail():
    raw = make_issue("XYZ-1", "Cloud 一件目")
    raw["fields"]["description"] = ADF_BODY
    raw["fields"]["comment"] = {
        "total": 1,
        "comments": [
            {"author": {"displayName": "Test User"}, "created": "2026-11-20T11:00:00.000+0900", "body": ADF_BODY},
        ],
    }
    return raw


class DcHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send_json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.headers.get("Authorization") != "Bearer " + DC_TOKEN:
            self.send_json({"error": "unauthorized"}, 401)
            return
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        if path == "/rest/api/2/myself":
            self.send_json({"name": "test-user", "displayName": "Test User"})
        elif path == "/rest/api/2/field":
            self.send_json(FIELDS)
        elif path == "/rest/api/2/serverInfo":
            self.send_json({"version": "9.12.0", "deploymentType": "Server"})
        elif path == "/rest/api/2/search":
            jql = qs.get("jql", [""])[0]
            pool = filter_by_keys(DC_ISSUES, jql)
            max_results = int(qs.get("maxResults", ["100"])[0])
            if max_results == 0:
                # count query (project command): deterministic per
                # category; with a key filter, the filtered pool size
                if "key in (" in jql:
                    total = len(pool)
                elif 'statusCategory = "To Do"' in jql:
                    total = 2
                elif 'statusCategory = "In Progress"' in jql:
                    total = 1
                elif 'statusCategory = "Done"' in jql:
                    total = 3
                elif "duedate <" in jql:
                    total = 1
                else:
                    total = 6
                self.send_json({"total": total, "issues": []})
                return
            # Simulate a server-side page cap of 2, regardless of the
            # requested maxResults=100: the helper must advance startAt
            # by the number actually returned until it reaches total.
            start = int(qs.get("startAt", ["0"])[0])
            page = pool[start : start + 2]
            self.send_json({"total": len(pool), "startAt": start, "maxResults": 2, "issues": page})
        elif path == "/rest/api/2/issue/ABC-1":
            self.send_json(dc_issue_detail())
        elif path == "/rest/api/2/issue/TRUNC-1":
            # Declares 100 bytes but delivers 11 and closes: the helper
            # must reject the short body instead of parsing it.
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "100")
            self.end_headers()
            self.wfile.write(b'{"key": "x"')
            self.wfile.flush()
            self.close_connection = True
        elif path == "/rest/api/2/issue/BIG-1":
            # Over the 32 MB body cap: the helper must stop reading and
            # fail instead of loading the whole body.
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            total = 33 * 1024 * 1024
            self.send_header("Content-Length", str(total))
            self.end_headers()
            chunk = b"x" * 65536
            try:
                for _ in range(total // len(chunk)):
                    self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass
            self.close_connection = True
        elif path == "/rest/api/2/issue/LEAK-1":
            # Error body echoing the secret: the helper's excerpt must
            # redact it before printing.
            body = ("failed for token " + DC_TOKEN).encode()
            self.send_response(500)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/rest/api/2/project/ABC":
            self.send_json({"key": "ABC", "name": "Sample Project"})
        else:
            self.send_json({"error": "not found: " + path}, 404)


class CloudHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send_json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.headers.get("Authorization") != CLOUD_BASIC:
            self.send_json({"error": "unauthorized"}, 401)
            return
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        if path == "/rest/api/3/myself":
            self.send_json({"accountId": "abc123", "displayName": "Test User"})
        elif path == "/rest/api/3/field":
            self.send_json(FIELDS)
        elif path == "/rest/api/3/serverInfo":
            self.send_json({"version": "1001.0.0", "deploymentType": "Cloud"})
        elif path == "/rest/api/3/search/jql":
            # nextPageToken paging over the (possibly key-filtered)
            # pool: pages of 2, the token is the next start index.
            jql = qs.get("jql", [""])[0]
            pool = filter_by_keys(CLOUD_ISSUES, jql)
            token = qs.get("nextPageToken", [None])[0]
            start = int(token) if token else 0
            page = pool[start : start + 2]
            is_last = start + 2 >= len(pool)
            resp = {"issues": page, "isLast": is_last}
            if not is_last:
                resp["nextPageToken"] = str(start + 2)
            self.send_json(resp)
        elif path == "/rest/api/3/issue/XYZ-1":
            self.send_json(cloud_issue_detail())
        else:
            self.send_json({"error": "not found: " + path}, 404)


def run_helper(env, *argv):
    proc = subprocess.run(
        [sys.executable, HELPER, *argv],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    for secret in SECRETS:
        assert secret not in proc.stdout, "SECRET LEAKED TO STDOUT"
        assert secret not in proc.stderr, "SECRET LEAKED TO STDERR"
    return proc


def clean_env():
    env = dict(os.environ)
    for key in ("JIRA_BASE_URL", "JIRA_PAT", "JIRA_EMAIL", "JIRA_API_TOKEN", "JIRA_EDITION", "JIRA_ISSUE_KEYS"):
        env.pop(key, None)
    return env


def start(handler):
    server = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def redirect_tests(dc_port):
    """Redirect rules (Jira helper): same host keeps the token and is
    followed; a different host aborts before any request is sent there,
    so the other server must see no request at all."""
    b_hits = []

    class BHandler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            b_hits.append((self.path, self.headers.get("Authorization")))
            body = json.dumps({"version": "9.12.0"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server_b, port_b = start(BHandler)
    seen = {}

    class AHandler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def redirect(self, location):
            self.send_response(302)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def send_json(self, obj, status=200):
            body = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            parsed = urlparse(self.path)
            port_a = self.server.server_address[1]
            if parsed.path == "/rest/api/2/myself":
                mode = getattr(self.server, "mode", "same")
                if mode == "same":
                    self.redirect(f"http://127.0.0.1:{port_a}/rest/api/2/myself-real")
                elif mode == "scheme":
                    self.redirect("ftp://127.0.0.1:9/rest/api/2/myself")
                else:
                    self.redirect(f"http://127.0.0.1:{port_b}/rest/api/2/myself")
            elif parsed.path == "/rest/api/2/myself-real":
                if self.headers.get("Authorization") != "Bearer " + DC_TOKEN:
                    self.send_json({"error": "unauthorized"}, 401)
                    return
                seen["auth"] = self.headers.get("Authorization")
                self.send_json({"name": "test-user", "displayName": "Test User"})
            elif parsed.path == "/rest/api/2/serverInfo":
                self.send_json({"version": "9.12.0"})
            else:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()

    server_a, port_a = start(AHandler)

    env = clean_env()
    env["JIRA_BASE_URL"] = f"http://127.0.0.1:{port_a}"
    env["JIRA_PAT"] = DC_TOKEN

    # same host: followed, token kept
    server_a.mode = "same"
    p = run_helper(env, "check")
    assert p.returncode == 0, p.stderr
    assert seen.get("auth") == "Bearer " + DC_TOKEN, seen
    assert "Test User" in p.stdout, p.stdout
    print("redirect same-host OK")

    # different host: aborts, and B is never contacted
    server_a.mode = "cross"
    p = run_helper(env, "check")
    assert p.returncode == 1, (p.returncode, p.stdout, p.stderr)
    assert b_hits == [], b_hits
    print("redirect cross-host drop OK")

    # non-http(s) scheme: refused outright
    server_a.mode = "scheme"
    p = run_helper(env, "check")
    assert p.returncode == 1, (p.returncode, p.stdout, p.stderr)
    assert "http(s) 以外" in p.stderr, p.stderr
    print("redirect non-http scheme refusal OK")

    server_a.shutdown()
    server_b.shutdown()


def main():
    dc_server, dc_port = start(DcHandler)
    cloud_server, cloud_port = start(CloudHandler)

    # ---- DC (v2), edition auto-detected from the PAT
    env = clean_env()
    env["JIRA_BASE_URL"] = f"http://127.0.0.1:{dc_port}"
    env["JIRA_PAT"] = DC_TOKEN

    p = run_helper(env, "check")
    assert p.returncode == 0, p.stderr
    assert "Data Center" in p.stdout and "9.12.0" in p.stdout, p.stdout
    assert "Test User" in p.stdout, p.stdout
    print("dc check OK")

    # DC paging: the fixture caps pages at 2, so collecting all 3
    # issues proves startAt paging works.
    p = run_helper(env, "my-issues", "--json")
    assert p.returncode == 0, p.stderr
    issues = json.loads(p.stdout)
    assert [i["key"] for i in issues] == ["ABC-1", "ABC-2", "ABC-3"], issues
    assert issues[0]["duedate"] == "2026-11-10", issues[0]
    assert issues[0]["status"] == "進行中", issues[0]
    print("dc paging (startAt) OK")

    # free JQL search goes through the same paging
    p = run_helper(env, "search", "--jql", "project = ABC", "--json")
    assert p.returncode == 0, p.stderr
    assert len(json.loads(p.stdout)) == 3
    print("dc search OK")

    # --keys narrows the result server-side (fixture honours key in (...))
    p = run_helper(env, "my-issues", "--keys", "ABC-2,ABC-3", "--json")
    assert p.returncode == 0, p.stderr
    assert [i["key"] for i in json.loads(p.stdout)] == ["ABC-2", "ABC-3"]
    print("dc --keys OK")

    # JIRA_ISSUE_KEYS works as the default; --keys overrides it
    env_keys = dict(env)
    env_keys["JIRA_ISSUE_KEYS"] = "ABC-1"
    p = run_helper(env_keys, "my-issues", "--json")
    assert p.returncode == 0, p.stderr
    assert [i["key"] for i in json.loads(p.stdout)] == ["ABC-1"]
    p = run_helper(env_keys, "my-issues", "--keys", "ABC-3", "--json")
    assert p.returncode == 0, p.stderr
    assert [i["key"] for i in json.loads(p.stdout)] == ["ABC-3"]
    print("dc JIRA_ISSUE_KEYS + override OK")

    # search: the user JQL is parenthesised before AND-ing the key
    # clause, and an ORDER BY in it stays at the end
    p = run_helper(env, "search", "--jql", "project = ABC ORDER BY duedate ASC", "--keys", "ABC-2", "--json")
    assert p.returncode == 0, p.stderr
    assert [i["key"] for i in json.loads(p.stdout)] == ["ABC-2"]
    print("dc search --keys with ORDER BY OK")

    # malformed / hostile keys are rejected before any JQL is built:
    # no number part, and a JQL-injection attempt
    for bad in ("ABC", "ABC-1) OR (1=1", "ABC-1;DELETE"):
        p = run_helper(env, "my-issues", "--keys", bad, "--json")
        assert p.returncode == 1, (bad, p.returncode, p.stdout, p.stderr)
        assert "形式が不正" in p.stderr, (bad, p.stderr)
    print("dc malformed key rejection OK")

    # issue detail with plain-text comments (DC)
    p = run_helper(env, "issue", "ABC-1", "--json")
    assert p.returncode == 0, p.stderr
    detail = json.loads(p.stdout)
    assert detail["comments"][-1]["body"] == "直近のコメントです。", detail
    p = run_helper(env, "issue", "ABC-1")
    assert p.returncode == 0, p.stderr
    assert "DC の平文の説明です。" in p.stdout, p.stdout
    assert "直近のコメントです。" in p.stdout, p.stdout
    print("dc issue + comments OK")

    # project overview: counts come from total with maxResults=0
    p = run_helper(env, "project", "ABC")
    assert p.returncode == 0, p.stderr
    assert "Sample Project" in p.stdout, p.stdout
    assert "未着手: 2 件" in p.stdout, p.stdout
    assert "進行中: 1 件" in p.stdout, p.stdout
    assert "完了: 3 件" in p.stdout, p.stdout
    assert "期限超過（未完了）: 1 件" in p.stdout, p.stdout
    print("dc project OK")

    # overdue / stale / standup / weekly all run on the fixture
    for argv in (
        ("overdue", "--json"),
        ("stale", "--days", "14", "--json"),
        ("standup", "--json"),
        ("weekly", "--json"),
    ):
        p = run_helper(env, *argv)
        assert p.returncode == 0, (argv, p.stderr)
        json.loads(p.stdout)
    print("dc overdue/stale/standup/weekly OK")

    # fields: custom only by default, type labels from the schema,
    # unknown custom types fall back to the plugin-key suffix
    p = run_helper(env, "fields", "--json")
    assert p.returncode == 0, p.stderr
    fields = json.loads(p.stdout)
    # sorted by name (Unicode code point order of the fixture names)
    assert [f["id"] for f in fields] == [
        "customfield_10001",
        "customfield_10004",
        "customfield_10003",
        "customfield_10002",
    ], fields
    by_id = {f["id"]: f for f in fields}
    assert by_id["customfield_10001"]["typeLabel"] == "テキスト（複数行）"
    assert by_id["customfield_10001"]["customId"] == 10001
    assert by_id["customfield_10002"]["typeLabel"] == "日付ピッカー"
    assert by_id["customfield_10003"]["typeLabel"] == "複数選択リスト"
    assert by_id["customfield_10003"]["items"] == "option"
    assert by_id["customfield_10004"]["typeLabel"] == "external-id"
    p = run_helper(env, "fields", "--all", "--json")
    assert p.returncode == 0, p.stderr
    assert len(json.loads(p.stdout)) == 5
    p = run_helper(env, "fields")
    assert p.returncode == 0, p.stderr
    assert "customfield_10001" in p.stdout and "cf[10001]" in p.stdout, p.stdout
    print("dc fields OK")

    # stdout stays UTF-8 even when the ambient encoding is cp932
    # (Windows console code page): raw bytes must decode as UTF-8
    env_cp = dict(env)
    env_cp["PYTHONIOENCODING"] = "cp932"
    proc = subprocess.run([sys.executable, HELPER, "fields"], capture_output=True, env=env_cp, timeout=60)
    assert proc.returncode == 0, proc.stderr
    text = proc.stdout.decode("utf-8")  # raises if the bytes came out as cp932
    assert "テキスト（複数行）" in text, text
    print("utf-8 stdio under cp932 ambient OK")

    # wrong token -> 401 surfaces as an API error, without leaking it
    env_bad = dict(env)
    env_bad["JIRA_PAT"] = "WRONGTOKEN"
    p = subprocess.run([sys.executable, HELPER, "check"], capture_output=True, text=True, env=env_bad, timeout=60)
    assert p.returncode == 1, (p.returncode, p.stdout, p.stderr)
    assert "HTTP 401" in p.stderr, p.stderr
    print("dc auth failure OK")

    # truncated body: declared 100 bytes, delivered 11 -> ApiError
    p = run_helper(env, "issue", "TRUNC-1")
    assert p.returncode == 1, (p.returncode, p.stdout, p.stderr)
    assert "切断" in p.stderr, p.stderr
    print("truncation OK")

    # oversized body: over the 32 MB cap -> ApiError
    p = run_helper(env, "issue", "BIG-1")
    assert p.returncode == 1, (p.returncode, p.stdout, p.stderr)
    assert "上限" in p.stderr, p.stderr
    print("body cap OK")

    # error excerpt redaction: the server echoes the token in a 500
    p = run_helper(env, "issue", "LEAK-1")
    assert p.returncode == 1, (p.returncode, p.stdout, p.stderr)
    assert "***" in p.stderr, p.stderr
    print("error redaction OK")

    # ---- Cloud (v3). The *.atlassian.net host rule cannot fire on
    # localhost, so the edition is pinned via JIRA_EDITION here; the
    # email+token auto-detection is proven separately below.
    env_c = clean_env()
    env_c["JIRA_BASE_URL"] = f"http://127.0.0.1:{cloud_port}"
    env_c["JIRA_EMAIL"] = CLOUD_EMAIL
    env_c["JIRA_API_TOKEN"] = CLOUD_TOKEN
    env_c["JIRA_EDITION"] = "cloud"

    p = run_helper(env_c, "check")
    assert p.returncode == 0, p.stderr
    assert "Cloud" in p.stdout and "Test User" in p.stdout, p.stdout
    print("cloud check OK (Basic auth header verified by fixture)")

    # Cloud paging: nextPageToken across two pages collects all 3
    p = run_helper(env_c, "my-issues", "--json")
    assert p.returncode == 0, p.stderr
    issues = json.loads(p.stdout)
    assert [i["key"] for i in issues] == ["XYZ-1", "XYZ-2", "XYZ-3"], issues
    print("cloud paging (nextPageToken) OK")

    # Cloud --keys narrows through the same clause
    p = run_helper(env_c, "my-issues", "--keys", "XYZ-2", "--json")
    assert p.returncode == 0, p.stderr
    assert [i["key"] for i in json.loads(p.stdout)] == ["XYZ-2"]
    print("cloud --keys OK")

    # Cloud fields come from the v3 /field endpoint, same shape
    p = run_helper(env_c, "fields", "--json")
    assert p.returncode == 0, p.stderr
    cfields = json.loads(p.stdout)
    assert len(cfields) == 4 and all(f["custom"] for f in cfields), cfields
    print("cloud fields OK")

    # ADF extraction for description and comments
    p = run_helper(env_c, "issue", "XYZ-1", "--json")
    assert p.returncode == 0, p.stderr
    detail = json.loads(p.stdout)
    assert detail["comments"][-1]["body"] == ADF_TEXT, detail
    p = run_helper(env_c, "issue", "XYZ-1")
    assert p.returncode == 0, p.stderr
    assert "進捗は順調です。" in p.stdout, p.stdout
    print("cloud ADF extraction OK")

    # edition auto-detection: with no PAT and no pin, the email+token
    # combination is judged Cloud (the documented order is: atlassian
    # host, then PAT, then email+token). Verify check succeeds against
    # the cloud fixture with the pin removed.
    env_c2 = dict(env_c)
    env_c2.pop("JIRA_EDITION", None)
    p = run_helper(env_c2, "check")
    assert p.returncode == 0, p.stderr
    assert "Cloud" in p.stdout, p.stdout
    print("cloud edition auto-detection OK")

    # explicit DC pin with a PAT against the DC fixture
    env_d2 = dict(env)
    env_d2["JIRA_EDITION"] = "dc"
    p = run_helper(env_d2, "check")
    assert p.returncode == 0, p.stderr
    print("dc edition pin OK")

    # redirects: same host keeps the token, cross host drops the request
    redirect_tests(dc_port)

    # missing env -> exit 2 (config error)
    env_none = clean_env()
    p = subprocess.run([sys.executable, HELPER, "check"], capture_output=True, text=True, env=env_none, timeout=60)
    assert p.returncode == 2, (p.returncode, p.stdout, p.stderr)
    print("config error OK")

    dc_server.shutdown()
    cloud_server.shutdown()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
