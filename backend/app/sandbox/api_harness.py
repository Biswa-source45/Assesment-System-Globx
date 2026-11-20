"""A backend (API) question: the candidate's file defines `app` (Flask, FastAPI or any Starlette app). The judge starts this file as
`python -I -B api_harness.py main.py`, as a separate user with the usual limits. It never opens a port: it calls the app in this process through the
framework's own test client, so there is no network, no start-up wait and no server to clean up. A fresh process per test case means fresh in-memory data.

stdin : one request per line, `METHOD /path` or `METHOD /path {json body}` (blank lines ignored, at most 200)
stdout: one line per request, `<status> <body>`; a JSON body is printed with sorted keys and no spaces, any other body is trimmed and cut short."""
import contextlib
import importlib.util
import json
import sys

MAX_REQUESTS = 200
SHOWN = 300


def die(message, code=2):
    print(message, file=sys.stderr)
    sys.exit(code)


def requests_from(text):
    out = []
    for n, line in enumerate((x.strip() for x in text.splitlines()), 1):
        if not line:
            continue
        parts = line.split(None, 2)
        if len(parts) < 2 or not parts[1].startswith("/"):
            die(f"Request {n}: write METHOD /path or METHOD /path {{json body}}")
        try:
            body = json.loads(parts[2]) if len(parts) == 3 else None
        except ValueError:
            die(f"Request {n}: the body must be JSON")
        out.append((parts[0].upper(), parts[1], body))
    if len(out) > MAX_REQUESTS:
        die(f"At most {MAX_REQUESTS} requests in one test case")
    return out


def load(path):
    spec = importlib.util.spec_from_file_location("candidate_app", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["candidate_app"] = module  # not __main__: an `if __name__ == "__main__": app.run()` block does not start a server
    spec.loader.exec_module(module)
    app = getattr(module, "app", None)
    if app is None:
        die("The file must define a variable named app (your Flask or FastAPI application)", 3)
    return app


def caller(app):
    if hasattr(app, "test_client"):  # Flask
        client = app.test_client()

        def call(method, path, body):
            r = client.open(path, method=method, **({} if body is None else {"json": body}))
            return r.status_code, r.get_data(as_text=True)
    else:  # FastAPI, Starlette
        from starlette.testclient import TestClient
        client = TestClient(app, raise_server_exceptions=False)  # a crash is a 500 answer, like a real server

        def call(method, path, body):
            r = client.request(method, path, **({} if body is None else {"json": body}))
            return r.status_code, r.text
    return call


def show(text):
    try:
        return json.dumps(json.loads(text), sort_keys=True, separators=(",", ":"))
    except ValueError:
        return " ".join(text.split())[:SHOWN]


def main():
    todo = requests_from(sys.stdin.read())  # read first: the candidate's code never sees the test script
    real = sys.stdout
    lines = []
    with contextlib.redirect_stdout(sys.stderr):  # whatever the candidate prints cannot get into the answer
        call = caller(load(sys.argv[1]))
        for method, path, body in todo:
            status, text = call(method, path, body)
            lines.append(f"{status} {show(text)}")
    real.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
