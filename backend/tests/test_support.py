"""The guard that keeps tests, and each pytest-xdist worker, off any database
that could be the app's own."""

import pytest

from tests.support import _test_database_url

BASE = "postgresql+psycopg2://u:p@localhost:5432/"
APP = BASE + "song_study"


def test_without_a_worker_the_test_database_is_used_as_given():
    assert _test_database_url(BASE + "song_study_test", APP, None) == (
        BASE + "song_study_test"
    )


def test_a_worker_gets_its_id_before_the_test_suffix():
    assert _test_database_url(BASE + "song_study_test", APP, "gw0") == (
        BASE + "song_study_gw0_test"
    )


@pytest.mark.parametrize("worker", [None, "gw0"])
@pytest.mark.parametrize(
    "test_db",
    [
        # Would pass as `song_study_gw0_test` if a worker id were appended
        # with a `_test` before the base was checked.
        "song_study",
        "song_study_testing",
        "",
    ],
)
def test_a_base_not_ending_in_test_is_refused(test_db, worker):
    with pytest.raises(RuntimeError):
        _test_database_url(BASE + test_db, APP, worker)


def test_the_apps_own_database_is_refused_even_if_it_ends_in_test():
    with pytest.raises(RuntimeError):
        _test_database_url(BASE + "song_study_test", BASE + "song_study_test", None)


def test_a_worker_database_that_is_the_apps_own_is_refused():
    with pytest.raises(RuntimeError):
        _test_database_url(
            BASE + "song_study_test", BASE + "song_study_gw0_test", "gw0"
        )


def test_an_unset_test_database_is_refused():
    with pytest.raises(RuntimeError):
        _test_database_url(None, APP, "gw0")


def test_a_worker_id_that_could_alter_the_name_is_refused():
    with pytest.raises(RuntimeError):
        _test_database_url(BASE + "song_study_test", APP, 'gw0"; DROP')
