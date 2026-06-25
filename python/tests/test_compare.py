"""Unit tests for the compare status helper."""

from grove.core.compare import status_word


def test_status_word_in_sync():
    assert status_word(0, 0) == "in sync"


def test_status_word_ahead():
    assert status_word(2, 0) == "ahead"


def test_status_word_behind():
    assert status_word(0, 3) == "behind"


def test_status_word_diverged():
    assert status_word(1, 1) == "diverged"
