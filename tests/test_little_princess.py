"""Lessons from A Little Princess (the night run's report, 2026-11-17, sent on by the session that cleans
the classics for CleanRead Mobile): family and friends kissing in an older book, a pet sleeping with
someone, and "killed" with the animal or the sorrow told in the sentence before. The real thing is still
found in each case."""
import cleanlisten as E
import cleanread as R
from conftest import words
from test_old_words_and_gump import MODERN, OLD, _book


def kinds(an):
    return [c["kind"] for c in an["cuts"]]


def test_family_and_friends_kissing_in_an_old_book(tmp_path):
    book = _book(tmp_path, OLD + [
        "Oh, little Sara, he said. What shall I do when I have no one to say solemn things to me?",
        "And then suddenly he swept her into his arms and kissed her very hard, stopping laughing all at once.",
        "You can't help being a doll, she said with a resigned sigh.",
        "And she kissed her and shook her clothes straight, and put her back upon her chair.",
        "Mrs. Carmichael was crying as she kissed her again."], "old_kisses")
    assert book.old_style
    an = R.analyze(book, dict(kiss="passionate", kiss_ss="all"))
    assert [k for k in kinds(an) if k.startswith("kiss")] == []


def test_romantic_kissing_still_found_in_an_old_book(tmp_path):
    book = _book(tmp_path, OLD + ["He took her in his arms and kissed her lips passionately.",
                                  "She pressed her lips to hers, and she kissed her passionately."], "old_romance")
    assert book.old_style
    an = R.analyze(book, dict(kiss="passionate", kiss_ss="all"))
    assert "kiss" in kinds(an) and "kiss_ss" in kinds(an)


def test_modern_kisses_unchanged(tmp_path):
    book = _book(tmp_path, MODERN + ["He swept her into his arms and kissed her very hard."], "modern_kisses")
    assert not book.old_style
    an = R.analyze(book, dict(kiss="passionate", kiss_ss="all"))
    assert "kiss" in kinds(an)


def test_a_pet_sleeping_with_someone():
    ws = words("Monkey, my love, have you a mind? But the monkey only put up a tiny paw and scratched his head. "
               "What shall you do with him? Becky asked. I shall let him sleep with me tonight.")
    assert E.find_language(ws, ["sexual"]) == []


def test_sleeping_with_someone_still_found():
    assert E.find_language(words("I'm not sleeping with her, he said."), ["sexual"])
    assert E.find_language(words("She slept with him on their first date."), ["sexual"])


def test_a_pet_in_bed_not_a_sexual_reference(tmp_path):
    book = _book(tmp_path, MODERN + ["But the monkey only put up a tiny paw and scratched his head.",
                                     "I shall let him sleep with me tonight, and then take him back tomorrow."], "pet")
    an = R.analyze(book, dict(sexual=True, refs=True))
    assert "ref" not in kinds(an) and an["mutes"] == []


def test_killed_with_the_animal_or_sorrow_told_before(tmp_path):
    book = _book(tmp_path, MODERN + [
        "Well, said Jessie, slowly, he's killed tigers.", "He killed the one in the skin Sara has in her room.",
        "The suffering was just as bad for my papa, she said.", "It killed him."], "killed_before")
    an = R.analyze(book, dict(violence=True))
    assert "violence" not in kinds(an)


def test_killing_still_violence(tmp_path):
    book = _book(tmp_path, MODERN + [
        "He's killed tigers.", "He killed the man too, with his bare hands.",
        "The bear attacked the camp.", "It killed him."], "killed_real")
    an = R.analyze(book, dict(violence=True))
    assert kinds(an).count("violence") == 2
