from helpers import make_question

from utmetag.bank import (
    filter_questions,
    get_subject_subtopics,
    get_subject_topics,
    is_verified,
    load_bank,
)


def test_load_bank_reads_all_files(data_dir):
    loaded = load_bank(data_dir)
    assert len(loaded["questions"]) == 5
    assert loaded["subtopics"][0]["slug"] == "surds"


def test_is_verified_only_for_passing_human_rows(bank):
    assert is_verified(bank, "q2") is True
    assert is_verified(bank, "q1") is False


def test_filter_unverified_excludes_pass(bank):
    ids = [q.id for q in filter_questions(bank, "mathematics", "JAMB", 10, only_unverified=True)]
    assert ids == ["q1", "q5"]


def test_filter_all_includes_verified(bank):
    ids = [q.id for q in filter_questions(bank, "mathematics", "JAMB", 10, only_unverified=False)]
    assert ids == ["q1", "q2", "q5"]


def test_filter_excludes_other_exam_and_subject(bank):
    ids = [q.id for q in filter_questions(bank, None, "JAMB", 10, only_unverified=False)]
    assert "q4" not in ids  # WAEC
    assert "q3" in ids      # physics, still JAMB


def test_filter_by_question_id(bank):
    ids = [q.id for q in filter_questions(bank, "mathematics", "JAMB", 10, False, question_ids=["q2"])]
    assert ids == ["q2"]


def test_filter_respects_limit(bank):
    ids = [q.id for q in filter_questions(bank, "mathematics", "JAMB", 1, only_unverified=False)]
    assert ids == ["q1"]


def test_filter_maps_question_fields(bank):
    q = filter_questions(bank, "mathematics", "JAMB", 1, only_unverified=False)[0]
    assert q.exam == "JAMB"
    assert q.subject == "mathematics"
    assert q.marks == 2.5
    assert q.difficulty == 3


def test_nullable_explanation_is_preserved_as_none(bank):
    q = filter_questions(bank, "mathematics", "JAMB", 1, only_unverified=False)[0]
    assert q.explanation is None


def test_get_subject_subtopics(bank):
    subs = get_subject_subtopics(bank, "JAMB", "mathematics")
    assert {s.slug for s in subs} == {"surds", "indices"}
    assert all(s.topic == "algebra" for s in subs)


def test_get_subject_subtopics_other_subject_empty(bank):
    assert get_subject_subtopics(bank, "JAMB", "physics") == []


def test_get_subject_topics(bank):
    topics = get_subject_topics(bank, "JAMB", "mathematics")
    assert [t.slug for t in topics] == ["algebra"]


def test_missing_verifications_file_is_optional(tmp_path):
    import json

    bank = {
        "questions": [make_question("q1")],
        "subjects": [], "topics": [], "subtopics": [], "passages": [],
    }
    for name in ("questions", "subjects", "topics", "subtopics", "passages"):
        (tmp_path / f"{name}.json").write_text(json.dumps(bank[name]))
    loaded = load_bank(tmp_path)
    assert loaded["verifications"] == []
