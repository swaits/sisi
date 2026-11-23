"""Lesson and statement tiers: core, user, or one project.

The owner's test, two questions: (a) does it apply to all projects where sisi may be used?
(b) would it be useful to every user who installs sisi? Both yes is `core`: a change to the
product itself (a rule, a recipe or technique, a mechanism, a design principle), in force for
this user at once through the personal overlay and queued for the product (`sisi promote`).
(a) yes, (b) no is `user`: how this owner wants work done, kept in the personal store and
delivered in all of this user's projects. (a) no is `project`: a fact about one project,
handed over to that project's own documentation or work list. Items recorded with the old
two-way scope `everywhere` are `unscoped-tier`: still delivered, tiered by the next learning
round. sisi is normally the shell around other projects; working in the sisi repository
itself is the exception, and an item is never project merely because it was recorded there -
a statement about how sisi itself should behave is core.

A project is identified by its git remote URL when there is one (normalised, so an
ssh and an https remote for the same repository, a trailing `.git`, credentials and a
renamed or re-cloned folder all give the same id), else by its repository root path
(a clone without a remote, or a renamed folder with no remote, is then a different
project: there is nothing more stable to key on). Project-scoped items live only in
the personal data store, keyed by that id; nothing is written into the repository.

The universality check is structural only, no model call: it looks at the parts that
are delivered to agents (change, short, when-terms; a learn statement) and refuses
when a core or user item names the current project. The tool's own name, sisi, is always
exempt. History (moment, cause, occurrences) may name the project freely and is never checked.
"""
import os, re, subprocess

from . import gitutil

SCOPES = ("core", "user", "project")
UNTIERED = (None, "", "unscoped", "unscoped-tier", "everywhere")
TIER_QUESTIONS = (
    "Ask two questions: (a) does it apply to all projects where sisi may be used? "
    "(b) would it be useful to every user who installs sisi? Both yes: --scope core (a change "
    "to sisi itself - a rule, a recipe or technique, a mechanism, a design principle; it takes "
    "effect for you at once and is queued for the product, `sisi promote`). (a) yes but (b) no, "
    "because it is how this owner wants things: --scope user (kept in your personal store, "
    "delivered in all your projects). (a) no: --scope project (a fact about this project, "
    "handed over to its own documentation or work list).")
MISSING_SCOPE = (
    "sisi: --scope is required (core, user or project). " + TIER_QUESTIONS + " "
    "Core and user items are stated in general terms so any project can use them: name the kind "
    "of work and the rule that follows, not this project's name, files or address (for example, "
    "not 'the exporter here joins rows by hand' but 'write delimited files with a quoting "
    "writer'). A statement about how sisi itself should behave is core, even recorded inside "
    "the sisi repository. The moment and cause may name this project either way: they stay as "
    "its history.")


def tier_of(value):
    """The tier a stored scope value means today: legacy `everywhere` is not yet tiered."""
    if value in SCOPES:
        return value
    return "unscoped-tier"


def normalize_scope(value):
    """A scope given on a command line, canonicalised: legacy `everywhere` is accepted and
    stored as unscoped-tier (still delivered; the next learning round tiers it)."""
    if value == "everywhere":
        return "unscoped-tier"
    return value

# File and directory names so common that merely mentioning them names no project.
COMMON_NAMES = {
    "readme", "readme.md", "readme.txt", "readme.rst", "changelog", "changelog.md", "changelog.txt",
    "history", "history.md", "news", "news.md", "license", "license.md", "licence", "licence.md",
    "copying", "authors", "notice", "contributing", "contributing.md", "security", "security.md",
    "code_of_conduct", "code_of_conduct.md", ".gitignore", ".gitattributes", "makefile", "dockerfile",
    "tests", "test", "src", "source", "docs", "doc", "bin", "lib", "scripts", "script", "examples",
    "example", "config", "configs", "build", "dist", "assets", "static", "templates", "vendor",
    "main.py", "main.rs", "main.go", "main.c", "main.cpp", "index.html", "index.js", "index.ts",
    "app.py", "setup.py", "pyproject.toml", "package.json", "cargo.toml", "go.mod", "requirements.txt",
}


def _git(cwd, *args):
    try:
        p = subprocess.run(("git",) + args, cwd=cwd, capture_output=True, timeout=5)
        return p.stdout.decode("utf-8", "replace").strip() if p.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def normalized_remote(url):
    """One id for the same repository however it was cloned."""
    u = " ".join((url or "").split()).strip().rstrip("/")
    if u.endswith(".git"):
        u = u[:-4]
    m = re.match(r"^[^/@]+@([^/:]+)[:/](.+)$", u)  # git@host:owner/repo
    if m:
        u = m.group(1).lower() + "/" + m.group(2)
    else:
        m = re.match(r"^(?:[a-z][a-z0-9+.-]*://)?(?:[^/@]+@)?([^/]+)/(.+)$", u, re.I)
        if m:
            u = m.group(1).lower() + "/" + m.group(2)
    return u.rstrip("/")


def remote_url(cwd):
    url = _git(cwd, "remote", "get-url", "origin")
    if not url:
        names = _git(cwd, "remote").splitlines()
        if names:
            url = _git(cwd, "remote", "get-url", names[0].strip())
    return url or None


def project_id(cwd):
    """Remote URL when there is one, else the repository root path, else the folder."""
    url = remote_url(cwd)
    if url:
        return normalized_remote(url)
    root = gitutil.root(cwd)
    return os.path.realpath(root or os.path.abspath(cwd))


def project_label(pid):
    """A short human name for a project id (last path part, without .git)."""
    s = (pid or "").rstrip("/")
    name = s.rsplit("/", 1)[-1]
    return name[:-4] if name.endswith(".git") else name


def visible(scope_value, project_value, cwd=None):
    """Core, user and not-yet-tiered items show in every project; project items only at home."""
    if tier_of(scope_value) == "project":
        return (project_value or "") == project_id(cwd or os.getcwd())
    return True


def row_visible(row, cwd=None):
    try:
        get = row.get if isinstance(row, dict) else (lambda k: row[k] if k in row.keys() else None)
    except Exception:
        get = lambda k: None
    return visible(get("scope"), get("project"), cwd)


def row_scope(row):
    try:
        v = row.get("scope") if isinstance(row, dict) else (row["scope"] if "scope" in row.keys() else None)
    except Exception:
        v = None
    return tier_of(v)


def _existing(cwd):
    """(basenames, relative paths) of files and folders in the project, .git excluded."""
    root = gitutil.root(cwd) or os.path.abspath(cwd)
    names, rels = set(), set()
    out = _git(root, "ls-files", "-c", "-o", "--exclude-standard")
    if out:
        for rel in out.splitlines():
            rels.add(rel.replace(os.sep, "/").lower())
            parts = rel.split("/")
            for p in parts:
                names.add(p.lower())
    else:
        for dp, dns, fns in os.walk(root):
            dns[:] = [d for d in dns if d != ".git"][:200]
            for n in list(dns) + list(fns):
                names.add(n.lower())
            if len(names) > 20000:
                break
    return root, names, rels


def universal_refusal(texts, cwd, kind=None):
    """Reason string when a delivered text names the current project, else None.

    Checks the repository name, its remote URL (and the repository name inside it),
    any path or file name that exists in it, and the root path itself. The tool's own
    name, 'sisi', is always exempt: how sisi itself should behave is core, not project.
    """
    texts = [t for t in (texts or []) if t and str(t).strip()]
    if not texts:
        return None
    cwd = cwd or os.getcwd()
    root, names, rels = _existing(cwd)
    repo_name = os.path.basename(os.path.realpath(root)).lower()
    remote = remote_url(cwd)
    remote_norm = normalized_remote(remote) if remote else ""
    remote_name = project_label(remote_norm).lower() if remote_norm else ""
    blob = "\n".join(str(t) for t in texts)
    low = blob.lower()
    if os.path.realpath(root).lower() in low:
        return "it gives this project's path (%s)" % root
    for form in {remote or "", remote_norm}:
        if form and form.lower() in low:
            return "it gives this project's remote address (%s)" % form
    tokens = re.findall(r"[A-Za-z0-9_./~:-]+", blob)
    for tok in tokens:
        t = tok.strip(".,;:()[]{}\"'")
        tl = t.lower()
        # the repository's own name, as a whole token or inside a path/URL token
        for name in {repo_name, remote_name} - {""}:
            if tl == name or tl.endswith("/" + name) or ("/" in tl and tl.rsplit("/", 1)[-1] == name):
                if name == "sisi":
                    continue
                return "it names this project (%s)" % name
        if "/" in tl:
            rel = tl.split("://", 1)[-1]
            rel = rel[rel.find("/") + 1:] if rel.startswith(("github.com/", "gitlab.com/", "bitbucket.org/")) else rel
            if rel in rels:
                return "it names a path in this project (%s)" % t
            base = rel.rsplit("/", 1)[-1]
            if base in names and base not in COMMON_NAMES:
                return "it names a file in this project (%s)" % base
        elif "." in tl and not tl.startswith(".") or tl.startswith("."):
            base = tl.rsplit("/", 1)[-1]
            if base in names and base not in COMMON_NAMES and re.search(r"\.[a-z0-9]{1,6}$", base):
                return "it names a file in this project (%s)" % base
    return None


def refusal_text(reason):
    return ("sisi: refused: a core or user item must be universal, and %s. Rewrite it in general "
            "terms (the kind of work and the rule that follows, not this project's name, files or address), "
            "or record it with --scope project so it stays with this project. " + TIER_QUESTIONS) % reason


def cmd_learn(argv):
    """`sisi learn [--scope core|user|project] TEXT` (also `--scope=X`)."""
    from . import store
    scope_value, text_parts, i = None, [], 0
    argv = list(argv)
    while i < len(argv):
        a = argv[i]
        if a == "--scope" and i + 1 < len(argv):
            scope_value = argv[i + 1]; i += 2
        elif a.startswith("--scope="):
            scope_value = a.split("=", 1)[1]; i += 1
        else:
            text_parts.append(a); i += 1
    text = " ".join(text_parts).strip()
    if not text:
        print("usage: sisi learn --scope core|user|project TEXT")
        return 1
    if scope_value not in SCOPES and scope_value != "everywhere":
        print(MISSING_SCOPE)
        return 2
    scope_value = normalize_scope(scope_value)
    cwd = os.getcwd()
    if scope_value in ("core", "user", "unscoped-tier"):
        reason = universal_refusal([text], cwd, kind="learn")
        if reason:
            print(refusal_text(reason))
            return 2
    rec = {"text": text, "scope": scope_value}
    if scope_value == "project":
        from . import handover
        handover.move_learn(store.stamp(rec), project_id(cwd))
        print("recorded for this project; it will be handed over to this "
              "project at session start (`sisi handover` lists it)")
        return 0
    store.append("learn", store.stamp(rec))
    try:
        from . import cli
        cli._commit_personal(store.file_path("learn"),
                             "learn: %s" % " ".join(text.split())[:60])
    except Exception:
        pass
    if scope_value == "core":
        print("recorded as core; it takes effect at once (`sisi oracle` shows it) and is queued "
              "for the product (`sisi promote` lists core items)")
    elif scope_value == "unscoped-tier":
        print("recorded (the old everywhere scope); it takes effect at once and the next "
              "learning round will tier it core, user or project")
    else:
        print("recorded; it takes effect at once as a standing principle (`sisi oracle` shows it)")
    return 0
