from flask import Flask, render_template, request, redirect, url_for, jsonify, flash, Response
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user
)
from werkzeug.security import check_password_hash
from database import get_db, init_db
from datetime import date
import os
import json
import csv
import io

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-secret-key-change-in-production")

# gunicorn 起動時も含め、モジュール読み込み時に DB を初期化する
init_db()

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message = "ログインが必要です。"
login_manager.login_message_category = "info"


class User(UserMixin):
    def __init__(self, row):
        self.id = row["id"]
        self.username = row["username"]


@login_manager.user_loader
def load_user(user_id):
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return None
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    conn.close()
    return User(row) if row else None


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("order_list"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        conn = get_db()
        row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        conn.close()
        if row and check_password_hash(row["password_hash"], password):
            login_user(User(row))
            next_url = request.args.get("next")
            return redirect(next_url or url_for("order_list"))
        flash("ユーザー名またはパスワードが正しくありません。", "danger")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("ログアウトしました。", "info")
    return redirect(url_for("login"))


@app.template_filter("status_class")
def status_class(status):
    return {"進行中": "進行中", "完了": "完了", "キャンセル": "キャンセル"}.get(status, "")


@app.template_filter("commas")
def commas(value):
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return value


@app.context_processor
def inject_today():
    return {"today": date.today().isoformat()}


# ──────────────────────────────────────────────
# 受注一覧
# ──────────────────────────────────────────────
@app.route("/")
@login_required
def order_list():
    status_filter = request.args.get("status", "")
    search = request.args.get("search", "")
    conn = get_db()
    query = """
        SELECT o.*,
               COALESCE(SUM(r.actual_quantity), 0) AS delivered_qty
        FROM orders o
        LEFT JOIN delivery_records r ON r.order_id = o.id
        WHERE 1=1
    """
    params = {}
    if status_filter:
        query += " AND o.status = :status"
        params["status"] = status_filter
    if search:
        query += " AND (o.product_name LIKE :s OR o.order_number LIKE :s OR o.control_no LIKE :s)"
        params["s"] = f"%{search}%"
    query += " GROUP BY o.id ORDER BY o.id DESC"
    orders = conn.execute(query, params).fetchall()

    # 全delivery_plansを取得してorder_idでまとめる
    order_ids = [o["id"] for o in orders]
    plans_map = {}
    if order_ids:
        placeholders = ",".join("?" * len(order_ids))
        plans_rows = conn.execute(
            f"SELECT order_id, reply_date, reply_quantity FROM delivery_plans "
            f"WHERE order_id IN ({placeholders}) ORDER BY order_id, reply_date",
            order_ids
        ).fetchall()
        for row in plans_rows:
            plans_map.setdefault(row["order_id"], []).append(row)

    products = conn.execute("SELECT name FROM products ORDER BY name").fetchall()
    colors   = conn.execute("SELECT color_code FROM colors ORDER BY color_code").fetchall()
    conn.close()
    return render_template("orders.html", orders=orders, plans_map=plans_map,
                           status_filter=status_filter, search=search,
                           products=products, colors=colors)


# ──────────────────────────────────────────────
# 受注登録
# ──────────────────────────────────────────────
@app.route("/orders/new", methods=["GET", "POST"])
@login_required
def order_new():
    conn = get_db()
    if request.method == "POST":
        f = request.form
        conn.execute("""
            INSERT INTO orders (control_no, order_date, order_number, product_name,
                base_material, color_code, material_delivery_memo,
                desired_delivery, order_quantity, status)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (f["control_no"], f["order_date"], f["order_number"], f["product_name"],
              f["base_material"], f["color_code"], f["material_delivery_memo"],
              f["desired_delivery"], int(f["order_quantity"] or 0), "進行中"))
        conn.commit()
        order_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        _log(conn, order_id, "受注登録", f"製品: {f['product_name']}", f.get("operator", ""))
        conn.commit()
        conn.close()
        flash("受注を登録しました。", "success")
        return redirect(url_for("order_list"))
    products = conn.execute("SELECT * FROM products ORDER BY name").fetchall()
    colors = conn.execute("SELECT * FROM colors ORDER BY color_code").fetchall()
    conn.close()
    return render_template("order_form.html", order=None, products=products, colors=colors)


# ──────────────────────────────────────────────
# 受注詳細・編集
# ──────────────────────────────────────────────
@app.route("/orders/<int:order_id>")
@login_required
def order_detail(order_id):
    conn = get_db()
    order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order:
        conn.close()
        flash("受注が見つかりません。", "danger")
        return redirect(url_for("order_list"))
    plans = conn.execute(
        "SELECT * FROM delivery_plans WHERE order_id=? ORDER BY reply_date", (order_id,)).fetchall()
    records = conn.execute(
        "SELECT * FROM delivery_records WHERE order_id=? ORDER BY actual_date", (order_id,)).fetchall()
    logs = conn.execute(
        "SELECT * FROM change_logs WHERE order_id=? ORDER BY changed_at DESC", (order_id,)).fetchall()
    delivered = sum(r["actual_quantity"] for r in records)
    planned = sum(p["reply_quantity"] for p in plans)
    conn.close()
    return render_template("order_detail.html", order=order, plans=plans,
                           records=records, logs=logs,
                           delivered=delivered, planned=planned)


@app.route("/orders/<int:order_id>/edit", methods=["GET", "POST"])
@login_required
def order_edit(order_id):
    conn = get_db()
    order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order:
        conn.close()
        return redirect(url_for("order_list"))
    if request.method == "POST":
        f = request.form
        old = dict(order)
        conn.execute("""
            UPDATE orders SET control_no=?, order_date=?, order_number=?, product_name=?,
                base_material=?, color_code=?, material_delivery_memo=?,
                desired_delivery=?, order_quantity=?
            WHERE id=?
        """, (f["control_no"], f["order_date"], f["order_number"], f["product_name"],
              f["base_material"], f["color_code"], f["material_delivery_memo"],
              f["desired_delivery"], int(f["order_quantity"] or 0), order_id))
        conn.commit()
        changes = []
        for key, label in [("product_name", "製品名"), ("order_quantity", "受注数量"),
                            ("desired_delivery", "希望納期"), ("color_code", "色番"),
                            ("base_material", "ベース材")]:
            new_val = f.get(key, "")
            old_val = str(old.get(key) or "")
            if new_val != old_val:
                changes.append(f"{label}: {old_val}→{new_val}")
        if changes:
            _log(conn, order_id, "受注編集", "、".join(changes), f.get("operator", ""))
            conn.commit()
        conn.close()
        flash("受注情報を更新しました。", "success")
        return redirect(url_for("order_detail", order_id=order_id))
    products = conn.execute("SELECT * FROM products ORDER BY name").fetchall()
    colors = conn.execute("SELECT * FROM colors ORDER BY color_code").fetchall()
    conn.close()
    return render_template("order_form.html", order=order, products=products, colors=colors)


# ──────────────────────────────────────────────
# 納品スケジュール
# ──────────────────────────────────────────────
@app.route("/orders/<int:order_id>/plans/add", methods=["POST"])
@login_required
def plan_add(order_id):
    f = request.form
    conn = get_db()
    conn.execute("INSERT INTO delivery_plans (order_id, reply_date, reply_quantity) VALUES (?,?,?)",
                 (order_id, f["reply_date"], int(f["reply_quantity"] or 0)))
    conn.commit()
    _log(conn, order_id, "納品計画追加",
         f"回答納期: {f['reply_date']} 数量: {f['reply_quantity']}", f.get("operator", ""))
    conn.commit()
    conn.close()
    return redirect(url_for("order_detail", order_id=order_id))


@app.route("/orders/<int:order_id>/plans/<int:plan_id>/edit", methods=["POST"])
@login_required
def plan_edit(order_id, plan_id):
    f = request.form
    conn = get_db()
    conn.execute("UPDATE delivery_plans SET reply_date=?, reply_quantity=? WHERE id=? AND order_id=?",
                 (f["reply_date"], int(f["reply_quantity"] or 0), plan_id, order_id))
    conn.commit()
    _log(conn, order_id, "納品計画編集",
         f"計画ID:{plan_id} 回答納期:{f['reply_date']} 数量:{f['reply_quantity']}",
         f.get("operator", ""))
    conn.commit()
    conn.close()
    return redirect(url_for("order_detail", order_id=order_id))


@app.route("/orders/<int:order_id>/plans/<int:plan_id>/delete", methods=["POST"])
@login_required
def plan_delete(order_id, plan_id):
    conn = get_db()
    conn.execute("DELETE FROM delivery_plans WHERE id=? AND order_id=?", (plan_id, order_id))
    conn.commit()
    _log(conn, order_id, "納品計画削除", f"計画ID: {plan_id}", "")
    conn.commit()
    conn.close()
    return redirect(url_for("order_detail", order_id=order_id))


# ──────────────────────────────────────────────
# 納品実績
# ──────────────────────────────────────────────
@app.route("/orders/<int:order_id>/records/add", methods=["POST"])
@login_required
def record_add(order_id):
    f = request.form
    conn = get_db()
    qty = int(f["actual_quantity"] or 0)
    mold = f.get("mold_number", "").strip()
    conn.execute(
        "INSERT INTO delivery_records (order_id, mold_number, actual_date, actual_quantity) VALUES (?,?,?,?)",
        (order_id, mold or None, f["actual_date"], qty))
    conn.commit()
    _log(conn, order_id, "納品実績入力",
         f"金型:{mold or '—'} 実績納期:{f['actual_date']} 数量:{qty}", f.get("operator", ""))
    conn.commit()

    # 合計が受注数量と一致したら自動完了
    order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    delivered = conn.execute(
        "SELECT COALESCE(SUM(actual_quantity),0) FROM delivery_records WHERE order_id=?",
        (order_id,)).fetchone()[0]
    if order["status"] == "進行中" and delivered >= order["order_quantity"]:
        conn.execute("UPDATE orders SET status='完了' WHERE id=?", (order_id,))
        conn.commit()
        _log(conn, order_id, "ステータス変更", "進行中→完了（自動）", "system")
        conn.commit()
        flash("納品数量が受注数量に達したため、自動完了しました。", "info")
    conn.close()
    return redirect(url_for("order_detail", order_id=order_id))


@app.route("/orders/<int:order_id>/records/<int:rec_id>/edit", methods=["POST"])
@login_required
def record_edit(order_id, rec_id):
    f = request.form
    conn = get_db()
    mold = f.get("mold_number", "").strip()
    conn.execute(
        "UPDATE delivery_records SET mold_number=?, actual_date=?, actual_quantity=? WHERE id=? AND order_id=?",
        (mold or None, f["actual_date"], int(f["actual_quantity"] or 0), rec_id, order_id))
    conn.commit()
    _log(conn, order_id, "納品実績編集",
         f"実績ID:{rec_id} 金型:{mold or '—'} 実績納期:{f['actual_date']} 数量:{f['actual_quantity']}",
         f.get("operator", ""))
    conn.commit()

    # 再集計して自動完了チェック
    order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    delivered = conn.execute(
        "SELECT COALESCE(SUM(actual_quantity),0) FROM delivery_records WHERE order_id=?",
        (order_id,)).fetchone()[0]
    if order["status"] == "進行中" and delivered >= order["order_quantity"]:
        conn.execute("UPDATE orders SET status='完了' WHERE id=?", (order_id,))
        conn.commit()
        _log(conn, order_id, "ステータス変更", "進行中→完了（自動）", "system")
        conn.commit()
        flash("納品数量が受注数量に達したため、自動完了しました。", "info")
    conn.close()
    return redirect(url_for("order_detail", order_id=order_id))


@app.route("/orders/<int:order_id>/records/<int:rec_id>/delete", methods=["POST"])
@login_required
def record_delete(order_id, rec_id):
    conn = get_db()
    conn.execute("DELETE FROM delivery_records WHERE id=? AND order_id=?", (rec_id, order_id))
    conn.commit()
    _log(conn, order_id, "納品実績削除", f"実績ID: {rec_id}", "")
    conn.commit()
    conn.close()
    return redirect(url_for("order_detail", order_id=order_id))


# ──────────────────────────────────────────────
# ステータス変更
# ──────────────────────────────────────────────
@app.route("/orders/<int:order_id>/complete", methods=["POST"])
@login_required
def order_complete(order_id):
    conn = get_db()
    order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    old_status = order["status"]
    conn.execute("UPDATE orders SET status='完了' WHERE id=?", (order_id,))
    conn.commit()
    _log(conn, order_id, "ステータス変更", f"{old_status}→完了（手動）",
         request.form.get("operator", ""))
    conn.commit()
    conn.close()
    flash("受注を完了しました。", "success")
    return redirect(url_for("order_detail", order_id=order_id))


@app.route("/orders/<int:order_id>/cancel", methods=["POST"])
@login_required
def order_cancel(order_id):
    conn = get_db()
    order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    old_status = order["status"]
    conn.execute("UPDATE orders SET status='キャンセル' WHERE id=?", (order_id,))
    conn.commit()
    _log(conn, order_id, "ステータス変更", f"{old_status}→キャンセル",
         request.form.get("operator", ""))
    conn.commit()
    conn.close()
    flash("受注をキャンセルしました。", "warning")
    return redirect(url_for("order_detail", order_id=order_id))


@app.route("/orders/<int:order_id>/reopen", methods=["POST"])
@login_required
def order_reopen(order_id):
    conn = get_db()
    conn.execute("UPDATE orders SET status='進行中' WHERE id=?", (order_id,))
    conn.commit()
    _log(conn, order_id, "ステータス変更", "→進行中（再開）",
         request.form.get("operator", ""))
    conn.commit()
    conn.close()
    flash("受注を進行中に戻しました。", "info")
    return redirect(url_for("order_detail", order_id=order_id))


@app.route("/orders/<int:order_id>/delete", methods=["POST"])
@login_required
def order_delete(order_id):
    conn = get_db()
    order = conn.execute("SELECT control_no FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order:
        conn.close()
        flash("受注が見つかりません。", "danger")
        return redirect(url_for("order_list"))
    control_no = order["control_no"] or str(order_id)
    conn.execute("DELETE FROM change_logs WHERE order_id=?", (order_id,))
    conn.execute("DELETE FROM delivery_records WHERE order_id=?", (order_id,))
    conn.execute("DELETE FROM delivery_plans WHERE order_id=?", (order_id,))
    conn.execute("DELETE FROM orders WHERE id=?", (order_id,))
    conn.commit()
    conn.close()
    flash(f"管理No.{control_no} を削除しました。", "success")
    return redirect(url_for("order_list"))


# ──────────────────────────────────────────────
# マスタ管理
# ──────────────────────────────────────────────
@app.route("/masters")
@login_required
def masters():
    conn = get_db()
    products = conn.execute("SELECT * FROM products ORDER BY name").fetchall()
    colors = conn.execute("SELECT * FROM colors ORDER BY color_code").fetchall()
    users = conn.execute("SELECT id, username, created_at FROM users ORDER BY id").fetchall()
    conn.close()
    return render_template("masters.html", products=products, colors=colors, users=users)


@app.route("/masters/products/add", methods=["POST"])
@login_required
def product_add():
    f = request.form
    conn = get_db()
    conn.execute("INSERT INTO products (name, base_material) VALUES (?,?)",
                 (f["name"], f.get("base_material") or None))
    conn.commit()
    conn.close()
    flash("製品を追加しました。", "success")
    return redirect(url_for("masters"))


@app.route("/masters/products/<int:pid>/edit", methods=["POST"])
@login_required
def product_edit(pid):
    f = request.form
    conn = get_db()
    conn.execute("UPDATE products SET name=?, base_material=? WHERE id=?",
                 (f["name"], f.get("base_material") or None, pid))
    conn.commit()
    conn.close()
    flash("製品を更新しました。", "success")
    return redirect(url_for("masters"))


@app.route("/masters/products/<int:pid>/delete", methods=["POST"])
@login_required
def product_delete(pid):
    conn = get_db()
    conn.execute("DELETE FROM products WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    flash("製品を削除しました。", "warning")
    return redirect(url_for("masters"))


@app.route("/masters/colors/add", methods=["POST"])
@login_required
def color_add():
    f = request.form
    conn = get_db()
    try:
        conn.execute("INSERT INTO colors (color_code) VALUES (?)", (f["color_code"],))
        conn.commit()
        flash("色材を追加しました。", "success")
    except Exception:
        flash("色番コードが重複しています。", "danger")
    conn.close()
    return redirect(url_for("masters"))


@app.route("/masters/colors/<int:cid>/delete", methods=["POST"])
@login_required
def color_delete(cid):
    conn = get_db()
    conn.execute("DELETE FROM colors WHERE id=?", (cid,))
    conn.commit()
    conn.close()
    flash("色材を削除しました。", "warning")
    return redirect(url_for("masters"))


@app.route("/masters/users/add", methods=["POST"])
@login_required
def user_add():
    from werkzeug.security import generate_password_hash
    f = request.form
    username = f.get("username", "").strip()
    password = f.get("password", "")
    if not username or not password:
        flash("ユーザー名とパスワードを入力してください。", "danger")
        return redirect(url_for("masters"))
    if len(password) < 8:
        flash("パスワードは8文字以上にしてください。", "danger")
        return redirect(url_for("masters"))
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, generate_password_hash(password))
        )
        conn.commit()
        flash(f"ユーザー「{username}」を追加しました。", "success")
    except Exception:
        flash("そのユーザー名は既に使用されています。", "danger")
    conn.close()
    return redirect(url_for("masters"))


@app.route("/masters/users/<int:uid>/password", methods=["POST"])
@login_required
def user_change_password(uid):
    from werkzeug.security import generate_password_hash
    password = request.form.get("password", "")
    if len(password) < 8:
        flash("パスワードは8文字以上にしてください。", "danger")
        return redirect(url_for("masters"))
    conn = get_db()
    conn.execute("UPDATE users SET password_hash=? WHERE id=?",
                 (generate_password_hash(password), uid))
    conn.commit()
    conn.close()
    flash("パスワードを変更しました。", "success")
    return redirect(url_for("masters"))


@app.route("/masters/users/<int:uid>/delete", methods=["POST"])
@login_required
def user_delete(uid):
    conn = get_db()
    user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if user_count <= 1:
        flash("最後の1人のユーザーは削除できません。", "danger")
        conn.close()
        return redirect(url_for("masters"))
    if uid == current_user.id:
        flash("自分自身は削除できません。", "danger")
        conn.close()
        return redirect(url_for("masters"))
    conn.execute("DELETE FROM users WHERE id=?", (uid,))
    conn.commit()
    conn.close()
    flash("ユーザーを削除しました。", "warning")
    return redirect(url_for("masters"))


# ──────────────────────────────────────────────
# CSVインポート
# ──────────────────────────────────────────────
PRODUCT_HEADERS = ["品名", "ベース材"]
COLOR_HEADERS   = ["色番コード"]


def _decode_csv(file_storage):
    """バイト列をUTF-8 → Shift-JIS の順で試してテキストに変換する。"""
    raw = file_storage.read()
    for enc in ("utf-8-sig", "utf-8", "shift_jis", "cp932"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    raise ValueError("文字コードを判別できませんでした（UTF-8 / Shift-JIS に対応しています）。")


def _parse_csv(text, expected_headers):
    """CSVテキストをパースし (rows, error) を返す。"""
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return None, "CSVが空です。"
    actual = [h.strip() for h in reader.fieldnames]
    missing = [h for h in expected_headers if h not in actual]
    if missing:
        return None, f"ヘッダーが正しくありません。必要な列: {', '.join(expected_headers)}"
    rows = [{k.strip(): v.strip() if v else "" for k, v in row.items()} for row in reader]
    return rows, None


@app.route("/masters/products/import", methods=["POST"])
@login_required
def product_import():
    f = request.files.get("csv_file")
    if not f or not f.filename:
        flash("ファイルを選択してください。", "danger")
        return redirect(url_for("masters"))
    if not f.filename.lower().endswith(".csv"):
        flash("CSVファイル（.csv）を選択してください。", "danger")
        return redirect(url_for("masters"))

    try:
        text = _decode_csv(f)
    except ValueError as e:
        flash(str(e), "danger")
        return redirect(url_for("masters"))

    rows, err = _parse_csv(text, PRODUCT_HEADERS)
    if err:
        flash(err, "danger")
        return redirect(url_for("masters"))

    conn = get_db()
    existing = {(r["name"], r["base_material"] or "")
                for r in conn.execute("SELECT name, base_material FROM products").fetchall()}
    added = skipped = 0
    for row in rows:
        name = row.get("品名", "").strip()
        base = row.get("ベース材", "").strip()
        if not name:
            skipped += 1
            continue
        if (name, base) in existing:
            skipped += 1
            continue
        conn.execute(
            "INSERT INTO products (name, base_material) VALUES (?,?)",
            (name, base or None))
        existing.add((name, base))
        added += 1
    conn.commit()
    conn.close()
    flash(f"{added + skipped}件中 {added}件を追加しました。{skipped}件は重複のためスキップしました。", "success")
    return redirect(url_for("masters"))


@app.route("/masters/colors/import", methods=["POST"])
@login_required
def color_import():
    f = request.files.get("csv_file")
    if not f or not f.filename:
        flash("ファイルを選択してください。", "danger")
        return redirect(url_for("masters"))
    if not f.filename.lower().endswith(".csv"):
        flash("CSVファイル（.csv）を選択してください。", "danger")
        return redirect(url_for("masters"))

    try:
        text = _decode_csv(f)
    except ValueError as e:
        flash(str(e), "danger")
        return redirect(url_for("masters"))

    rows, err = _parse_csv(text, COLOR_HEADERS)
    if err:
        flash(err, "danger")
        return redirect(url_for("masters"))

    conn = get_db()
    existing = {r["color_code"]
                for r in conn.execute("SELECT color_code FROM colors").fetchall()}
    added = skipped = 0
    for row in rows:
        code = row.get("色番コード", "").strip()
        if not code:
            skipped += 1
            continue
        if code in existing:
            skipped += 1
            continue
        conn.execute("INSERT INTO colors (color_code) VALUES (?)", (code,))
        existing.add(code)
        added += 1
    conn.commit()
    conn.close()
    flash(f"{added + skipped}件中 {added}件を追加しました。{skipped}件は重複のためスキップしました。", "success")
    return redirect(url_for("masters"))


# ──────────────────────────────────────────────
# CSVエクスポート
# ──────────────────────────────────────────────
@app.route("/orders/export")
@login_required
def order_export():
    conn = get_db()

    # フィルター条件をクエリパラメータから取得
    f_control_no  = request.args.get("f_control_no",  "").strip()
    f_date_from   = request.args.get("f_date_from",   "").strip()
    f_date_to     = request.args.get("f_date_to",     "").strip()
    f_product     = request.args.get("f_product",     "").strip()
    f_color       = request.args.get("f_color",       "").strip()

    query  = "SELECT * FROM orders WHERE 1=1"
    params = {}
    if f_control_no:
        query += " AND control_no LIKE :control_no"
        params["control_no"] = f"%{f_control_no}%"
    if f_date_from:
        query += " AND order_date >= :date_from"
        params["date_from"] = f_date_from
    if f_date_to:
        query += " AND order_date <= :date_to"
        params["date_to"] = f_date_to
    if f_product:
        query += " AND product_name LIKE :product"
        params["product"] = f"%{f_product}%"
    if f_color:
        query += " AND color_code LIKE :color"
        params["color"] = f"%{f_color}%"
    query += " ORDER BY id"

    orders = conn.execute(query, params).fetchall()

    plans_map = {}
    for row in conn.execute(
        "SELECT order_id, reply_date, reply_quantity FROM delivery_plans ORDER BY order_id, reply_date"
    ).fetchall():
        plans_map.setdefault(row["order_id"], []).append(row)

    records_map = {}
    for row in conn.execute(
        "SELECT order_id, mold_number, actual_date, actual_quantity "
        "FROM delivery_records ORDER BY order_id, actual_date"
    ).fetchall():
        records_map.setdefault(row["order_id"], []).append(row)

    conn.close()

    def _fmt_date(d):
        if d and len(d) == 10 and "-" in d:
            return d.replace("-", "/")
        return d or ""

    header = [
        "管理No.", "受注日", "注文番号", "製品名", "ベース材", "色番",
        "材料納期メモ", "希望納期", "受注数量", "ステータス",
        "回答納期", "回答数量", "金型番号", "実績納期", "実績数量",
    ]

    rows_out = []
    for o in orders:
        base = [
            o["control_no"]             or "",
            _fmt_date(o["order_date"]),
            o["order_number"]           or "",
            o["product_name"]           or "",
            o["base_material"]          or "",
            o["color_code"]             or "",
            o["material_delivery_memo"] or "",
            _fmt_date(o["desired_delivery"]),
            o["order_quantity"],
            o["status"]                 or "",
        ]
        plans = plans_map.get(o["id"], [])
        recs  = records_map.get(o["id"], [])
        n = max(len(plans), len(recs), 1)

        for i in range(n):
            p = plans[i] if i < len(plans) else None
            r = recs[i]  if i < len(recs)  else None
            plan_cols   = [_fmt_date(p["reply_date"]), p["reply_quantity"]] if p else ["", ""]
            record_cols = [r["mold_number"] or "", _fmt_date(r["actual_date"]), r["actual_quantity"]] if r else ["", "", ""]
            rows_out.append(base + plan_cols + record_cols)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows(rows_out)

    sjis_bytes = buf.getvalue().encode("shift_jis", errors="replace")
    filename = f"受注管理データ_{date.today().strftime('%Y%m%d')}.csv"

    return Response(
        sjis_bytes,
        mimetype="text/csv; charset=shift_jis",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{_url_encode(filename)}"}
    )


def _url_encode(s):
    from urllib.parse import quote
    return quote(s, safe="")


# ──────────────────────────────────────────────
# オートコンプリート API
# ──────────────────────────────────────────────
@app.route("/api/products")
@login_required
def api_products():
    conn = get_db()
    rows = conn.execute("SELECT name, base_material FROM products ORDER BY name").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


# ──────────────────────────────────────────────
# ユーティリティ
# ──────────────────────────────────────────────
def _log(conn, order_id, change_type, detail, operator):
    conn.execute("""
        INSERT INTO change_logs (order_id, change_type, change_detail, operator)
        VALUES (?,?,?,?)
    """, (order_id, change_type, detail, operator))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
