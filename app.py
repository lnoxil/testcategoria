from __future__ import annotations

import json
import random
from datetime import date
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, session

app = Flask(__name__)
app.secret_key = "transport-safety-secret"
DATA_PATH = Path(__file__).parent / "data" / "questions.json"
STATS_PATH = Path(__file__).parent / "data" / "user_stats.json"


def load_questions() -> list[dict]:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def load_stats() -> dict:
    if not STATS_PATH.exists():
        return {"attempts": [], "mistake_counts": {}}
    return json.loads(STATS_PATH.read_text(encoding="utf-8"))


def save_stats(stats: dict) -> None:
    STATS_PATH.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")


def build_analytics() -> dict:
    stats = load_stats()
    attempts = stats.get("attempts", [])
    attempts_50 = [a for a in attempts if a.get("size") == 50]
    avg_50 = round(sum(a.get("percent", 0) for a in attempts_50) / len(attempts_50), 2) if attempts_50 else 0

    mistake_counts = stats.get("mistake_counts", {})
    top_ids = sorted(mistake_counts, key=lambda k: mistake_counts[k], reverse=True)[:10]
    top_mistakes = []
    for qid_str in top_ids:
        qid = int(qid_str)
        q = QUESTIONS_BY_ID.get(qid)
        if q:
            top_mistakes.append(
                {
                    "question_number": qid,
                    "count": mistake_counts[qid_str],
                    "question": q["question"],
                }
            )

    by_day = {}
    for a in attempts:
        d = a.get("date", "unknown")
        row = by_day.setdefault(d, {"percent_sum": 0, "wrong_sum": 0, "count": 0})
        row["percent_sum"] += a.get("percent", 0)
        row["wrong_sum"] += a.get("wrong", 0)
        row["count"] += 1

    daily_progress = []
    for d in sorted(by_day.keys()):
        row = by_day[d]
        avg_percent = round(row["percent_sum"] / row["count"], 2)
        avg_wrong = round(row["wrong_sum"] / row["count"], 2)
        daily_progress.append({"date": d, "avg_percent": avg_percent, "avg_wrong": avg_wrong})

    persistent_mistakes_count = sum(1 for _, v in mistake_counts.items() if v > 0)

    return {
        "avg_percent_50": avg_50,
        "top_mistakes": top_mistakes,
        "attempts_total": len(attempts),
        "daily_progress": daily_progress,
        "persistent_mistakes_count": persistent_mistakes_count,
    }


QUESTIONS = load_questions()
QUESTIONS_BY_ID = {q["question_number"]: q for q in QUESTIONS}


@app.route("/")
def home():
    analytics = build_analytics()
    return render_template(
        "index.html",
        total=len(QUESTIONS),
        mistakes=len(session.get("mistakes", [])),
        analytics=analytics,
    )


@app.post("/start")
def start_test():
    mode = request.form.get("mode", "common_50")

    if mode == "mistakes":
        stats = load_stats()
        persistent_ids = [int(k) for k, v in stats.get("mistake_counts", {}).items() if v > 0]
        session_ids = session.get("mistakes", [])
        ids = sorted(set(persistent_ids + session_ids))
        pool = [QUESTIONS_BY_ID[i] for i in ids if i in QUESTIONS_BY_ID]
        random.shuffle(pool)
    else:
        pool = QUESTIONS[:]
        random.shuffle(pool)
        limit = 20 if mode == "quick_20" else 50
        pool = pool[:limit]

    if not pool:
        return redirect(url_for("home"))

    session["test_ids"] = [q["question_number"] for q in pool]
    session["index"] = 0
    session["correct"] = 0
    session["answers"] = []
    session["mode"] = mode
    return redirect(url_for("list_test"))


@app.route("/exit_test")
def exit_test():
    for key in ["test_ids", "index", "correct", "answers", "mode"]:
        session.pop(key, None)
    return redirect(url_for("home"))


@app.route("/list_test")
def list_test():
    test_ids = session.get("test_ids", [])
    if not test_ids:
        return redirect(url_for("home"))
    questions = [QUESTIONS_BY_ID[qid] for qid in test_ids if qid in QUESTIONS_BY_ID]
    return render_template("list_test.html", questions=questions, mode=session.get("mode", "common_50"))


@app.post("/submit_list")
def submit_list():
    test_ids = session.get("test_ids", [])
    if not test_ids:
        return redirect(url_for("home"))

    correct = 0
    answers = []
    mistakes = set(session.get("mistakes", []))
    wrong_ids = []

    for qid in test_ids:
        q = QUESTIONS_BY_ID[qid]
        raw = request.form.get(f"q_{qid}")
        if raw is None:
            selected = -1
            is_correct = False
        else:
            selected = int(raw)
            is_correct = selected == q["correct_option_index"]

        if is_correct:
            correct += 1
        else:
            mistakes.add(qid)
            wrong_ids.append(qid)

        answers.append(
            {
                "question_number": qid,
                "selected": selected,
                "correct": q["correct_option_index"],
                "is_correct": is_correct,
            }
        )

    total = len(test_ids)
    percent = round((correct / total) * 100) if total else 0

    stats = load_stats()
    stats.setdefault("attempts", []).append(
        {
            "date": date.today().isoformat(),
            "size": total,
            "percent": percent,
            "correct": correct,
            "wrong": total - correct,
            "mode": session.get("mode", "common_50"),
        }
    )
    stats.setdefault("mistake_counts", {})
    for qid in wrong_ids:
        key = str(qid)
        stats["mistake_counts"][key] = stats["mistake_counts"].get(key, 0) + 1
    save_stats(stats)

    session["correct"] = correct
    session["answers"] = answers
    session["mistakes"] = sorted(mistakes)
    session["index"] = len(test_ids)
    return redirect(url_for("result"))


@app.route("/result")
def result():
    test_ids = session.get("test_ids", [])
    total = len(test_ids)
    correct = session.get("correct", 0)
    wrong = total - correct
    percent = round((correct / total) * 100) if total else 0
    return render_template(
        "result.html",
        total=total,
        correct=correct,
        wrong=wrong,
        percent=percent,
        mistakes=len(session.get("mistakes", [])),
    )


if __name__ == "__main__":
    app.run(debug=True)
