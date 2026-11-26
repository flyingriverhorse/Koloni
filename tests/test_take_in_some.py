"""Take in of some of a card's files (T93-01: `files` was taken for nothing, and every file went
in): only the chosen ones are taken; the rest stay on the card - a turn's still asked about, a
kept copy's still kept - for Take in or Discard."""

from tests.test_chat_flow import text
from tests.test_claim_scenarios import write
from tests.test_copy_later_scenarios import again
from tests.test_copy_runner import at_work, card_of, kept_folders
from tests.test_copy_scenarios import files, one, seen
from tests.test_parallel import until
from tests.test_spawn import step

TWO = [step(write("a.txt", "A")), step(write("b.txt", "B", "w2"))]


def some(client, merge, *paths, **more):
    return client.post(
        f"/api/merges/{merge['id']}/approve",
        json={"files": list(paths), "shown": seen(merge), **more},
    )


def test_a_turns_card_takes_only_the_files_chosen_and_asks_on_about_the_rest(
    make_client, wait_run, project_dir
):
    client, _model, cid, run_id = one(
        make_client, project_dir, [*TWO, text("A done")], permission_mode="ask"
    )
    snap = until(client, cid, lambda s: [m["status"] for m in s["merges"]] == ["pending"])
    (card,) = snap["merges"]
    taken = some(client, card, "a.txt")
    assert taken.status_code == 200, taken.text
    assert (project_dir / "a.txt").read_text(encoding="utf-8") == "A"
    assert not (project_dir / "b.txt").exists()
    # The card is still asked about, with what is left on it.
    card = until(client, cid, lambda s: files(s["merges"][0]).get("a.txt") == "applied")["merges"][
        0
    ]
    assert card["status"] == "pending" and files(card) == {"a.txt": "applied", "b.txt": "ready"}
    # Discard the rest: what was taken stays taken, and the card says so.
    assert client.post(f"/api/merges/{card['id']}/reject").status_code == 200
    snap = wait_run(client, cid, run_id)
    assert snap["merges"][0]["status"] == "applied"
    assert (project_dir / "a.txt").exists() and not (project_dir / "b.txt").exists()


def test_a_kept_copy_takes_only_the_files_chosen_and_keeps_the_rest(settings_env, project_dir):
    cid = at_work(settings_env, project_dir, TWO)
    with again(settings_env) as client:
        card = card_of(client, cid)
        taken = some(client, card, "b.txt")
        assert taken.status_code == 200, taken.text
        assert (project_dir / "b.txt").read_text(encoding="utf-8") == "B"
        assert not (project_dir / "a.txt").exists()
        card = card_of(client, cid)
        assert card["status"] == "kept" and files(card) == {"a.txt": "ready", "b.txt": "applied"}
        assert kept_folders(settings_env) != []
        rest = client.post(f"/api/merges/{card['id']}/approve", json={"shown": seen(card)})
        assert rest.status_code == 200 and rest.json()["status"] == "applied", rest.text
        assert (project_dir / "a.txt").read_text(encoding="utf-8") == "A"
        assert kept_folders(settings_env) == []


def test_files_that_are_not_the_cards_to_take_are_refused_not_ignored(settings_env, project_dir):
    cid = at_work(settings_env, project_dir, TWO)
    with again(settings_env) as client:
        card = card_of(client, cid)
        for chosen, said in (
            ([], "choose at least one file"),
            (["c.txt"], "not on this card to take: c.txt"),
        ):
            refused = some(client, card, *chosen)
            assert refused.status_code == 409 and said in refused.json()["detail"], refused.text
        check = client.post(f"/api/merges/{card['id']}/check", json={"files": ["a.txt"]})
        assert check.status_code == 409, check.text
        assert not (project_dir / "a.txt").exists() and not (project_dir / "b.txt").exists()
        assert card_of(client, cid)["status"] == "kept"
