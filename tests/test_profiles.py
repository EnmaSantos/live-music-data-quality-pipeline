import pytest

from app.core.profiles import get_profile, list_profiles


def test_published_profiles_have_distinct_immutable_versions() -> None:
    profiles = list_profiles()

    assert {(profile.profile_key, profile.profile_version) for profile in profiles} == {
        ("generic", "1.0.0"),
        ("live-events", "1.0.0"),
    }
    assert all(profile.status == "published" for profile in profiles)
    with pytest.raises(AttributeError):
        profiles[0].profile_version = "2.0.0"  # type: ignore[misc]


def test_unknown_profile_version_is_rejected() -> None:
    with pytest.raises(KeyError):
        get_profile("live-events", "9.9.9")
