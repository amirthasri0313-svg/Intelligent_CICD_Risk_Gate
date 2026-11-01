"""Built-in static analysis on Python's ast module.

Used for cyclomatic complexity everywhere, and as a fallback for the security
and quality stages when bandit / ruff are not installed (the CI pipeline always
installs both, so in GitHub Actions the real tools run).
"""
import ast
import re

_BRANCHES = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.With,
             ast.AsyncWith, ast.Assert, ast.comprehension, ast.IfExp)


def cyclomatic(node) -> int:
    score = 1
    for child in ast.walk(node):
        if isinstance(child, _BRANCHES):
            score += 1
        elif isinstance(child, ast.BoolOp):
            score += len(child.values) - 1
    return score


def complexity(source: str) -> dict:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {"max_cc": 0, "functions": 0}
    funcs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    scores = [cyclomatic(f) for f in funcs] or [0]
    return {"max_cc": max(scores), "functions": len(funcs)}


SECRET_NAME = re.compile(r"(password|passwd|secret|api_?key|token|private_?key)", re.I)


def _name(call: ast.Call) -> str:
    f, parts = call.func, []
    while isinstance(f, ast.Attribute):
        parts.append(f.attr)
        f = f.value
    if isinstance(f, ast.Name):
        parts.append(f.id)
    return ".".join(reversed(parts))


def _kw(call, key):
    for k in call.keywords:
        if k.arg == key and isinstance(k.value, ast.Constant):
            return k.value.value
    return None


HTTP_METHODS = {"get", "post", "put", "delete", "request"}

# (test, severity, bandit id, message) - each test takes (call name, call node)
CALL_RULES = [
    (lambda n, c: n in ("eval", "exec"), "HIGH", "B307", "Use of {n}() can run arbitrary code"),
    (lambda n, c: n in ("pickle.loads", "pickle.load"), "HIGH", "B301", "Unsafe pickle deserialisation"),
    (lambda n, c: n == "yaml.load" and _kw(c, "Loader") is None, "HIGH", "B506", "yaml.load without a safe Loader"),
    (lambda n, c: n.startswith("subprocess.") and _kw(c, "shell") is True, "HIGH", "B602",
     "subprocess call with shell=True (command injection)"),
    (lambda n, c: n in ("os.system", "os.popen"), "HIGH", "B605", "{n}() starts a shell (command injection)"),
    (lambda n, c: n.endswith("execute") and bool(c.args) and isinstance(c.args[0], (ast.JoinedStr, ast.BinOp)),
     "HIGH", "B608", "SQL query built with string formatting (SQL injection)"),
    (lambda n, c: n.split(".")[-1] in HTTP_METHODS and _kw(c, "verify") is False, "MEDIUM", "B501",
     "TLS certificate verification disabled (verify=False)"),
    (lambda n, c: n in ("hashlib.md5", "hashlib.sha1"), "MEDIUM", "B324", "Weak hash {n}()"),
    (lambda n, c: n.endswith(".run") and _kw(c, "debug") is True, "MEDIUM", "B201", "Flask app run with debug=True"),
]


def _hardcoded_secret(node):
    value = node.value
    if not (isinstance(value, ast.Constant) and isinstance(value.value, str) and len(value.value) >= 4):
        return None
    return next((t.id for t in node.targets if isinstance(t, ast.Name) and SECRET_NAME.search(t.id)), None)


def security_findings(source: str, filename: str = "<code>") -> list:
    """Bandit-like rules. Returns [{severity, test_id, issue, file, line}]."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    out = []
    for node in ast.walk(tree):
        hits = []
        if isinstance(node, ast.Call):
            name = _name(node)
            hits = [(sev, tid, msg.format(n=name)) for test, sev, tid, msg in CALL_RULES if test(name, node)][:1]
        elif isinstance(node, ast.Assign) and (secret := _hardcoded_secret(node)):
            hits = [("HIGH", "B105", f"Hard-coded secret in '{secret}'")]
        out += [{"severity": s, "test_id": t, "issue": m, "file": filename, "line": node.lineno} for s, t, m in hits]
    return out


def quality_findings(source: str, filename: str = "<code>") -> list:
    """Ruff-like rules. Returns [{code, message, file, line}]."""
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return [{"code": "E999", "message": f"SyntaxError: {e.msg}", "file": filename, "line": e.lineno or 0}]
    issue = lambda code, msg, line: {"code": code, "message": msg, "file": filename, "line": line}  # noqa: E731
    nodes = list(ast.walk(tree))
    out = [issue("F403", "wildcard import", n.lineno) for n in nodes
           if isinstance(n, ast.ImportFrom) and any(a.name == "*" for a in n.names)]
    out += [issue("E722", "bare except", n.lineno) for n in nodes if isinstance(n, ast.ExceptHandler) and n.type is None]
    out += [issue("E711", "comparison to None", n.lineno) for n in nodes if isinstance(n, ast.Compare) and _compares_none(n)]
    if "__all__" not in source:
        used = {n.id for n in nodes if isinstance(n, ast.Name)}
        out += [issue("F401", f"'{name}' imported but unused", line)
                for name, line in _imported_names(nodes).items() if name not in used and name != "annotations"]
    return out


def _compares_none(node):
    return any(isinstance(op, (ast.Eq, ast.NotEq)) and isinstance(c, ast.Constant) and c.value is None
               for op, c in zip(node.ops, node.comparators))


def _imported_names(nodes):
    names = {}
    for n in nodes:
        if isinstance(n, ast.Import):
            names.update({(a.asname or a.name).split(".")[0]: n.lineno for a in n.names})
        elif isinstance(n, ast.ImportFrom):
            names.update({a.asname or a.name: n.lineno for a in n.names if a.name != "*"})
    return names
