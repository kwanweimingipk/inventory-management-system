import hashlib
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

# ============================================================
# Intelligent Business Inventory Management System - Web Version
# Streamlit + SQLite
# Database file is created beside this Python file: inventory.db
# ============================================================

DB = Path(__file__).with_name("inventory.db")


def pw_hash(password: str) -> str:
    """Keep the same SHA-256 password-hash format as the original app."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def get_connection():
    conn = sqlite3.connect(DB, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users(
                id INTEGER PRIMARY KEY,
                username TEXT UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS products(
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                quantity INTEGER NOT NULL CHECK(quantity>=0),
                min_stock INTEGER NOT NULL CHECK(min_stock>=0),
                price REAL NOT NULL CHECK(price>=0),
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS transactions(
                id INTEGER PRIMARY KEY,
                product_id INTEGER,
                product_name TEXT NOT NULL,
                kind TEXT NOT NULL,
                quantity INTEGER NOT NULL CHECK(quantity>0),
                price REAL NOT NULL,
                note TEXT,
                username TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE SET NULL
            );
            """
        )

        if not conn.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            conn.executemany(
                "INSERT INTO users(username,password_hash,role) VALUES(?,?,?)",
                [
                    ("admin", pw_hash("Admin123!"), "admin"),
                    ("staff", pw_hash("Staff123!"), "staff"),
                ],
            )

        if not conn.execute("SELECT 1 FROM products LIMIT 1").fetchone():
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.executemany(
                """INSERT INTO products
                   (name,category,quantity,min_stock,price,created_at)
                   VALUES(?,?,?,?,?,?)""",
                [
                    ("Wireless Mouse", "Accessories", 25, 8, 39.9, now),
                    ("Keyboard", "Accessories", 12, 5, 69.0, now),
                    ("USB-C Cable", "Cables", 4, 10, 15.5, now),
                    ("Laptop Stand", "Office", 9, 4, 49.9, now),
                    ("Headset", "Audio", 6, 5, 89.0, now),
                    ("Webcam", "Accessories", 3, 5, 119.0, now),
                    ("Notebook", "Stationery", 40, 10, 4.5, now),
                ],
            )
        conn.commit()


def authenticate(username, password):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username=? AND password_hash=?",
            (username.strip(), pw_hash(password)),
        ).fetchone()
    return dict(row) if row else None


def fetch_products(search="", category="All"):
    sql = "SELECT * FROM products WHERE (name LIKE ? OR category LIKE ?)"
    args = [f"%{search}%", f"%{search}%"]
    if category != "All":
        sql += " AND category=?"
        args.append(category)
    sql += " ORDER BY name"
    with get_connection() as conn:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]


def fetch_categories():
    with get_connection() as conn:
        return [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT category FROM products ORDER BY category"
            ).fetchall()
        ]


def fetch_product(product_id):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM products WHERE id=?", (int(product_id),)
        ).fetchone()
    return dict(row) if row else None


def add_product(name, category, quantity, min_stock, price, username):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO products
               (name,category,quantity,min_stock,price,created_at)
               VALUES(?,?,?,?,?,?)""",
            (name.strip(), category.strip(), quantity, min_stock, price, now),
        )
        product_id = cur.lastrowid
        if quantity > 0:
            conn.execute(
                """INSERT INTO transactions
                   (product_id,product_name,kind,quantity,price,note,username,created_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (
                    product_id, name.strip(), "IN", quantity, price,
                    "Initial stock", username,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )
        conn.commit()


def update_product(product_id, name, category, min_stock, price):
    with get_connection() as conn:
        conn.execute(
            """UPDATE products SET name=?,category=?,min_stock=?,price=?
               WHERE id=?""",
            (name.strip(), category.strip(), min_stock, price, int(product_id)),
        )
        conn.commit()


def delete_product(product_id):
    with get_connection() as conn:
        conn.execute("DELETE FROM products WHERE id=?", (int(product_id),))
        conn.commit()


def record_stock(product_id, kind, quantity, note, username):
    if kind not in ("IN", "OUT"):
        raise ValueError("Invalid stock movement type.")
    if quantity <= 0:
        raise ValueError("Quantity must be a positive whole number.")

    with get_connection() as conn:
        product = conn.execute(
            "SELECT * FROM products WHERE id=?", (int(product_id),)
        ).fetchone()
        if not product:
            raise ValueError("Product not found.")
        if kind == "OUT" and quantity > product["quantity"]:
            raise ValueError(
                f"Insufficient stock. Only {product['quantity']} units available."
            )

        new_quantity = (
            product["quantity"] + quantity
            if kind == "IN"
            else product["quantity"] - quantity
        )
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "UPDATE products SET quantity=? WHERE id=?",
            (new_quantity, int(product_id)),
        )
        conn.execute(
            """INSERT INTO transactions
               (product_id,product_name,kind,quantity,price,note,username,created_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            (
                int(product_id), product["name"], kind, quantity, product["price"],
                note.strip(), username, now,
            ),
        )
        conn.commit()


def dashboard_data():
    with get_connection() as conn:
        row = conn.execute(
            """SELECT COUNT(*) products,
                      COALESCE(SUM(quantity),0) units,
                      COALESCE(SUM(quantity*price),0) value,
                      COALESCE(SUM(CASE WHEN quantity<=min_stock THEN 1 ELSE 0 END),0) low
               FROM products"""
        ).fetchone()
    return dict(row)


def fetch_transactions(limit=500):
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM transactions ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def restock_data():
    cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    output = []
    with get_connection() as conn:
        products = conn.execute("SELECT * FROM products ORDER BY name").fetchall()
        for p in products:
            sold = conn.execute(
                """SELECT COALESCE(SUM(quantity),0) FROM transactions
                   WHERE product_id=? AND kind='OUT' AND created_at>=?""",
                (p["id"], cutoff),
            ).fetchone()[0]
            target = max(p["min_stock"] * 2, round((sold / 30) * 14))
            output.append(
                {
                    "ID": p["id"],
                    "Product Name": p["name"],
                    "Current Stock": p["quantity"],
                    "Min Stock": p["min_stock"],
                    "30-Day Outbound": sold,
                    "Daily Demand": f"{sold / 30:.2f}",
                    "Target Stock": target,
                    "Recommended Reorder Quantity": max(0, target - p["quantity"]),
                }
            )
    return output


def analytics_data():
    cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        categories = conn.execute(
            """SELECT p.category, COALESCE(SUM(t.quantity),0) total
               FROM products p
               LEFT JOIN transactions t
                 ON p.id=t.product_id AND t.kind='OUT'
               GROUP BY p.category ORDER BY total DESC"""
        ).fetchall()
        recent = conn.execute(
            """SELECT product_name, SUM(quantity) total
               FROM transactions
               WHERE kind='OUT' AND created_at>=?
               GROUP BY product_name ORDER BY total DESC LIMIT 8""",
            (cutoff,),
        ).fetchall()
    return [dict(r) for r in categories], [dict(r) for r in recent]


def change_password(username, old_password, new_password):
    if not authenticate(username, old_password):
        return False, "The current password is incorrect."
    if len(new_password) < 8:
        return False, "The new password must be at least 8 characters long."
    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET password_hash=? WHERE username=?",
            (pw_hash(new_password), username),
        )
        conn.commit()
    return True, "Password updated successfully."


def login_screen():
    st.markdown(
        """
        <div class="hero">
          <div class="hero-title">📦 Intelligent Business Inventory Management System</div>
          <div class="hero-subtitle">Inventory overview · Product management · Stock movement · Analytics</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    _, center, _ = st.columns([1, 1.15, 1])
    with center:
        with st.container(border=True):
            st.subheader("Sign in")
            with st.form("login_form"):
                username = st.text_input("Username")
                password = st.text_input("Password", type="password")
                submitted = st.form_submit_button(
                    "Login", type="primary", use_container_width=True
                )
            if submitted:
                user = authenticate(username, password)
                if user:
                    st.session_state.user = user
                    st.rerun()
                else:
                    st.error("Invalid username or password.")
            #st.caption("Demo accounts: admin / Admin123!  ·  staff / Staff123!")


def show_dashboard():
    st.subheader("Inventory Overview")
    data = dashboard_data()
    cols = st.columns(4)
    cards = [
        ("Total Products", data["products"], "🧾"),
        ("Total Units in Stock", data["units"], "📦"),
        ("Total Stock Value", f"RM {data['value']:,.2f}", "💰"),
        ("Low Stock Items", data["low"], "⚠️"),
    ]
    for col, (label, value, emoji) in zip(cols, cards):
        with col:
            st.markdown(
                f"""<div class="metric-card">
                <div class="metric-label">{emoji} {label}</div>
                <div class="metric-value">{value}</div>
                </div>""",
                unsafe_allow_html=True,
            )

    st.markdown("### Stock Status")
    products = fetch_products()
    if products:
        df = pd.DataFrame(products)
        low = df[df["quantity"] <= df["min_stock"]]
        if not low.empty:
            st.warning(f"{len(low)} product(s) are at or below their minimum stock level.")
            st.dataframe(
                low[["id", "name", "category", "quantity", "min_stock", "price"]]
                .rename(columns={
                    "id": "ID", "name": "Product Name", "category": "Category",
                    "quantity": "Stock", "min_stock": "Min Stock", "price": "Unit Price (RM)"
                }),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.success("All products are above their minimum stock level.")
    st.caption("Items at or below the minimum stock threshold should be reviewed for replenishment.")


def product_management():
    st.subheader("Product Management")
    user = st.session_state.user
    products = fetch_products()
    if products:
        df = pd.DataFrame(products)
        df["Stock Value (RM)"] = (df["quantity"] * df["price"]).round(2)
        df["Status"] = df.apply(
            lambda r: "LOW STOCK" if r["quantity"] <= r["min_stock"] else "OK", axis=1
        )
        df = df.rename(columns={
            "id": "ID", "name": "Product Name", "category": "Category",
            "quantity": "Stock", "min_stock": "Min Stock",
            "price": "Unit Price (RM)", "created_at": "Created At"
        })
    else:
        df = pd.DataFrame()

    with st.container(border=True):
        st.markdown("#### 🔎 Search and filter")
        c1, c2 = st.columns([2, 1])
        search = c1.text_input("Search by product name or category", key="product_search")
        categories = ["All"] + fetch_categories()
        category = c2.selectbox("Category", categories, key="product_category")
    shown = fetch_products(search, category)
    if shown:
        view = pd.DataFrame(shown)
        view["Stock Value (RM)"] = (view["quantity"] * view["price"]).round(2)
        view["Status"] = view.apply(
            lambda r: "LOW STOCK" if r["quantity"] <= r["min_stock"] else "OK", axis=1
        )
        view = view.rename(columns={
            "id": "ID", "name": "Product Name", "category": "Category",
            "quantity": "Stock", "min_stock": "Min Stock",
            "price": "Unit Price (RM)", "created_at": "Created At"
        })
        display_cols = ["ID", "Product Name", "Category", "Stock", "Min Stock",
                        "Unit Price (RM)", "Stock Value (RM)", "Status"]
        st.dataframe(view[display_cols], use_container_width=True, hide_index=True)
    else:
        st.info("No products match your search.")

    st.markdown("#### Product actions")
    add_tab, edit_tab, delete_tab = st.tabs(["➕ Add product", "✏️ Edit product", "🗑️ Delete product"])
    with add_tab:
        with st.form("add_product_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            name = c1.text_input("Product name")
            category_new = c2.text_input("Category")
            quantity = c1.number_input("Initial stock", min_value=0, step=1, value=0)
            min_stock = c2.number_input("Minimum stock", min_value=0, step=1, value=5)
            price = c1.number_input("Unit price (RM)", min_value=0.0, step=1.0, format="%.2f")
            submit = st.form_submit_button("Add product", type="primary")
        if submit:
            if not name.strip() or not category_new.strip():
                st.error("Product name and category cannot be empty.")
            else:
                try:
                    add_product(name, category_new, int(quantity), int(min_stock), float(price), user["username"])
                    st.success("Product added successfully.")
                    st.rerun()
                except sqlite3.IntegrityError as ex:
                    st.error(f"Could not add product: {ex}")

    with edit_tab:
        if user["role"] != "admin":
            st.info("Only administrators can edit products.")
        elif not products:
            st.info("There are no products to edit.")
        else:
            options = {f'{p["id"]} | {p["name"]}': p["id"] for p in fetch_products()}
            chosen = st.selectbox("Select product to edit", list(options.keys()), key="edit_product_select")
            p = fetch_product(options[chosen])
            with st.form("edit_product_form"):
                c1, c2 = st.columns(2)
                new_name = c1.text_input("Product name", value=p["name"])
                new_category = c2.text_input("Category", value=p["category"])
                c1.number_input("Current stock (read-only)", min_value=0, value=int(p["quantity"]), disabled=True)
                new_min = c2.number_input("Minimum stock", min_value=0, value=int(p["min_stock"]), step=1)
                new_price = c1.number_input("Unit price (RM)", min_value=0.0, value=float(p["price"]), step=1.0, format="%.2f")
                save_edit = st.form_submit_button("Save changes", type="primary")
            if save_edit:
                if not new_name.strip() or not new_category.strip():
                    st.error("Product name and category cannot be empty.")
                else:
                    update_product(p["id"], new_name, new_category, int(new_min), float(new_price))
                    st.success("Product updated.")
                    st.rerun()

    with delete_tab:
        if user["role"] != "admin":
            st.info("Only administrators can delete products.")
        elif not products:
            st.info("There are no products to delete.")
        else:
            delete_options = {f'{p["id"]} | {p["name"]} (stock: {p["quantity"]})': p["id"] for p in fetch_products()}
            selected = st.selectbox("Select product to delete", list(delete_options.keys()), key="delete_product_select")
            confirm = st.checkbox("I understand this product will be deleted.", key="confirm_delete_product")
            if st.button("Delete selected product", type="primary", disabled=not confirm):
                delete_product(delete_options[selected])
                st.success("Product deleted.")
                st.rerun()


def stock_movement():
    st.subheader("Inbound / Outbound Stock")
    products = fetch_products()
    if not products:
        st.info("Add a product before recording stock movement.")
        return
    with st.container(border=True):
        st.markdown("#### 📥 Record a stock change")
        options = {f'{p["id"]} | {p["name"]} (in stock: {p["quantity"]})': p for p in products}
        with st.form("stock_movement_form", clear_on_submit=True):
            selected_label = st.selectbox("Product", list(options.keys()))
            movement = st.radio("Movement type", ["Incoming (IN)", "Outgoing (OUT)"], horizontal=True)
            quantity = st.number_input("Quantity", min_value=1, step=1, value=1)
            note = st.text_input("Note (optional)")
            submitted = st.form_submit_button("Submit stock change", type="primary")
        if submitted:
            product = options[selected_label]
            kind = "IN" if movement.startswith("Incoming") else "OUT"
            try:
                record_stock(product["id"], kind, int(quantity), note, st.session_state.user["username"])
                st.success("Stock movement recorded.")
                st.rerun()
            except (ValueError, sqlite3.Error) as ex:
                st.error(str(ex))
    st.caption("The system prevents outgoing quantities from exceeding available stock and automatically records each transaction.")


def analytics_page():
    st.subheader("Inventory Analytics")
    categories, recent = analytics_data()
    if categories:
        df = pd.DataFrame(categories).rename(columns={"category": "Category", "total": "Outbound quantity"})
        left, right = st.columns(2)
        with left:
            st.markdown("#### Outbound quantity by category")
            st.bar_chart(df.set_index("Category"))
        with right:
            st.markdown("#### Category summary")
            st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No analytics data available.")
    st.markdown("#### Most frequently outgoing products (last 30 days)")
    if recent:
        st.dataframe(
            pd.DataFrame(recent).rename(columns={"product_name": "Product", "total": "Outbound quantity"}),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No outgoing transactions in the last 30 days.")
    st.caption("Outbound quantity is an approximate indicator of stock movement, not actual sales revenue.")


def restock_page():
    st.subheader("Intelligent Restock Recommendations")
    st.markdown(
        """<div class="info-card"><b>Restock rule</b><br>
        Target Stock = max(Minimum Stock × 2, Average Daily Outbound × 14 days).<br>
        Recommended Reorder Quantity = max(0, Target Stock − Current Stock).</div>""",
        unsafe_allow_html=True,
    )
    rows = restock_data()
    if rows:
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)
        need = df[df["Recommended Reorder Quantity"] > 0]
        if not need.empty:
            st.warning(f"{len(need)} product(s) currently have a positive recommended reorder quantity.")
        else:
            st.success("No additional replenishment is recommended by the current rule.")
    else:
        st.info("No products available.")


def transaction_history():
    st.subheader("Transaction History")
    transactions = fetch_transactions()
    if not transactions:
        st.info("No transactions recorded yet.")
        return
    df = pd.DataFrame(transactions)
    df["kind"] = df["kind"].map({"IN": "Incoming", "OUT": "Outgoing"})
    df = df.rename(columns={
        "id": "ID", "created_at": "Date / Time", "product_name": "Product",
        "kind": "Type", "quantity": "Quantity", "price": "Unit Price (RM)",
        "note": "Note", "username": "User", "product_id": "Product ID"
    })
    cols = ["ID", "Date / Time", "Product", "Type", "Quantity", "Unit Price (RM)", "Note", "User"]
    c1, c2 = st.columns([2, 1])
    with c1:
        search = st.text_input("Filter by product or user", key="history_search").strip().lower()
    with c2:
        movement_filter = st.selectbox("Movement type", ["All", "Incoming", "Outgoing"], key="history_type")
    if search:
        df = df[
            df["Product"].astype(str).str.lower().str.contains(search, na=False)
            | df["User"].astype(str).str.lower().str.contains(search, na=False)
        ]
    if movement_filter != "All":
        df = df[df["Type"] == movement_filter]
    st.dataframe(df[cols], use_container_width=True, hide_index=True)
    st.caption("Showing the latest 500 transactions.")


def password_page():
    st.subheader("Change Password")
    with st.container(border=True):
        with st.form("change_password_form", clear_on_submit=True):
            old = st.text_input("Current password", type="password")
            new = st.text_input("New password (at least 8 characters)", type="password")
            confirm = st.text_input("Confirm new password", type="password")
            submit = st.form_submit_button("Update password", type="primary")
        if submit:
            if new != confirm:
                st.error("The new passwords do not match.")
            else:
                ok, message = change_password(st.session_state.user["username"], old, new)
                if ok:
                    st.success(message)
                else:
                    st.error(message)


def main():
    st.set_page_config(
        page_title="Intelligent Business Inventory Management System",
        page_icon="📦",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(
        """
        <style>
        .stApp { background: #f4f7fb; }
        [data-testid="stSidebar"] { background: #eaf0f8; }
        .hero {
            background: linear-gradient(120deg, #142b4a, #2364a5);
            color: white; padding: 1.5rem 1.7rem; border-radius: 16px;
            margin-bottom: 1.2rem; box-shadow: 0 5px 16px rgba(20,43,74,.16);
        }
        .hero-title { font-size: 1.55rem; font-weight: 750; }
        .hero-subtitle { margin-top: .45rem; opacity: .88; font-size: .95rem; }
        .metric-card {
            background: white; border: 1px solid #dbe5f1; border-left: 5px solid #3478bd;
            border-radius: 12px; padding: 1rem 1.1rem; min-height: 112px;
            box-shadow: 0 2px 9px rgba(20,43,74,.06);
        }
        .metric-label { color: #53657b; font-size: .88rem; }
        .metric-value { color: #142b4a; font-size: 1.75rem; font-weight: 750; margin-top: .4rem; }
        .info-card {
            background: #e9f3ff; border-left: 5px solid #3478bd;
            padding: 1rem 1.2rem; border-radius: 9px; line-height: 1.8;
        }
        div.stButton > button[kind="primary"], div.stFormSubmitButton > button[kind="primary"] {
            background: #2364a5; border-color: #2364a5; color: white;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    init_db()
    if "user" not in st.session_state:
        st.session_state.user = None

    if not st.session_state.user:
        login_screen()
        return

    user = st.session_state.user
    with st.sidebar:
        st.markdown("## 📦 Inventory System")
        st.caption(f"Signed in as **{user['username']}**")
        st.markdown(f"Role: `{user['role'].upper()}`")
        st.divider()
        if st.button("🔄 Refresh data", use_container_width=True):
            st.rerun()
        if st.button("🔐 Change password", use_container_width=True):
            st.session_state.page = "password"
        if st.button("🚪 Logout", use_container_width=True):
            st.session_state.user = None
            st.session_state.page = "dashboard"
            st.rerun()
        st.divider()
        st.caption("Local browser app · SQLite storage")

    page = st.session_state.get("page", "dashboard")
    pages = {
        "dashboard": "📊 Dashboard",
        "products": "📦 Product Management",
        "stock": "🔁 Inbound / Outbound",
        "analytics": "📈 Analytics",
        "restock": "🧠 Intelligent Restock",
        "history": "🧾 Transaction History",
        "password": "🔐 Change Password",
    }
    with st.sidebar:
        selected_label = st.radio(
            "Navigation",
            list(pages.values()),
            index=list(pages.keys()).index(page) if page in pages else 0,
            label_visibility="collapsed",
        )
    selected_page = next(k for k, v in pages.items() if v == selected_label)
    st.session_state.page = selected_page

    st.markdown(
        f"""<div class="hero">
        <div class="hero-title">{pages[selected_page]}</div>
        <div class="hero-subtitle">Intelligent Business Inventory Management System</div>
        </div>""",
        unsafe_allow_html=True,
    )

    if selected_page == "dashboard":
        show_dashboard()
    elif selected_page == "products":
        product_management()
    elif selected_page == "stock":
        stock_movement()
    elif selected_page == "analytics":
        analytics_page()
    elif selected_page == "restock":
        restock_page()
    elif selected_page == "history":
        transaction_history()
    elif selected_page == "password":
        password_page()


if __name__ == "__main__":
    main()
