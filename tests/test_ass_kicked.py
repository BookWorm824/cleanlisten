"""From CleanView (2026-11-17): "kick" made "ass" look like the donkey, so common lines went unmuted
("kick your ass", "get your ass kicked"). After "your/his/my/our/some..." or a name's "'s", "ass" is the
body, unless a farm animal, a cart or harness is close by (The Swiss Family Robinson's "my cow and my ass")."""
import pytest

import cleanlisten as E


def words(text):
    return [E.norm(w) for w in text.split()]


def found(text):
    ws = words(text)
    return [" ".join(ws[i:j]) for i, j, _ in E.find_language(ws, list(E.PHRASES))]


@pytest.mark.parametrize("text", [
    "I'm going to kick your ass.", "Prepare to get your ass kicked.", "He kicked his ass sideways.",
    "They're the ones who got their asses kicked.", "We're going to kick cancer's ass.",
    "Go kick some Red Rock ass.",
])
def test_said_about_the_body(text):
    assert any("ass" in f for f in found(text)), text


@pytest.mark.parametrize("text", [
    "Both my cow and my ass were equipped for swimming.",
    "Our ass instantly ran up to take its favourite oats.",
    "The ass began to kick at the goats.", "He loaded the ass and the cart with hay.",
])
def test_the_donkey(text):
    assert not any("ass" in f for f in found(text)), text
