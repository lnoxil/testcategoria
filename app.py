from __future__ import annotations

import json
import random
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, session

app = Flask(__name__)
app.secret_key = "transport-safety-secret"
DATA_PATH = Path(__file__).parent / "data" / "questions.json"


def load_questions() -> list[dict]:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


QUESTIONS = load_questions()
QUESTIONS_BY_ID = {q["question_number"]: q for q in QUESTIONS}


@app.route("/")
def home():
    return render_template("index.html", total=len(QUESTIONS), mistakes=len(session.get("mistakes", [])))


@app.post("/start")
def start_test():
    mode = request.form.get("mode", "common")
    if mode == "mistakes":
        ids = session.get("mistakes", [])
        pool = [QUESTIONS_BY_ID[i] for i in ids if i in QUESTIONS_BY_ID]
        random.shuffle(pool)
    else:
        pool = QUESTIONS[:]
        random.shuffle(pool)
        pool = pool[:50]

    if not pool:
        return redirect(url_for("home"))

    session["test_ids"] = [q["question_number"] for q in pool]
    session["index"] = 0
    session["correct"] = 0
    session["answers"] = []
    return redirect(url_for("question"))


@app.route("/question")
def question():
    test_ids = session.get("test_ids", [])
    index = session.get("index", 0)
    if not test_ids:
        return redirect(url_for("home"))
    if index >= len(test_ids):
        return redirect(url_for("result"))

    q = QUESTIONS_BY_ID[test_ids[index]]
    return render_template("question.html", q=q, index=index + 1, total=len(test_ids))


@app.post("/answer")
def answer():
    test_ids = session.get("test_ids", [])
    index = session.get("index", 0)
    if index >= len(test_ids):
        return redirect(url_for("result"))

    q = QUESTIONS_BY_ID[test_ids[index]]
    selected = int(request.form["answer"])
    is_correct = selected == q["correct_option_index"]

    if is_correct:
        session["correct"] = session.get("correct", 0) + 1
    else:
        mistakes = set(session.get("mistakes", []))
        mistakes.add(q["question_number"])
        session["mistakes"] = sorted(mistakes)

    answers = session.get("answers", [])
    answers.append({
        "question_number": q["question_number"],
        "selected": selected,
        "correct": q["correct_option_index"],
        "is_correct": is_correct,
    })
    session["answers"] = answers
    session["index"] = index + 1
    return redirect(url_for("question"))


@app.route("/result")
def result():
    test_ids = session.get("test_ids", [])
    total = len(test_ids)
    correct = session.get("correct", 0)
    wrong = total - correct
    percent = round((correct / total) * 100) if total else 0
    return render_template("result.html", total=total, correct=correct, wrong=wrong, percent=percent, mistakes=len(session.get("mistakes", [])))


if __name__ == "__main__":
    app.run(debug=True)
