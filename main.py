
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from datetime import datetime
import sqlite3, re, io, csv, hashlib

BASE=Path(__file__).resolve().parent.parent
DB=BASE/"exam.db"
app=FastAPI(title="AI Examination Assessment System")
app.mount("/static",StaticFiles(directory=str(BASE/"static")),name="static")

def db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c

def init():
    c=db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT UNIQUE,password TEXT,role TEXT);
    CREATE TABLE IF NOT EXISTS exams(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT,course TEXT,duration INTEGER,status TEXT DEFAULT 'Active');
    CREATE TABLE IF NOT EXISTS questions(id INTEGER PRIMARY KEY AUTOINCREMENT,exam_id INTEGER,text TEXT,max_marks REAL,model_answer TEXT,rubric TEXT);
    CREATE TABLE IF NOT EXISTS submissions(id INTEGER PRIMARY KEY AUTOINCREMENT,student TEXT,student_id TEXT,exam_id INTEGER,created_at TEXT);
    CREATE TABLE IF NOT EXISTS answers(id INTEGER PRIMARY KEY AUTOINCREMENT,submission_id INTEGER,question_id INTEGER,text TEXT,similarity REAL,marks REAL,ai_risk REAL,reviewed INTEGER DEFAULT 0);
    """)
    if not c.execute("SELECT 1 FROM users WHERE username='admin'").fetchone():
        c.execute("INSERT INTO users(username,password,role) VALUES('admin',?,'lecturer')",(hashlib.sha256(b'admin123').hexdigest(),))
    if not c.execute("SELECT 1 FROM exams").fetchone():
        c.execute("INSERT INTO exams(title,course,duration) VALUES(?,?,?)",("Introduction to Computer Science","CSC 401",60))
        eid=c.execute("SELECT last_insert_rowid()").fetchone()[0]
        qs=[
        ("What is a database?","A database is an organized collection of data that can be stored, managed and retrieved electronically.",10,"definition;organized collection;data;storage;retrieval"),
        ("Explain artificial intelligence.","Artificial intelligence is the field of computing concerned with systems that perform tasks associated with human intelligence such as learning, reasoning and language understanding.",10,"computer systems;human intelligence;learning;reasoning"),
        ("What is Natural Language Processing?","Natural Language Processing is a branch of artificial intelligence that enables computers to process, understand and analyze human language.",10,"artificial intelligence;human language;process;understand;analyze")]
        for q,a,m,r in qs:c.execute("INSERT INTO questions(exam_id,text,max_marks,model_answer,rubric) VALUES(?,?,?,?,?)",(eid,q,m,a,r))
    c.commit(); c.close()
init()

model=None
def similarity(a,b):
    global model
    if not a.strip() or not b.strip(): return 0.0
    try:
        from sentence_transformers import SentenceTransformer
        if model is None:model=SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        e=model.encode([a,b],normalize_embeddings=True)
        return max(0,min(1,float(e[0]@e[1])))
    except Exception:
        A=set(re.findall(r"\b[a-zA-Z]{3,}\b",a.lower())); B=set(re.findall(r"\b[a-zA-Z]{3,}\b",b.lower()))
        return len(A&B)/len(A|B) if A|B else 0.0

def ai_risk(t):
    words=re.findall(r"\b[\w']+\b",t)
    if len(words)<25:return 0.0
    sentences=[x for x in re.split(r"[.!?]+",t) if x.strip()]
    lens=[len(re.findall(r"\b\w+\b",x)) for x in sentences]
    avg=sum(lens)/len(lens); var=sum((x-avg)**2 for x in lens)/len(lens)
    vocab=len(set(x.lower() for x in words))/len(words)
    score=.10+(.20 if var<15 else 0)+(.15 if avg>18 else 0)+(.15 if vocab>.65 else 0)
    return round(min(.85,score),2)

def score_answer(text,q):
    sim=similarity(text,q["model_answer"])
    keywords=[x.strip().lower() for x in (q["rubric"] or "").split(";") if x.strip()]
    low=text.lower()
    hit=sum(1 for k in keywords if k in low)/len(keywords) if keywords else 0
    combined=.65*sim+.35*hit if keywords else sim
    return sim,round(max(0,min(1,combined))*q["max_marks"],1),ai_risk(text)

def page(title,body,logged=False):
    nav="<nav><a href='/'>AI Assessment</a><span>AI-Based Examination Assessment System</span></nav>"
    return f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{title}</title><link rel='stylesheet' href='/static/style.css'></head><body>{nav}<main>{body}</main><footer>AI-Based Examination Assessment System · Academic Prototype</footer></body></html>"""

def is_logged(request): return request.cookies.get("lecturer")=="1"

@app.get("/",response_class=HTMLResponse)
def home():
    c=db(); exams=c.execute("SELECT * FROM exams ORDER BY id DESC").fetchall(); subs=c.execute("SELECT COUNT(*) n FROM submissions").fetchone()["n"]; c.close()
    cards="".join(f"""<div class='card'><h2>{e['title']}</h2><p>{e['course']} · {e['duration']} minutes</p>
    <a class='button' href='/exam/{e['id']}'>Student View</a>
    <a class='button secondary' href='/lecturer/exam/{e['id']}'>Lecturer</a></div>""" for e in exams)
    return page("Dashboard",f"""<section class='hero'><span>AI ASSESSMENT</span><h1>Examination Assessment System</h1><p>Automated marking, semantic answer comparison and AI-writing risk analysis.</p><a class='button' href='/login'>Lecturer Login</a></section>
    <div class='stats'><div><b>{len(exams)}</b><small>Examinations</small></div><div><b>{subs}</b><small>Submissions</small></div><div><b>NLP</b><small>Semantic marking</small></div></div>
    <h2>Available Examinations</h2><div class='grid'>{cards}</div>""")

@app.get("/login",response_class=HTMLResponse)
def login():
    return page("Lecturer Login","""<form class='panel narrow' method='post' action='/login'><h1>Lecturer Login</h1><input name='username' placeholder='Username' required><input name='password' type='password' placeholder='Password' required><button>Login</button><p class='muted'>Demo: admin / admin123</p></form>""")

@app.post("/login")
def do_login(username:str=Form(...),password:str=Form(...)):
    c=db(); u=c.execute("SELECT * FROM users WHERE username=? AND password=?",(username,hashlib.sha256(password.encode()).hexdigest())).fetchone(); c.close()
    if not u:return HTMLResponse(page("Login","<div class='panel'><h2>Invalid login</h2><a href='/login'>Try again</a></div>"),401)
    r=RedirectResponse("/lecturer",303); r.set_cookie("lecturer","1",httponly=True); return r

@app.get("/logout")
def logout():
    r=RedirectResponse("/",303); r.delete_cookie("lecturer"); return r

@app.get("/lecturer",response_class=HTMLResponse)
def lecturer(request:Request):
    if not is_logged(request):return RedirectResponse("/login",303)
    c=db(); exams=c.execute("SELECT * FROM exams").fetchall(); subs=c.execute("""SELECT s.*,e.title FROM submissions s JOIN exams e ON e.id=s.exam_id ORDER BY s.id DESC""").fetchall(); c.close()
    rows="".join(f"<tr><td>{s['student']}</td><td>{s['student_id'] or '-'}</td><td>{s['title']}</td><td>{s['created_at']}</td><td><a href='/lecturer/submission/{s['id']}'>Review</a></td></tr>" for s in subs)
    cards="".join(f"<div class='card'><h3>{e['title']}</h3><p>{e['course']} · {e['duration']} min</p><a class='button' href='/lecturer/exam/{e['id']}'>Manage Exam</a></div>" for e in exams)
    return page("Lecturer Dashboard",f"<div class='topline'><div><span>LECTURER DASHBOARD</span><h1>Assessment Control Centre</h1></div><a href='/logout'>Logout</a></div><div class='grid'>{cards}</div><div class='panel'><h2>Recent Submissions</h2><table><tr><th>Student</th><th>ID</th><th>Exam</th><th>Date</th><th></th></tr>{rows or '<tr><td colspan=5>No submissions yet.</td></tr>'}</table></div>")

@app.get("/lecturer/exam/{eid}",response_class=HTMLResponse)
def manage_exam(request:Request,eid:int):
    if not is_logged(request):return RedirectResponse("/login",303)
    c=db(); e=c.execute("SELECT * FROM exams WHERE id=?",(eid,)).fetchone(); qs=c.execute("SELECT * FROM questions WHERE exam_id=?",(eid,)).fetchall(); c.close()
    qrows="".join(f"<div class='question'><b>Q{i+1}. {q['text']}</b><p>Max marks: {q['max_marks']}</p><details><summary>Model answer & rubric</summary><p>{q['model_answer']}</p><p><b>Rubric:</b> {q['rubric']}</p></details></div>" for i,q in enumerate(qs))
    return page("Manage Exam",f"""<div class='topline'><div><span>EXAM MANAGEMENT</span><h1>{e['title']}</h1><p>{e['course']} · {e['duration']} minutes</p></div><a href='/lecturer'>Dashboard</a></div>
    <div class='panel'><h2>Questions & Marking Scheme</h2>{qrows}</div>
    <div class='panel'><h2>Add Question</h2><form method='post' action='/lecturer/exam/{eid}/question'><input name='text' placeholder='Question' required><input name='max_marks' type='number' step='0.5' placeholder='Maximum marks' required><textarea name='model_answer' placeholder='Expected/model answer' required></textarea><input name='rubric' placeholder='Key marking concepts separated by semicolons'><button>Add Question</button></form></div>""")

@app.post("/lecturer/exam/{eid}/question")
def add_question(request:Request,eid:int,text:str=Form(...),max_marks:float=Form(...),model_answer:str=Form(...),rubric:str=Form("")):
    if not is_logged(request):return RedirectResponse("/login",303)
    c=db();c.execute("INSERT INTO questions(exam_id,text,max_marks,model_answer,rubric) VALUES(?,?,?,?,?)",(eid,text,max_marks,model_answer,rubric));c.commit();c.close()
    return RedirectResponse(f"/lecturer/exam/{eid}",303)

@app.get("/exam/{eid}",response_class=HTMLResponse)
def exam(eid:int):
    c=db();e=c.execute("SELECT * FROM exams WHERE id=?",(eid,)).fetchone();qs=c.execute("SELECT * FROM questions WHERE exam_id=?",(eid,)).fetchall();c.close()
    fields="".join(f"<div class='question'><label>{i+1}. {q['text']} <small>({q['max_marks']} marks)</small></label><textarea name='q_{q['id']}' required></textarea></div>" for i,q in enumerate(qs))
    return page("Student Examination",f"<form class='panel' method='post' action='/submit/{eid}'><span>STUDENT EXAMINATION</span><h1>{e['title']}</h1><p>{e['course']} · {e['duration']} minutes</p><input name='student' placeholder='Student full name' required><input name='student_id' placeholder='Student ID' required>{fields}<button>Submit Examination for Assessment</button></form>")

@app.post("/submit/{eid}",response_class=HTMLResponse)
async def submit(eid:int,request:Request,student:str=Form(...),student_id:str=Form(...)):
    data=await request.form();c=db();qs=c.execute("SELECT * FROM questions WHERE exam_id=?",(eid,)).fetchall()
    sid=c.execute("INSERT INTO submissions(student,student_id,exam_id,created_at) VALUES(?,?,?,?)",(student,student_id,eid,datetime.now().strftime("%Y-%m-%d %H:%M"))).lastrowid
    total=mx=0; cards=""
    for q in qs:
        txt=str(data.get("q_"+str(q["id"]),""));sim,marks,risk=score_answer(txt,q)
        c.execute("INSERT INTO answers(submission_id,question_id,text,similarity,marks,ai_risk) VALUES(?,?,?,?,?,?)",(sid,q["id"],txt,sim,marks,risk))
        total+=marks;mx+=q["max_marks"]
        flag="flag" if risk>=.5 else ""
        cards+=f"<div class='result {flag}'><b>{q['text']}</b><div class='bar'><i style='width:{sim*100:.0f}%'></i></div><p>Semantic similarity: <strong>{sim*100:.1f}%</strong> · Mark: <strong>{marks}/{q['max_marks']}</strong> · AI-risk indicator: <strong>{risk*100:.0f}%</strong></p></div>"
    c.commit();c.close()
    return page("Assessment Result",f"<div class='panel'><span>ASSESSMENT COMPLETE</span><h1>{student}</h1><p>Student ID: {student_id}</p><div class='score'>{total:.1f}<small> / {mx}</small></div>{cards}<div class='warning'>AI-risk is an indicator for lecturer review, not proof that AI was used.</div><a class='button' href='/'>Return Home</a></div>")

@app.get("/lecturer/submission/{sid}",response_class=HTMLResponse)
def review(request:Request,sid:int):
    if not is_logged(request):return RedirectResponse("/login",303)
    c=db();s=c.execute("SELECT s.*,e.title FROM submissions s JOIN exams e ON e.id=s.exam_id WHERE s.id=?",(sid,)).fetchone();ans=c.execute("""SELECT a.*,q.text,q.max_marks,q.model_answer FROM answers a JOIN questions q ON q.id=a.question_id WHERE a.submission_id=?""",(sid,)).fetchall();c.close()
    total=sum(a["marks"] for a in ans);mx=sum(a["max_marks"] for a in ans)
    rows="".join(f"<div class='review'><h3>{a['text']}</h3><blockquote>{a['text']}</blockquote><p><b>Model answer:</b> {a['model_answer']}</p><p>Similarity {a['similarity']*100:.1f}% · AI-risk {a['ai_risk']*100:.0f}% · Mark <b>{a['marks']}/{a['max_marks']}</b></p></div>" for a in ans)
    return page("Review Submission",f"<div class='topline'><div><span>LECTURER REVIEW</span><h1>{s['student']}</h1><p>{s['title']} · {s['student_id']}</p></div><a href='/lecturer'>Dashboard</a></div><div class='panel'><div class='score'>{total:.1f}<small> / {mx}</small></div>{rows}<a class='button' href='/lecturer/report/{sid}'>Download CSV Report</a></div>")

@app.get("/lecturer/report/{sid}")
def report(request:Request,sid:int):
    if not is_logged(request):return RedirectResponse("/login",303)
    c=db();s=c.execute("SELECT * FROM submissions WHERE id=?",(sid,)).fetchone();ans=c.execute("""SELECT a.*,q.text,q.max_marks FROM answers a JOIN questions q ON q.id=a.question_id WHERE a.submission_id=?""",(sid,)).fetchall();c.close()
    out=io.StringIO();w=csv.writer(out);w.writerow(["Student","Student ID","Question","Similarity","Mark","Maximum","AI Risk"])
    for a in ans:w.writerow([s["student"],s["student_id"],a["text"],f"{a['similarity']:.3f}",a["marks"],a["max_marks"],f"{a['ai_risk']:.2f}"])
    return StreamingResponse(iter([out.getvalue()]),media_type="text/csv",headers={"Content-Disposition":f"attachment; filename=assessment_{sid}.csv"})
