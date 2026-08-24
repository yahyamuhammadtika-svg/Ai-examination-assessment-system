
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from datetime import datetime
import sqlite3
import re
import io
import csv
import hashlib

BASE = Path(__file__).resolve().parent.parent
DB = BASE / "exam.db"

app = FastAPI(title="AI Examination Assessment System")

app.mount(
    "/static",
    StaticFiles(directory=str(BASE / "static")),
    name="static"
)


# ============================================================
# DATABASE
# ============================================================

def db():
    connection = sqlite3.connect(DB)
    connection.row_factory = sqlite3.Row
    return connection


def init():
    connection = db()

    connection.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT,
            role TEXT
        );

        CREATE TABLE IF NOT EXISTS exams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            course TEXT NOT NULL,
            duration INTEGER NOT NULL,
            status TEXT DEFAULT 'Active'
        );

        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_id INTEGER,
            text TEXT,
            max_marks REAL,
            model_answer TEXT,
            rubric TEXT
        );

        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student TEXT,
            student_id TEXT,
            exam_id INTEGER,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS answers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            submission_id INTEGER,
            question_id INTEGER,
            text TEXT,
            similarity REAL,
            marks REAL,
            ai_risk REAL,
            reviewed INTEGER DEFAULT 0
        );
    """)

    # Default lecturer account
    if not connection.execute(
        "SELECT 1 FROM users WHERE username='admin'"
    ).fetchone():

        password = hashlib.sha256(
            b"admin123"
        ).hexdigest()

        connection.execute(
            """
            INSERT INTO users
            (username, password, role)
            VALUES (?, ?, ?)
            """,
            ("admin", password, "lecturer")
        )

    # Create demonstration examination only
    if not connection.execute(
        "SELECT 1 FROM exams"
    ).fetchone():

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
                10,
                "definition;organized collection;data;storage;retrieval"
            ),

            (
                "Explain artificial intelligence.",
                "Artificial intelligence is the field of computing concerned with systems that perform tasks associated with human intelligence such as learning, reasoning and language understanding.",
                10,
                "computer systems;human intelligence;learning;reasoning"
            ),

            (
                "What is Natural Language Processing?",
                "Natural Language Processing is a branch of artificial intelligence that enables computers to process, understand and analyze human language.",
                10,
                "artificial intelligence;human language;process;understand;analyze"
            )
        ]

        for question, answer, marks, rubric in questions:

            connection.execute(
                """
                INSERT INTO questions
                (exam_id, text, max_marks, model_answer, rubric)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    exam_id,
                    question,
                    marks,
                    answer,
                    rubric
                )
            )

    connection.commit()
    connection.close()


init()


# ============================================================
# AI / NLP FUNCTIONS
# ============================================================

model = None


def similarity(answer, model_answer):

    global model

    if not answer.strip() or not model_answer.strip():
        return 0.0

    try:

        from sentence_transformers import SentenceTransformer

        if model is None:

            model = SentenceTransformer(
                "sentence-transformers/all-MiniLM-L6-v2"
            )

        embeddings = model.encode(
            [answer, model_answer],
            normalize_embeddings=True
        )

        score = float(
            embeddings[0] @ embeddings[1]
        )

        return max(0.0, min(1.0, score))

    except Exception:

        student_words = set(
            re.findall(
                r"\b[a-zA-Z]{3,}\b",
                answer.lower()
            )
        )

        model_words = set(
            re.findall(
                r"\b[a-zA-Z]{3,}\b",
                model_answer.lower()
            )
        )

        if not student_words or not model_words:
            return 0.0

        common = student_words.intersection(
            model_words
        )

        return len(common) / len(model_words)


def ai_risk(text):

    words = re.findall(
        r"\b[\w']+\b",
        text
    )

    if len(words) < 25:
        return 0.0

    sentences = [
        sentence
        for sentence in re.split(
            r"[.!?]+",
            text
        )
        if sentence.strip()
    ]

    if not sentences:
        return 0.0

    lengths = [
        len(
            re.findall(
                r"\b\w+\b",
                sentence
            )
        )
        for sentence in sentences
    ]

    average = sum(lengths) / len(lengths)

    variance = sum(
        (length - average) ** 2
        for length in lengths
    ) / len(lengths)

    vocabulary_ratio = (
        len(
            set(
                word.lower()
                for word in words
            )
        )
        / len(words)
    )

    risk = 0.10

    if variance < 15:
        risk += 0.20

    if average > 18:
        risk += 0.15

    if vocabulary_ratio > 0.65:
        risk += 0.15

    return round(
        min(0.85, risk),
        2
    )


def score_answer(text, question):

    sim = similarity(
        text,
        question["model_answer"]
    )

    keywords = [
        item.strip().lower()
        for item in (
            question["rubric"] or ""
        ).split(";")
        if item.strip()
    ]

    answer_lower = text.lower()

    if keywords:

        hits = sum(
            1
            for keyword in keywords
            if keyword in answer_lower
        )

        keyword_score = (
            hits / len(keywords)
        )

        combined = (
            0.65 * sim
            + 0.35 * keyword_score
        )

    else:

        combined = sim

    combined = max(
        0.0,
        min(1.0, combined)
    )

    marks = round(
        combined * question["max_marks"],
        1
    )

    risk = ai_risk(text)

    return sim, marks, risk


# ============================================================
# PAGE TEMPLATE
# ============================================================

def page(title, body):

    return f"""
    <!doctype html>

    <html>

    <head>

        <meta charset="utf-8">

        <meta
            name="viewport"
            content="width=device-width, initial-scale=1"
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
                AI Assessment
            </a>

            <span>
                AI-Based Examination Assessment System
            </span>

        </nav>

        <main>

            {body}

        </main>

        <footer>
            AI-Based Examination Assessment System
        </footer>

    </body>

    </html>
    """


def is_logged(request):

    return request.cookies.get(
        "lecturer"
    ) == "1"


# ============================================================
# HOME PAGE
# ============================================================

@app.get(
    "/",
    response_class=HTMLResponse
)
def home():

    connection = db()

    exams = connection.execute(
        """
        SELECT *
        FROM exams
        WHERE status='Active'
        ORDER BY id DESC
        """
    ).fetchall()

    submission_count = connection.execute(
        """
        SELECT COUNT(*) AS total
        FROM submissions
        """
    ).fetchone()["total"]

    connection.close()

    cards = ""

    for exam in exams:

        cards += f"""
        <div class="card">

            <h2>
                {exam['title']}
            </h2>

            <p>
                {exam['course']}
                ·
                {exam['duration']} minutes
            </p>

            <a
                class="button"
                href="/exam/{exam['id']}"
            >
                Student View
            </a>

            <a
                class="button secondary"
                href="/lecturer/exam/{exam['id']}"
            >
                Manage
            </a>

        </div>
        """

    body = f"""

    <section class="hero">

        <span>
            AI ASSESSMENT
        </span>

        <h1>
            Examination Assessment System
        </h1>

        <p>
            Automated examination marking,
            semantic answer comparison and
            AI-generated-answer risk analysis.
        </p>

        <a
            class="button"
            href="/login"
        >
            Lecturer Login
        </a>

    </section>


    <div class="stats">

        <div>
            <b>{len(exams)}</b>
            <small>Examinations</small>
        </div>

        <div>
            <b>{submission_count}</b>
            <small>Submissions</small>
        </div>

        <div>
            <b>NLP</b>
            <small>Semantic Marking</small>
        </div>

    </div>


    <h2>
        Available Examinations
    </h2>

    <div class="grid">

        {cards}

    </div>

    <div class="info">

        <strong>Important:</strong>

        The AI-risk percentage is an indicator
        for lecturer review. It is not absolute
        proof that artificial intelligence was used.

    </div>

    """

    return page(
        "AI Examination Assessment System",
        body
    )


# ============================================================
# LECTURER LOGIN
# ============================================================

@app.get(
    "/login",
    response_class=HTMLResponse
)
def login():

    body = """

    <form
        class="panel narrow"
        method="post"
        action="/login"
    >

        <h1>
            Lecturer Login
        </h1>

        <input
            name="username"
            placeholder="Username"
            required
        >

        <input
            name="password"
            type="password"
            placeholder="Password"
            required
        >

        <button>
            Login
        </button>

        <p class="muted">
            Demo account:
            admin / admin123
        </p>

    </form>

    """

    return page(
        "Lecturer Login",
        body
    )


@app.post("/login")
def do_login(
    username: str = Form(...),
    password: str = Form(...)
):

    password_hash = hashlib.sha256(
        password.encode()
    ).hexdigest()

    connection = db()

    user = connection.execute(
        """
        SELECT *
        FROM users
        WHERE username=?
        AND password=?
        """,
        (
            username,
            password_hash
        )
    ).fetchone()

    connection.close()

    if not user:

        return HTMLResponse(
            page(
                "Login Error",
                """
                <div class="panel">

                    <h2>
                        Invalid username or password.
                    </h2>

                    <a href="/login">
                        Try Again
                    </a>

                </div>
                """
            ),
            status_code=401
        )

    response = RedirectResponse(
        "/lecturer",
        status_code=303
    )

    response.set_cookie(
        "lecturer",
        "1",
        httponly=True
    )

    return response


@app.get("/logout")
def logout():

    response = RedirectResponse(
        "/",
        status_code=303
    )

    response.delete_cookie(
        "lecturer"
    )

    return response


# ============================================================
# LECTURER DASHBOARD
# ============================================================

@app.get(
    "/lecturer",
    response_class=HTMLResponse
)
def lecturer_dashboard(
    request: Request
):

    if not is_logged(request):

        return RedirectResponse(
            "/login",
            status_code=303
        )

    connection = db()

    exams = connection.execute(
        """
        SELECT *
        FROM exams
        ORDER BY id DESC
        """
    ).fetchall()

    submissions = connection.execute(
        """
        SELECT
            s.*,
            e.title
        FROM submissions s
        JOIN exams e
        ON e.id = s.exam_id
        ORDER BY s.id DESC
        """
    ).fetchall()

    connection.close()

    exam_cards = ""

    for exam in exams:

        exam_cards += f"""

        <div class="card">

            <h3>
                {exam['title']}
            </h3>

            <p>
                {exam['course']}
                ·
                {exam['duration']} minutes
            </p>

            <p>
                Status:
                <strong>
                    {exam['status']}
                </strong>
            </p>

            <a
                class="button"
                href="/lecturer/exam/{exam['id']}"
            >
                Manage Exam
            </a>

        </div>

        """

    rows = ""

    for submission in submissions:

        rows += f"""

        <tr>

            <td>
                {submission['student']}
            </td>

            <td>
                {submission['student_id']}
            </td>

            <td>
                {submission['title']}
            </td>

            <td>
                {submission['created_at']}
            </td>

            <td>

                <a
                    href="/lecturer/submission/{submission['id']}"
                >
                    Review
                </a>

            </td>

        </tr>

        """

    if not rows:

        rows = """
        <tr>
            <td colspan="5">
                No submissions yet.
            </td>
        </tr>
        """

    body = f"""

    <div class="topline">

        <div>

            <span>
                LECTURER DASHBOARD
            </span>

            <h1>
                Assessment Control Centre
            </h1>

        </div>

        <div>

            <a
                class="button"
                href="/lecturer/create"
            >
                + Create New Examination
            </a>

            <a href="/logout">
                Logout
            </a>

        </div>

    </div>


    <h2>
        Examinations
    </h2>

    <div class="grid">

        {exam_cards}

    </div>


    <div class="panel">

        <h2>
            Recent Submissions
        </h2>

        <table>

            <tr>

                <th>
                    Student
                </th>

                <th>
                    ID
                </th>

                <th>
                    Examination
                </th>

                <th>
                    Date
                </th>

                <th>
                    Action
                </th>

            </tr>

            {rows}

        </table>

    </div>

    """

    return page(
        "Lecturer Dashboard",
        body
    )


# ============================================================
# CREATE NEW EXAMINATION
# ============================================================

@app.get(
    "/lecturer/create",
    response_class=HTMLResponse
)
def create_exam_page(
    request: Request
):

    if not is_logged(request):

        return RedirectResponse(
            "/login",
            status_code=303
        )

    body = """

    <div class="topline">

        <div>

            <span>
                NEW EXAMINATION
            </span>

            <h1>
                Create Examination
            </h1>

            <p>
                Enter the basic details of the
                new examination.
            </p>

        </div>

        <a href="/lecturer">
            Dashboard
        </a>

    </div>


    <form
        class="panel"
        method="post"
        action="/lecturer/create"
    >

        <h2>
            Examination Details
        </h2>

        <label>
            Examination Title
        </label>

        <input
            type="text"
            name="title"
            placeholder="e.g. Database Management Systems Examination"
            required
        >


        <label>
            Course / Course Code
        </label>

        <input
            type="text"
            name="course"
            placeholder="e.g. CSC 401"
            required
        >


        <label>
            Duration in Minutes
        </label>

        <input
            type="number"
            name="duration"
            placeholder="e.g. 60"
            min="1"
            required
        >


        <button type="submit">
            Create Examination
        </button>

    </form>

    """

    return page(
        "Create Examination",
        body
    )


@app.post("/lecturer/create")
def create_exam(
    request: Request,
    title: str = Form(...),
    course: str = Form(...),
    duration: int = Form(...)
):

    if not is_logged(request):

        return RedirectResponse(
            "/login",
            status_code=303
        )

    title = title.strip()
    course = course.strip()

    if not title or not course or duration <= 0:

        return HTMLResponse(
            page(
                "Invalid Examination",
                """
                <div class="panel">

                    <h2>
                        Please enter valid
                        examination details.
                    </h2>

                    <a href="/lecturer/create">
                        Go Back
                    </a>

                </div>
                """
            ),
            status_code=400
        )

    connection = db()

    cursor = connection.execute(
        """
        INSERT INTO exams
        (title, course, duration, status)
        VALUES (?, ?, ?, 'Active')
        """,
        (
            title,
            course,
            duration
        )
    )

    exam_id = cursor.lastrowid

    connection.commit()
    connection.close()

    return RedirectResponse(
        f"/lecturer/exam/{exam_id}",
        status_code=303
    )


# ============================================================
# MANAGE EXAMINATION
# ============================================================

@app.get(
    "/lecturer/exam/{exam_id}",
    response_class=HTMLResponse
)
def manage_exam(
    request: Request,
    exam_id: int
):

    if not is_logged(request):

        return RedirectResponse(
            "/login",
            status_code=303
        )

    connection = db()

    exam = connection.execute(
        """
        SELECT *
        FROM exams
        WHERE id=?
        """,
        (exam_id,)
    ).fetchone()

    questions = connection.execute(
        """
        SELECT *
        FROM questions
        WHERE exam_id=?
        ORDER BY id
        """,
        (exam_id,)
    ).fetchall()

    connection.close()

    if not exam:

        return HTMLResponse(
            page(
                "Not Found",
                """
                <div class="panel">

                    <h2>
                        Examination not found.
                    </h2>

                    <a href="/lecturer">
                        Dashboard
                    </a>

                </div>
                """
            ),
            status_code=404
        )

    question_cards = ""

    for number, question in enumerate(
        questions,
        start=1
    ):

        question_cards += f"""

        <div class="question">

            <b>
                Q{number}.
                {question['text']}
            </b>

            <p>
                Maximum marks:
                {question['max_marks']}
            </p>

            <details>

                <summary>
                    View Model Answer and Rubric
                </summary>

                <p>
                    <strong>
                        Model Answer:
                    </strong>
                </p>

                <p>
                    {question['model_answer']}
                </p>

                <p>
                    <strong>
                        Marking Keywords:
                    </strong>
                </p>

                <p>
                    {question['rubric'] or 'Not specified'}
                </p>

            </details>

        </div>

        """

    if not question_cards:

        question_cards = """

        <div class="info">

            No questions have been added yet.

            Add the first question below.

        </div>

        """

    body = f"""

    <div class="topline">

        <div>

            <span>
                EXAM MANAGEMENT
            </span>

            <h1>
                {exam['title']}
            </h1>

            <p>
                {exam['course']}
                ·
                {exam['duration']} minutes
            </p>

        </div>

        <div>

            <a href="/lecturer">
                Dashboard
            </a>

            &nbsp;

            <a
                class="button"
                href="/exam/{exam_id}"
            >
                Student Preview
            </a>

        </div>

    </div>


    <div class="panel">

        <h2>
            Questions and Marking Scheme
        </h2>

        {question_cards}

    </div>


    <div class="panel">

        <h2>
            Add Question
        </h2>

        <form
            method="post"
            action="/lecturer/exam/{exam_id}/question"
        >

            <label>
                Question
            </label>

            <textarea
                name="text"
                placeholder="Enter the examination question"
                required
            ></textarea>


            <label>
                Maximum Marks
            </label>

            <input
                type="number"
                name="max_marks"
                step="0.5"
                min="0.5"
                placeholder="e.g. 10"
                required
            >


            <label>
                Model / Expected Answer
            </label>

            <textarea
                name="model_answer"
                placeholder="Enter the expected answer or marking guide"
                required
            ></textarea>


            <label>
                Marking Keywords
            </label>

            <input
                type="text"
                name="rubric"
                placeholder="Separate important concepts with semicolons"
            >

            <p class="muted">
                Example:
                database;organized collection;data;storage;retrieval
            </p>


            <button type="submit">
                Add Question
            </button>

        </form>

    </div>

    """

    return page(
        "Manage Examination",
        body
    )


@app.post(
    "/lecturer/exam/{exam_id}/question"
)
def add_question(
    request: Request,
    exam_id: int,
    text: str = Form(...),
    max_marks: float = Form(...),
    model_answer: str = Form(...),
    rubric: str = Form("")
):

    if not is_logged(request):

        return RedirectResponse(
            "/login",
            status_code=303
        )

    if max_marks <= 0:

        return HTMLResponse(
            page(
                "Invalid Marks",
                """
                <div class="panel">

                    <h2>
                        Maximum marks must be
                        greater than zero.
                    </h2>

                    <a href="/lecturer">
                        Dashboard
                    </a>

                </div>
                """
            ),
            status_code=400
        )

    connection = db()

    exam = connection.execute(
        """
        SELECT id
        FROM exams
        WHERE id=?
        """,
        (exam_id,)
    ).fetchone()

    if not exam:

        connection.close()

        return HTMLResponse(
            page(
                "Error",
                """
                <div class="panel">
                    <h2>
                        Examination not found.
                    </h2>
                </div>
                """
            ),
            status_code=404
        )

    connection.execute(
        """
        INSERT INTO questions
        (
            exam_id,
            text,
            max_marks,
            model_answer,
            rubric
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            exam_id,
            text.strip(),
            max_marks,
            model_answer.strip(),
            rubric.strip()
        )
    )

    connection.commit()
    connection.close()

    return RedirectResponse(
        f"/lecturer/exam/{exam_id}",
        status_code=303
    )


# ============================================================
# STUDENT EXAMINATION
# ============================================================

@app.get(
    "/exam/{exam_id}",
    response_class=HTMLResponse
)
def exam(
    exam_id: int
):

    connection = db()

    exam_data = connection.execute(
        """
        SELECT *
        FROM exams
        WHERE id=?
        AND status='Active'
        """,
        (exam_id,)
    ).fetchone()

    questions = connection.execute(
        """
        SELECT *
        FROM questions
        WHERE exam_id=?
        ORDER BY id
        """,
        (exam_id,)
    ).fetchall()

    connection.close()

    if not exam_data:

        return HTMLResponse(
            page(
                "Not Found",
                """
                <div class="panel">

                    <h2>
                        Examination not found
                        or is not active.
                    </h2>

                    <a href="/">
                        Return Home
                    </a>

                </div>
                """
            ),
            status_code=404
        )

    if not questions:

        return HTMLResponse(
            page(
                "No Questions",
                f"""
                <div class="panel">

                    <h2>
                        This examination does
                        not have any questions yet.
                    </h2>

                    <a href="/">
                        Return Home
                    </a>

                </div>
                """
            )
        )

    fields = ""

    for number, question in enumerate(
        questions,
        start=1
    ):

        fields += f"""

        <div class="question">

            <label>

                {number}.
                {question['text']}

                <small>
                    ({question['max_marks']} marks)
                </small>

            </label>

            <textarea
                name="q_{question['id']}"
                placeholder="Type your answer here..."
                required
            ></textarea>

        </div>

        """

    body = f"""

    <form
        class="panel"
        method="post"
        action="/submit/{exam_id}"
    >

        <span>
            STUDENT EXAMINATION
        </span>

        <h1>
            {exam_data['title']}
        </h1>

        <p>
            {exam_data['course']}
            ·
            {exam_data['duration']} minutes
        </p>


        <input
            name="student"
            placeholder="Student Full Name"
            required
        >


        <input
            name="student_id"
            placeholder="Student ID"
            required
        >


        {fields}


        <button type="submit">
            Submit Examination for Assessment
        </button>

    </form>

    """

    return page(
        "Student Examination",
        body
    )


# ============================================================
# SUBMIT EXAMINATION
# ============================================================

@app.post(
    "/submit/{exam_id}",
    response_class=HTMLResponse
)
async def submit(
    exam_id: int,
    request: Request,
    student: str = Form(...),
    student_id: str = Form(...)
):

    form = await request.form()

    connection = db()

    exam_data = connection.execute(
        """
        SELECT *
        FROM exams
        WHERE id=?
        """,
        (exam_id,)
    ).fetchone()

    questions = connection.execute(
        """
        SELECT *
        FROM questions
        WHERE exam_id=?
        ORDER BY id
        """,
        (exam_id,)
    ).fetchall()

    if not exam_data:

        connection.close()

        return HTMLResponse(
            page(
                "Error",
                """
                <div class="panel">

                    <h2>
                        Examination not found.
                    </h2>

                    <a href="/">
                        Return Home
                    </a>

                </div>
                """
            ),
            status_code=404
        )

    submission_id = connection.execute(
        """
        INSERT INTO submissions
        (
            student,
            student_id,
            exam_id,
            created_at
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            student,
            student_id,
            exam_id,
            datetime.now().strftime(
                "%Y-%m-%d %H:%M"
            )
        )
    ).lastrowid

    total_score = 0.0
    total_marks = 0.0

    ai_risks = []

    result_cards = ""

    for question in questions:

        field_name = (
            "q_"
            + str(question["id"])
        )

        answer = str(
            form.get(
                field_name,
                ""
            )
        )

        sim, marks, risk = score_answer(
            answer,
            question
        )

        connection.execute(
            """
            INSERT INTO answers
            (
                submission_id,
                question_id,
                text,
                similarity,
                marks,
                ai_risk
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                submission_id,
                question["id"],
                answer,
                sim,
                marks,
                risk
            )
        )

        total_score += marks
        total_marks += question["max_marks"]

        ai_risks.append(risk)

        risk_percent = risk * 100
        similarity_percent = sim * 100

        result_cards += f"""

        <div class="result">

            <h3>
                {question['text']}
            </h3>

            <p>
                Mark awarded:
                <strong>
                    {marks}/{question['max_marks']}
                </strong>
            </p>

            <p>
                Answer similarity:
                <strong>
                    {similarity_percent:.1f}%
                </strong>
            </p>

            <p>
                AI-risk indicator:
                <strong>
                    {risk_percent:.0f}%
                </strong>
            </p>

        </div>

        """

    connection.commit()
    connection.close()

    if ai_risks:

        overall_risk = (
            sum(ai_risks)
            / len(ai_risks)
        )

    else:

        overall_risk = 0

    body = f"""

    <div class="panel">

        <span>
            ASSESSMENT COMPLETE
        </span>

        <h1>
            {student}
        </h1>

        <p>
            Student ID:
            {student_id}
        </p>

        <div class="score">

            {total_score:.1f}

            <small>
                / {total_marks:.1f}
            </small>

        </div>


        {result_cards}


        <div class="warning">

            <strong>
                Overall AI-risk indicator:
                {overall_risk * 100:.0f}%
            </strong>

            <br><br>

            This indicator is intended to
            support lecturer review. It should
            not be treated as absolute proof
            that artificial intelligence was used.

        </div>


        <br>

        <a
            class="button"
            href="/"
        >
            Return Home
        </a>

    </div>

    """

    return page(
        "Assessment Result",
        body
    )


# ============================================================
# LECTURER SUBMISSION REVIEW
# ============================================================

@app.get(
    "/lecturer/submission/{submission_id}",
    response_class=HTMLResponse
)
def review_submission(
    request: Request,
    submission_id: int
):

    if not is_logged(request):

        return RedirectResponse(
            "/login",
            status_code=303
        )

    connection = db()

    submission = connection.execute(
        """
        SELECT
            s.*,
            e.title
        FROM submissions s
        JOIN exams e
        ON e.id=s.exam_id
        WHERE s.id=?
        """,
        (submission_id,)
    ).fetchone()

    answers = connection.execute(
        """
        SELECT
            a.*,
            q.text,
            q.max_marks,
            q.model_answer
        FROM answers a
        JOIN questions q
        ON q.id=a.question_id
        WHERE a.submission_id=?
        """,
        (submission_id,)
    ).fetchall()

    connection.close()

    if not submission:

        return HTMLResponse(
            page(
                "Not Found",
                """
                <div class="panel">

                    <h2>
                        Submission not found.
                    </h2>

                    <a href="/lecturer">
                        Dashboard
                    </a>

                </div>
                """
            ),
            status_code=404
        )

    total = sum(
        answer["marks"]
        for answer in answers
    )

    maximum = sum(
        answer["max_marks"]
        for answer in answers
    )

    review_cards = ""

    for answer in answers:

        review_cards += f"""

        <div class="review">

            <h3>
                {answer['text']}
            </h3>

            <p>
                <strong>
                    Student Answer:
                </strong>
            </p>

            <blockquote>
                {answer['text']}
            </blockquote>

            <p>
                <strong>
                    Model Answer:
                </strong>
            </p>

            <blockquote>
                {answer['model_answer']}
            </blockquote>

            <p>
                Similarity:
                {answer['similarity'] * 100:.1f}%
            </p>

            <p>
                AI-risk:
                {answer['ai_risk'] * 100:.0f}%
            </p>

            <p>
                Mark:
                <strong>
                    {answer['marks']}
                    /
                    {answer['max_marks']}
                </strong>
            </p>

        </div>

        """

    body = f"""

    <div class="topline">

        <div>

            <span>
                LECTURER REVIEW
            </span>

            <h1>
                {submission['student']}
            </h1>

            <p>
                {submission['title']}
                ·
                {submission['student_id']}
            </p>

        </div>

        <a href="/lecturer">
            Dashboard
        </a>

    </div>


    <div class="panel">

        <div class="score">

            {total:.1f}

            <small>
                / {maximum:.1f}
            </small>

        </div>

        {review_cards}

        <a
            class="button"
            href="/lecturer/report/{submission_id}"
        >
            Download CSV Report
        </a>

    </div>

    """

    return page(
        "Review Submission",
        body
    )


# ============================================================
# CSV REPORT
# ============================================================

@app.get(
    "/lecturer/report/{submission_id}"
)
def report(
    request: Request,
    submission_id: int
):

    if not is_logged(request):

        return RedirectResponse(
            "/login",
            status_code=303
        )

    connection = db()

    submission = connection.execute(
        """
        SELECT *
        FROM submissions
        WHERE id=?
        """,
        (submission_id,)
    ).fetchone()

    answers = connection.execute(
        """
        SELECT
            a.*,
            q.text,
            q.max_marks
        FROM answers a
        JOIN questions q
        ON q.id=a.question_id
        WHERE a.submission_id=?
        """,
        (submission_id,)
    ).fetchall()

    connection.close()

    if not submission:

        return HTMLResponse(
            "Submission not found",
            status_code=404
        )

    output = io.StringIO()

    writer = csv.writer(output)

    writer.writerow([
        "Student",
        "Student ID",
        "Question",
        "Similarity",
        "Mark",
        "Maximum Marks",
        "AI Risk"
    ])

    for answer in answers:

        writer.writerow([
            submission["student"],
            submission["student_id"],
            answer["text"],
            f"{answer['similarity']:.3f}",
            answer["marks"],
            answer["max_marks"],
            f"{answer['ai_risk']:.2f}"
        ])

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition":
            f"attachment; filename=assessment_{submission_id}.csv"
        }
    )
