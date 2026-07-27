import quiz_data as q


def test_fifteen_questions():
    assert len(q.QUESTIONS) == 15


def test_each_question_has_four_scored_options():
    for i, question in enumerate(q.QUESTIONS):
        opts = question["options"]
        assert len(opts) == 4, f"Q{i+1}: не 4 варианта"
        scores = sorted(s for _, s in opts)
        assert scores == [1, 2, 3, 4], f"Q{i+1}: баллы не {{1,2,3,4}}"


def test_options_not_in_ascending_score_order():
    # «вразнобой»: хотя бы у части вопросов порядок не по возрастанию,
    # и ни у одного вопроса варианты не идут строго 1,2,3,4 сверху вниз
    for i, question in enumerate(q.QUESTIONS):
        shown = [s for _, s in question["options"]]
        assert shown != [1, 2, 3, 4], f"Q{i+1}: варианты идут по возрастанию баллов"


def test_score_bounds():
    assert q.MIN_SCORE == 15
    assert q.MAX_SCORE == 60


def test_result_tiers_boundaries():
    assert q.result_for_score(15)[1].startswith("«В плену")
    assert q.result_for_score(30)[1].startswith("«В плену")
    assert q.result_for_score(31)[1].startswith("«На пороге")
    assert q.result_for_score(46)[1].startswith("«На пороге")
    assert q.result_for_score(47)[1].startswith("«Автономия")
    assert q.result_for_score(60)[1].startswith("«Автономия")


def test_result_full_range_covered():
    for score in range(15, 61):
        symbol, title, body = q.result_for_score(score)
        assert symbol and title and body
        assert str(score) in body  # балл подставлен в текст


def test_intro_present():
    assert "автономию, сценарии мышления" in q.INTRO_TEXT
