"""Slice 43's acceptance set: every built-in role has a tier, and nine more built-in roles.
Written before the code.

A new database has twenty-one built-in roles (the Observer since slice 33b), each asking for the tier the design gives it - the
lead none: it runs on the conversation's model. On a
database made before, a built-in role nobody changed takes its tier when the app starts; one the
user changed, and a role of the user's own that bears a built-in name, stay as they are. A role
with neither writing nor commands among its tools changes nothing.
"""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app import roles

if "Spec writer" not in roles.BUILTIN_ROLES:  # written before the code: skipped until it exists
    pytest.skip("slice 43 is not built yet", allow_module_level=True)

from app.db.models import Role, Team  # noqa: E402
from app.db.session import make_engine, make_session_factory, upgrade_db  # noqa: E402

TIERS = {
    # The lead runs on the conversation's model: the one picked, else the default (or the
    # automatic lead's choice). A tier would take the chat's picker away from the user.
    "Lead": None, "Planner": "strongest", "Coder": "strongest", "Tester": "balanced",
    "Reviewer": "strongest", "Researcher": "balanced", "Debugger": "strongest",
    "Architect": "strongest", "Security reviewer": "strongest", "Docs writer": "fast",
    "Refactorer": "balanced",
    "UI designer": "balanced", "Data analyst": "balanced", "DevOps": "balanced",
    "Spec writer": "strongest", "Performance engineer": "balanced",
    "Database engineer": "balanced", "Dependency keeper": "balanced", "Translator": "fast",
    "Summarizer": "fast",
    # Slice 52: they keep the backlog.
    "Product owner": "strongest", "Assistant product owner": "balanced",
    # Slice 33b: asked once, without tools, over a sub-agent's report.
    "Observer": "balanced",
}
CHANGES = {*roles.WRITE, "run_command"}


def test_a_new_database_has_twenty_three_built_in_roles_each_with_no_tier(client):
    listed = {r["name"]: r for r in client.get("/api/roles").json() if r["builtin"]}
    assert set(listed) == set(roles.BUILTIN_ROLES) >= set(TIERS)  # (and K-takim-duzen's five)
    # Slice 81b: the tiers above are what they came with until then; now none has one - the
    # Lead picks a tier for each job (migration 0065 takes them from a database made before).
    assert {role["tier"] for role in listed.values()} == {None}


@pytest.mark.parametrize("name", ["Spec writer", "Summarizer"])
def test_a_role_that_writes_a_document_runs_nothing_and_writes_no_code(name):
    # B-190: the document asked for is written by it; still no command, nor code.
    spec = roles.BUILTIN_ROLES[name]
    assert CHANGES & set(spec.tools) == set(roles.WRITE) and "never code" in spec.instructions


@pytest.mark.parametrize("name", ["Data analyst", "UI designer"])
def test_a_role_that_shows_its_work_has_show(name):
    assert "show" in roles.BUILTIN_ROLES[name].tools


def test_every_new_role_tool_is_one_a_role_can_have():
    for name in TIERS:
        assert set(roles.BUILTIN_ROLES[name].tools) <= set(roles.ALL_TOOLS), name


# --- a database made before ----------------------------------------------------------------


def seeded(tmp_path):
    db = tmp_path / "k.db"
    upgrade_db(db)
    return make_session_factory(make_engine(db))


def test_a_built_in_role_the_user_changed_is_left_as_it_is(tmp_path):
    factory = seeded(tmp_path)
    with factory() as session:
        roles.seed_builtin_roles(session)
        coder = session.scalar(select(Role).where(Role.name == "Coder"))
        coder.tier = None                         # the user chose the conversation's model
        coder.updated_at = coder.created_at + timedelta(minutes=5)
        session.commit()
    with factory() as session:
        roles.seed_builtin_roles(session)
        assert session.scalar(select(Role.tier).where(Role.name == "Coder")) is None


def test_a_role_of_the_users_own_with_a_new_built_in_name_is_left_as_it_is(tmp_path):
    factory = seeded(tmp_path)
    with factory() as session:
        session.add(Role(name="translator", description="mine", instructions="mine",
                         tools=["read_file"], builtin=False))
        session.commit()
        roles.seed_builtin_roles(session)
        mine = session.scalars(select(Role).where(Role.name.ilike("translator"))).all()
        assert [(r.name, r.builtin, r.description, r.tier) for r in mine] == [
            ("translator", False, "mine", None)]


# --- K-site-roller: three roles a database made before is given as the app starts -------------

SITE = ("SEO specialist", "Copywriter", "Accessibility reviewer")


def test_the_site_roles_join_the_ready_web_app_team_in_their_stages(tmp_path):
    factory = seeded(tmp_path)  # (migrated only: as an install was before they were added)
    with factory() as session:
        assert not session.scalars(select(Role).where(Role.name.in_(SITE))).all()
        session.add(Role(name="copywriter", description="mine", instructions="mine",
                         tools=["read_file"], builtin=False))
        session.commit()
        roles.seed_builtin_roles(session)
        web = session.scalar(select(Team).where(Team.name == "Web app"))
        stages = dict(roles.stage_roles(session, web))
        assert "SEO specialist" in stages["Build"] and "Accessibility reviewer" in stages["Check"]
        # the user's own copywriter keeps the name: no built-in is made, nor put in the team
        assert not any("Copywriter" in held for held in stages.values())
        mine = session.scalars(select(Role).where(Role.name.ilike("copywriter"))).all()
        assert [(r.name, r.builtin, r.description) for r in mine] == [("copywriter", False, "mine")]


def test_the_site_roles_join_no_web_app_team_the_user_renamed(tmp_path):
    factory = seeded(tmp_path)
    with factory() as session:
        session.scalar(select(Team).where(Team.name == "Web app")).name = "Shop"
        session.commit()
        roles.seed_builtin_roles(session)
        made = session.scalars(select(Role).where(Role.name.in_(SITE))).all()
        assert sorted(r.name for r in made) == sorted(SITE)
        assert all(r.builtin and r.teams == [] for r in made)
        stages = dict(roles.stage_roles(session, session.scalar(select(Team).where(
            Team.name == "Shop"))))
        assert not {"SEO specialist", "Copywriter"} & set(stages["Build"])


def test_on_a_new_database_the_copywriter_writes_in_the_web_app_teams_build_stage(tmp_path):
    factory = seeded(tmp_path)
    with factory() as session:
        roles.seed_builtin_roles(session)
        web = session.scalar(select(Team).where(Team.name == "Web app"))
        assert "Copywriter" in dict(roles.stage_roles(session, web))["Build"]
