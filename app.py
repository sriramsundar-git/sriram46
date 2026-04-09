from flask import (Flask, render_template, request, jsonify,
                   session, redirect, url_for)
import json, uuid, os
from datetime import datetime
from functools import wraps

from menu_loader  import load_menu, get_menu_dict, get_menu_names
from auto_nlp_updater import auto_register_item
from nlp_parser   import parse_command, parse_multi_item_command
from order_manager import OrderManager
from database import (
    init_db, save_order, get_all_orders, get_dashboard_stats,
    get_order_by_id, get_all_staff, add_staff, update_staff,
    delete_staff, reset_staff_password, verify_staff,
    get_active_orders, update_order_status,
    save_feedback, get_all_feedback,
    get_all_schedules, set_schedule, delete_schedule,
)

app = Flask(__name__)
app.secret_key = "voice_ordering_secret_2024"

MENU_FILE     = os.path.join(os.path.dirname(os.path.abspath(__file__)), "menu.json")
LOW_STOCK_QTY = 10

# ── Menu state ─────────────────────────────────────────────────────────────
MENU = []; MENU_DICT = {}; MENU_NAMES = []

def reload_menu():
    global MENU, MENU_DICT, MENU_NAMES
    MENU       = load_menu("menu.json")
    MENU_DICT  = get_menu_dict(MENU)
    MENU_NAMES = get_menu_names(MENU)

def save_menu_to_file(data):
    with open(MENU_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_live_menu_dict():
    return get_menu_dict(MENU)   # always live — new items appear immediately

reload_menu()
order_managers = {}

def get_order_manager():
    sid = session.get("sid")
    if not sid:
        sid = str(uuid.uuid4()); session["sid"] = sid
    if sid not in order_managers:
        order_managers[sid] = OrderManager(get_live_menu_dict)
    return order_managers[sid]

# ── Auth decorators ────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("staff_id"):
            # Return JSON 401 for fetch/XHR requests, redirect for browser nav
            if request.is_json or request.headers.get("Content-Type","").startswith("application/json"):
                return jsonify({"status":"error","message":"Session expired. Please login again."}), 401
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated

def manager_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("staff_role") != "manager":
            return jsonify({"status":"error","message":"Manager access required."}), 403
        return f(*args, **kwargs)
    return decorated

# ── Time-based menu helper ─────────────────────────────────────────────────
def _get_available_menu():
    """Returns menu items filtered by time schedule."""
    now_hour   = datetime.now().hour
    schedules  = get_all_schedules()   # {item_id: {start_hour, end_hour}}
    result     = []
    for item in MENU:
        sched = schedules.get(item["item_id"])
        if sched:
            # active only within [start_hour, end_hour)
            s, e = sched["start_hour"], sched["end_hour"]
            if s <= e:
                active = s <= now_hour < e
            else:  # wraps midnight
                active = now_hour >= s or now_hour < e
            if not active:
                continue   # skip — outside time window
        result.append(item)
    return result

def _is_item_available_now(item_name):
    """Returns (True, None) or (False, reason_string)."""
    now_hour  = datetime.now().hour
    schedules = get_all_schedules()
    for item in MENU:
        if item["item_name"].lower() == item_name.lower():
            sched = schedules.get(item["item_id"])
            if sched:
                s, e = sched["start_hour"], sched["end_hour"]
                if s <= e:
                    active = s <= now_hour < e
                else:
                    active = now_hour >= s or now_hour < e
                if not active:
                    return False, f"'{item['item_name'].title()}' is only available {s:02d}:00–{e:02d}:00."
            return True, None
    return True, None   # item not found — let OrderManager handle it

# ── Sentiment analyser (simple rule-based, no external lib) ───────────────
_POS = ["good","great","excellent","amazing","love","delicious","tasty",
        "perfect","fantastic","hot","fresh","wonderful","nice","best","நன்றாக",
        "super","nalla","nallairukku"]
_NEG = ["bad","cold","stale","late","wrong","terrible","awful","slow","poor",
        "disgusting","horrible","worst","வேண்டாம்","கெட்ட","delay","missing"]

def _analyse_sentiment(text):
    t = text.lower()
    pos = sum(1 for w in _POS if w in t)
    neg = sum(1 for w in _NEG if w in t)
    if pos > neg:   return "positive"
    if neg > pos:   return "negative"
    return "neutral"

# ── Recommendations ────────────────────────────────────────────────────────
def _get_recommendations(cart_items, limit=3):
    """
    Suggest items based on:
    1. Same category as cart items (complementary)
    2. Time of day defaults
    3. Highest-selling from stats (popularity)
    Not already in cart. Returns list of item dicts.
    """
    now_hour = datetime.now().hour
    cart_names = {i["item_name"].lower() for i in cart_items}
    cart_cats  = {i.get("category","") for i in cart_items}

    # Time-of-day popular defaults
    if 6 <= now_hour < 11:
        time_cats = ["Breakfast", "Beverages"]
    elif 11 <= now_hour < 15:
        time_cats = ["Main Course", "Bread", "Starter"]
    elif 15 <= now_hour < 18:
        time_cats = ["Beverages", "Dessert", "Starter"]
    else:
        time_cats = ["Main Course", "Bread", "Dessert"]

    available = _get_available_menu()
    scored = []
    for item in available:
        if not item.get("is_available", True): continue
        if item["item_name"].lower() in cart_names: continue
        score = 0
        if item["category"] in cart_cats:    score += 3   # same category as cart
        if item["category"] in time_cats:    score += 2   # time-relevant
        if item.get("stock", 50) > 20:       score += 1   # well-stocked
        scored.append((score, item))

    scored.sort(key=lambda x: -x[0])
    return [item for _, item in scored[:limit]]

# ════════════════════════════════════════════════════════════════
#  CUSTOMER ROUTES
# ════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    available = _get_available_menu()
    menu_by_category = {}
    for item in available:
        menu_by_category.setdefault(item["category"], []).append(item)
    now_hour = datetime.now().hour
    return render_template("index.html",
                           menu_by_category=menu_by_category,
                           now_hour=now_hour)

@app.route("/process_command", methods=["POST"])
def process_command():
    data = request.get_json()
    text = data.get("text","").strip()
    if not text:
        return jsonify({"status":"error","message":"No command received."})

    om     = get_order_manager()
    intent, items, qty = parse_command(text, MENU_NAMES)
    multi  = parse_multi_item_command(text, MENU_NAMES)
    msgs   = []

    # Diet / allergy filter applied first
    diet_filter = session.get("diet_filter", [])  # e.g. ["vegetarian","no spicy"]

    if intent == "CONFIRM":
        if om.is_empty():
            return jsonify({"status":"error","message":"Your cart is empty.","cart":[],"total":0})
        cart  = om.get_cart_summary()
        total = om.calculate_total()
        order_id, token = save_order(cart, total)
        _deduct_stock(cart)
        om.clear_order()
        session.pop("diet_filter", None)   # clear diet for next order
        return jsonify({
            "status"      : "confirmed",
            "message"     : f"Order #{order_id} confirmed! Token: T-{token:02d}. Total: ₹{total:.2f}. Thank you!",
            "order_id"    : order_id,
            "token_number": token,
            "cart"        : [], "total": 0
        })

    elif intent == "CANCEL":
        om.clear_order()
        return jsonify({"status":"cancelled","message":"Order cancelled.","cart":[],"total":0})

    elif intent == "SHOW":
        recs = _get_recommendations(om.get_cart_summary())
        rec_names = ", ".join(r["item_name"].title() for r in recs)
        msg = "Here is your current order."
        if rec_names: msg += f" You might also like: {rec_names}."
        return jsonify({"status":"show","message":msg,
                        "cart":om.get_cart_summary(),"total":om.calculate_total(),
                        "recommendations":recs})

    elif intent == "DIET":
        # handled below in /set_diet route
        pass

    else:
        targets = multi if multi else [(i, qty) for i in items]
        if not targets:
            msgs.append("Sorry, I couldn't find any menu items. Try: 'add two naan'.")
        else:
            for name, q in targets:
                # Time check
                ok_time, time_msg = _is_item_available_now(name)
                if not ok_time:
                    msgs.append(time_msg)
                    continue
                # Diet guard
                if "vegetarian" in diet_filter and name in _NON_VEG_ITEMS:
                    msgs.append(f"⚠️ '{name.title()}' is non-veg. Skipped (vegetarian mode on).")
                    continue
                if intent == "REMOVE":   _, m = om.remove_item(name)
                elif intent == "UPDATE": _, m = om.update_item(name, q)
                else:                    _, m = om.add_item(name, q)
                msgs.append(m)

        # Proactive recommendations after adding
        if intent not in ("REMOVE","CANCEL") and not om.is_empty():
            recs = _get_recommendations(om.get_cart_summary())
            if recs:
                names = ", ".join(r["item_name"].title() for r in recs[:2])
                msgs.append(f"💡 Try also: {names}")

        return jsonify({"status":"updated","message":" | ".join(msgs),
                        "cart":om.get_cart_summary(),"total":om.calculate_total()})

# Non-veg items list (for diet guard)
_NON_VEG_ITEMS = {"chicken curry","chicken","kozhi"}

@app.route("/set_diet", methods=["POST"])
def set_diet():
    data   = request.get_json()
    prefs  = data.get("preferences", [])
    session["diet_filter"] = prefs
    msg = "Diet preferences saved: " + (", ".join(prefs) if prefs else "none")
    return jsonify({"status":"ok","message":msg})

@app.route("/get_recommendations")
def get_recommendations():
    om   = get_order_manager()
    recs = _get_recommendations(om.get_cart_summary())
    return jsonify({"recommendations": recs})

@app.route("/add_item_manual", methods=["POST"])
def add_item_manual():
    data = request.get_json()
    name = data.get("item_name","").lower()
    qty  = int(data.get("qty",1))
    ok_time, time_msg = _is_item_available_now(name)
    if not ok_time:
        om = get_order_manager()
        return jsonify({"status":"error","message":time_msg,
                        "cart":om.get_cart_summary(),"total":om.calculate_total()})
    om = get_order_manager()
    ok, msg = om.add_item(name, qty)
    return jsonify({"status":"updated" if ok else "error","message":msg,
                    "cart":om.get_cart_summary(),"total":om.calculate_total()})

@app.route("/remove_item_manual", methods=["POST"])
def remove_item_manual():
    data = request.get_json()
    om   = get_order_manager()
    ok, msg = om.remove_item(data.get("item_name","").lower())
    return jsonify({"status":"updated" if ok else "error","message":msg,
                    "cart":om.get_cart_summary(),"total":om.calculate_total()})

@app.route("/clear_cart", methods=["POST"])
def clear_cart():
    get_order_manager().clear_order()
    return jsonify({"status":"cleared","message":"Cart cleared.","cart":[],"total":0})

@app.route("/get_cart")
def get_cart():
    om = get_order_manager()
    return jsonify({"cart":om.get_cart_summary(),"total":om.calculate_total()})

@app.route("/history")
def history():
    return render_template("history.html", orders=get_all_orders())

@app.route("/receipt/<int:order_id>")
def receipt(order_id):
    order = get_order_by_id(order_id)
    if not order: return "Order not found", 404
    return render_template("receipt.html", order=order)

# ── Feedback ───────────────────────────────────────────────────────────────
@app.route("/submit_feedback", methods=["POST"])
def submit_feedback():
    data      = request.get_json()
    order_id  = data.get("order_id")
    text      = data.get("text","").strip()
    if not text:
        return jsonify({"status":"error","message":"Feedback text is required."})
    sentiment = _analyse_sentiment(text)
    save_feedback(order_id, text, sentiment)
    emoji = "😊" if sentiment=="positive" else "😟" if sentiment=="negative" else "😐"
    return jsonify({"status":"ok",
                    "message":f"Thank you for your feedback! {emoji}",
                    "sentiment":sentiment})

# ── Kitchen display ─────────────────────────────────────────────────────────
@app.route("/kitchen")
def kitchen():
    return render_template("kitchen.html")

@app.route("/api/kitchen/orders")
def api_kitchen_orders():
    return jsonify({"orders": get_active_orders()})

@app.route("/api/kitchen/ready/<int:order_id>", methods=["POST"])
def api_kitchen_ready(order_id):
    update_order_status(order_id, "ready")
    order  = get_order_by_id(order_id)
    token  = order["token_number"] if order and order.get("token_number") else 0
    token  = int(token) if token else 0
    label  = f"T-{token:02d}" if token else f"#{order_id}"
    return jsonify({"status":"ok","token":token,
                    "announce":f"{label}, your order is ready!"})

@app.route("/api/kitchen/served/<int:order_id>", methods=["POST"])
def api_kitchen_served(order_id):
    update_order_status(order_id, "served")
    return jsonify({"status":"ok"})

# ════════════════════════════════════════════════════════════════
#  ADMIN ROUTES
# ════════════════════════════════════════════════════════════════

@app.route("/admin/login", methods=["GET","POST"])
def admin_login():
    error = None
    if request.method == "POST":
        staff = verify_staff(request.form.get("username",""),
                             request.form.get("password",""))
        if staff:
            session["staff_id"]   = staff["staff_id"]
            session["staff_name"] = staff["name"]
            session["staff_role"] = staff["role"]
            return redirect(url_for("admin"))
        error = "Invalid username or password."
    return render_template("admin_login.html", error=error)

@app.route("/admin/logout")
def admin_logout():
    session.pop("staff_id",None); session.pop("staff_name",None); session.pop("staff_role",None)
    return redirect(url_for("admin_login"))

@app.route("/admin")
@login_required
def admin():
    stats      = get_dashboard_stats()
    staff_list = get_all_staff()
    feedbacks  = get_all_feedback()
    schedules  = get_all_schedules()
    low_stock  = [i for i in MENU if i.get("stock",50) <= LOW_STOCK_QTY]
    return render_template("admin.html",
                           stats=stats, menu=MENU,
                           staff_list=staff_list, low_stock=low_stock,
                           feedbacks=feedbacks, schedules=schedules,
                           staff_name=session.get("staff_name",""),
                           staff_role=session.get("staff_role",""))

@app.route("/admin/api/stats")
@login_required
def admin_api_stats():
    return jsonify(get_dashboard_stats())

# ── Food management ─────────────────────────────────────────────────────────
@app.route("/admin/menu", methods=["GET"])
@login_required
def admin_get_menu():
    return jsonify(MENU)

@app.route("/admin/menu/add", methods=["POST"])
@login_required
def admin_add_food():
    data  = request.get_json()
    name  = data.get("item_name","").strip().lower()
    cat   = data.get("category","").strip()
    price = data.get("price")
    stock = int(data.get("stock",50))
    avail = data.get("is_available",True)
    if not name or not cat or price is None:
        return jsonify({"status":"error","message":"Name, category, and price are required."})
    if float(price)<=0:
        return jsonify({"status":"error","message":"Price must be > 0."})
    if any(i["item_name"].lower()==name for i in MENU):
        return jsonify({"status":"error","message":f"'{name.title()}' already exists."})
    new_id   = max((i["item_id"] for i in MENU),default=0)+1
    image    = data.get("image","").strip()
    new_item = {"item_id":new_id,"item_name":name,"category":cat,
                "price":float(price),"stock":stock,"is_available":bool(avail),
                "image":image}
    MENU.append(new_item); save_menu_to_file(MENU); reload_menu()  # reloads MENU + MENU_NAMES
    # Auto-update NLP with Tamil+English variants for the new item
    nlp_result = auto_register_item(name)
    nlp_msg = f" NLP: {len(nlp_result['nlp_entries_added'])} voice variants added." if nlp_result['nlp_entries_added'] else ""
    return jsonify({"status":"success","message":f"'{name.title()}' added.{nlp_msg}","item":new_item,"nlp":nlp_result})

@app.route("/admin/menu/edit/<int:item_id>", methods=["POST"])
@login_required
def admin_edit_food(item_id):
    data = request.get_json()
    for item in MENU:
        if item["item_id"]==item_id:
            if data.get("item_name","").strip(): item["item_name"]=data["item_name"].strip().lower()
            if data.get("category","").strip():  item["category"]=data["category"].strip()
            if "price" in data and float(data["price"])>0: item["price"]=float(data["price"])
            if "stock" in data: item["stock"]=max(0,int(data["stock"]))
            if "is_available" in data: item["is_available"]=bool(data["is_available"])
            if "image" in data: item["image"]=data["image"].strip()
            save_menu_to_file(MENU); reload_menu()
            return jsonify({"status":"success","message":"Item updated.","item":item})
    return jsonify({"status":"error","message":"Item not found."})

@app.route("/admin/menu/delete/<int:item_id>", methods=["POST"])
@login_required
def admin_delete_food(item_id):
    global MENU
    before = len(MENU)
    MENU   = [i for i in MENU if i["item_id"]!=item_id]
    if len(MENU)==before:
        return jsonify({"status":"error","message":"Item not found."})
    save_menu_to_file(MENU); reload_menu()
    return jsonify({"status":"success","message":"Item deleted."})

@app.route("/admin/menu/toggle/<int:item_id>", methods=["POST"])
@login_required
def admin_toggle_food(item_id):
    for item in MENU:
        if item["item_id"]==item_id:
            item["is_available"]=not item["is_available"]
            save_menu_to_file(MENU); reload_menu()
            label="Available" if item["is_available"] else "Unavailable"
            return jsonify({"status":"success",
                            "message":f"'{item['item_name'].title()}' is now {label}.",
                            "is_available":item["is_available"]})
    return jsonify({"status":"error","message":"Item not found."})

@app.route("/admin/menu/restock/<int:item_id>", methods=["POST"])
@login_required
def admin_restock(item_id):
    data = request.get_json()
    qty  = int(data.get("qty",50))
    for item in MENU:
        if item["item_id"]==item_id:
            item["stock"]=item.get("stock",0)+qty
            if item["stock"]>0: item["is_available"]=True
            save_menu_to_file(MENU); reload_menu()
            return jsonify({"status":"success",
                            "message":f"Restocked '{item['item_name'].title()}'. New stock: {item['stock']}.",
                            "stock":item["stock"]})
    return jsonify({"status":"error","message":"Item not found."})

# ── Schedule management ─────────────────────────────────────────────────────
@app.route("/admin/schedule/set", methods=["POST"])
@login_required
def admin_set_schedule():
    data = request.get_json()
    set_schedule(int(data["item_id"]),int(data["start_hour"]),int(data["end_hour"]))
    return jsonify({"status":"success","message":"Schedule saved."})

@app.route("/admin/schedule/delete/<int:item_id>", methods=["POST"])
@login_required
def admin_delete_schedule(item_id):
    delete_schedule(item_id)
    return jsonify({"status":"success","message":"Schedule removed (available all day)."})

# ── Staff management ─────────────────────────────────────────────────────────
@app.route("/admin/staff", methods=["GET"])
@login_required
def admin_get_staff():
    return jsonify(get_all_staff())

@app.route("/admin/staff/add", methods=["POST"])
@login_required
@manager_required
def admin_add_staff():
    data     = request.get_json()
    name     = data.get("name","").strip()
    username = data.get("username","").strip()
    password = data.get("password","").strip()
    role     = data.get("role","cashier")
    if not name or not username or not password:
        return jsonify({"status":"error","message":"Name, username, and password are required."})
    if len(password)<6:
        return jsonify({"status":"error","message":"Password must be at least 6 characters."})
    ok, result = add_staff(name,username,password,role)
    if ok:
        return jsonify({"status":"success","message":f"Staff '{name}' added.","staff_id":result})
    return jsonify({"status":"error","message":str(result)})

@app.route("/admin/staff/edit/<int:staff_id>", methods=["POST"])
@login_required
@manager_required
def admin_edit_staff(staff_id):
    data = request.get_json()
    update_staff(staff_id,data.get("name",""),data.get("role","cashier"),data.get("is_active",True))
    return jsonify({"status":"success","message":"Staff updated."})

@app.route("/admin/staff/delete/<int:staff_id>", methods=["POST"])
@login_required
@manager_required
def admin_delete_staff(staff_id):
    if staff_id==session.get("staff_id"):
        return jsonify({"status":"error","message":"You cannot delete your own account."})
    ok, msg = delete_staff(staff_id)
    return jsonify({"status":"success" if ok else "error","message":msg})

@app.route("/admin/staff/reset-password/<int:staff_id>", methods=["POST"])
@login_required
@manager_required
def admin_reset_password(staff_id):
    data = request.get_json()
    pw   = data.get("password","").strip()
    if len(pw)<6:
        return jsonify({"status":"error","message":"Password must be at least 6 characters."})
    reset_staff_password(staff_id,pw)
    return jsonify({"status":"success","message":"Password reset."})


# ── NLP viewer ─────────────────────────────────────────────────────────────
@app.route("/admin/nlp/entries/<item_name>")
@login_required
def admin_nlp_entries(item_name):
    """Return current NLP map entries for an item."""
    from nlp_parser import TAMIL_FOOD_MAP
    entries = {k: v for k, v in TAMIL_FOOD_MAP.items()
               if v.lower() == item_name.lower()}
    return jsonify({"item": item_name, "entries": entries})

@app.route("/admin/nlp/add", methods=["POST"])
@login_required
def admin_nlp_add():
    """Manually add a NLP variant for an item."""
    data       = request.get_json()
    trigger    = data.get("trigger","").strip()
    target     = data.get("target","").strip().lower()
    if not trigger or not target:
        return jsonify({"status":"error","message":"Trigger and target are required."})
    from auto_nlp_updater import update_nlp_parser
    result = update_nlp_parser(trigger, target)
    return jsonify({"status":"success","added": result["added"]})

# ── Image upload ───────────────────────────────────────────────────────────
ALLOWED_EXT = {"jpg","jpeg","png","webp"}

def _allowed(filename):
    return "." in filename and filename.rsplit(".",1)[1].lower() in ALLOWED_EXT

@app.route("/admin/menu/upload_image", methods=["POST"])
@login_required
def admin_upload_image():
    if "image" not in request.files:
        return jsonify({"status":"error","message":"No file sent."})
    f = request.files["image"]
    if not f or f.filename == "":
        return jsonify({"status":"error","message":"No file selected."})
    if not _allowed(f.filename):
        return jsonify({"status":"error","message":"Only JPG, PNG, WEBP allowed."})
    # Sanitise filename — keep original name, replace spaces with hyphens
    from werkzeug.utils import secure_filename
    filename  = secure_filename(f.filename).replace("_","-").lower()
    save_dir  = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "static", "images")
    os.makedirs(save_dir, exist_ok=True)
    f.save(os.path.join(save_dir, filename))
    return jsonify({"status":"success","filename":filename})

# ── Stock deduction ─────────────────────────────────────────────────────────
def _deduct_stock(cart):
    changed = False
    for ci in cart:
        name = ci["item_name"].lower()
        for mi in MENU:
            if mi["item_name"].lower()==name:
                mi["stock"]=max(0,mi.get("stock",50)-ci["qty"])
                if mi["stock"]==0: mi["is_available"]=False
                changed=True
    if changed:
        save_menu_to_file(MENU); reload_menu()

if __name__ == "__main__":
    init_db()
    print("="*55)
    print("  VoiceOrder — Restaurant Ordering System")
    print("  Customer : http://127.0.0.1:5000")
    print("  Kitchen  : http://127.0.0.1:5000/kitchen")
    print("  Admin    : http://127.0.0.1:5000/admin")
    print("  Login    : admin / admin123")
    print("="*55)
    app.run(debug=True)
