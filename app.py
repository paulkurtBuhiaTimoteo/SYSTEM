import os
import sqlite3
import json
import traceback
from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key")
DB_NAME = "/tmp/database.db"


def get_db():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL DEFAULT 'student',
            fullname TEXT NOT NULL,
            student_id TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS rooms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS issues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            room TEXT NOT NULL,
            computer_no TEXT NOT NULL,
            issue_type TEXT NOT NULL,
            description TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Pending',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS equipment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            total_qty INTEGER NOT NULL DEFAULT 0,
            available_qty INTEGER NOT NULL DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS borrow_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            equipment_id INTEGER NOT NULL,
            borrower_name TEXT NOT NULL,
            borrower_student_id TEXT NOT NULL,
            borrow_date TEXT NOT NULL,
            due_date TEXT NOT NULL,
            return_date TEXT,
            status TEXT NOT NULL DEFAULT 'Borrowed',
            admin_username TEXT DEFAULT '',
            item_category TEXT DEFAULT 'Equipment',
            borrow_limit_days INTEGER DEFAULT 3,
            item_title TEXT DEFAULT '',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (equipment_id) REFERENCES equipment(id)
        )
    """)

    default_rooms = ["ML", "PL", "308"]
    for room_name in default_rooms:
        cur.execute("INSERT OR IGNORE INTO rooms (name) VALUES (?)", (room_name,))

    default_categories = ["Equipment", "Printed Materials"]
    for category_name in default_categories:
        cur.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (category_name,))

    conn.commit()
    conn.close()


def get_all_rooms(conn):
    return conn.execute("SELECT * FROM rooms ORDER BY name").fetchall()


def get_all_categories(conn):
    return conn.execute("SELECT * FROM categories ORDER BY name").fetchall()


def require_student():
    return session.get("role") == "student" and session.get("user_id") is not None


def require_admin():
    return session.get("role") == "admin"


@app.route("/health")
def health():
    return "ok", 200


@app.route("/")
def login_page():
    try:
        conn = get_db()
        reported = conn.execute("""
            SELECT room, computer_no, issue_type, created_at
            FROM issues
            WHERE status = 'Pending'
            ORDER BY id DESC
            LIMIT 20
        """).fetchall()
        conn.close()
        return render_template("login.html", reported=reported)
    except Exception as e:
        print("LOGIN PAGE ERROR:", e)
        traceback.print_exc()
        return f"Server error: {e}", 500


@app.route("/login", methods=["POST"])
def login():
    username = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    if (username == "admin1" and password == "ccitadmin1") or (username == "admin2" and password == "admindept2"):
        session.clear()
        session["role"] = "admin"
        session["admin_username"] = username
        return redirect(url_for("admin_dashboard"))

    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE email = ? AND role = 'student'",
        (username,)
    ).fetchone()
    conn.close()

    if user and check_password_hash(user["password_hash"], password):
        session.clear()
        session["role"] = "student"
        session["user_id"] = user["id"]
        session["fullname"] = user["fullname"]
        session["student_id"] = user["student_id"]
        return redirect(url_for("student_dashboard"))

    flash("Invalid username/email or password.", "error")
    return redirect(url_for("login_page"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login_page"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")

    fullname = request.form.get("fullname", "").strip()
    student_id = request.form.get("student_id", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    confirm = request.form.get("confirm_password", "")

    if not fullname or not student_id or not email or not password or not confirm:
        flash("Please fill in all fields.", "error")
        return redirect(url_for("register"))

    if password != confirm:
        flash("Passwords do not match.", "error")
        return redirect(url_for("register"))

    password_hash = generate_password_hash(password)

    try:
        conn = get_db()
        conn.execute(
            """
            INSERT INTO users (role, fullname, student_id, email, password_hash)
            VALUES ('student', ?, ?, ?, ?)
            """,
            (fullname, student_id, email, password_hash)
        )
        conn.commit()
        conn.close()

        flash("Account created! You can now sign in.", "success")
        return redirect(url_for("login_page"))

    except sqlite3.IntegrityError:
        flash("Student ID or Email already exists.", "error")
        return redirect(url_for("register"))


@app.route("/student")
def student_dashboard():
    if not require_student():
        return redirect(url_for("login_page"))

    user_id = session["user_id"]
    conn = get_db()

    issues = conn.execute(
        """
        SELECT id, room, computer_no, issue_type, description, status, created_at
        FROM issues
        WHERE user_id = ?
        ORDER BY id DESC
        """,
        (user_id,)
    ).fetchall()

    rooms = get_all_rooms(conn)
    conn.close()

    return render_template("student_dashboard.html", issues=issues, rooms=rooms)


@app.route("/student/report", methods=["POST"])
def student_report_issue():
    if not require_student():
        return redirect(url_for("login_page"))

    room = request.form.get("room", "").strip()
    computer_no = request.form.get("computer_no", "").strip()
    issue_type = request.form.get("issue_type", "").strip()
    description = request.form.get("description", "").strip()

    if not room or not computer_no or not issue_type or not description:
        flash("Please complete all fields to submit an issue.", "error")
        return redirect(url_for("student_dashboard"))

    conn = get_db()

    room_exists = conn.execute(
        "SELECT id FROM rooms WHERE name = ?",
        (room,)
    ).fetchone()

    if not room_exists:
        conn.close()
        flash("Selected room does not exist.", "error")
        return redirect(url_for("student_dashboard"))

    conn.execute(
        """
        INSERT INTO issues (user_id, room, computer_no, issue_type, description, status)
        VALUES (?, ?, ?, ?, ?, 'Pending')
        """,
        (session["user_id"], room, computer_no, issue_type, description)
    )
    conn.commit()
    conn.close()

    flash("Issue submitted successfully!", "success")
    return redirect(url_for("student_dashboard"))


@app.route("/admin/dashboard")
def admin_dashboard():
    if not require_admin():
        return redirect(url_for("login_page"))

    room = request.args.get("room", "").strip()
    conn = get_db()

    if room:
        issues = conn.execute(
            """
            SELECT issues.*, users.fullname, users.student_id
            FROM issues
            JOIN users ON issues.user_id = users.id
            WHERE issues.room = ?
            ORDER BY issues.id DESC
            """,
            (room,)
        ).fetchall()
    else:
        issues = conn.execute(
            """
            SELECT issues.*, users.fullname, users.student_id
            FROM issues
            JOIN users ON issues.user_id = users.id
            ORDER BY issues.id DESC
            """
        ).fetchall()

    total = conn.execute("SELECT COUNT(*) AS c FROM issues").fetchone()["c"]
    pending = conn.execute("SELECT COUNT(*) AS c FROM issues WHERE status='Pending'").fetchone()["c"]
    fixed = conn.execute("SELECT COUNT(*) AS c FROM issues WHERE status='Fixed'").fetchone()["c"]
    rooms = get_all_rooms(conn)

    conn.close()

    return render_template(
        "admin_dashboard.html",
        issues=issues,
        room_filter=room,
        total=total,
        pending=pending,
        fixed=fixed,
        rooms=rooms
    )


@app.route("/admin/rooms/add", methods=["POST"])
def admin_add_room():
    if not require_admin():
        return redirect(url_for("login_page"))

    room_name = request.form.get("room_name", "").strip()

    if not room_name:
        flash("Please enter a room name.", "error")
        return redirect(url_for("admin_dashboard"))

    try:
        conn = get_db()
        conn.execute("INSERT INTO rooms (name) VALUES (?)", (room_name,))
        conn.commit()
        conn.close()
        flash("Room added successfully.", "success")
    except sqlite3.IntegrityError:
        flash("Room already exists.", "error")

    return redirect(url_for("admin_dashboard"))


@app.route("/admin/rooms/<int:room_id>/delete", methods=["POST"])
def admin_delete_room(room_id):
    if not require_admin():
        return redirect(url_for("login_page"))

    conn = get_db()
    room = conn.execute("SELECT * FROM rooms WHERE id = ?", (room_id,)).fetchone()

    if not room:
        conn.close()
        flash("Room not found.", "error")
        return redirect(url_for("admin_dashboard"))

    issue_exists = conn.execute(
        "SELECT id FROM issues WHERE room = ? LIMIT 1",
        (room["name"],)
    ).fetchone()

    if issue_exists:
        conn.close()
        flash("Cannot delete room because it is already used in issue records.", "error")
        return redirect(url_for("admin_dashboard"))

    conn.execute("DELETE FROM rooms WHERE id = ?", (room_id,))
    conn.commit()
    conn.close()

    flash("Room deleted successfully.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/categories/add", methods=["POST"])
def admin_add_category():
    if not require_admin():
        return redirect(url_for("login_page"))

    category_name = request.form.get("category_name", "").strip()

    if not category_name:
        flash("Please enter a category name.", "error")
        return redirect(url_for("admin_inventory"))

    try:
        conn = get_db()
        conn.execute("INSERT INTO categories (name) VALUES (?)", (category_name,))
        conn.commit()
        conn.close()
        flash("Category added successfully.", "success")
    except sqlite3.IntegrityError:
        flash("Category already exists.", "error")

    return redirect(url_for("admin_inventory"))


@app.route("/admin/categories/<int:category_id>/delete", methods=["POST"])
def admin_delete_category(category_id):
    if not require_admin():
        return redirect(url_for("login_page"))

    conn = get_db()
    category = conn.execute("SELECT * FROM categories WHERE id = ?", (category_id,)).fetchone()

    if not category:
        conn.close()
        flash("Category not found.", "error")
        return redirect(url_for("admin_inventory"))

    equipment_exists = conn.execute(
        "SELECT id FROM equipment WHERE category = ? LIMIT 1",
        (category["name"],)
    ).fetchone()

    if equipment_exists:
        conn.close()
        flash("Cannot delete category because it is already used in inventory.", "error")
        return redirect(url_for("admin_inventory"))

    conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))
    conn.commit()
    conn.close()

    flash("Category deleted successfully.", "success")
    return redirect(url_for("admin_inventory"))


@app.route("/admin/issue/<int:issue_id>/status", methods=["POST"])
def admin_update_status(issue_id):
    if not require_admin():
        return redirect(url_for("login_page"))

    new_status = request.form.get("status", "").strip()
    if new_status not in ("Pending", "Fixed"):
        flash("Invalid status.", "error")
        return redirect(url_for("admin_dashboard"))

    conn = get_db()
    conn.execute("UPDATE issues SET status = ? WHERE id = ?", (new_status, issue_id))
    conn.commit()
    conn.close()

    flash("Status updated.", "success")
    return redirect(request.referrer or url_for("admin_dashboard"))


@app.route("/admin/issue/<int:issue_id>/delete", methods=["POST"])
def admin_delete_issue(issue_id):
    if not require_admin():
        return redirect(url_for("login_page"))

    conn = get_db()
    conn.execute("DELETE FROM issues WHERE id = ?", (issue_id,))
    conn.commit()
    conn.close()

    flash("Issue deleted.", "success")
    return redirect(request.referrer or url_for("admin_dashboard"))


def sync_borrowing_status():
    conn = get_db()
    today = datetime.now().date().isoformat()

    conn.execute("""
        UPDATE borrow_logs
        SET status = 'Overdue'
        WHERE status = 'Borrowed' AND due_date < ?
    """, (today,))

    conn.commit()
    conn.close()


def get_inventory_counts(conn):
    total_items = conn.execute("SELECT COUNT(*) AS c FROM equipment").fetchone()["c"]
    total_stock = conn.execute("SELECT COALESCE(SUM(total_qty), 0) AS c FROM equipment").fetchone()["c"]
    available_stock = conn.execute("SELECT COALESCE(SUM(available_qty), 0) AS c FROM equipment").fetchone()["c"]
    borrowed_stock = total_stock - available_stock
    returned = conn.execute("SELECT COUNT(*) AS c FROM borrow_logs WHERE status='Returned'").fetchone()["c"]
    overdue = conn.execute("SELECT COUNT(*) AS c FROM borrow_logs WHERE status='Overdue'").fetchone()["c"]
    return total_items, total_stock, available_stock, borrowed_stock, returned, overdue


@app.route("/admin/inventory")
def admin_inventory():
    if not require_admin():
        return redirect(url_for("login_page"))

    sync_borrowing_status()
    conn = get_db()

    equipment = conn.execute("""
        SELECT * FROM equipment
        ORDER BY category, name
    """).fetchall()

    categories = get_all_categories(conn)

    total_items, total_stock, available_stock, borrowed_stock, returned, overdue = get_inventory_counts(conn)
    conn.close()

    return render_template(
        "admin_inventory.html",
        equipment=equipment,
        categories=categories,
        total_eq=total_items,
        total_stock=total_stock,
        available_stock=available_stock,
        borrowed_stock=borrowed_stock,
        returned=returned,
        overdue=overdue
    )


@app.route("/admin/inventory/add", methods=["POST"])
def admin_add_equipment():
    if not require_admin():
        return redirect(url_for("login_page"))

    name = request.form.get("name", "").strip()
    category = request.form.get("category", "").strip()
    quantity_raw = request.form.get("quantity", "").strip()

    try:
        quantity = int(quantity_raw)
    except ValueError:
        quantity = 0

    if not name or not category or quantity <= 0:
        flash("Please fill required fields correctly.", "error")
        return redirect(url_for("admin_inventory"))

    conn = get_db()

    category_exists = conn.execute(
        "SELECT id FROM categories WHERE name = ?",
        (category,)
    ).fetchone()

    if not category_exists:
        conn.close()
        flash("Selected category does not exist.", "error")
        return redirect(url_for("admin_inventory"))

    existing = conn.execute(
        "SELECT * FROM equipment WHERE name = ? AND category = ?",
        (name, category)
    ).fetchone()

    if existing:
        conn.execute("""
            UPDATE equipment
            SET total_qty = total_qty + ?,
                available_qty = available_qty + ?
            WHERE id = ?
        """, (quantity, quantity, existing["id"]))
    else:
        conn.execute("""
            INSERT INTO equipment (name, category, total_qty, available_qty)
            VALUES (?, ?, ?, ?)
        """, (name, category, quantity, quantity))

    conn.commit()
    conn.close()

    flash("Equipment added.", "success")
    return redirect(url_for("admin_inventory"))


@app.route("/admin/inventory/<int:equipment_id>/delete", methods=["POST"])
def admin_delete_equipment(equipment_id):
    if not require_admin():
        return redirect(url_for("login_page"))

    conn = get_db()
    eq = conn.execute("SELECT * FROM equipment WHERE id = ?", (equipment_id,)).fetchone()

    if not eq:
        conn.close()
        flash("Equipment not found.", "error")
        return redirect(url_for("admin_inventory"))

    if eq["available_qty"] != eq["total_qty"]:
        conn.close()
        flash("Cannot delete equipment while some stock is still borrowed.", "error")
        return redirect(url_for("admin_inventory"))

    conn.execute("DELETE FROM equipment WHERE id = ?", (equipment_id,))
    conn.commit()
    conn.close()

    flash("Equipment deleted.", "success")
    return redirect(url_for("admin_inventory"))


@app.route("/admin/borrowing")
def admin_borrowing():
    if not require_admin():
        return redirect(url_for("login_page"))

    sync_borrowing_status()
    conn = get_db()

    borrow_logs = conn.execute("""
        SELECT
            borrow_logs.*,
            equipment.name AS equipment_name,
            equipment.category AS equipment_category
        FROM borrow_logs
        JOIN equipment ON borrow_logs.equipment_id = equipment.id
        ORDER BY borrow_logs.id DESC
    """).fetchall()

    equipment_items = conn.execute("""
        SELECT id, name, category, total_qty, available_qty
        FROM equipment
        ORDER BY category, name
    """).fetchall()

    categories = get_all_categories(conn)

    total_items, total_stock, available_stock, borrowed_stock, returned, overdue = get_inventory_counts(conn)
    conn.close()

    equipment_items_json = json.dumps([
        {
            "id": row["id"],
            "name": row["name"],
            "category": row["category"],
            "total_qty": row["total_qty"],
            "available_qty": row["available_qty"]
        }
        for row in equipment_items
    ])

    return render_template(
        "admin_borrowing.html",
        borrow_logs=borrow_logs,
        total_eq=total_items,
        total_stock=total_stock,
        available_stock=available_stock,
        borrowed_stock=borrowed_stock,
        returned=returned,
        overdue=overdue,
        now_text=datetime.now().strftime("%Y-%m-%d %I:%M %p"),
        categories=categories,
        equipment_items_json=equipment_items_json
    )


@app.route("/admin/borrowing/add", methods=["POST"])
def admin_add_borrowing():
    if not require_admin():
        return redirect(url_for("login_page"))

    selected_category = request.form.get("item_category", "").strip()
    borrower_student_id = request.form.get("borrower_student_id", "").strip()
    borrower_name = request.form.get("borrower_name", "").strip()
    equipment_id_raw = request.form.get("equipment_id", "").strip()
    item_title = request.form.get("item_title", "").strip()
    borrow_limit_days_raw = request.form.get("borrow_limit_days", "").strip()

    try:
        equipment_id = int(equipment_id_raw)
    except ValueError:
        equipment_id = 0

    try:
        borrow_limit_days = int(borrow_limit_days_raw)
    except ValueError:
        borrow_limit_days = 3

    if borrow_limit_days not in [1, 2, 3, 5, 7, 14]:
        borrow_limit_days = 3

    if not selected_category or not borrower_student_id or not borrower_name or equipment_id <= 0:
        flash("Please complete all borrowing fields.", "error")
        return redirect(url_for("admin_borrowing"))

    conn = get_db()

    eq = conn.execute(
        "SELECT * FROM equipment WHERE id = ?",
        (equipment_id,)
    ).fetchone()

    if not eq:
        conn.close()
        flash("Item not found in inventory.", "error")
        return redirect(url_for("admin_borrowing"))

    if eq["category"] != selected_category:
        conn.close()
        flash("Selected item category does not match.", "error")
        return redirect(url_for("admin_borrowing"))

    if eq["available_qty"] <= 0:
        conn.close()
        flash("This item is out of stock.", "error")
        return redirect(url_for("admin_borrowing"))

    if "printed" in selected_category.lower() and not item_title:
        conn.close()
        flash("Please enter the title/name for printed materials.", "error")
        return redirect(url_for("admin_borrowing"))

    now = datetime.now()
    borrow_date = now.strftime("%Y-%m-%d %I:%M %p")
    due_date = (now + timedelta(days=borrow_limit_days)).date().isoformat()

    conn.execute(
        """
        INSERT INTO borrow_logs (
            equipment_id,
            borrower_name,
            borrower_student_id,
            borrow_date,
            due_date,
            status,
            admin_username,
            item_category,
            borrow_limit_days,
            item_title
        )
        VALUES (?, ?, ?, ?, ?, 'Borrowed', ?, ?, ?, ?)
        """,
        (
            eq["id"],
            borrower_name,
            borrower_student_id,
            borrow_date,
            due_date,
            session.get("admin_username", ""),
            eq["category"],
            borrow_limit_days,
            item_title
        )
    )

    conn.execute(
        "UPDATE equipment SET available_qty = available_qty - 1 WHERE id = ?",
        (eq["id"],)
    )

    conn.commit()
    conn.close()

    flash(f"Borrowing record added. Limit: {borrow_limit_days} day(s).", "success")
    return redirect(url_for("admin_borrowing"))


@app.route("/admin/borrowing/return/<int:borrow_id>", methods=["POST"])
def admin_return_equipment(borrow_id):
    if not require_admin():
        return redirect(url_for("login_page"))

    conn = get_db()
    log = conn.execute("SELECT * FROM borrow_logs WHERE id = ?", (borrow_id,)).fetchone()

    if not log:
        conn.close()
        flash("Borrow record not found.", "error")
        return redirect(url_for("admin_borrowing"))

    if log["status"] == "Returned":
        conn.close()
        flash("This item was already returned.", "error")
        return redirect(url_for("admin_borrowing"))

    conn.execute(
        "UPDATE borrow_logs SET status = 'Returned', return_date = ? WHERE id = ?",
        (datetime.now().strftime("%Y-%m-%d %I:%M %p"), borrow_id)
    )

    conn.execute(
        "UPDATE equipment SET available_qty = available_qty + 1 WHERE id = ?",
        (log["equipment_id"],)
    )

    conn.commit()
    conn.close()

    flash("Equipment returned.", "success")
    return redirect(url_for("admin_borrowing"))


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)