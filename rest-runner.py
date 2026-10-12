"""rest-runner: runs the API requests listed in a YAML file and writes a Markdown report.

Usage:
    python rest-runner.py testcases.yml           # run the whole chain
    python rest-runner.py -r CIP-YYYYMMDD-HHMMSS  # run the stored requests again
    python rest-runner.py -i CIP-YYYYMMDD-HHMMSS  # write the report again
"""

import argparse
import json
import shlex
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import jinja2
import requests
import urllib3
import yaml

# Every path hangs from the script's folder, not from the current directory.
BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config" / "config.yml"
TEMPLATE_FILE = BASE_DIR / "config" / "report-template.md"
DB_FILE = BASE_DIR / "data" / "rest-runner.db"
REPORTS_DIR = BASE_DIR / "reports"

# Black text on a green ("ok") or red ("ko") background.
ANSI_STYLES = {"ok": "\033[30;42m", "ko": "\033[30;41m"}
ANSI_RESET = "\033[0m"

SCHEMA = """
CREATE TABLE IF NOT EXISTS executions (
    cip         TEXT PRIMARY KEY,
    suite_title TEXT NOT NULL,
    created_at  TEXT NOT NULL            -- 'YYYY-MM-DD HH:MM:SS', local time
);

CREATE TABLE IF NOT EXISTS test_cases (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    cip          TEXT    NOT NULL REFERENCES executions (cip),
    test_number  INTEGER NOT NULL,
    description  TEXT    NOT NULL DEFAULT '',
    req_method   TEXT    NOT NULL,
    req_url      TEXT    NOT NULL,
    req_headers  TEXT    NOT NULL,       -- JSON object
    req_params   TEXT    NOT NULL,       -- JSON object
    req_body     TEXT,                   -- JSON text, NULL when there is no body
    curl_command TEXT    NOT NULL,
    res_status   INTEGER,                -- NULL on error or not executed
    res_headers  TEXT,                   -- JSON object
    res_body     TEXT,
    duration_ms  REAL,
    error        TEXT,                   -- 'timeout' | 'connection error: ...' | NULL
    UNIQUE (cip, test_number)
);
"""


class StepError(Exception):
    """Stops the chain. `label` is the KO message, `reason` an optional detail line."""

    def __init__(self, label: str, reason: str = ""):
        super().__init__(label)
        self.label = label
        self.reason = reason


def say(message, kind=None):
    """Print a console message, coloured only when the output is a terminal."""
    if kind in ANSI_STYLES and sys.stdout.isatty():
        message = f"{ANSI_STYLES[kind]}{message}{ANSI_RESET}"
    print(message, flush=True)


def load_config():
    """Read and validate config/config.yml."""
    try:
        with open(CONFIG_FILE, encoding="utf-8") as config_file:
            section = yaml.safe_load(config_file)["rest-runner"]
        config = {key: section[key] for key in ("retries", "threads", "timeout", "verify_ssl")}
    except (OSError, ValueError, yaml.YAMLError, KeyError, TypeError) as error:
        raise StepError("config KO") from error
    # type() and not isinstance(): in Python True is also an int.
    valid = (
        type(config["retries"]) is int and config["retries"] >= 1
        and type(config["threads"]) is int and config["threads"] >= 1
        and type(config["timeout"]) is int and config["timeout"] > 0
        and type(config["verify_ssl"]) is bool
    )
    if not valid:
        raise StepError("config KO")
    return config


def read_suite(path):
    """Read, validate and normalize the input YAML file."""

    def fail(reason):
        raise StepError("reading KO", reason)

    def is_text(value):
        return isinstance(value, str) and value.strip() != ""

    try:
        with open(path, encoding="utf-8") as suite_file:
            data = yaml.safe_load(suite_file)
    except OSError as error:
        fail(f"cannot read '{path}': {error.strerror}")
    except yaml.MarkedYAMLError as error:
        fail(f"invalid YAML at line {error.problem_mark.line + 1}: {error.problem}")
    except (ValueError, yaml.YAMLError):
        fail("invalid YAML")

    if not isinstance(data, dict) or not is_text(data.get("suite_title")):
        fail("missing required field 'suite_title'")
    if not isinstance(data.get("tests"), list) or not data["tests"]:
        fail("'tests' must be a non-empty list")

    tests = []
    numbers = set()
    for position, test in enumerate(data["tests"], start=1):
        number = test.get("test_number") if isinstance(test, dict) else None
        # type() and not isinstance(): in Python True is also an int.
        if type(number) is not int:
            fail(f"test at position {position}: missing required field 'test_number'")
        if number in numbers:
            fail(f"duplicated test_number {number}")
        numbers.add(number)

        request = test.get("request")
        if not isinstance(request, dict):
            request = {}
        for field in ("method", "url"):
            if not is_text(request.get(field)):
                fail(f"test {number}: missing required field 'request.{field}'")
        for field in ("headers", "params"):
            if request.get(field) is not None and not isinstance(request[field], dict):
                fail(f"test {number}: 'request.{field}' must be a mapping")

        description = test.get("description")
        tests.append({
            "test_number": number,
            "description": "" if description is None else str(description),
            "method": request["method"].strip().upper(),
            "url": request["url"].strip(),
            "headers": request.get("headers") or {},
            "params": request.get("params") or {},
            "body": request.get("body"),
        })

    say("reading OK", "ok")
    return {"suite_title": data["suite_title"], "tests": tests}


def open_db(ko_label):
    """Open the database, creating its folder and tables when missing."""
    try:
        DB_FILE.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA)
    except (OSError, sqlite3.Error) as error:
        raise StepError(ko_label) from error
    return conn


def build_curl(method, url, headers, body_text, verify_ssl):
    """Build the bash cURL command that reproduces a request."""
    first_line = "curl" if verify_ssl else "curl -k"
    lines = [f"{first_line} -X {shlex.quote(method)} {shlex.quote(url)}"]
    for name, value in headers.items():
        lines.append(f"  -H {shlex.quote(f'{name}: {value}')}")
    if body_text is not None:
        lines.append(f"  -d {shlex.quote(body_text)}")
    return " \\\n".join(lines)


def store_suite(conn, suite, config):
    """Assign the CIP and store the execution with its tests. Returns the CIP."""
    now = datetime.now()
    cip = now.strftime("CIP-%Y%m%d-%H%M%S")
    say(f"assigned call sign {cip}")
    try:
        rows = []
        for test in suite["tests"]:
            headers = {str(name): str(value) for name, value in test["headers"].items()}
            body_text = None
            if test["body"] is not None:
                # Serialized once: this text is stored, sent and shown in the cURL.
                body_text = json.dumps(test["body"], ensure_ascii=False)
                if not any(name.lower() == "content-type" for name in headers):
                    headers["Content-Type"] = "application/json"
            try:
                # The same URL, query params included, that the execution will use.
                curl_url = requests.Request(
                    test["method"], test["url"], params=test["params"]
                ).prepare().url
            except requests.RequestException:
                # A malformed URL is stored as written; it fails when executed.
                curl_url = test["url"]
            rows.append((
                cip, test["test_number"], test["description"], test["method"], test["url"],
                json.dumps(headers, ensure_ascii=False),
                json.dumps(test["params"], ensure_ascii=False),
                body_text,
                build_curl(test["method"], curl_url, headers, body_text, config["verify_ssl"]),
            ))
        # One transaction: nothing is left half stored.
        with conn:
            conn.execute(
                "INSERT INTO executions (cip, suite_title, created_at) VALUES (?, ?, ?)",
                (cip, suite["suite_title"], now.strftime("%Y-%m-%d %H:%M:%S")),
            )
            conn.executemany(
                "INSERT INTO test_cases (cip, test_number, description, req_method, req_url,"
                " req_headers, req_params, req_body, curl_command)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
    except (sqlite3.Error, TypeError, ValueError) as error:
        raise StepError("stored KO") from error
    say("stored OK", "ok")
    return cip


def execute_test(test, config):
    """Send one request, retrying on timeout or connection error.

    Runs in a worker thread: it only does HTTP and never touches the database.
    """
    headers = json.loads(test["req_headers"])
    params = json.loads(test["req_params"])
    body = None if test["req_body"] is None else test["req_body"].encode("utf-8")
    for _ in range(config["retries"]):
        result = {"res_status": None, "res_headers": None, "res_body": None, "error": None}
        started = time.perf_counter()
        try:
            response = requests.request(
                test["req_method"], test["req_url"], headers=headers, params=params,
                data=body,
                timeout=config["timeout"] / 1000,
                verify=config["verify_ssl"],
                allow_redirects=False,
            )
            result["res_status"] = response.status_code
            result["res_headers"] = json.dumps(dict(response.headers), ensure_ascii=False)
            result["res_body"] = response.text
        # Timeout goes first: ConnectTimeout is also a ConnectionError.
        except requests.exceptions.Timeout:
            result["error"] = "timeout"
        except requests.exceptions.RequestException as error:
            result["error"] = f"connection error: {error}"
        # The duration of this attempt only, not the sum of all of them.
        result["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
        if result["error"] is None:
            break
    return result


def run_tests(conn, cip, config):
    """Run every test of the execution and store each result as it finishes."""
    if not config["verify_ssl"]:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    try:
        tests = conn.execute(
            "SELECT * FROM test_cases WHERE cip = ? ORDER BY test_number", (cip,)
        ).fetchall()
        with ThreadPoolExecutor(max_workers=config["threads"]) as pool:
            jobs = {pool.submit(execute_test, dict(test), config): test["test_number"]
                    for test in tests}
            # Only this thread writes to the database and to the console.
            for job in as_completed(jobs):
                number = jobs[job]
                result = job.result()
                with conn:
                    conn.execute(
                        "UPDATE test_cases SET res_status = :res_status,"
                        " res_headers = :res_headers, res_body = :res_body,"
                        " duration_ms = :duration_ms, error = :error"
                        " WHERE cip = :cip AND test_number = :test_number",
                        {**result, "cip": cip, "test_number": number},
                    )
                if result["error"] is None:
                    say(f"request {number} OK", "ok")
                elif result["error"] == "timeout":
                    say(f"request {number} timeout KO", "ko")
                else:
                    say(f"request {number} connection KO", "ko")
    except Exception as error:
        raise StepError("execution KO", str(error)) from error


def pretty_body(text):
    """Format a response body for the report: indented when it is JSON, as is otherwise."""
    if text is None:
        return ""
    try:
        return json.dumps(json.loads(text), indent=2, ensure_ascii=False)
    except ValueError:
        return text


def write_report(conn, cip):
    """Render the report template with the stored data of the execution."""
    try:
        execution = conn.execute("SELECT * FROM executions WHERE cip = ?", (cip,)).fetchone()
        tests = [
            dict(row) for row in conn.execute(
                "SELECT * FROM test_cases WHERE cip = ? ORDER BY test_number", (cip,)
            )
        ]
        for test in tests:
            test["res_body_pretty"] = pretty_body(test["res_body"])
        environment = jinja2.Environment(
            autoescape=False,  # the output is Markdown, not HTML
            trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True,
            # A test that was not executed shows empty fields instead of "None".
            finalize=lambda value: "" if value is None else value,
        )
        template = environment.from_string(TEMPLATE_FILE.read_text(encoding="utf-8"))
        report = template.render(executions=dict(execution), total_tests=len(tests), tests=tests)
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        # Unix line endings also on Windows, so the cURL can be pasted into bash.
        (REPORTS_DIR / f"{cip}.md").write_text(report, encoding="utf-8", newline="\n")
    except (OSError, ValueError, sqlite3.Error, jinja2.TemplateError) as error:
        raise StepError("report KO") from error
    say("report OK", "ok")


def find_execution(conn, cip):
    """Check that the CIP is a stored execution."""
    try:
        found = conn.execute("SELECT 1 FROM executions WHERE cip = ?", (cip,)).fetchone()
    except sqlite3.Error:
        found = None
    if not found:
        raise StepError(f"CIP {cip} not found KO")


def reset_execution(conn, cip):
    """Clear the stored responses and set the execution date to now."""
    try:
        with conn:
            conn.execute(
                "UPDATE test_cases SET res_status = NULL, res_headers = NULL,"
                " res_body = NULL, duration_ms = NULL, error = NULL WHERE cip = ?",
                (cip,),
            )
            conn.execute(
                "UPDATE executions SET created_at = ? WHERE cip = ?",
                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), cip),
            )
    except sqlite3.Error as error:
        raise StepError("execution KO", str(error)) from error


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="rest-runner.py",
        description="Run the API requests of a YAML file and write a Markdown report.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("input_file", nargs="?", help="YAML file with the requests to run")
    mode.add_argument("-i", metavar="CIP", dest="report_cip",
                      help="write again the report of a stored execution")
    mode.add_argument("-r", metavar="CIP", dest="rerun_cip",
                      help="run again the requests of a stored execution")
    args = parser.parse_args(argv)

    try:
        config = load_config()
        if args.input_file is not None:
            suite = read_suite(args.input_file)
            conn = open_db("stored KO")
            cip = store_suite(conn, suite, config)
            run_tests(conn, cip, config)
        else:
            # -i and -r enter the chain at a later step, with a stored execution.
            cip = args.report_cip if args.report_cip is not None else args.rerun_cip
            conn = open_db(f"CIP {cip} not found KO")
            find_execution(conn, cip)
            if args.rerun_cip is not None:
                reset_execution(conn, cip)
                run_tests(conn, cip, config)
        write_report(conn, cip)
    except StepError as error:
        say(error.label, "ko")
        if error.reason:
            say(error.reason)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
