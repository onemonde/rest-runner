# rest-runner

A command-line script that automates the test report of a REST service.

You describe the requests in a YAML file. `rest-runner` sends every one of them,
stores what the service answers and writes a Markdown report with one section
per request: the equivalent cURL command, the HTTP status, the response body
and how long it took. The report is the evidence of the test run, ready to be
attached to a ticket.

Every run is stored in a local SQLite database under an identifier, the **CIP**
(`CIP-YYYYMMDD-HHMMSS`). With it you can write the report again, or send the
same requests again, without going back to the YAML file.

The script reports what the service answered and nothing else. It does not
decide whether a test passed: any HTTP response, a `200` as much as a `400` or
a `500`, is a valid result. Reading the report and judging it is up to you.

## Requirements

- Python 3.11 or later.
- The script is meant to be run from bash (Git Bash on Windows).

## Installation

From the project folder, create a virtual environment and install the
libraries (`requests`, `PyYAML` and `Jinja2`):

```bash
python -m venv .venv
source .venv/Scripts/activate      # on Linux or macOS: source .venv/bin/activate
pip install -r requirements.txt
```

Activate the environment in every new terminal before running the script.

## Usage

```bash
python rest-runner.py testcases.yml            # run the requests and write the report
python rest-runner.py -i CIP-20261012-102937   # write the report again, no requests sent
python rest-runner.py -r CIP-20261012-102937   # send the stored requests again, then write the report
```

| Mode | What it does |
|---|---|
| `{file.yml}` | Reads the file, stores it under a new CIP, sends the requests and writes the report. Running the same file twice gives two executions. |
| `-i {CIP}` | Writes the report of a stored execution again from the database. Nothing is sent to the service. |
| `-r {CIP}` | Sends the stored requests of an execution again and writes the report. The previous responses are replaced; the CIP and the report file stay the same. |

The console shows one line per step:

```
reading OK
assigned call sign CIP-20261012-102937
stored OK
request 1 OK
request 2 timeout KO
request 3 connection KO
report OK
```

- `request {n} OK` means the service answered, with any status.
- `request {n} timeout KO` and `request {n} connection KO` mean that every
  attempt failed. The other requests still run and the report is still written.
- A `KO` in any other step (`config KO`, `reading KO`, `stored KO`,
  `report KO`, `CIP {CIP} not found KO`) stops the script. `reading KO` is
  followed by a line with the reason.

| Exit code | Meaning |
|---|---|
| `0` | The script reached the end, even if some requests ended in `KO`. |
| `1` | A step failed and the script stopped. |
| `2` | Wrong arguments; the usage message is shown. |

### The input file

```yaml
suite_title: "Users module - field validation"
tests:
  - test_number: 1
    description: "Create a user with all the required fields"
    request:
      method: "POST"
      url: "https://api.example.com/v1/users"
      headers:
        Content-Type: "application/json"
        Accept: "application/json"
      params:
        dry_run: "true"
      body:
        username: "johndoe"
        email: "john@example.com"
        role: "admin"
```

| Field | Required | Description |
|---|---|---|
| `suite_title` | Yes | Title of the suite, shown at the top of the report. |
| `tests` | Yes | List of tests, at least one. |
| `tests[].test_number` | Yes | Integer, unique within the file. The report is sorted by it. |
| `tests[].description` | No | Text shown as the title of the test in the report. |
| `tests[].request.method` | Yes | HTTP method (`GET`, `POST`, ...). |
| `tests[].request.url` | Yes | Full URL, including scheme and host. |
| `tests[].request.headers` | No | Map of headers. |
| `tests[].request.params` | No | Map of query parameters. |
| `tests[].request.body` | No | Request body. It is always sent as JSON. |

When a test has a body and no `Content-Type` header, `application/json` is
added.

### Configuration

`config/config.yml`:

```yaml
rest-runner:
    retries: 5
    threads: 1
    timeout: 30_000
    verify_ssl: true
```

| Key | Meaning |
|---|---|
| `retries` | Total number of attempts per request. Only timeouts and connection errors are retried, with no wait in between. An HTTP response is never retried. |
| `threads` | Number of requests sent in parallel. With `1` they run one after another, in `test_number` order. |
| `timeout` | Maximum wait per attempt, in milliseconds. |
| `verify_ssl` | Whether the SSL certificate of the service is checked. |

### The report

The report is written to `reports/{CIP}.md` from the template
`config/report-template.md`, which you can edit to change its layout. Each test
looks like this:

````markdown
## [Test #1] Create a user with all the required fields

```bash
curl -X POST 'https://api.example.com/v1/users?dry_run=true' \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json' \
  -d '{"username": "johndoe", "email": "john@example.com", "role": "admin"}'
```
- **Duration:** 36.77 ms  
- **HTTP Response Status:** `201`

### Response Body
```json
{
  "id": 1042,
  "status": "created"
}
```
````

A test that ended in `KO` shows the reason (`timeout` or
`connection error: ...`) instead of the status and the body.

### Files and folders

| Path | Content |
|---|---|
| `rest-runner.py` | The script. |
| `config/config.yml` | Configuration. |
| `config/report-template.md` | Template of the report. |
| `data/rest-runner.db` | SQLite database with every execution. Created on first use. |
| `reports/` | Generated reports, one per CIP. Created on first use. |
| `skill/rest-runner/SKILL.md` | Skill for AI agents (see below). |

All of them are located from the folder of the script, so it can be run from
any directory.

## Trying it with mock-service

The `mock-service/` folder holds a small REST service made to try `rest-runner`
against something. It exposes `POST /orders`, validates the order it receives
and answers `201` or `400`. It comes with `mock-service/testcases.yml`, a suite
of 21 requests for it.

1. Start the service. See the [mock-service README](mock-service/README.md)
   for the details; in short, with Docker:

   ```bash
   cd mock-service
   docker build -t mock-service .
   docker run --rm -p 8000:8000 mock-service
   ```

   or without Docker, with its own virtual environment:

   ```bash
   cd mock-service
   python -m venv .venv
   source .venv/Scripts/activate
   pip install -r requirements.txt
   python mock-service.py
   ```

   Either way it listens on `http://127.0.0.1:8000`.

2. In another terminal, from the project folder and with the `rest-runner`
   environment active, run the suite:

   ```bash
   python rest-runner.py mock-service/testcases.yml
   ```

   You should see 21 lines `request {n} OK` and a final `report OK`.

3. Open `reports/{CIP}.md`. Six tests are answered with `201` and fifteen with
   `400`, each with the message of the field that failed.

4. Try the other two modes with the CIP shown in the console:

   ```bash
   python rest-runner.py -i CIP-20261012-102937
   python rest-runner.py -r CIP-20261012-102937
   ```

To see a `KO`, stop the service and run the suite again: every request ends in
`connection KO` once its attempts are used up. Lower `retries` in
`config/config.yml` first, or it takes a while.

The suite points to port `8000`. If you publish the service on another port,
replace `127.0.0.1:8000` in a copy of `testcases.yml`.

## Using it from an AI agent

`skill/rest-runner/SKILL.md` is a skill that teaches an AI coding agent (AWS
Kiro, Claude Code or any other that reads skills) to use `rest-runner` while
it develops a feature or a bugfix: how to write the YAML file of requests,
when to run the script itself and when to hand the command to you, and how to
read the report and draw conclusions from it.

To install it, copy the `skill/rest-runner/` folder to the skills folder of
your agent, or ask the agent to install it. The first time, tell the agent
where this project is, because the reports are written here and not in the
folder it is working on.

The script gives no verdict, so the skill sets one convention: the
`description` of each test states the case and the expected result
(`age = -1: 400 error on age`). The agent compares it with the response.

## Good to know

- Headers are stored and shown as they are, tokens and API keys included.
  Treat the database and the reports accordingly.
- The response headers are stored in the database but not shown in the report.
- A cURL command whose body has non-ASCII characters (accents, `ñ`) does not
  reproduce the request when run from Git Bash on Windows, because `curl` does
  not receive them as UTF-8. The script itself always sends UTF-8, so the
  report is correct.
- On Windows, a closed local port takes about 2 seconds to refuse a
  connection. With a shorter `timeout` it is reported as `timeout KO` instead
  of `connection KO`.
- Two runs started in the same second get the same CIP; the second one ends in
  `stored KO`.
