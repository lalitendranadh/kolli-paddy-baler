from flask import Flask, request, redirect, url_for, session, flash, render_template, jsonify
import sqlite3, os, hashlib, hmac, secrets
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key")
DB = os.environ.get("DATABASE_PATH", os.path.join(os.path.dirname(__file__), "business.db"))

def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 180000).hex()
    return salt + "$" + digest

def check_password(stored, password):
    try:
        salt, digest = stored.split("$", 1)
        return hmac.compare_digest(hash_password(password, salt).split("$",1)[1], digest)
    except Exception:
        return False

def init_db():
    con=db()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL,
      password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('owner','driver'))
    );
    CREATE TABLE IF NOT EXISTS farmers (
      id INTEGER PRIMARY KEY, name TEXT NOT NULL, mobile TEXT NOT NULL UNIQUE,
      village TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS jobs (
      id INTEGER PRIMARY KEY, farmer_id INTEGER NOT NULL REFERENCES farmers(id),
      date_time TEXT NOT NULL, rolls INTEGER NOT NULL, rate REAL NOT NULL,
      total REAL NOT NULL, paid REAL NOT NULL DEFAULT 0,
      status TEXT NOT NULL DEFAULT 'Unpaid', payment_method TEXT,
      sms_sent INTEGER NOT NULL DEFAULT 0, created_by INTEGER REFERENCES users(id),
      notes TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS expenses (
      id INTEGER PRIMARY KEY, date TEXT NOT NULL, category TEXT NOT NULL,
      description TEXT, amount REAL NOT NULL, rolls_today INTEGER,
      created_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS audit_log (
      id INTEGER PRIMARY KEY, user_id INTEGER, action TEXT NOT NULL,
      record_type TEXT NOT NULL, record_id INTEGER, details TEXT,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS settings (
      key TEXT PRIMARY KEY, value TEXT NOT NULL
    );
    """)
    # Default demo accounts only on first run
    if not con.execute("SELECT 1 FROM users LIMIT 1").fetchone():
        con.execute("INSERT INTO users(username,password_hash,role) VALUES(?,?,?)",
                    ("owner", hash_password(os.environ.get("OWNER_PASSWORD","owner123")), "owner"))
        con.execute("INSERT INTO users(username,password_hash,role) VALUES(?,?,?)",
                    ("driver", hash_password(os.environ.get("DRIVER_PASSWORD","driver123")), "driver"))
    defaults={"business_name":"Kolli Satyanarayana Earth Work & Paddy Baler Services",
              "owner_contact":"","sms_mode":"disabled"}
    for k,v in defaults.items():
        con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",(k,v))
    con.commit(); con.close()

init_db()

def current_user():
    if "uid" not in session: return None
    con=db(); u=con.execute("SELECT * FROM users WHERE id=?",(session["uid"],)).fetchone(); con.close()
    return u

def login_required(fn):
    from functools import wraps
    @wraps(fn)
    def inner(*a,**kw):
        if not current_user(): return redirect(url_for("login"))
        return fn(*a,**kw)
    return inner

def owner_required(fn):
    from functools import wraps
    @wraps(fn)
    def inner(*a,**kw):
        u=current_user()
        if not u: return redirect(url_for("login"))
        if u["role"]!="owner":
            flash("Owner-only section.")
            return redirect(url_for("dashboard"))
        return fn(*a,**kw)
    return inner

def audit(user_id, action, typ, rid, details=""):
    con=db(); con.execute("INSERT INTO audit_log(user_id,action,record_type,record_id,details) VALUES(?,?,?,?,?)",
                          (user_id,action,typ,rid,details)); con.commit(); con.close()

def settings():
    con=db(); rows=con.execute("SELECT key,value FROM settings").fetchall(); con.close()
    return {r["key"]:r["value"] for r in rows}

def send_sms(number, text):
    # SMS provider integration is intentionally off until credentials are configured.
    # Configure Twilio credentials in environment variables to enable sending.
    sid=os.environ.get("TWILIO_ACCOUNT_SID")
    token=os.environ.get("TWILIO_AUTH_TOKEN")
    from_number=os.environ.get("TWILIO_PHONE_NUMBER")
    if not (sid and token and from_number):
        return False, "SMS provider not configured"
    try:
        from twilio.rest import Client
        Client(sid, token).messages.create(body=text, from_=from_number, to=number)
        return True, "sent"
    except Exception as e:
        return False, str(e)

@app.route("/")
def index():
    return redirect(url_for("dashboard") if current_user() else url_for("login"))

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method=="POST":
        con=db(); u=con.execute("SELECT * FROM users WHERE username=?",(request.form.get("username","").strip(),)).fetchone(); con.close()
        if u and check_password(u["password_hash"],request.form.get("password","")):
            session["uid"]=u["id"]; flash("Welcome.")
            return redirect(url_for("dashboard"))
        flash("Incorrect username or password.")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear(); return redirect(url_for("login"))

@app.route("/dashboard")
@login_required
def dashboard():
    u=current_user(); con=db()
    today=datetime.now().strftime("%Y-%m-%d")
    summary=con.execute("""SELECT COALESCE(SUM(rolls),0) rolls,COALESCE(SUM(total),0) income,
       COALESCE(SUM(paid),0) paid,COALESCE(SUM(total-paid),0) pending FROM jobs WHERE date(date_time)=?""",(today,)).fetchone()
    exp=con.execute("SELECT COALESCE(SUM(amount),0) total FROM expenses WHERE date=?",(today,)).fetchone()["total"]
    recent=con.execute("""SELECT j.*,f.name,f.mobile,f.village FROM jobs j JOIN farmers f ON f.id=j.farmer_id ORDER BY j.id DESC LIMIT 8""").fetchall()
    con.close()
    return render_template("dashboard.html", user=u, summary=summary, expenses=exp, recent=recent, today=today, cfg=settings())

@app.route("/farmers", methods=["GET","POST"])
@login_required
def farmers():
    if request.method=="POST":
        name=request.form.get("name","").strip(); mobile=request.form.get("mobile","").strip(); village=request.form.get("village","").strip()
        if not name or not mobile or not village:
            flash("Enter name, mobile and village."); return redirect(url_for("farmers"))
        con=db()
        existing=con.execute("SELECT id FROM farmers WHERE mobile=?",(mobile,)).fetchone()
        if existing:
            con.execute("UPDATE farmers SET name=?,village=? WHERE mobile=?",(name,village,mobile))
            fid=existing["id"]; flash("Existing farmer updated — history retained.")
        else:
            cur=con.execute("INSERT INTO farmers(name,mobile,village) VALUES(?,?,?)",(name,mobile,village)); fid=cur.lastrowid
            flash("Farmer saved.")
        con.commit(); con.close()
        return redirect(url_for("farmer_detail",fid=fid))
    q=request.args.get("q","").strip()
    con=db()
    if q:
        rows=con.execute("SELECT * FROM farmers WHERE name LIKE ? OR mobile LIKE ? OR village LIKE ? ORDER BY name",
                         (f"%{q}%",f"%{q}%",f"%{q}%")).fetchall()
    else: rows=con.execute("SELECT * FROM farmers ORDER BY id DESC LIMIT 150").fetchall()
    con.close()
    return render_template("farmers.html", user=current_user(), farmers=rows, q=q)

@app.route("/farmer/<int:fid>", methods=["GET"])
@login_required
def farmer_detail(fid):
    con=db(); f=con.execute("SELECT * FROM farmers WHERE id=?",(fid,)).fetchone()
    jobs=con.execute("SELECT * FROM jobs WHERE farmer_id=? ORDER BY id DESC",(fid,)).fetchall()
    totals=con.execute("SELECT COALESCE(SUM(total),0) total,COALESCE(SUM(paid),0) paid,COALESCE(SUM(rolls),0) rolls FROM jobs WHERE farmer_id=?",(fid,)).fetchone()
    con.close()
    if not f: return "Farmer not found",404
    return render_template("farmer_detail.html", user=current_user(), farmer=f, jobs=jobs, totals=totals)

@app.route("/job/new", methods=["GET","POST"])
@login_required
def new_job():
    if request.method=="POST":
        mobile=request.form.get("mobile","").strip()
        name=request.form.get("name","").strip()
        village=request.form.get("village","").strip()
        rolls=int(request.form.get("rolls",0))
        rate=float(request.form.get("rate",35))
        dt=request.form.get("date_time") or datetime.now().strftime("%Y-%m-%dT%H:%M")
        if rolls<=0 or not mobile or not name or not village or rate<30 or rate>40:
            flash("Check required fields. Rate must be between ₹30 and ₹40.")
            return redirect(url_for("new_job"))
        con=db()
        f=con.execute("SELECT * FROM farmers WHERE mobile=?",(mobile,)).fetchone()
        if f:
            con.execute("UPDATE farmers SET name=?,village=? WHERE mobile=?",(name,village,mobile))
            fid=f["id"]
        else:
            fid=con.execute("INSERT INTO farmers(name,mobile,village) VALUES(?,?,?)",(name,mobile,village)).lastrowid
        total=rolls*rate
        cur=con.execute("INSERT INTO jobs(farmer_id,date_time,rolls,rate,total,created_by) VALUES(?,?,?,?,?,?)",
                        (fid,dt,rolls,rate,total,current_user()["id"]))
        jid=cur.lastrowid
        con.commit(); con.close()
        cfg=settings()
        msg=f'{cfg["business_name"]}: Baling completed. Date: {dt.replace("T"," ")}. Rolls: {rolls}. Rate: Rs {rate:g}/roll. Total: Rs {total:g}. Contact: {cfg.get("owner_contact") or "Contact your driver"}. Thank you.'
        sent, status=send_sms(mobile,msg)
        con=db(); con.execute("UPDATE jobs SET sms_sent=? WHERE id=?",(1 if sent else 0,jid)); con.commit(); con.close()
        audit(current_user()["id"],"CREATE","job",jid,f"rolls={rolls}, total={total}, SMS={status}")
        flash(f"Entry saved. SMS {'sent' if sent else 'not sent (provider not configured)'}; receipt record #{jid}.")
        return redirect(url_for("farmer_detail",fid=fid))
    now=datetime.now().strftime("%Y-%m-%dT%H:%M")
    return render_template("new_job.html", user=current_user(), now=now)

@app.route("/api/farmer")
@login_required
def api_farmer():
    mobile=request.args.get("mobile","").strip()
    con=db(); f=con.execute("SELECT name,village,mobile FROM farmers WHERE mobile=?",(mobile,)).fetchone(); con.close()
    if f: return jsonify({"found":True,"name":f["name"],"village":f["village"],"mobile":f["mobile"]})
    return jsonify({"found":False})

@app.route("/billing")
@login_required
def billing():
    q=request.args.get("q","")
    con=db()
    rows=con.execute("""SELECT j.*,f.name,f.mobile,f.village FROM jobs j JOIN farmers f ON f.id=j.farmer_id
      WHERE (?='' OR f.name LIKE ? OR f.mobile LIKE ? OR f.village LIKE ?) ORDER BY j.id DESC LIMIT 300""",
      (q,f"%{q}%",f"%{q}%",f"%{q}%")).fetchall()
    con.close()
    return render_template("billing.html", user=current_user(), jobs=rows, q=q)

@app.route("/payment/<int:jid>", methods=["POST"])
@login_required
def payment(jid):
    amount=float(request.form.get("paid",0))
    method=request.form.get("method","Cash")
    con=db(); j=con.execute("SELECT * FROM jobs WHERE id=?",(jid,)).fetchone()
    if not j: con.close(); return "Not found",404
    new_paid=min(j["total"], max(0,j["paid"]+amount))
    status="Paid" if new_paid>=j["total"] else "Partially Paid" if new_paid>0 else "Unpaid"
    con.execute("UPDATE jobs SET paid=?,status=?,payment_method=? WHERE id=?",(new_paid,status,method,jid))
    con.commit(); con.close()
    audit(current_user()["id"],"PAYMENT","job",jid,f"amount={amount}, status={status}")
    flash("Payment updated.")
    return redirect(url_for("billing"))

@app.route("/expenses", methods=["GET","POST"])
@owner_required
def expenses():
    if request.method=="POST":
        date=request.form.get("date"); cat=request.form.get("category"); desc=request.form.get("description","")
        amount=float(request.form.get("amount",0)); rolls=request.form.get("rolls_today") or None
        if amount<0: flash("Amount must be positive."); return redirect(url_for("expenses"))
        con=db(); con.execute("INSERT INTO expenses(date,category,description,amount,rolls_today,created_by) VALUES(?,?,?,?,?,?)",
                              (date,cat,desc,amount,rolls,current_user()["id"])); con.commit(); con.close()
        flash("Expense saved."); return redirect(url_for("expenses"))
    con=db(); rows=con.execute("SELECT * FROM expenses ORDER BY id DESC LIMIT 250").fetchall(); con.close()
    return render_template("expenses.html", user=current_user(), expenses=rows, today=datetime.now().strftime("%Y-%m-%d"))

@app.route("/reports")
@owner_required
def reports():
    start=request.args.get("start",datetime.now().strftime("%Y-%m-01"))
    end=request.args.get("end",datetime.now().strftime("%Y-%m-%d"))
    con=db()
    income=con.execute("SELECT COALESCE(SUM(total),0) total,COALESCE(SUM(paid),0) paid,COALESCE(SUM(total-paid),0) pending,COALESCE(SUM(rolls),0) rolls FROM jobs WHERE date(date_time) BETWEEN ? AND ?",(start,end)).fetchone()
    expenses=con.execute("SELECT category,COALESCE(SUM(amount),0) amount FROM expenses WHERE date BETWEEN ? AND ? GROUP BY category",(start,end)).fetchall()
    total_exp=sum(x["amount"] for x in expenses)
    con.close()
    return render_template("reports.html", user=current_user(), start=start,end=end,income=income,expenses=expenses,total_exp=total_exp,profit=income["total"]-total_exp)

@app.route("/settings", methods=["GET","POST"])
@owner_required
def settings_page():
    cfg=settings()
    if request.method=="POST":
        con=db()
        for k in ["business_name","owner_contact"]:
            con.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(k,request.form.get(k,"").strip()))
        newpw=request.form.get("owner_password","")
        if newpw:
            con.execute("UPDATE users SET password_hash=? WHERE id=?",(hash_password(newpw),current_user()["id"]))
        driverpw=request.form.get("driver_password","")
        if driverpw:
            con.execute("UPDATE users SET password_hash=? WHERE username='driver'",(hash_password(driverpw),))
        con.commit(); con.close(); flash("Settings saved."); return redirect(url_for("settings_page"))
    return render_template("settings.html",user=current_user(),cfg=cfg)

@app.route("/audit")
@owner_required
def audit_page():
    con=db(); rows=con.execute("SELECT a.*,u.username FROM audit_log a LEFT JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT 300").fetchall(); con.close()
    return render_template("audit.html",user=current_user(),rows=rows)

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",5000)), debug=False)
