from __future__ import annotations

import json
import os
import random
import re
from datetime import date
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, session

app = Flask(__name__)
app.secret_key = "transport-safety-secret"
DATA_PATH = Path(__file__).parent / "data" / "questions.json"
STATS_PATH = Path(__file__).parent / "data" / "user_stats.json"
CERT_PATH = Path(__file__).parent / "cert.pem"
KEY_PATH = Path(__file__).parent / "cert_key.pem"


def load_questions() -> list[dict]:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def save_questions(questions: list[dict]) -> None:
    DATA_PATH.write_text(json.dumps(questions, ensure_ascii=False, indent=2), encoding="utf-8")


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

    section_errors: dict[str, int] = {}
    for qid_str, count in mistake_counts.items():
        question = QUESTIONS_BY_ID.get(int(qid_str))
        if not question:
            continue
        bucket_start = _section_bucket(question) * 10 + 1
        bucket_label = f"{bucket_start}-{bucket_start + 9}"
        section_errors[bucket_label] = section_errors.get(bucket_label, 0) + count

    sorted_sections = sorted(section_errors.items(), key=lambda row: row[1], reverse=True)
    recommended_focus = sorted_sections[:3]

    return {
        "avg_percent_50": avg_50,
        "top_mistakes": top_mistakes,
        "attempts_total": len(attempts),
        "daily_progress": daily_progress,
        "persistent_mistakes_count": persistent_mistakes_count,
        "section_errors": sorted_sections,
        "recommended_focus": recommended_focus,
    }


QUESTIONS = load_questions()
QUESTIONS_BY_ID = {q["question_number"]: q for q in QUESTIONS}


def refresh_questions_cache() -> None:
    global QUESTIONS, QUESTIONS_BY_ID
    QUESTIONS = load_questions()
    QUESTIONS_BY_ID = {q["question_number"]: q for q in QUESTIONS}


def _question_original_number(question: dict) -> int:
    return question.get("original_question_number") or question.get("question_number", 0)


def _section_bucket(question: dict) -> int:
    original = _question_original_number(question)
    return max(0, (original - 1) // 10)


def build_balanced_pool(questions: list[dict], limit: int, exclude_ids: set[int] | None = None) -> list[dict]:
    exclude_ids = exclude_ids or set()
    by_bucket: dict[int, list[dict]] = {}
    for question in questions:
        by_bucket.setdefault(_section_bucket(question), []).append(question)

    for bucket in by_bucket.values():
        random.shuffle(bucket)

    ordered_buckets = sorted(by_bucket.keys())
    selected: list[dict] = []
    selected_ids: set[int] = set()

    # Первый проход: берём до двух вопросов из каждого блока (1-10, 11-20 и т.д.),
    # отдавая приоритет вопросам, которые ещё не встречались пользователю.
    for bucket in ordered_buckets:
        if len(selected) >= limit:
            break

        bucket_questions = by_bucket[bucket]
        fresh = [q for q in bucket_questions if q["question_number"] not in exclude_ids]
        fallback = [q for q in bucket_questions if q["question_number"] in exclude_ids]

        for candidate in fresh + fallback:
            qid = candidate["question_number"]
            if qid in selected_ids:
                continue
            selected.append(candidate)
            selected_ids.add(qid)
            if len([q for q in selected if _section_bucket(q) == bucket]) >= 2 or len(selected) >= limit:
                break

    # Второй проход: добираем оставшиеся места, снова с приоритетом неиспользованных вопросов.
    if len(selected) < limit:
        remaining = [q for q in questions if q["question_number"] not in selected_ids]
        random.shuffle(remaining)
        remaining.sort(key=lambda q: q["question_number"] in exclude_ids)
        for candidate in remaining:
            selected.append(candidate)
            selected_ids.add(candidate["question_number"])
            if len(selected) >= limit:
                break

    return selected[:limit]

def parse_questions_from_text(raw_text: str, category: int = 5, section: str | None = None) -> list[dict]:
    section_name = section or f"Категория {category}"
    blocks = re.split(r"(?=Вопрос\s+\d+)", raw_text, flags=re.MULTILINE)
    parsed = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        m_num = re.match(r"Вопрос\s+(\d+)", block)
        if not m_num:
            continue
        qnum = int(m_num.group(1))

        m_q = re.search(rf"Вопрос\s+{qnum}\s*(.+?)\nВыберите один ответ:", block, flags=re.DOTALL)
        if not m_q:
            continue
        question_text = m_q.group(1).strip()

        m_ans = re.search(r"Правильный ответ:\s*(.+)$", block, flags=re.DOTALL)
        if not m_ans:
            continue
        correct_raw = m_ans.group(1).strip()

        opts_part = block[m_q.end():m_ans.start()]
        options = []
        for line in opts_part.splitlines():
            line = line.strip()
            if re.match(r"^[a-zа-я]\.\s+", line, flags=re.IGNORECASE):
                options.append(re.sub(r"^[a-zа-я]\.\s+", "", line, flags=re.IGNORECASE).strip())
        if not options:
            continue

        letter_map = {"a": 0, "b": 1, "c": 2, "d": 3, "e": 4, "f": 5, "g": 6, "h": 7, "i": 8, "j": 9, "k": 10,
                      "а": 0, "б": 1, "в": 2, "г": 3, "д": 4, "е": 5, "ж": 6, "з": 7}
        correct_idx = None
        m_letter = re.match(r"^([a-zа-я])[\.\)]?$", correct_raw.lower())
        if m_letter and m_letter.group(1) in letter_map:
            idx = letter_map[m_letter.group(1)]
            if idx < len(options):
                correct_idx = idx

        if correct_idx is None:
            normalized = correct_raw.lower().strip()
            for idx, opt in enumerate(options):
                if opt.lower().strip() == normalized:
                    correct_idx = idx
                    break

        if correct_idx is None:
            continue

        stored_number = qnum if category == 5 else (category * 1000 + qnum)
        parsed.append(
            {
                "category": category,
                "section": section_name,
                "question_number": stored_number,
                "original_question_number": qnum,
                "question": question_text,
                "options": options,
                "correct_option_index": correct_idx,
                "correct_text": options[correct_idx],
                "source_batch": "bulk_import",
            }
        )
    return parsed




def _normalize_question_text(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip().lower())
    cleaned = cleaned.replace("ё", "е")
    return cleaned


def _detect_topic(question: dict) -> str:
    haystack = " ".join([
        question.get("question", ""),
        " ".join(question.get("options", [])),
        question.get("correct_text", ""),
    ]).lower()

    topic_rules: list[tuple[str, tuple[str, ...]]] = [
        ("Медицина и первая помощь", ("первая помощь", "сердечно-легочной", "кровотеч", "жгут", "ранен", "ампутац", "перелом", "реанимац")),
        ("Взрывчатые вещества и опасные предметы", ("взрыв", "взрывчат", "детонатор", "гранат", "тротил", "взрывное устройство", "подозрительн")),
        ("Оружие и спецсредства", ("оруж", "боеприпас", "патрон", "огнестрель", "наручник", "спецсредств", "гбр")),
        ("Досмотр и КПП", ("досмотр", "кпп", "металлоиск", "интроскоп", "повторный досмотр", "дополнительный досмотр", "собеседован")),
        ("Режимы и пропуска", ("пропуск", "внутриобъектов", "пропускной режим", "перевозочный сектор", "технологический сектор", "критический элемент")),
        ("Законодательство и ответственность", ("федерального закона", "коап", "ук рф", "постановлен", "приказ", "ответственност")),
        ("Сигналы и ЖД безопасность", ("железнодорож", "сигнал", "контактной сети", "поезд", "междупутье", "рельс")),
        ("Террористические угрозы и уровни", ("террорист", "уровень безопасности", "анв", "угроза", "незаконного вмешательства")),
    ]

    for topic, keywords in topic_rules:
        if any(keyword in haystack for keyword in keywords):
            return topic
    return "Прочее"


def build_topic_sections(categories: tuple[int, ...] = (4, 5)) -> list[dict]:
    allowed = [q for q in QUESTIONS if q.get("category") in categories]
    unique_by_text: dict[str, dict] = {}
    for q in sorted(allowed, key=lambda x: (x.get("original_question_number") or x.get("question_number", 0), x.get("category", 0))):
        key = _normalize_question_text(q.get("question", ""))
        if not key:
            continue
        if key in unique_by_text:
            continue
        unique_by_text[key] = q

    grouped: dict[str, list[dict]] = {}
    for q in unique_by_text.values():
        topic = _detect_topic(q)
        grouped.setdefault(topic, []).append(q)

    sections = []
    for topic in sorted(grouped.keys()):
        items = sorted(grouped[topic], key=lambda x: (x.get("original_question_number") or x.get("question_number", 0)))
        sections.append({"topic": topic, "items": items, "count": len(items)})
    return sections


@app.route("/")
def home():
    analytics = build_analytics()
    return render_template(
        "index.html",
        total=len(QUESTIONS),
        mistakes=len(session.get("mistakes", [])),
        analytics=analytics,
    )




@app.get("/sections")
def sections_page():
    sections = build_topic_sections((4, 5))
    total = sum(section["count"] for section in sections)
    return render_template("sections.html", sections=sections, total=total)


@app.get("/editor")
def questions_editor():
    questions = sorted(QUESTIONS, key=lambda x: x["question_number"])
    return render_template("editor.html", questions=questions)


@app.post("/editor/save")
def save_questions_editor():
    updated_questions = []
    for q in sorted(QUESTIONS, key=lambda x: x["question_number"]):
        qid = q["question_number"]
        question_text = request.form.get(f"question_{qid}", q["question"]).strip()

        updated_options = []
        for idx, opt in enumerate(q.get("options", [])):
            new_opt = request.form.get(f"option_{qid}_{idx}", opt).strip()
            updated_options.append(new_opt)

        raw_correct = request.form.get(f"correct_{qid}", str(q.get("correct_option_index", 0)))
        try:
            correct_idx = int(raw_correct)
        except ValueError:
            correct_idx = q.get("correct_option_index", 0)

        if correct_idx < 0 or correct_idx >= len(updated_options):
            correct_idx = 0 if updated_options else -1

        updated_q = {
            **q,
            "question": question_text,
            "options": updated_options,
            "correct_option_index": correct_idx,
            "correct_text": updated_options[correct_idx] if updated_options and correct_idx >= 0 else "",
        }
        updated_questions.append(updated_q)

    save_questions(updated_questions)
    refresh_questions_cache()
    return redirect(url_for("questions_editor"))


@app.post("/editor/import")
def import_questions_editor():
    raw_text = request.form.get("bulk_text", "")
    raw_category = request.form.get("import_category", "5")
    try:
        category = int(raw_category)
    except ValueError:
        category = 5
    section = request.form.get("import_section", "").strip() or f"Категория {category}"

    parsed = parse_questions_from_text(raw_text, category=category, section=section)
    if not parsed:
        return redirect(url_for("questions_editor"))

    by_number = {q["question_number"]: q for q in QUESTIONS}
    for q in parsed:
        by_number[q["question_number"]] = q

    merged = [by_number[k] for k in sorted(by_number.keys())]
    save_questions(merged)
    refresh_questions_cache()
    return redirect(url_for("questions_editor"))


@app.post("/start")
def start_test():
    mode = request.form.get("mode", "common_50")
    raw_category = request.form.get("category", "5")
    try:
        selected_category = int(raw_category)
    except ValueError:
        selected_category = 5
    category_pool = [q for q in QUESTIONS if q.get("category") == selected_category]

    if mode == "mistakes":
        stats = load_stats()
        persistent_ids = [int(k) for k, v in stats.get("mistake_counts", {}).items() if v > 0]
        session_ids = session.get("mistakes", [])
        ids = sorted(set(persistent_ids + session_ids))
        pool = [QUESTIONS_BY_ID[i] for i in ids if i in QUESTIONS_BY_ID and QUESTIONS_BY_ID[i].get("category") == selected_category]
        random.shuffle(pool)
    else:
        limit = 20 if mode == "quick_20" else 50
        recent_ids = set(session.get("recent_question_ids", []))
        pool = build_balanced_pool(category_pool, limit, exclude_ids=recent_ids)

    if not pool:
        return redirect(url_for("home"))

    session["test_ids"] = [q["question_number"] for q in pool]
    session["index"] = 0
    session["correct"] = 0
    session["answers"] = []
    session["mode"] = mode
    session["category"] = selected_category
    session["is_review"] = False
    return redirect(url_for("list_test"))




@app.post("/start_followup")
def start_followup():
    wrong_ids = session.get("last_wrong_ids", [])
    if not wrong_ids:
        return redirect(url_for("home"))

    pool = [QUESTIONS_BY_ID[qid] for qid in wrong_ids if qid in QUESTIONS_BY_ID]
    if not pool:
        return redirect(url_for("home"))

    session["test_ids"] = [q["question_number"] for q in pool]
    session["index"] = 0
    session["correct"] = 0
    session["answers"] = []
    session["mode"] = "followup"
    session["is_review"] = True
    return redirect(url_for("list_test"))


@app.route("/exit_test")
def exit_test():
    for key in ["test_ids", "index", "correct", "answers", "mode", "category"]:
        session.pop(key, None)
    return redirect(url_for("home"))


@app.route("/list_test")
def list_test():
    test_ids = session.get("test_ids", [])
    if not test_ids:
        return redirect(url_for("home"))
    questions = [QUESTIONS_BY_ID[qid] for qid in test_ids if qid in QUESTIONS_BY_ID]
    return render_template(
        "list_test.html",
        questions=questions,
        mode=session.get("mode", "common_50"),
        category=session.get("category", 5),
    )


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

    is_review = session.get("is_review", False)
    if not is_review:
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
    session["last_wrong_ids"] = wrong_ids

    recent_ids = list(dict.fromkeys(session.get("recent_question_ids", []) + test_ids))
    session["recent_question_ids"] = recent_ids[-500:]
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
        has_followup=wrong > 0 and not session.get("is_review", False),
        is_review=session.get("is_review", False),
    )


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "5000"))
    debug = os.getenv("DEBUG", "0") == "1"
    # По умолчанию HTTPS для удобного доступа с телефона
    use_https = os.getenv("USE_HTTPS", "1") == "1"

    if use_https and CERT_PATH.exists() and KEY_PATH.exists():
        app.run(host=host, port=port, debug=debug, ssl_context=(str(CERT_PATH), str(KEY_PATH)))
    elif use_https:
        print("[WARN] Не найдены cert.pem/cert_key.pem. Запускаем HTTP. Для HTTPS добавьте сертификаты.")
        app.run(host=host, port=port, debug=debug)
    else:
        app.run(host=host, port=port, debug=debug)
