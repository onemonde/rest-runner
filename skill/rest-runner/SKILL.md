---
name: rest-runner
description: Send a batch of HTTP requests to a REST service with the rest-runner script and get a Markdown report with every response. Use it while developing a feature or a bugfix, when you need to check what a service answers to a set of inputs (valid and invalid field values, missing fields, edge cases) and keep the result as test evidence. Covers writing the YAML file of requests, running the script or handing the command to the user, and reading the report to draw conclusions.
---

# rest-runner

`rest-runner` is a Python command-line script. You describe a list of HTTP
requests in a YAML file; the script sends them, stores every response in a
local SQLite database and writes a Markdown report with one section per
request. The report is the evidence of the test run and is usually attached to
a ticket.

Use it when the question is: *for the inputs x1, x2, x3... does the service
answer z1, z2, z3...?*

## What it does not do

- **It gives no verdict.** Any HTTP response (`200`, `400`, `500`...) counts as
  "OK": it only means the service answered. Comparing each response with what
  was expected is your job (see *Reading the report*).
- **Request bodies are always JSON.** No forms, XML, files or raw text. A body
  that is not valid JSON cannot be sent either.
- **Requests are independent.** A request cannot use a value returned by
  another one. There are no variables, environments or base URLs: every test
  carries its full URL.
- **Redirects are not followed.** A `3xx` is reported as it is.

## The workflow

1. Write the YAML file with the requests.
2. Ask the user for confirmation.
3. Run the script yourself, or hand the command to the user and stop.
4. Read the report and tell the user what you found.
5. After a fix in the service, send the same requests again with `-r`.

## 1. Writing the YAML file

```yaml
suite_title: "Orders service - POST /orders field validation"
tests:
  - test_number: 1
    description: "Valid order: 201 created"
    request:
      method: "POST"
      url: "http://127.0.0.1:8000/orders"
      headers: &headers
        Content-Type: "application/json"
        Authorization: "Bearer abc123"
      params:
        dry_run: "true"
      body: &order
        orderNumber: 10482
        name: "Alejandro"
        member: true
        products:
          - name: "Coffee"
            price: 20.0

  - test_number: 2
    description: "name longer than 20 characters: 400 error on name"
    request:
      method: "POST"
      url: "http://127.0.0.1:8000/orders"
      headers: *headers
      body:
        <<: *order
        name: "Alejandromaximilianoo"

  - test_number: 3
    description: "Unknown order: 404"
    request:
      method: "GET"
      url: "http://127.0.0.1:8000/orders/999999"
```

| Field | Required | Rules |
|---|---|---|
| `suite_title` | Yes | Non-empty text. Title of the report. |
| `tests` | Yes | List with at least one test. |
| `tests[].test_number` | Yes | Integer (not quoted), unique in the file. The report is sorted by it. |
| `tests[].description` | No | Title of the test in the report. Always write it (see below). |
| `tests[].request.method` | Yes | HTTP method, non-empty text. |
| `tests[].request.url` | Yes | Full URL, with scheme and host. |
| `tests[].request.headers` | No | Map of headers. |
| `tests[].request.params` | No | Map of query parameters; they are URL-encoded and appended to the URL. |
| `tests[].request.body` | No | Any YAML value; it is sent as JSON. Absent or `null` means no body. |

When a test has a body and no `Content-Type` header, `application/json` is
added.

### The description carries the expected result

The script does not store what you expect, so put it in `description`, with
this form:

```
{case under test}: {expected result}
```

Examples: `Valid order: 201 created`, `age = -1: 400 error on age`,
`email missing: 400 error on email`.

The description is the title of each test in the report, so the expectation
stays next to the actual response, for you and for whoever reads the report.
Take the expected results from the specification or from the code of the
service, not from what the service currently answers.

### Designing the cases

- Start with one valid request, the baseline, and check it is really valid.
- Then change **one thing per test**: one field with one invalid or edge
  value. A response to a request with two changes cannot be attributed.
- For each field think of: missing, `null`, empty, wrong type, below and above
  the limits, the exact limits, invalid format, unexpected extra field.
- Number the tests in the order you want them in the report.

### YAML details that matter

- **Anchors and merge keys work** (`&order`, `*order`, `<<: *order`), and they
  keep the file short. The merge is shallow: to change something inside a
  nested object or list, write that whole object or list again.
- **A merge key cannot remove a field.** To test a missing field, write the
  body in full without it.
- **Quote what must be a string.** Unquoted, `123` is a number, `true`, `yes`,
  `no`, `on` and `off` are booleans, and `2026-10-12` is a date. An unquoted
  date in a body cannot be turned into JSON and the run stops with
  `stored KO`.
- To send the wrong type on purpose, use exactly that: `age: "abc"` sends a
  string, `age: -1` a number, `age: null` a JSON `null`.

## 2. Asking the user before running

The requests are real: a `POST`, `PUT` or `DELETE` changes data in the
service. Before running, tell the user and wait for a yes:

- how many requests the file has;
- which service they go to (host and path);
- whether any of them creates, changes or deletes data;
- the worst-case duration and who will run it (next section).

## 3. Running the script

### Where the script is

If you do not know the folder where `rest-runner` is installed, ask the user.
Everything the script reads and writes hangs from **that folder**, not from
the current directory:

| Path | Content |
|---|---|
| `rest-runner.py` | The script. |
| `config/config.yml` | Configuration. |
| `data/rest-runner.db` | SQLite database with every execution. |
| `reports/{CIP}.md` | The reports. |

The YAML file can be anywhere; pass its path as the argument.

### Commands

The libraries live in the `.venv` of the script's folder. Run it from bash
with that Python:

```bash
RR=/path/to/rest-runner

"$RR/.venv/Scripts/python.exe" "$RR/rest-runner.py" /path/to/testcases.yml   # Windows (Git Bash)
"$RR/.venv/bin/python"         "$RR/rest-runner.py" /path/to/testcases.yml   # Linux, macOS
```

`ModuleNotFoundError: No module named 'yaml'` means the script ran with another
Python. If there is no `.venv`, ask the user before creating it
(`python -m venv .venv`, then `pip install -r requirements.txt` with it).

| Command | What it does |
|---|---|
| `rest-runner.py {file.yml}` | Reads the file, stores it under a new CIP, sends the requests, writes the report. |
| `rest-runner.py -r {CIP}` | Sends the stored requests of that execution again and rewrites its report. The old responses are lost. The YAML file is **not** read again. |
| `rest-runner.py -i {CIP}` | Rewrites the report from the database. Nothing is sent. |

The **CIP** (`CIP-YYYYMMDD-HHMMSS`) identifies one execution. Running the same
file twice gives two executions with two CIPs.

### Run it yourself or hand it over

Read `config/config.yml`:

```yaml
rest-runner:
    retries: 5        # total attempts per request
    threads: 1        # requests sent in parallel
    timeout: 30_000   # maximum wait per attempt, in milliseconds
    verify_ssl: true
```

Only timeouts and connection errors are retried, immediately. So the
worst-case duration, reached when the service does not answer, is:

```
tests × retries × timeout / threads
```

With the values above, 21 tests take up to 21 × 5 × 30 s = 52 minutes.

- **Worst case of 2 minutes or less:** run the script and wait for it.
- **Worst case above 2 minutes:** do not run it. Give the user the exact
  command, ask them to come back with the CIP (or the console output), and
  stop. Do not wait or poll. When the user returns, continue with the report.

Do not edit `config/config.yml` on your own to get under the limit; propose
the change to the user.

### Console output and exit codes

```
reading OK
assigned call sign CIP-20261012-102937
stored OK
request 1 OK
request 2 timeout KO
request 3 connection KO
report OK
```

Take the CIP from the `assigned call sign` line. With more than one thread the
`request` lines come in order of completion.

| Exit code | Meaning |
|---|---|
| `0` | The script reached the end and the report exists, even if some requests ended in `KO`. |
| `1` | A step failed and the script stopped. |
| `2` | Wrong arguments. |

A `request {n} ... KO` does not stop the script. These do:

| Message | Cause | What to do |
|---|---|---|
| `config KO` | `config/config.yml` is missing or has invalid values. | Tell the user; nothing was sent. |
| `reading KO` + a reason line | The YAML file is missing, not parseable or breaks a rule of the table above. | Fix the file as the reason says and run again; nothing was sent. |
| `stored KO` | A body value cannot be turned into JSON (an unquoted date), another run started in the same second, or the database cannot be written. | Fix the body or run again; nothing was sent. |
| `execution KO` + a reason line | Unexpected failure while sending. | Report the reason to the user. Responses received so far are stored: `-i {CIP}` writes a partial report. |
| `report KO` | The template is missing or broken, or `reports/` cannot be written. | The responses are stored. Once fixed, use `-i {CIP}`; do not send the requests again. |
| `CIP {CIP} not found KO` | `-i` or `-r` with a CIP that is not in the database. | Check the CIP. |

## 4. Reading the report

Open `reports/{CIP}.md` in the script's folder. The header has the suite
title, the CIP, the date and the number of tests. Then one section per test,
sorted by `test_number`:

````markdown
## [Test #2] name longer than 20 characters: 400 error on name

```bash
curl -X POST 'http://127.0.0.1:8000/orders' \
  -H 'Content-Type: application/json' \
  -d '{"orderNumber": 10482, "name": "Alejandromaximilianoo"}'
```
- **Duration:** 5.13 ms  
- **HTTP Response Status:** `400`

### Response Body
```json
{
  "orderNumber": 10482,
  "message": "error on name"
}
```
````

- The title is `description`: the case and **what was expected**.
- The cURL command is exactly what was sent, headers and body included.
- The body is pretty-printed when it is JSON and shown as plain text
  otherwise. It is never truncated.

A test that got no HTTP response shows the reason instead of the status and
the body:

```markdown
- **Duration:** 30004.12 ms  
- **Error:** `timeout`
```

### Classify every test

| What the section shows | Meaning | Conclusion |
|---|---|---|
| Status and body equal to the expected result | The service behaves as expected. | Match. |
| Status or body different from the expected result | See below. | Mismatch. |
| `Error: timeout` or `Error: connection error: ...` | The service did not answer in any attempt: it is down, unreachable or too slow, or the URL is wrong. | No answer. It says nothing about the behaviour under test; it is not a failed validation. |
| Empty duration, empty status, empty body | The test was not executed (the run was interrupted). | Not executed. |

Compare both the status and the relevant part of the body: a `400` with the
message of another field is a mismatch.

A mismatch has three possible causes; check them in this order before blaming
the service:

1. **The request is not what you meant.** Read the cURL: a merged body, a
   value that YAML typed differently, a wrong URL.
2. **The expectation is wrong.** Check it against the specification.
3. **The service is wrong.** This is the finding.

Never change an expected result just to make it match the response.

### What to tell the user

Give a short summary, not the whole report:

- the CIP and the path of the report;
- the totals: matches, mismatches, no answer, not executed;
- one line per mismatch: test number, what was expected, what came back and
  the cause you found;
- the tests with no answer, with their error;
- what you propose next.

### Limits of the report

- Response headers are not in the report. They are stored as JSON in the
  `res_headers` column of the `test_cases` table (`cip`, `test_number`) of
  `data/rest-runner.db`, in case you need one, such as `Location` of a `3xx`.
- After retries, the duration is that of the last attempt, not the sum.
- Run from Git Bash on Windows, a cURL whose body has non-ASCII characters
  (accents, `ñ`) does not reproduce the request. The script itself always
  sends UTF-8, so the report is right.

## 5. After a fix

- **The service was fixed and the requests are the same:** `-r {CIP}`. Same
  CIP, same report file, new responses and new date. It sends real requests
  again and uses the current `config.yml`, so ask the user and apply the
  2-minute rule as before.
- **The YAML file changed** (new tests, corrected requests or descriptions):
  run the file again. `-r` would ignore the changes. It gives a new CIP.
- **Only the report is needed again** (deleted, or the template changed):
  `-i {CIP}`. Nothing is sent, so no confirmation is needed.

## Secrets

Headers are stored in the database and printed in the cURL of the report
exactly as written, tokens and API keys included. If a request carries
credentials, tell the user before the report is attached to a ticket or shared.
