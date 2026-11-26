"""The ready Feature, Model change and Pipeline change run fewer agents (tarifler T3, 0.1.10)

KOLONİ's own checks at a recipe's end (its Checks step) run the tests and have a big or
security-touching change reviewed; these recipes' Tester and general Reviewer steps were a second
layer over them, and each loop round opened every review of its group again. As 0172 thinned
Bugfix:
- Feature: Write the spec (approved) -> Build it -> UI review (the UI designer: KOLONİ's checks
  have no design judgement), back to Build it at most 2 rounds - 3 to 7 agents, not 6 to 16. Its
  Code review, Security review and Test it go: KOLONİ's own Reviewer and Security reviewer still
  look at a big or security-touching change.
- Model change: Plan the experiment -> Experts review the plan -> Build it -> Compare the metrics,
  back to Build it at most 2 rounds (its last loop: where a fix round goes back to) - 4 to 10, not
  6 to 14. Its Run the tests and Review it go.
- Pipeline change: Change the pipeline -> Check the data quality, back at most 2 rounds - 2 to 6,
  not 4 to 10. Its Run the tests and Review it go.
The two followed the project's After a change: with no test step of their own now, they check
their tests and a review, as Feature does - a project at Nothing would leave them unchecked.
Only a row still as KOLONİ drew it (0074 + 0084 + 0170; 0103) is changed: a ready recipe is
KOLONİ's own, the user's are copies. A row under way runs by its own copy of the graph.

Going back draws them as before.

Revision ID: 0195
Revises: 0194
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "0195"
# (Written on the k-tarif-ince branch: re-chained after main's newest at its merge.)
down_revision = "0194"
branch_labels = None
depends_on = None


# As 0074, 0084, 0103 and 0170 wrote them (`app.schemas.RecipeGraph`, version 1): a migration does
# not follow later code.
def _step(id, name, role, **more):
    return {
        "id": id,
        "name": name,
        "who": {"role": role},
        "done_when": "done",
        "if_fails": "ask",
        "ask_me": False,
        "group": None,
        **more,
    }


def _review(id, name, role, **more):
    return _step(id, name, role, done_when="no_findings", **more)


def _graph(steps, way, groups=(), loops=(), checks=None):
    graph = {
        "version": 1,
        "steps": steps,
        "groups": [{"id": id, "name": "All at once, wait for all"} for id in groups],
        "ends": [{"id": "end", "then": "in"}],
        "arrows": [
            {"from": a, "to": b} for a, b in zip(("start", *way), (*way, "end"), strict=True)
        ],
        "loops": [{"from": a, "to": b, "rounds": n} for a, b, n in loops],
    }
    return {**graph, "checks": checks} if checks else graph


# (0170's: tests and a review.)
CHECKS = {
    "tests": True,
    "review": True,
    "docs": False,
    "diagram": False,
    "data": False,
    "slides": False,
    "fix_rounds": None,
}
SPEC = _step("spec", "Write the spec", "Spec writer", ask_me=True)
BUILD = _step("build", "Build it", "Coder")
UI = _review("ui", "UI review", "UI designer")
PLAN = _step("plan", "Plan the experiment", "Data scientist")
EXPERTS = {**_review("experts", "Experts review the plan", None), "who": {"experts": "learned"}}
ML_BUILD = _step("build", "Build it", "ML engineer")
METRICS = _review("metrics", "Compare the metrics", "Model evaluator")
CHANGE = _step("build", "Change the pipeline", "Data engineer")
QUALITY = _review("quality", "Check the data quality", "Data analyst")
# {name: (as KOLONİ drew it, now)}
THIN = {
    "Feature": (
        _graph(
            [
                SPEC,
                BUILD,
                _review("code", "Code review", "Reviewer", group="reviews"),
                _review("security", "Security review", "Security reviewer", group="reviews"),
                {**UI, "group": "reviews"},
                _review("tests", "Test it", "Tester", group="reviews"),
            ],
            ("spec", "build", "reviews"),
            groups=("reviews",),
            loops=(("reviews", "build", 2),),
            checks=CHECKS,
        ),
        _graph(
            [SPEC, BUILD, UI],
            ("spec", "build", "ui"),
            loops=(("ui", "build", 2),),
            checks=CHECKS,
        ),
    ),
    "Model change": (
        _graph(
            [
                PLAN,
                EXPERTS,
                ML_BUILD,
                _review("tests", "Run the tests", "Tester", group="checks"),
                {**METRICS, "group": "checks"},
                _review("review", "Review it", "Reviewer"),
            ],
            ("plan", "experts", "build", "checks", "review"),
            groups=("checks",),
            loops=(("experts", "plan", 1), ("checks", "build", 2)),
        ),
        _graph(
            [PLAN, EXPERTS, ML_BUILD, METRICS],
            ("plan", "experts", "build", "metrics"),
            loops=(("experts", "plan", 1), ("metrics", "build", 2)),
            checks=CHECKS,
        ),
    ),
    "Pipeline change": (
        _graph(
            [
                CHANGE,
                _review("tests", "Run the tests", "Tester", group="checks"),
                {**QUALITY, "group": "checks"},
                _review("review", "Review it", "Reviewer"),
            ],
            ("build", "checks", "review"),
            groups=("checks",),
            loops=(("checks", "build", 2),),
        ),
        _graph(
            [CHANGE, QUALITY],
            ("build", "quality"),
            loops=(("quality", "build", 2),),
            checks=CHECKS,
        ),
    ),
}


def _swap(back: bool) -> None:
    bind = op.get_bind()
    for name, (was, now) in THIN.items():
        was, now = (now, was) if back else (was, now)
        for id_, graph in bind.execute(
            sa.text("SELECT id, graph FROM recipes WHERE name = :name AND ready = 1"),
            {"name": name},
        ).fetchall():
            # (Compared as data: the same drawing whatever its JSON's spacing.)
            if (json.loads(graph) if isinstance(graph, str) else graph) == was:
                bind.execute(
                    sa.text("UPDATE recipes SET graph = :graph WHERE id = :id"),
                    {"graph": json.dumps(now), "id": id_},
                )


def upgrade() -> None:
    _swap(back=False)


def downgrade() -> None:
    _swap(back=True)
