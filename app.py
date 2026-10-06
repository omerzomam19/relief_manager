"""تطبيق إدارة المساعدات الإغاثية - Flask + JSON"""
import csv, io, os, re, secrets
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, Response, g
from werkzeug.security import generate_password_hash, check_password_hash
import storage
from storage import load_data, save_data, next_id, now
from i18n import TR

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
LOW_STOCK = 10
PHONE_RE = re.compile(r"^\+?[0-9\s\-]{7,15}$")
storage.init_storage()


# ---------- أدوات مساعدة ----------
def lang():
    return session.get("lang", "ar")


def t(key):
    return TR.get(key, (key, key))[0 if lang() == "ar" else 1]


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


def F(k):
    return request.form.get(k, "").strip()


def posint(v, minimum=1):
    try:
        n = int(str(v).strip())
        return n if n >= minimum else None
    except ValueError:
        return None


def upsert(name, iid, rec):
    with storage.lock:
        items = load_data(name)
        row = next((x for x in items if str(x["id"]) == str(iid)), None) if iid else None
        if row:
            row.update(rec)
        else:
            items.append({"id": next_id(items), **rec, "created_at": now()})
        save_data(name, items)


def remove(name, iid, ref_field):
    with storage.lock:  # منع حذف عنصر مرتبط بتوزيعات
        if any(d[ref_field] == iid for d in load_data("distributions")):
            flash("m_in_use", "warning")
        else:
            save_data(name, [x for x in load_data(name) if x["id"] != iid])
            flash("m_deleted", "success")


def enrich(rows):
    b = {x["id"]: x for x in load_data("beneficiaries")}
    i = {x["id"]: x for x in load_data("inventory")}
    return [{**r, "ben": b.get(r["beneficiary_id"], {}).get("name", "—"),
             "item": i.get(r["inventory_id"], {}).get("name", "—"),
             "unit": i.get(r["inventory_id"], {}).get("unit", "")} for r in rows]


def admin_required(f):
    @wraps(f)
    def w(*a, **k):
        if g.user["role"] != "admin":
            flash("m_forbidden", "error")
            return redirect(url_for("dashboard"))
        return f(*a, **k)
    return w


@app.context_processor
def inject():
    return dict(t=t, lang=lang(), direction="rtl" if lang() == "ar" else "ltr",
                user=g.get("user"), csrf_token=csrf_token, low_stock=LOW_STOCK)


@app.before_request
def guard():
    g.user = next((u for u in load_data("users") if u["id"] == session.get("uid")), None)
    if request.method == "POST":  # حماية CSRF
        sent, real = request.form.get("csrf_token", ""), session.get("csrf", "")
        if not real or not secrets.compare_digest(sent.encode(), real.encode()):
            flash("m_csrf", "error")
            return redirect(request.referrer or url_for("login"))
    if request.endpoint and request.endpoint not in ("login", "static", "set_lang") and not g.user:
        return redirect(url_for("login"))


# ---------- الدخول واللغة ----------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = next((u for u in load_data("users") if u["username"] == F("username")), None)
        if u and check_password_hash(u["password_hash"], request.form.get("password", "")):
            lg = lang(); session.clear(); session["lang"] = lg; session["uid"] = u["id"]
            return redirect(url_for("dashboard"))
        flash("m_login_fail", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    lg = lang(); session.clear(); session["lang"] = lg
    return redirect(url_for("login"))


@app.route("/lang/<code>")
def set_lang(code):
    if code in ("ar", "en"):
        session["lang"] = code
    return redirect(request.referrer or url_for("dashboard"))


# ---------- لوحة التحكم ----------
@app.route("/")
def dashboard():
    inv, dist = load_data("inventory"), load_data("distributions")
    days = [(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)]
    chart = dict(labels=days, values=[sum(d["quantity"] for d in dist if d["date"][:10] == x) for x in days])
    stats = dict(inv=len(inv), ben=len(load_data("beneficiaries")), dist=len(dist), qty=sum(i["quantity"] for i in inv))
    recent = enrich(sorted(dist, key=lambda d: d["id"], reverse=True)[:5])
    return render_template("dashboard.html", stats=stats, chart=chart, recent=recent,
                           low=[i for i in inv if i["quantity"] <= LOW_STOCK])


# ---------- المخزون ----------
@app.route("/inventory", methods=["GET", "POST"])
def inventory():
    if request.method == "POST":  # إضافة (id فارغ) أو تعديل
        rec = dict(name=F("name"), category=F("category"), unit=F("unit"), quantity=posint(F("quantity"), 0))
        if not (rec["name"] and rec["category"] and rec["unit"]):
            flash("m_required", "error")
        elif rec["quantity"] is None:
            flash("m_qty_invalid", "error")
        else:
            upsert("inventory", F("id"), rec); flash("m_saved", "success")
        return redirect(url_for("inventory"))
    q, cat = request.args.get("q", "").strip().lower(), request.args.get("cat", "")
    all_items = load_data("inventory")
    items = [i for i in all_items if q in i["name"].lower() and (not cat or i["category"] == cat)]
    return render_template("inventory.html", items=items, cats=sorted({i["category"] for i in all_items}), q=q, cat=cat)


@app.post("/inventory/<int:iid>/delete")
@admin_required
def inventory_delete(iid):
    remove("inventory", iid, "inventory_id")
    return redirect(url_for("inventory"))


# ---------- المستفيدون ----------
@app.route("/beneficiaries", methods=["GET", "POST"])
def beneficiaries():
    if request.method == "POST":
        rec = dict(name=F("name"), address=F("address"), phone=F("phone"), family_size=posint(F("family_size")), notes=F("notes"))
        if not (rec["name"] and rec["address"]):
            flash("m_required", "error")
        elif rec["family_size"] is None:
            flash("m_family_invalid", "error")
        elif rec["phone"] and not PHONE_RE.match(rec["phone"]):
            flash("m_phone_invalid", "error")
        else:
            upsert("beneficiaries", F("id"), rec); flash("m_saved", "success")
        return redirect(url_for("beneficiaries"))
    q = request.args.get("q", "").strip().lower()
    rows = [b for b in load_data("beneficiaries") if q in (b["name"] + b["phone"]).lower()]
    return render_template("beneficiaries.html", rows=rows, q=q)


@app.route("/beneficiaries/<int:bid>")
def beneficiary_detail(bid):
    b = next((x for x in load_data("beneficiaries") if x["id"] == bid), None)
    if not b:
        return render_template("404.html"), 404
    got = enrich([d for d in load_data("distributions") if d["beneficiary_id"] == bid][::-1])
    return render_template("beneficiary_detail.html", b=b, got=got)


@app.post("/beneficiaries/<int:bid>/delete")
@admin_required
def beneficiary_delete(bid):
    remove("beneficiaries", bid, "beneficiary_id")
    return redirect(url_for("beneficiaries"))


# ---------- التوزيع ----------
@app.route("/distribute", methods=["GET", "POST"])
def distribute():
    if request.method == "POST":
        bid, iid, qty = posint(F("beneficiary_id")), posint(F("inventory_id")), posint(F("quantity"))
        with storage.lock:
            inv = load_data("inventory")
            item = next((i for i in inv if i["id"] == iid), None)
            if not (item and qty and any(b["id"] == bid for b in load_data("beneficiaries"))):
                flash("m_qty_invalid", "error")
            elif qty > item["quantity"]:
                flash("m_stock", "error")
            else:
                item["quantity"] -= qty; save_data("inventory", inv)
                d = load_data("distributions")
                d.append(dict(id=next_id(d), beneficiary_id=bid, inventory_id=iid, quantity=qty, date=now(), created_by=g.user["username"]))
                save_data("distributions", d); flash("m_dist_done", "success")
        return redirect(url_for("distribute"))
    return render_template("distribute.html", ben=load_data("beneficiaries"), inv=load_data("inventory"),
                           rows=enrich(sorted(load_data("distributions"), key=lambda d: d["id"], reverse=True)))


@app.post("/distribute/<int:did>/delete")
@admin_required
def distribute_delete(did):
    with storage.lock:  # إرجاع الكمية للمخزون
        dist = load_data("distributions")
        d = next((x for x in dist if x["id"] == did), None)
        if d:
            inv = load_data("inventory")
            for i in inv:
                if i["id"] == d["inventory_id"]:
                    i["quantity"] += d["quantity"]
            save_data("inventory", inv)
            save_data("distributions", [x for x in dist if x["id"] != did])
            flash("m_dist_del", "success")
    return redirect(url_for("distribute"))


# ---------- التقارير ----------
COLS = {"inventory": ["name", "category", "quantity", "unit", "created_at"],
        "beneficiaries": ["name", "address", "phone", "family_size", "created_at"],
        "distributions": ["date", "ben", "item", "quantity", "created_by"]}


@app.route("/reports")
def reports():
    kind = request.args.get("type", "distributions")
    kind = kind if kind in COLS else "distributions"
    df, dt = request.args.get("from", ""), request.args.get("to", "")
    key = "date" if kind == "distributions" else "created_at"
    rows = [r for r in load_data(kind) if (not df or r[key][:10] >= df) and (not dt or r[key][:10] <= dt)]
    if kind == "distributions":
        rows = enrich(rows)
    cols = COLS[kind]
    if request.args.get("export"):
        out = io.StringIO(); w = csv.writer(out)
        w.writerow([t(c) for c in cols]); w.writerows([[r.get(c, "") for c in cols] for r in rows])
        return Response("\ufeff" + out.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment; filename={kind}.csv"})
    return render_template("reports.html", rows=rows, cols=cols, kind=kind, df=df, dt=dt,
                           args=dict(type=kind, **{"from": df, "to": dt}))


# ---------- المستخدمون (للمدير فقط) ----------
@app.route("/users", methods=["GET", "POST"])
@admin_required
def users():
    if request.method == "POST":
        name, pwd, role = F("username"), request.form.get("password", ""), F("role")
        with storage.lock:
            us = load_data("users")
            if not name or not pwd or role not in ("admin", "staff"):
                flash("m_required", "error")
            elif len(pwd) < 6:
                flash("m_pwd", "error")
            elif any(u["username"] == name for u in us):
                flash("m_exists", "error")
            else:
                us.append(dict(id=next_id(us), username=name, password_hash=generate_password_hash(pwd), role=role, created_at=now()))
                save_data("users", us); flash("m_saved", "success")
        return redirect(url_for("users"))
    return render_template("users.html", rows=load_data("users"))


@app.post("/users/<int:uid>/delete")
@admin_required
def user_delete(uid):
    if uid == g.user["id"]:
        flash("m_self", "error")
    else:
        save_data("users", [u for u in load_data("users") if u["id"] != uid]); flash("m_deleted", "success")
    return redirect(url_for("users"))


@app.errorhandler(404)
def e404(_):
    return render_template("404.html"), 404


@app.errorhandler(500)
def e500(_):
    return render_template("500.html"), 500


if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 5000)),
            debug=os.environ.get("FLASK_DEBUG") == "1")
