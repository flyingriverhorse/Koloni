"""Slice 90: how a command's output is hidden (`OutputMask`); end to end in the scenarios."""

import json
from urllib.parse import quote

import pytest

from app.commands import OutputMask, secret_values

SECRET = "s3cr3t-value-ABCDEFGH"


def test_values_of_variables_named_like_secrets_are_taken():
    env = {
        "GITHUB_TOKEN": "t" * 20, "OPENAI_API_KEY": "k" * 20, "DB_PASSWORD": "p" * 20,
        "AWS_SECRET_ACCESS_KEY": "a" * 20, "SENTRY_DSN": "d" * 20, "MY_APIKEY": "m" * 20,
        "SESSION_COOKIE": "c" * 20, "GH_AUTH": "h" * 20, "CLIENTSECRET": "s" * 20,
        "PATH": "C:/Windows/System32;C:/Python", "PWD": "C:/Users/me/project",
        "KEYBOARD_LAYOUT": "turkish-q-layout", "USERNAME": "someone-long-name",
        "SHORT_TOKEN": "abc",  # too short to look for
    }
    found = set(secret_values(env))
    assert found == {"t" * 20, "k" * 20, "p" * 20, "a" * 20, "d" * 20, "m" * 20, "c" * 20,
                     "h" * 20, "s" * 20}


@pytest.mark.parametrize("written", [
    SECRET, json.dumps(SECRET)[1:-1], quote(SECRET, safe=""), f'{{"token": "{SECRET}"}}',
])
def test_a_known_value_is_hidden_however_it_is_written(written):
    mask = OutputMask([SECRET])
    out = mask.hide(f"line: {written}\n")
    assert SECRET not in out and quote(SECRET, safe="") not in out and "***" in out


@pytest.mark.parametrize("token", [
    "sk-" + "a1B2" * 8,
    "sk-proj-" + "Zz9_" * 8,
    "ghp_" + "A" * 36,
    "github_pat_" + "B" * 40,
    "xoxb-" + "1234567890-" * 3,
    "AKIA" + "ABCDEFGHIJKLMNOP",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c",
])
def test_well_known_token_shapes_are_hidden_without_being_known(token):
    out = OutputMask([]).hide(f"value={token} done\n")
    assert token not in out and out.endswith(" done\n")


def test_bearer_and_a_password_in_an_address_are_hidden():
    out = OutputMask([]).hide(
        "Authorization: Bearer abcdefghijklmnop1234\n"
        "postgres://admin:hunter2pass@db.local:5432/app\n")
    assert "abcdefghijklmnop1234" not in out and "hunter2pass" not in out
    assert "Authorization: Bearer ***" in out and "postgres://admin:***@db.local:5432/app" in out


def test_ordinary_output_is_left_as_it_is():
    plain = "2 passed in 0.31s\nhttp://localhost:5173/\nsk-short\n"
    assert OutputMask(["unrelated-secret-value"]).hide(plain) == plain


def test_a_secret_cut_between_two_chunks_is_still_hidden():
    mask = OutputMask([SECRET])
    first = mask.feed("token: s3cr3t-va")
    second = mask.feed("lue-ABCDEFGH\nok\n")
    assert first == ""  # half a line waits for the rest of it
    assert second == "token: ***\nok\n"


def test_what_is_left_without_a_line_end_comes_out_at_the_end_hidden():
    mask = OutputMask([SECRET])
    assert mask.feed(f"Password? {SECRET}") == ""
    assert mask.flush() == "Password? ***"
    assert mask.flush() == ""


def test_a_carriage_return_ends_a_line_too():
    mask = OutputMask([])
    assert mask.feed("10%\r20%\r") == "10%\r20%\r"


def test_a_very_long_line_is_not_held_back_forever():
    mask = OutputMask([])
    assert len(mask.feed("x" * 5000)) == 5000


def test_a_key_of_many_lines_is_hidden_line_by_line_across_chunks():
    body = ["MIIEvQIBADANBgkqhkiG9w0BAQEFAASC", "a8Hk2LmPq9Rz3XwYt7Vb1Nc5Jd0Fs6Ge"]
    pem = "\n".join(["-----BEGIN PRIVATE KEY-----", *body, "-----END PRIVATE KEY-----"])
    mask = OutputMask(secret_values({"PRIVATE_KEY": pem}))
    out = mask.feed(f"PRIVATE_KEY={pem[:60]}") + mask.feed(pem[60:] + "\n") + mask.flush()
    assert not any(line in out for line in body) and out.count("***") >= 3


def test_a_password_in_an_address_without_a_user_is_hidden():
    out = OutputMask([]).hide("redis://:p4ssw0rd-x@cache:6379/0\n")
    assert out == "redis://:***@cache:6379/0\n"


@pytest.mark.parametrize("words", [
    "task-runner-for-everything-in-this-project", "sk-learn-preprocessing-pipeline-steps",
])
def test_a_word_in_kebab_case_is_not_taken_for_a_key(words):
    assert OutputMask([]).hide(f"{words}\n") == f"{words}\n"


def test_bearer_is_not_taken_across_a_line_end():
    out = OutputMask([]).hide("the scheme is Bearer\nauthorization-header-value\n")
    assert out == "the scheme is Bearer\nauthorization-header-value\n"


def test_an_address_in_a_variable_named_for_auth_stays_readable():
    env = {"AUTH_URL": "http://localhost:3000", "SESSION_DIR": "C:/tmp/sessions",
           "AUTH_TOKEN": "t" * 20}
    assert secret_values(env) == ["t" * 20]
    out = OutputMask(secret_values(env)).hide("Ready on http://localhost:3000/\n")
    assert out == "Ready on http://localhost:3000/\n"


def test_a_private_key_and_a_value_named_a_secret_are_hidden_by_their_shape():
    """Slice 85b: what an attached file holds goes through this mask too."""
    pem = ("-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA1x\nabcdefgh\n"
           "-----END RSA PRIVATE KEY-----")
    out = OutputMask(()).hide(
        f"{pem}\n[default]\naws_secret_access_key = wJalrXUtnFEMIK7MDENGbPxRfiCYEXAMPLEKEY\n"
        '{"user": "ann", "password": "hunter2-and-more"}\napi_key: abcd1234efgh\n'
        "max_tokens = 4096\npassword_hint: none\n")
    assert out == ("-----BEGIN RSA PRIVATE KEY-----\n***\n-----END RSA PRIVATE KEY-----\n"
                   "[default]\naws_secret_access_key = ***\n"
                   '{"user": "ann", "password": "***"}\napi_key: ***\n'
                   "max_tokens = 4096\npassword_hint: none\n")

