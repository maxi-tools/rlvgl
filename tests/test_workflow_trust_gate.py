"""Fork pull requests must not reach rlvgl's self-hosted ARM64 fleet.

WHY THIS IS A PARSER AND NOT A `grep`.

This repository is PUBLIC, so `pull_request` reaches it from forks. Seven jobs
in `.github/workflows/ci.yml` run on `[self-hosted, Linux, ARM64]`, and the
first of them builds the PR's own `Dockerfile` on a fleet runner and pushes it
to `ghcr.io/maxi-tools/rlvgl` with `packages: write`. Every later job then runs
INSIDE that image. A substring check for "trust gate" would have gone green on
the file as it stood in October 2026, which contained neither a gate nor a
same-repo predicate anywhere: the lane was simply open.

The three ways a check like that lies, all of which have bitten this org:

  1. A guard one level too deep. maxi-config#345/#346 had the same-repo
     predicate present, inside a larger expression whose
     `vars.CI_ENFORCEMENT_MODE == 'strict'` disjunct admitted every pull
     request on its own. Every substring assertion passed; the job ran on the
     fleet anyway. So the assertion here EVALUATES the condition under a
     concrete event context rather than looking for a fragment of it.

  2. A guard that cannot fire. A step-level `if:` inside a `container:` job is
     not a boundary: GitHub pulls and starts the container before the first
     step runs, and the container image is built from the PR's Dockerfile. A
     gate there executes inside exactly the code it exists to keep off the
     machine, and it reads as handled. So a `container:` job is required to
     carry its guard at the JOB level, which is where the decision to hand out
     a fleet runner is actually made.

  3. A guard that was never checked. Every assertion here is driven by a
     population derived from the workflow files, so a self-hosted job added
     later is in scope without anyone remembering to extend this file, and
     `test_the_suite_can_fail` runs the checker against the pre-fix shape to
     prove the checker is not vacuous.

WHAT THIS DOES NOT CLAIM.

For `pull_request`, GitHub runs the workflow file from the PR's merge commit,
so a fork can edit this gate, or add a job that was never here, and no
condition in this repository constrains a job that does not exist yet. This
file checks the DECLARED lanes. The boundary for the rest is the organisation's
"self-hosted runners for fork pull requests" setting plus required approval for
outside contributors. Read a green here as "the lanes we ship are guarded",
not as "a fork cannot reach the fleet".

The `merge_group` and `workflow_dispatch` arms of the fleet gate are inert in
this repository: `ci.yml` triggers on `pull_request` only. They are carried
anyway, because a workflow that grows a trigger should not have to grow a gate.
"""

from __future__ import annotations

import json
import pathlib
import re
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

# The numeric sender ids ci/review-trusted-actors.toml pins. Matched as
# integers because a login can be reassigned and an id cannot. `264883562` is
# maxi-tools-auth[bot], which opens the fan-out PRs this repository actually
# receives, so a gate that dropped it would stop the org's own automation.
TRUSTED_SENDER_IDS = (874012, 264883562)

# Self-hosted pools, matched against the `runs-on` label list. `nas-unstick` is
# a separate single-purpose pool; listing it means a future pull_request job
# routed there is in scope rather than quietly out of it.
SELF_HOSTED_LABELS = frozenset({"self-hosted", "nas-unstick"})

# Every value a condition may read that this file does not pin. `vars.*` and
# `needs.*` are free by construction: a guard that holds only for one setting
# of a repository variable is not a guard, and the qodana.yml defect above was
# exactly that. Both settings are evaluated for every job.
FREE_VARS = (
    {},
    {"CI_ENFORCEMENT_MODE": "strict"},
    {"CI_ENFORCEMENT_MODE": "degraded"},
)

# Event contexts a JOB-LEVEL guard must skip, and a trust-gate STEP must fire
# on. A guard holds only if the job is skipped in ALL of them.
#
# fork: an outside contributor's pull request. Nobody but a writer can create
# this, so it is the case the repository's own token cannot police.
#
# untrusted_dispatch: a writer dispatches CI at a branch of their own.
# `gh workflow run --ref` accepts any ref, so a dispatch is a trigger, not a
# statement about who wrote the tree. Inert in ci.yml today, live the moment a
# trigger is added.
UNTRUSTED_CONTEXTS = {
    "fork": {
        "github.event_name": "pull_request",
        "github.event.action": "opened",
        "github.event.sender.id": 4242,
        "github.event.sender.login": "outside-contributor",
        "github.actor": "outside-contributor",
        "github.repository": "maxi-tools/rlvgl",
        "github.event.pull_request.number": 1,
        "github.event.pull_request.head.repo.full_name": "outside-contributor/rlvgl",
        "github.event.pull_request.head.sha": "0" * 40,
        "github.event.pull_request.head.ref": "patch-1",
    },
    "untrusted_dispatch": {
        "github.event_name": "workflow_dispatch",
        "github.event.action": "workflow_dispatch",
        "github.event.sender.id": 4242,
        "github.event.sender.login": "outside-contributor",
        "github.actor": "outside-contributor",
        "github.repository": "maxi-tools/rlvgl",
    },
}

# Events a guard must NOT block. A gate that is too tight is a self-inflicted
# outage, and it is the failure mode a test that only ever asserts "fails for
# forks" cannot see.
TRUSTED_EVENTS = {
    "trusted_push": {
        "github.event_name": "push",
        "github.event.action": "push",
        "github.event.sender.id": 874012,
        "github.event.sender.login": "maxiboch",
        "github.actor": "maxiboch",
        "github.repository": "maxi-tools/rlvgl",
        "github.ref": "refs/heads/main",
    },
}

# DOCUMENTED RESIDUE, and the reason this is a named constant rather than
# another line in UNTRUSTED_CONTEXTS.
#
# A `synchronize` sent by the owner is trigger authorization, not commit
# provenance: a collaborator pushes to a same-repository pull request branch,
# the owner pushes one follow-up commit, and the resulting owner-sent
# `synchronize` still carries the collaborator's code in the head tree. maxi-config
# records the same residue against its own lanes and accepts it there -- the
# mitigation is a read-only, scoped token rather than a stricter predicate,
# because no predicate on the event can recover who wrote the tree.
#
# Asserting this context FAILS would demand a guard that cannot be written,
# and would make this suite reject the fleet's own gate. It is asserted
# instead to DOCUMENT that the fleet gate admits it, so the acceptance is
# visible and revisited deliberately rather than discovered later.
COLLABORATOR_RESIDUE = {
    "github.event_name": "pull_request",
    "github.event.action": "synchronize",
    # The owner's push, carrying a collaborator's tree.
    "github.event.sender.id": 874012,
    "github.event.sender.login": "maxiboch",
    "github.actor": "maxiboch",
    "github.repository": "maxi-tools/rlvgl",
    "github.event.pull_request.number": 2,
    "github.event.pull_request.head.repo.full_name": "maxi-tools/rlvgl",
    "github.event.pull_request.head.sha": "1" * 40,
    "github.event.pull_request.head.ref": "feature",
}


# --------------------------------------------------------------------------
# A small evaluator for the subset of GitHub expression syntax this file's
# conditions use.
#
# Not a general implementation, and deliberately so: it handles `!`, `&&`,
# `||`, `==`, `!=`, parentheses, single-quoted strings, the `contains` and
# `startsWith` functions, and dotted context lookups. Anything else raises,
# which fails the assertion loudly rather than silently reading as a guard --
# a condition this file cannot evaluate must never be counted as a guard.
# --------------------------------------------------------------------------

_TOKEN = re.compile(
    r"""\s*(?:
        (?P<op>==|!=|>=|<=|&&|\|\||!|\(|\)|,|\[|\])
      | (?P<str>'(?:[^']|'')*')
      | (?P<num>\d+)
      | (?P<name>[A-Za-z_][A-Za-z0-9_-]*(?:\.(?:[A-Za-z0-9_-]+|\*))*)
    )""",
    re.VERBOSE,
)

# `github.event.pull_request.labels.*.name` -- GitHub's object filter, which
# projects an array of objects to an array of one of their fields.
# `contains(<that>, 'run-qodana')` is then a label test. qodana.yml is the one
# workflow here that spells a guard this way, and a tokenizer that cannot read
# it would fail a correct file.
_OBJECT_FILTER = re.compile(
    r"^([A-Za-z_][A-Za-z0-9_.-]*)\.\*\.([A-Za-z_][A-Za-z0-9_.-]*)$"
)


def _tokenize(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    pos = 0
    while pos < len(text):
        if text[pos].isspace():
            pos += 1
            continue
        m = _TOKEN.match(text, pos)
        if not m:
            raise ValueError(f"cannot tokenize at {text[pos : pos + 30]!r}")
        kind = m.lastgroup
        assert kind is not None
        out.append((kind, m.group(kind)))
        pos = m.end()
    return out


class _Parser:
    """Recursive descent over the token list. Truthiness follows GitHub's:
    the empty string, zero, false, null and the empty array are falsy."""

    def __init__(self, tokens: list[tuple[str, str]], context: dict[str, object]):
        self.tokens = tokens
        self.i = 0
        self.context = context

    def peek(self) -> tuple[str, str] | None:
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def take(self) -> tuple[str, str]:
        tok = self.tokens[self.i]
        self.i += 1
        return tok

    def parse(self) -> bool:
        value = self.or_expr()
        if self.peek() is not None:
            raise ValueError(f"trailing tokens at {self.peek()}")
        return value

    def or_expr(self) -> bool:
        value = self.and_expr()
        while (tok := self.peek()) and tok[1] == "||":
            self.take()
            # GitHub's `||` returns an operand, not a bool; only its
            # truthiness is used here, and both operands are already bools
            # because every leaf resolves to one.
            value = self.and_expr() or value
        return value

    def and_expr(self) -> bool:
        value = self.unary()
        while (tok := self.peek()) and tok[1] == "&&":
            self.take()
            value = self.unary() and value
        return value

    def unary(self) -> bool:
        tok = self.peek()
        if tok and tok[1] == "!":
            self.take()
            return not self.unary()
        return self.primary()

    def primary(self) -> bool:
        kind, text = self.take()
        if text == "(":
            value = self.or_expr()
            closing = self.take()
            if closing[1] != ")":
                raise ValueError(f"expected ), got {closing[1]!r}")
            return value
        if kind == "str":
            return self.comparison(text[1:-1].replace("''", "'"))
        if kind == "num":
            return self.comparison(int(text))
        if kind == "name":
            # A context path is an OPERAND, not a finished condition:
            # `github.event_name != 'pull_request'` is the commonest shape in
            # every guard in this repository, and reading the bare path as a
            # condition would leave the operator unconsumed and raise on
            # trailing tokens -- which reads as "this file cannot evaluate any
            # condition" rather than as the bug it is.
            filtered = _OBJECT_FILTER.match(text)
            if filtered:
                # A projection, so the value is an ARRAY whatever the labels
                # on this event are. Empty under every context here, which is
                # what makes a label-gated arm of a guard read as closed -- and
                # is the honest answer, because no context in this file
                # carries labels.
                return bool(self.comparison([]))
            if (tok := self.peek()) and tok[1] == "(":
                return bool(self.comparison(self.call(text)))
            # A missing context property is null, which is falsy -- the same
            # reading GitHub gives a `pull_request` payload field on an
            # `issue_comment` event.
            return self.comparison(self.context.get(text))
        raise ValueError(f"unexpected token {text!r}")

    def comparison(self, left: object) -> bool:
        tok = self.peek()
        if tok and tok[1] in ("==", "!="):
            self.take()
            right = self.operand()
            # GitHub compares case-insensitively when both sides are strings,
            # and casts when the types differ, so a repo name compared against
            # a login cannot pass by case.
            if isinstance(left, str) and isinstance(right, str):
                equal = left.lower() == right.lower()
            else:
                equal = left == right
            return equal if tok[1] == "==" else not equal
        return bool(left)

    def operand(self) -> object:
        kind, text = self.take()
        if kind == "str":
            return text[1:-1].replace("''", "'")
        if kind == "num":
            return int(text)
        if kind == "name":
            if (tok := self.peek()) and tok[1] == "(":
                return self.call(text)
            return self.context.get(text)
        raise ValueError(f"unexpected operand {text!r}")

    def call(self, name: str) -> object:
        self.take()  # (
        args: list[object] = []
        if (tok := self.peek()) and tok[1] == ")":
            self.take()
        else:
            while True:
                args.append(self.operand())
                tok = self.take()
                if tok[1] == ")":
                    break
                if tok[1] != ",":
                    raise ValueError(f"expected , or ) in {name}(), got {tok[1]!r}")
        if name == "contains":
            haystack, needle = args
            if isinstance(haystack, list):
                return any(str(needle).lower() == str(x).lower() for x in haystack)
            return str(needle).lower() in str(haystack).lower()
        if name == "startsWith":
            return str(args[0]).lower().startswith(str(args[1]).lower())
        if name == "endsWith":
            return str(args[0]).lower().endswith(str(args[1]).lower())
        if name == "fromJSON":
            # `fromJSON('["a","b"]')` is how every guard in this repository
            # spells a list literal for `contains`.
            raw = args[0]
            if not isinstance(raw, str):
                return raw
            try:
                return json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"fromJSON({raw!r}) is not JSON: {exc}") from exc
        if name in ("success", "always"):
            # Status functions on a job `if:` say what happened to the OTHER
            # jobs, never who sent the event. Treated as satisfied, so they
            # neither add nor remove trust -- maxi-review's `guaranteed-review`
            # carries `success() &&` ahead of a real guard, and reading it as
            # a term to satisfy would make the guard unreachable to check.
            return True
        if name in ("failure", "cancelled"):
            # Same reasoning, inverted: a lane that runs only when something
            # else FAILED is a different shape of lane, and none of these
            # workflows use it on a self-hosted job. Asserted rather than
            # ignored so a future use is a loud failure here.
            raise ValueError(
                f"{name}() guards a self-hosted lane; add a context for it "
                f"rather than assuming it is neutral"
            )
        raise ValueError(f"unsupported function {name}()")


def evaluate(condition: str, context: dict[str, object]) -> bool:
    """Does `condition` hold under `context`? Raises on syntax this file does
    not implement, so an unevaluable condition is never a silent pass.

    The `${{ }}` wrapper is stripped HERE rather than at each call site: it is
    optional in GitHub, the shipped fleet gate carries it and every job-level
    `if:` does not, and a wrapper that reached the tokenizer would fail every
    assertion in the file with a parse error -- indistinguishable from "this
    file cannot evaluate anything".
    """
    text = condition.strip()
    if text.startswith("${{") and text.endswith("}}"):
        text = text[3:-2].strip()
    return _Parser(_tokenize(text), context).parse()


def condition_of(value: object) -> str | None:
    """The expression behind a YAML `if:`, with the `${{ }}` wrapper GitHub
    accepts and does not require removed."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"`if:` is not a string: {value!r}")
    text = value.strip()
    if text.startswith("${{") and text.endswith("}}"):
        text = text[3:-2]
    return text.strip()


def _contexts(base: dict[str, object], variables: tuple[dict[str, str], ...]):
    for extra_vars in variables:
        context = dict(base)
        context.update({f"vars.{k}": v for k, v in extra_vars.items()})
        yield context


def job_admits_untrusted(condition: str | None) -> bool:
    """Does this JOB-level condition let a self-hosted job run under an
    untrusted event? True means the lane is open and the caller must fail.

    A missing condition admits everything, which is the defect this file was
    written for. A present condition must be false in EVERY untrusted context
    under EVERY setting of a free variable -- one permissive assignment of
    `vars.*` is enough to reopen the lane, which is the qodana.yml defect.
    """
    if condition is None:
        return True
    return any(
        evaluate(condition, context)
        for base in UNTRUSTED_CONTEXTS.values()
        for context in _contexts(base, FREE_VARS)
    )


def job_blocks_trusted_event(condition: str | None) -> bool:
    """The mirror image: a guard that also refuses post-merge code to main is
    a guard that will wedge the repository, not protect it."""
    if condition is None:
        return False
    return any(
        not evaluate(condition, context)
        for base in TRUSTED_EVENTS.values()
        for context in _contexts(base, FREE_VARS)
    )


def gate_fires_on_untrusted(condition: str | None) -> bool:
    """Does this trust-gate STEP fire under an untrusted event?

    INVERTED relative to `job_admits_untrusted`, and the inversion is the whole
    design of a gate step: its `if:` selects the events it REFUSES, and its body
    is `exit 1`. Reading it with the job-level polarity would conclude that the
    fleet gate admits forks -- because it does admit them, in exactly the sense
    that it fires on them.

    True means the gate does NOT hold: there is an untrusted event on which the
    step does not fire, so the job proceeds to checkout.
    """
    if condition is None:
        return True
    return any(
        not evaluate(condition, context)
        for base in UNTRUSTED_CONTEXTS.values()
        for context in _contexts(base, FREE_VARS)
    )


def gate_fires_on_trusted(condition: str | None) -> bool:
    """A gate that fires on post-merge code is a self-inflicted outage."""
    if condition is None:
        return True
    return any(
        evaluate(condition, context)
        for base in TRUSTED_EVENTS.values()
        for context in _contexts(base, FREE_VARS)
    )


# --------------------------------------------------------------------------
# The population, derived from the workflow files.
# --------------------------------------------------------------------------


def workflow_files() -> list[pathlib.Path]:
    return sorted(WORKFLOWS.glob("*.yml"))


def triggers_of(doc: dict) -> set[str]:
    """Every event name this workflow can be fired by.

    `on:` parses as the boolean True under YAML 1.1, which is why the key is
    looked up both ways.

    The set matters rather than just the presence of `pull_request`: a
    workflow that triggers on `pull_request` alone cannot be fired by a
    dispatch or a push, so asserting a guard against those contexts would
    demand a condition against events the workflow will never see. maxi-review's
    `lint-gate` is the live example -- its guard has no `event_name !=
    'pull_request'` disjunct because that workflow has no `push` trigger, and a
    suite that demanded one would fail a correct file.
    """
    on = doc.get("on", doc.get(True))
    if on is None:
        return set()
    if isinstance(on, str):
        return {on}
    if isinstance(on, list):
        return {str(x) for x in on}
    if isinstance(on, dict):
        return {str(x) for x in on}
    return set()


def labels_of(job: dict) -> list[str]:
    runs_on = job.get("runs-on")
    if runs_on is None:
        return []
    if isinstance(runs_on, str):
        return [runs_on]
    if isinstance(runs_on, list):
        return [str(x) for x in runs_on]
    # A routed runner (`${{ ... }}`) is not statically decidable. Treated as
    # self-hosted so that dynamic routing cannot smuggle a lane past this file.
    return [str(runs_on)]


def is_self_hosted(job: dict) -> bool:
    labels = labels_of(job)
    if not labels:
        return False
    return any(
        label in SELF_HOSTED_LABELS or label.startswith("${{") for label in labels
    )


def self_hosted_pr_jobs() -> list[tuple[pathlib.Path, str, dict]]:
    """(file, job name, job) for every job a fork pull request can reach."""
    population = []
    for path in workflow_files():
        doc = yaml.safe_load(path.read_text()) or {}
        if "pull_request" not in triggers_of(doc):
            continue
        for name, job in (doc.get("jobs") or {}).items():
            if not isinstance(job, dict) or not is_self_hosted(job):
                continue
            population.append((path, name, job))
    return population


def needs_of(job: dict) -> list[str]:
    needs = job.get("needs")
    if needs is None:
        return []
    if isinstance(needs, str):
        return [needs]
    if isinstance(needs, list):
        return [str(x) for x in needs]
    return []


def guarded_jobs_of(doc: dict) -> set[str]:
    """Job names whose own `if:` skips them in at least one untrusted context
    the workflow can actually receive.

    This is how trust propagates along `needs:`. GitHub does not run a
    dependent job when its dependency is skipped, so a job with no guard of
    its own is still off the fleet if every job it needs is guarded --
    maxi-review's `guaranteed-review` relies on exactly that, hanging off
    `lint-gate`. Asserting each job in isolation would demand a second copy of
    a predicate the graph already enforces, and the copies would drift.
    """
    triggers = triggers_of(doc)
    guarded: set[str] = set()
    for name, job in (doc.get("jobs") or {}).items():
        if not isinstance(job, dict):
            continue
        condition = condition_of(job.get("if"))
        if condition is None:
            continue
        if any(
            event in triggers and evaluate(condition, context)
            for event, base in UNTRUSTED_CONTEXTS.items()
            for context in _contexts(base, FREE_VARS)
        ):
            guarded.add(name)
    return guarded


def job_reaches_untrusted(path: pathlib.Path, name: str, job: dict) -> bool:
    """Can this job land on the fleet under an untrusted event?

    The job's own guard decides it, unless the guard is absent and the job
    inherits a closed one through `needs:`. Returns True when the lane is open.
    """
    doc = yaml.safe_load(path.read_text()) or {}
    triggers = triggers_of(doc)
    condition = condition_of(job.get("if"))
    if condition is None:
        dependencies = needs_of(job)
        if not dependencies:
            return True
        guarded = guarded_jobs_of(doc)
        return not all(dep in guarded for dep in dependencies)
    return any(
        event in triggers and evaluate(condition, context)
        for event, base in UNTRUSTED_CONTEXTS.items()
        for context in _contexts(base, FREE_VARS)
    )


def first_step(job: dict) -> dict | None:
    steps = job.get("steps")
    if not isinstance(steps, list) or not steps:
        return None
    return steps[0] if isinstance(steps[0], dict) else None


# --------------------------------------------------------------------------
# Assertions.
# --------------------------------------------------------------------------


class ThePopulationIsReal(unittest.TestCase):
    """Non-vacuity. Every assertion below is driven by a list computed from the
    workflow files, so a renamed file, an unparseable one, or a workflow whose
    jobs all moved to a hosted pool would satisfy them all by being empty."""

    def test_workflows_directory_is_populated(self):
        self.assertGreaterEqual(
            len(workflow_files()), 5, "no workflows found -- wrong root?"
        )

    def test_the_population_is_not_empty(self):
        population = self_hosted_pr_jobs()
        self.assertTrue(
            population,
            "no self-hosted pull_request jobs found; this suite has nothing "
            "to guard and would pass on any workflow file at all",
        )

    def test_the_arm64_lane_is_in_the_population(self):
        """Names the specific lane the fix exists for, so that a refactor that
        moved rlvgl's ARM64 CI elsewhere cannot quietly empty the population."""
        found = {
            (path.name, name)
            for path, name, _ in self_hosted_pr_jobs()
            if any("ARM64" in label for label in labels_of(_))
        }
        self.assertIn(("ci.yml", "image"), found)
        self.assertIn(("ci.yml", "build"), found)


class SelfHostedJobsRefuseUntrustedSenders(unittest.TestCase):
    """The guard itself, one job at a time."""

    def jobs(self):
        for path, name, job in self_hosted_pr_jobs():
            with self.subTest(workflow=path.name, job=name):
                yield path, name, job

    def test_no_self_hosted_pr_job_admits_fork_code(self):
        for path, name, job in self.jobs():
            self.assertFalse(
                job_reaches_untrusted(path, name, job),
                f"{path.name}: job {name!r} runs on a self-hosted runner with "
                f"no condition excluding untrusted senders, so a fork pull "
                f"request executes its code on the fleet",
            )

    def test_no_guard_blocks_a_post_merge_push_to_main(self):
        """A gate that is too tight is a self-inflicted outage, and this file
        would otherwise be the last place it was noticed.

        SCOPED TO `ci.yml`, deliberately. The property is not universal, and
        asserting it fleet-wide would demand a change to lanes that never
        claimed it: `qodana.yml`'s `qodana-full` is a label-gated advisory
        scan whose own guard declines a bare push unless
        `vars.CI_ENFORCEMENT_MODE == 'strict'`, and that is the design maxi-config
        ships. It is maxi-config-owned and fanned out to ~49 repositories;
        tightening it here would be an unrequested behaviour change to code
        this card does not own, made from a security fix in a different
        repository.

        `ci.yml` is the file this change edits, and there the property is real:
        every job in it is the repository's only ARM64 verification, so a job
        that stopped running would mean the lane silently stopped verifying
        anything -- which is how a guard becomes indistinguishable from an
        outage nobody is watching for.
        """
        doc = yaml.safe_load((WORKFLOWS / "ci.yml").read_text()) or {}
        if "push" not in triggers_of(doc):
            self.skipTest("ci.yml has no push trigger; nothing to block")
        for name, job in (doc.get("jobs") or {}).items():
            if not isinstance(job, dict) or not is_self_hosted(job):
                continue
            with self.subTest(job=name):
                self.assertFalse(
                    job_blocks_trusted_event(condition_of(job.get("if"))),
                    f"ci.yml: job {name!r} is skipped for a post-merge push "
                    f"to main; the guard is tighter than the lane it protects",
                )


class ContainerJobsGuardAtTheJobLevel(unittest.TestCase):
    """A `container:` job's image is built from the PR's Dockerfile and pulled
    before the first step runs. A step-level gate there is code the PR chose,
    executing inside code the PR chose -- it cannot be the boundary, and its
    presence reads as though it were."""

    def container_jobs(self):
        for path, name, job in self_hosted_pr_jobs():
            if isinstance(job.get("container"), (dict, str)):
                with self.subTest(workflow=path.name, job=name):
                    yield path, name, job

    def test_every_container_job_has_a_job_level_guard(self):
        jobs = list(self.container_jobs())
        self.assertTrue(jobs, "no container jobs found -- nothing exercised")
        for path, name, job in jobs:
            self.assertIsNotNone(
                condition_of(job.get("if")),
                f"{path.name}: job {name!r} runs a PR-built container on a "
                f"self-hosted runner with no job-level guard",
            )

    def test_the_guard_is_not_a_step_inside_a_pr_built_container(self):
        for path, name, job in self.container_jobs():
            step = first_step(job)
            self.assertIsNotNone(step, f"{path.name}: job {name!r} has no steps at all")
            assert step is not None
            self.assertNotEqual(
                (step.get("name") or "").strip().lower(),
                "trust gate",
                f"{path.name}: job {name!r} carries its trust gate as a step. "
                f"That step runs inside the container this job pulls, which "
                f"was built from the pull request's own Dockerfile -- it "
                f"cannot keep that code off the runner",
            )


class GuardsSurviveATriggerBeingAdded(unittest.TestCase):
    """A guard is only as good as the events it is evaluated against, and the
    set of events a workflow can receive CHANGES. This suite found its own
    blind spot here, and the assertion is the one that would have caught it.

    The guard shipped in the first version of this change was:

        github.event_name != 'pull_request' ||
        github.event.pull_request.head.repo.full_name == github.repository

    That is complete for `pull_request` and it is also, read carefully,
    an OPEN DOOR for `workflow_dispatch` -- for a dispatch the first
    disjunct is simply true, so anyone with write access could point the
    workflow at a branch of their own and have the fleet build it.
    `gh workflow run --ref` accepts any ref, which is why maxi-config pairs
    the same-repo test with a second clause pinning dispatch to the owner.

    `ci.yml` declares no `workflow_dispatch` trigger, so the gap was inert
    and every other assertion in this file stayed green. The suite scoped
    each context to the triggers its workflow actually declares -- correctly,
    since a workflow that cannot be fired by a dispatch cannot be opened by
    one -- and that scoping is exactly what made the gap invisible. A check
    that only asks "is today's event handled" cannot see "is tomorrow's
    event handled".

    So: each guard is evaluated against EVERY untrusted context, including
    ones this workflow cannot currently receive. A guard that admits an
    unreachable context is not wrong yet, but it is a trap for whoever adds
    the trigger -- and the whole value of writing the clause down now is
    that the trap is disarmed before anyone falls into it.
    """

    def test_no_guard_admits_an_untrusted_context_it_cannot_currently_receive(self):
        """Evaluated against every context, NOT filtered by declared triggers.

        The filter belongs in `job_reaches_untrusted`, which answers "can this
        happen today". This answers "would this still hold if it could", which
        is the question that catches a guard written for the trigger set its
        author happened to be looking at.
        """
        for path, name, job in self_hosted_pr_jobs():
            condition = condition_of(job.get("if"))
            if condition is None:
                continue  # inherits through `needs:`; covered elsewhere.
            with self.subTest(workflow=path.name, job=name):
                self.assertFalse(
                    job_admits_untrusted(condition),
                    f"{path.name}: job {name!r} admits at least one untrusted "
                    f"event context. If this workflow cannot currently be "
                    f"fired by that event the guard is merely premature; if it "
                    f"can, the lane is open. Either way the clause pinning "
                    f"that event belongs here now, before someone adds the "
                    f"trigger.",
                )

    def test_the_dispatch_clause_is_present_on_every_fleet_job(self):
        """Named explicitly, because the failure is a plausible-looking
        one-clause guard rather than a missing guard.

        maxi-config's codeql and clippy templates carry both clauses; a guard
        that keeps only the first reads as complete because it is the shape
        most of the examples in the wild use.
        """
        doc = yaml.safe_load((WORKFLOWS / "ci.yml").read_text()) or {}
        for name, job in (doc.get("jobs") or {}).items():
            if not isinstance(job, dict) or not is_self_hosted(job):
                continue
            # `polish` is gated on push alone, so for it the dispatch question
            # is already settled rather than unanswered. The dispatch clause is
            # only owed by jobs that admit events other than push, and a
            # `pull_request`-only workflow cannot be dispatched at all.
            if condition_of(job.get("if")) == "github.event_name == 'push'":
                continue
            with self.subTest(job=name):
                condition = condition_of(job.get("if")) or ""
                self.assertIn(
                    "github.event_name != 'workflow_dispatch'",
                    condition,
                    f"ci.yml: job {name!r} has no workflow_dispatch clause. "
                    f"'event_name != pull_request' is true for a dispatch, so "
                    f"without this clause any writer can dispatch this workflow "
                    f"at a branch of their own",
                )
                self.assertIn(
                    "github.event.sender.id == 874012",
                    condition,
                    f"ci.yml: job {name!r} does not pin workflow_dispatch to a "
                    f"sender id. The id, not the login: a login can be "
                    f"reassigned and the guard would silently follow it",
                )

    def test_a_single_clause_guard_is_reported(self):
        """The fixture is the exact expression this file shipped first, so a
        regression to it fails here rather than in production."""
        single_clause = (
            "github.event_name != 'pull_request' ||\n"
            "github.event.pull_request.head.repo.full_name == github.repository"
        )
        self.assertTrue(
            job_admits_untrusted(single_clause),
            "the one-clause same-repo guard is no longer reported as admitting "
            "an untrusted dispatch, so this file no longer distinguishes it "
            "from the two-clause form",
        )
        two_clause = (
            "(github.event_name != 'pull_request' ||\n"
            " github.event.pull_request.head.repo.full_name == github.repository)"
            " &&\n(github.event_name != 'workflow_dispatch' ||\n"
            " github.event.sender.id == 874012)"
        )
        self.assertFalse(
            job_admits_untrusted(two_clause),
            "the two-clause guard is reported as admitting an untrusted "
            "dispatch; the dispatch clause is not doing anything",
        )

    def test_the_parentheses_are_load_bearing(self):
        """`||` binds looser than `&&` in a GitHub expression, so dropping the
        parens around the first clause does not weaken the guard visibly -- it
        silently regroups it:

            A || B && C   is   A || (B && C)      <- A alone admits a dispatch

        Dropping one pair of brackets from the shipped expression therefore
        re-opens the dispatch door while leaving every token in place, so no
        substring or token-presence check can see it. This is the same class
        of edit as the inverted `!=` in the fleet gate: invisible to a
        grep-style check, fully effective against a real event.
        """
        regrouped = (
            "github.event_name != 'pull_request' ||\n"
            "github.event.pull_request.head.repo.full_name == github.repository &&\n"
            "(github.event_name != 'workflow_dispatch' ||\n"
            " github.event.sender.id == 874012)"
        )
        self.assertTrue(
            job_admits_untrusted(regrouped),
            "the regrouped one-clause-plus-and guard is no longer reported as "
            "open. If this stops holding, the fixture is not exercising "
            "operator precedence and the paren assertion above proves nothing",
        )


class TheImageJobGatesBeforeCheckout(unittest.TestCase):
    """`image` is the one job with no container: it runs directly on the fleet
    runner, holds `packages: write`, builds the PR's Dockerfile and pushes the
    result. It is the first thing a fork reaches and the only place a sender
    check can run before any PR-controlled file is read."""

    def image_job(self) -> dict:
        doc = yaml.safe_load((WORKFLOWS / "ci.yml").read_text())
        return doc["jobs"]["image"]

    def test_image_runs_on_the_arm64_fleet_with_package_write(self):
        """Non-vacuity for the assertions below: if the lane were re-routed,
        they would be checking a job that no longer publishes anything."""
        job = self.image_job()
        self.assertIn("ARM64", labels_of(job))
        self.assertEqual(job.get("permissions", {}).get("packages"), "write")

    def test_image_does_not_check_out_before_its_gate(self):
        """The property is ORDER, not presence: a gate after `checkout` has
        already materialised the PR's tree on the runner."""
        job = self.image_job()
        steps = job.get("steps") or []
        gate_at = None
        checkout_at = None
        for index, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            name = (step.get("name") or "").strip().lower()
            if name == "trust gate":
                gate_at = index
            uses = str(step.get("uses", ""))
            if uses.startswith("actions/checkout") and checkout_at is None:
                checkout_at = index
        self.assertIsNotNone(
            gate_at, "ci.yml: the image job has no trust gate step at all"
        )
        self.assertIsNotNone(
            checkout_at, "ci.yml: the image job does not check out; re-read it"
        )
        assert gate_at is not None and checkout_at is not None
        self.assertLess(
            gate_at,
            checkout_at,
            "ci.yml: the image job checks out before its trust gate runs, so "
            "the pull request's tree is already on the fleet runner",
        )

    def test_the_gate_itself_refuses_untrusted_senders(self):
        """The step's own `if:` is what decides whether it fires. A step named
        'trust gate' whose condition selects only TRUSTED senders is the
        qodana.yml defect with a reassuring name on it: it reads as a gate and
        never fires, so the job proceeds to checkout unchecked. The polarity is
        inverted relative to a job-level guard, and `gate_fires_on_untrusted`
        is the function that accounts for that."""
        job = self.image_job()
        for step in job.get("steps") or []:
            if (
                isinstance(step, dict)
                and (step.get("name") or "").strip().lower() == "trust gate"
            ):
                condition = condition_of(step.get("if"))
                self.assertFalse(
                    gate_fires_on_untrusted(condition),
                    "ci.yml: the image job's trust gate step does not fire on "
                    "every untrusted event, so an untrusted sender reaches "
                    "checkout. A gate step's `if:` selects the events it "
                    "REFUSES; read with job-level polarity this would pass.",
                )
                self.assertFalse(
                    gate_fires_on_trusted(condition),
                    "ci.yml: the image job's trust gate step fires on a "
                    "post-merge push to main",
                )
                # The fleet gate names its trusted senders by NUMERIC ID, and
                # both of them. Checked here rather than inferred from the
                # behavioural assertions above because they cannot tell the
                # two apart: an expression admitting only 874012 and one
                # admitting only maxi-tools-auth[bot] both refuse every
                # untrusted context in this file, because neither id is the
                # sender in any of them. What distinguishes them is who they
                # let IN -- the owner, and the org's own fan-out automation.
                for sender_id in TRUSTED_SENDER_IDS:
                    self.assertIn(
                        f"github.event.sender.id == {sender_id}",
                        condition or "",
                        f"ci.yml: the trust gate does not admit sender "
                        f"{sender_id}. Ids, not logins: a login can be "
                        f"reassigned and the gate would silently follow it.",
                    )
                return
        self.fail("ci.yml: no 'trust gate' step in the image job")


class TheSuiteCanFail(unittest.TestCase):
    """The checker, run against the shape this repository had in October 2026.

    An assertion suite that cannot fail is the failure mode maxi-config's own
    fork-guard suite was written against, and the only way to know this one
    still bites is to show it biting.
    """

    # Verbatim from ci.yml as it stood before this fix: a self-hosted ARM64 job
    # on `pull_request`, `packages: write`, checkout first, no gate anywhere.
    PRE_FIX = """
name: CI
on:
  pull_request:
    branches: [main]
jobs:
  image:
    runs-on: [self-hosted, Linux, ARM64]
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v4
      - name: Build and push arm64 toolchain image
        run: docker build -t ghcr.io/maxi-tools/rlvgl:${{ github.sha }} .
"""

    # The qodana.yml defect, transplanted: the same-repo predicate IS present,
    # one level down, behind a disjunct that admits every pull request alone.
    DISJUNCT = """
name: CI
on:
  pull_request:
    branches: [main]
jobs:
  build:
    if: >-
      github.event_name == 'push' ||
      vars.CI_ENFORCEMENT_MODE == 'strict' ||
      (github.event_name == 'pull_request' &&
       github.event.pull_request.head.repo.full_name == github.repository)
    runs-on: [self-hosted, Linux, ARM64]
    steps:
      - uses: actions/checkout@v4
"""

    # A guard so tight it refuses post-merge code. The mirror defect.
    OVER_TIGHT = """
name: CI
on:
  pull_request:
    branches: [main]
jobs:
  build:
    if: github.event_name == 'pull_request' &&
        github.event.pull_request.head.repo.full_name == github.repository
    runs-on: [self-hosted, Linux, ARM64]
    steps:
      - uses: actions/checkout@v4
"""

    def job_from(self, text: str) -> dict:
        doc = yaml.safe_load(text)
        return next(iter(doc["jobs"].values()))

    def test_the_pre_fix_lane_is_reported_open(self):
        job = self.job_from(self.PRE_FIX)
        self.assertTrue(
            job_admits_untrusted(condition_of(job.get("if"))),
            "the pre-fix lane was not detected as open; the assertions in "
            "SelfHostedJobsRefuseUntrustedSenders cannot fail",
        )

    def test_a_same_repo_predicate_buried_in_a_disjunct_is_reported_open(self):
        job = self.job_from(self.DISJUNCT)
        condition = condition_of(job.get("if"))
        self.assertIn(
            "head.repo.full_name",
            condition or "",
            "fixture lost the same-repo predicate; this test would pass for "
            "the wrong reason",
        )
        self.assertTrue(
            job_admits_untrusted(condition),
            "a guard whose only same-repo test sits behind a disjunct that "
            "admits every pull request was accepted as a guard -- this is the "
            "qodana.yml defect and the reason this file evaluates conditions "
            "instead of matching fragments",
        )

    def test_a_guard_that_blocks_trusted_pushes_is_reported(self):
        job = self.job_from(self.OVER_TIGHT)
        self.assertTrue(
            job_blocks_trusted_event(condition_of(job.get("if"))),
            "a guard that refuses post-merge pushes was not detected",
        )

    def test_the_fleet_gate_re_passes(self):
        """The shipped expression, checked against the same contexts the real
        files are checked with, so a typo in the copy cannot read as coverage.

        Gate polarity: the step fires to REFUSE, so the fleet gate holding means
        it fires on every untrusted context and on none of the trusted ones.
        """
        gate = (
            "${{ github.actor != 'dependabot[bot]' && !(github.event_name == 'push'"
            " || github.event_name == 'schedule'"
            " || ((github.event.sender.id == 874012"
            " || github.event.sender.id == 264883562)"
            " && (github.event_name == 'workflow_dispatch'"
            " || (github.event_name == 'pull_request'"
            " && github.event.pull_request.head.repo.full_name == github.repository)))"
            " || (github.event_name == 'merge_group'"
            " && github.event.action == 'checks_requested')) }}"
        )
        self.assertFalse(
            gate_fires_on_untrusted(gate),
            "the fleet trust-gate expression was copied wrong, or this "
            "file's evaluator disagrees with GitHub's",
        )
        self.assertFalse(
            gate_fires_on_trusted(gate),
            "the fleet trust-gate expression fires on a post-merge push to main",
        )

    def test_the_fleet_gate_admits_the_documented_residue(self):
        """Pinned deliberately, not asserted as a failure. maxi-config records
        the same acceptance against its own lanes: an owner-sent
        `synchronize` on a same-repository pull request can carry a
        collaborator's tree, and the mitigation there is a read-only scoped
        token rather than a predicate, because no predicate on the event can
        recover who wrote the tree.

        Recorded so the acceptance is a decision someone can revisit, not a
        behaviour discovered after it matters.
        """
        gate = (
            "${{ github.actor != 'dependabot[bot]' && !(github.event_name == 'push'"
            " || github.event_name == 'schedule'"
            " || ((github.event.sender.id == 874012"
            " || github.event.sender.id == 264883562)"
            " && (github.event_name == 'workflow_dispatch'"
            " || (github.event_name == 'pull_request'"
            " && github.event.pull_request.head.repo.full_name == github.repository)))"
            " || (github.event_name == 'merge_group'"
            " && github.event.action == 'checks_requested')) }}"
        )
        context = dict(COLLABORATOR_RESIDUE)
        context.update({f"vars.{k}": v for k, v in FREE_VARS[1].items()})
        self.assertFalse(
            evaluate(gate, context),
            "the fleet gate now refuses an owner-sent synchronize on a "
            "same-repository pull request. That would be a tightening, not a "
            "defect -- but it invalidates the comment in ci.yml and in "
            "maxi-config that documents the residue, so it must be a "
            "deliberate change to both rather than an accident here.",
        )

    def test_a_gate_missing_its_sender_clause_is_caught(self):
        """The failure mode a substring check cannot see and the qodana.yml
        defect is a cousin of: the gate keeps its name and its shape, and stops
        selecting untrusted senders.

        Dropping the sender-id pair turns the fleet gate into
        `!(push || schedule || (dispatch || same-repo-pr) || merge_group)`,
        which admits EVERY pull request from ANY sender -- forks included.
        `gate_fires_on_untrusted` must report that it no longer holds.
        """
        no_sender_clause = (
            "${{ github.actor != 'dependabot[bot]' && !(github.event_name == 'push'"
            " || github.event_name == 'schedule'"
            " || (github.event_name == 'workflow_dispatch'"
            " || (github.event_name == 'pull_request'"
            " && github.event.pull_request.head.repo.full_name == github.repository))"
            " || (github.event_name == 'merge_group'"
            " && github.event.action == 'checks_requested')) }}"
        )
        self.assertTrue(
            gate_fires_on_untrusted(no_sender_clause),
            "a gate with no sender clause still reads as a guard, so the check "
            "is not looking at the sender clause -- which is the clause that "
            "keeps a same-repository push by a non-trusted writer off the fleet",
        )

    def test_a_gate_whose_sender_clause_is_inverted_is_caught(self):
        """The adjacent typo: `!=` instead of `==` on the sender ids. The
        expression still contains every token a substring check would look
        for, and it admits every fork."""
        inverted = (
            "${{ github.actor != 'dependabot[bot]' && !(github.event_name == 'push'"
            " || github.event_name == 'schedule'"
            " || ((github.event.sender.id != 874012"
            " || github.event.sender.id != 264883562)"
            " && (github.event_name == 'workflow_dispatch'"
            " || (github.event_name == 'pull_request'"
            " && github.event.pull_request.head.repo.full_name == github.repository)))"
            " || (github.event_name == 'merge_group'"
            " && github.event.action == 'checks_requested')) }}"
        )
        self.assertTrue(
            gate_fires_on_untrusted(inverted),
            "an inverted sender comparison still reads as a gate; the check is "
            "evaluating the expression's truth rather than its contents",
        )


class UntrustedJobListing(unittest.TestCase):
    """A report, so that a failure names the offending lanes in one place
    rather than only in a subTest line."""

    def test_no_lane_is_left_open(self):
        open_lanes = [
            f"{path.name}:{name}"
            for path, name, job in self_hosted_pr_jobs()
            if job_reaches_untrusted(path, name, job)
        ]
        self.assertEqual(
            open_lanes, [], f"self-hosted lanes open to untrusted senders: {open_lanes}"
        )


if __name__ == "__main__":
    unittest.main()
