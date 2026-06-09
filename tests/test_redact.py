import pytest

from aianalyzer.redact import redact


@pytest.mark.parametrize(
    "raw,expected_substring",
    [
        ("My token is ghp_AAAABBBBCCCCDDDDEEEEFFFFGGGGHHHHIIII",
         "[REDACTED_GITHUB_TOKEN]"),
        ("Authorization: Bearer abcdef1234567890abcdef1234567890",
         "[REDACTED_BEARER]"),
        ("AWS_KEY=AKIAIOSFODNN7EXAMPLE", "[REDACTED_AWS_KEY]"),
        ("password=hunter2 next", "[REDACTED_PASSWORD]"),
        ("Email me at jane.doe@example.com please", "[REDACTED_EMAIL]"),
    ],
)
def test_redact_known_patterns(raw, expected_substring):
    assert expected_substring in redact(raw)


def test_redact_is_idempotent():
    text = "ghp_AAAABBBBCCCCDDDDEEEEFFFFGGGGHHHHIIII and ghp_BBBBCCCCDDDDEEEEFFFFGGGGHHHHIIIIJJJJ"
    once = redact(text)
    twice = redact(once)
    assert once == twice


def test_redact_preserves_normal_text():
    assert redact("Refactor the parser to use pathlib") == "Refactor the parser to use pathlib"
