BASE_POINTS = 1000
QUESTION_SECONDS = 60

def score_answer(is_correct: bool, response_seconds: float) -> int:
    if not is_correct or response_seconds > QUESTION_SECONDS:
        return 0
    remaining = max(0, QUESTION_SECONDS - response_seconds)
    return round(BASE_POINTS * (0.5 + 0.5 * remaining / QUESTION_SECONDS))
