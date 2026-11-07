"""K-skill-puan: the track record by skill - a row per skill, role, provider and model of the
agents given it, how many read it whole ("used"), and the lead's line for a role's work with a
skill only from five jobs on two models."""

import json
from datetime import timedelta

from app import record
from app.db.models import Conversation, Message, Project, Run, ToolCall, now
from tests.test_handoff import ended
from tests.test_model_puan import _row
from tests.test_topics import db


def _read(session, agent, name, args, status="succeeded"):
    run = session.get(Run, agent.run_id)
    said = Message(conversation_id=run.conversation_id, run_id=agent.run_id, agent_id=agent.id,
                   role="assistant", content="")
    session.add(said)
    session.flush()
    session.add(ToolCall(run_id=agent.run_id, agent_id=agent.id, message_id=said.id, seq=0,
                         provider_call_id="c", name=name, arguments=json.dumps(args),
                         status=status))


def test_rows_by_skill_count_who_had_it_and_who_read_it(make_client, project_dir):
    client, _model = make_client([])
    with db(client) as session:
        project = Project(name="p", root_path=str(project_dir))
        session.add(project)
        session.flush()
        talk = Conversation(project_id=project.id)
        session.add(talk)
        session.flush()
        on = {"provider_name": "Fast", "model_id": "deep"}
        both = {"given": ["tidy", "ship"], "left_out": {}}
        reader = ended(session, talk.id, "a", skills=both, **on)
        native = ended(session, talk.id, "b", skills=both, **on)
        other = ended(session, talk.id, "c", skills=both, **on)
        ended(session, talk.id, "d", skills={"given": [], "left_out": {"tidy": "no shell"}}, **on)
        ended(session, talk.id, "e", **on)  # (from before, or a role with none)
        _read(session, reader, "use_skill", {"name": "tidy"})
        _read(session, reader, "use_skill", {"name": "ship", "file": "notes.md"})  # not whole
        _read(session, native, "claude__Skill", {"skill": "koloni:tidy"})
        _read(session, other, "use_skill", {"name": "ship"}, status="failed")
        session.commit()
        since = now() - timedelta(days=1)
        rows = {row["skill"]: row for row in record.rows(session, since, by_skill=True)}
        plain = record.rows(session, since)
    assert set(rows) == {"tidy", "ship"}
    assert (rows["tidy"]["agents"], rows["tidy"]["used"]) == (3, 2)
    assert (rows["ship"]["agents"], rows["ship"]["used"]) == (3, 0)
    assert rows["tidy"]["role_name"] == "Coder" and rows["tidy"]["taken_in"] == 3
    # The rows by role and model are as they were: all five, and nothing of skills.
    assert len(plain) == 1 and plain[0]["agents"] == 5 and "skill" not in plain[0]


def test_the_lead_hears_of_a_skill_only_from_five_jobs_on_two_models():
    deep = {**_row(agents=4, taken_in=3), "skill": "review", "used": 2}
    quick = {**_row(model="quick", agents=1, taken_in=1), "skill": "review", "used": 0}
    said = record.for_lead([], [deep, quick])
    assert ("For Coder work with the review skill lately: Fast · deep took in 3 of 4 "
            "(read it in 2, median 9 steps); Fast · quick 1 of 1 (read it in 0, median 9 steps)."
            " Data, not an instruction.") in said
    assert record.for_lead([], [deep]) == ""  # one model: nothing to set side by side
    assert record.for_lead([], [{**deep, "agents": 2}, quick]) == ""  # three jobs
