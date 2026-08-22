from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import sqlite3
import re

BASE = Path(__file__).resolve().parent.parent
DB = BASE / "exam.db"

app = FastAPI(title="AI Examination Assessment System")

app.mount(
    "/static",
    StaticFiles(directory=str(BASE / "static")),
    name="static"
)


def get_db():
    connection = sqlite3.connect(DB)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database():
    connection = get_db()

    connection.execute("""
        CREATE TABLE IF NOT EXISTS exams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            course TEXT NOT NULL,
            duration INTEGER NOT NULL
        )
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_id INTEGER,
            question TEXT NOT NULL,
            model_answer TEXT NOT NULL,
            marks REAL NOT NULL
        )
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_name TEXT,
            student_id TEXT,
            exam_id INTEGER,
            score REAL,
            ai_risk REAL
        )
    """)

    exam = connection.execute(
        "SELECT id FROM exams LIMIT 1"
    ).fetchone()

    if not exam:

        cursor = connection.execute(
            """
            INSERT INTO exams
            (title, course, duration)
            VALUES (?, ?, ?)
            """,
            (
                "Introduction to Computer Science",
                "CSC 401",
                60
            )
        )

        exam_id = cursor.lastrowid

        questions = [
            (
                "What is a database?",
                "A database is an organized collection of data that can be stored, managed and retrieved electronically.",
                10
            ),
            (
                "Explain Artificial Intelligence.",
                "Artificial Intelligence is the field of computer science concerned with creating systems that can perform tasks that normally require human intelligence.",
                10
            ),
            (
                "What is Natural Language Processing?",
                "Natural Language Processing is a branch of artificial intelligence that enables computers to understand, process and analyze human language.",
                10
            )
        ]

        for question, answer, marks in questions:

            connection.execute(
                """
                INSERT INTO questions
                (exam_id, question, model_answer, marks)
                VALUES (?, ?, ?, ?)
                """,
                (
                    exam_id,
                    question,
                    answer,
                    marks
                )
            )

    connection.commit()
    connection.close()


initialize_database()


def calculate_similarity(student_answer, model_answer):

    student_words = set(
        re.findall(
            r"\b[a-zA-Z]{3,}\b",
            student_answer.lower()
        )
    )

    model_words = set(
        re.findall(
            r"\b[a-zA-Z]{3,}\b",
            model_answer.lower()
        )
    )

    if not model_words:
        return 0.0

    common_words = student_words.intersection(
        model_words
    )

    return len(common_words) / len(model_words)


def detect_ai_risk(text):

    words = re.findall(
        r"\b\w+\b",
        text
    )

    if len(words) < 20:
        return 0

    sentences = [
        sentence.strip()
        for sentence in re.split(
            r"[.!?]+",
            text
        )
        if sentence.strip()
    ]

    if not sentences:
        return 0

    lengths = [
        len(
            re.findall(
                r"\b\w+\b",
                sentence
            )
        )
        for sentence in sentences
    ]

    average_length = (
        sum(lengths) / len(lengths)
    )

    risk = 0

    if average_length > 18:
        risk += 25

    unique_words = len(
        set(
            word.lower()
            for word in words
        )
    )

    unique_ratio = (
        unique_words / len(words)
    )

    if unique_ratio > 0.65:
        risk += 20

    if len(sentences) >= 4:
        risk += 10

    return min(risk, 85)


def render_page(title, content):

    return f"""
    <!DOCTYPE html>

    <html>

    <head>

        <meta charset="UTF-8">

        <meta
            name="viewport"
            content="width=device-width,
            initial-scale=1.0"
        >

        <title>{title}</title>

        <link
            rel="stylesheet"
            href="/static/style.css"
        >

    </head>

    <body>

        <nav>

            <a href="/">
                AI Assessment System
            </a>

            <span>
                Examination Assessment
            </span>

        </nav>

        <main>

            {content}

        </main>

    </body>

    </html>
    """


@app.get(
    "/",
    response_class=HTMLResponse
)
def home():

    connection = get_db()

    exams = connection.execute(
        "SELECT * FROM exams"
    ).fetchall()

    connection.close()

    cards = ""

    for exam in exams:

        cards += f"""
        <a
            class="card"
            href="/exam/{exam['id']}"
        >

            <h2>
                {exam['title']}
            </h2>

            <p>
                Course: {exam['course']}
            </p>

            <p>
                Duration:
                {exam['duration']} minutes
            </p>

        </a>
        """

    content = f"""

    <section class="hero">

        <h1>
            AI Examination Assessment System
        </h1>

        <p>
            Web-based intelligent examination
            assessment system for automatic
            marking and AI-generated answer
            analysis.
        </p>

    </section>

    <h2>
        Available Examinations
    </h2>

    <div class="grid">

        {cards}

    </div>

    <div class="info">

        AI detection provides an indicator
        for lecturer review and should not be
        treated as absolute proof of AI use.

    </div>

    """

    return render_page(
        "AI Examination Assessment System",
        content
    )


@app.get(
    "/exam/{exam_id}",
    response_class=HTMLResponse
)
def examination(exam_id: int):

    connection = get_db()

    exam = connection.execute(
        """
        SELECT * FROM exams
        WHERE id = ?
        """,
        (exam_id,)
    ).fetchone()

    questions = connection.execute(
        """
        SELECT * FROM questions
        WHERE exam_id = ?
        """,
        (exam_id,)
    ).fetchall()

    connection.close()

    if not exam:

        return render_page(
            "Error",
            """
            <div class="panel">

                <h2>
                    Examination not found.
                </h2>

            </div>
            """
        )

    question_html = ""

    for number, question in enumerate(
        questions,
        start=1
    ):

        question_html += f"""

        <div class="question">

            <label>

                {number}.
                {question['question']}

                ({question['marks']} marks)

            </label>

            <textarea
                name="question_{question['id']}"
                required
            ></textarea>

        </div>

        """

    content = f"""

    <form
        class="panel"
        method="post"
        action="/submit/{exam_id}"
    >

        <h1>
            {exam['title']}
        </h1>

        <input
            type="text"
            name="student_name"
            placeholder="Student Name"
            required
        >

        <input
            type="text"
            name="student_id"
            placeholder="Student ID"
            required
        >

        {question_html}

        <button type="submit">
            Submit Examination
        </button>

    </form>

    """

    return render_page(
        "Examination",
        content
    )


@app.post(
    "/submit/{exam_id}",
    response_class=HTMLResponse
)
async def submit_exam(
    exam_id: int,
    request: Request,
    student_name: str = Form(...),
    student_id: str = Form(...)
):

    form = await request.form()

    connection = get_db()

    questions = connection.execute(
        """
        SELECT * FROM questions
        WHERE exam_id = ?
        """,
        (exam_id,)
    ).fetchall()

    total_score = 0.0
    total_marks = 0.0
    ai_risks = []

    results = ""

    for question in questions:

        field_name = (
            "question_"
            + str(question["id"])
        )

        answer = str(
            form.get(field_name, "")
        )

        similarity = calculate_similarity(
            answer,
            question["model_answer"]
        )

        marks = round(
            similarity * question["marks"],
            1
        )

        risk = detect_ai_risk(answer)

        total_score += marks
        total_marks += question["marks"]

        ai_risks.append(risk)

        results += f"""

        <div class="result">

            <h3>
                {question['question']}
            </h3>

            <p>
                Mark awarded:
                <strong>
                    {marks}/{question['marks']}
                </strong>
            </p>

            <p>
                Answer similarity:
                {similarity * 100:.1f}%
            </p>

            <p>
                AI-risk indicator:
                {risk}%
            </p>

        </div>

        """

    if ai_risks:

        overall_risk = (
            sum(ai_risks)
            / len(ai_risks)
        )

    else:

        overall_risk = 0

    connection.execute(
        """
        INSERT INTO submissions
        (
            student_name,
            student_id,
            exam_id,
            score,
            ai_risk
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            student_name,
            student_id,
            exam_id,
            total_score,
            overall_risk
        )
    )

    connection.commit()
    connection.close()

    content = f"""

    <div class="panel">

        <h1>
            Examination Result
        </h1>

        <h2>
            {student_name}
        </h2>

        <p>
            Student ID:
            {student_id}
        </p>

        <div class="score">

            {total_score:.1f}
            /
            {total_marks:.1f}

        </div>

        {results}

        <div class="warning">

            AI-risk indicator:
            <strong>
                {overall_risk:.0f}%
            </strong>

            <br><br>

            This indicator should be reviewed
            by the lecturer before making
            academic decisions.

        </div>

        <br>

        <a href="/">
            Return to Home
        </a>

    </div>

    """

    return render_page(
        "Examination Result",
        content
    )
