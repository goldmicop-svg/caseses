"""MEME CASE — серверная логика демо-приложения.

Учётные записи хранятся в локальном SQLite-файле ``meme_case.db``. Игровые
предметы и баланс остаются в памяти процесса — это позволяет не усложнять
демо, но авторизация, аватары, роль администратора и баны сохраняются.
"""

import os
import random
import re
import sqlite3
import uuid
from functools import wraps
from pathlib import Path

from flask import Flask, jsonify, render_template, request, session
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename


BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "static" / "uploads"
DATABASE = BASE_DIR / "meme_case.db"
ALLOWED_AVATAR_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}

app = Flask(__name__)
app.secret_key = os.environ.get("MEME_CASE_SECRET", "meme-case-demo-secret-change-me")
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024


# ======================================================================
# ИГРОВЫЕ ДАННЫЕ
# ======================================================================

RARITY = {
    "trash": {"label": "Хлам", "color": "var(--r-trash)"},
    "common": {"label": "Обычный", "color": "var(--r-common)"},
    "rare": {"label": "Редкий", "color": "var(--r-rare)"},
    "epic": {"label": "Эпический", "color": "var(--r-epic)"},
    "legendary": {"label": "Легендарный", "color": "var(--r-legendary)"},
    "mythic": {"label": "Мифический", "color": "var(--r-mythic)"},
}
RARITY_WEIGHT = {"trash": 80, "common": 60, "rare": 25, "epic": 12, "legendary": 3, "mythic": 1}

# В каталоге остаются только переданные пользователем фотографии-персонажи.
# Бывшие эмодзи-предметы намеренно исключены из выдачи, кейсов и админ-панели.
ITEM_POOL = []

# Все изображения из переданной папки стали отдельными персонажами.
CHARACTER_IMAGES = [
    "5278675408956104248.jpg", "5278675408956104249.jpg", "5278675408956104250.jpg",
    "5278675408956104251.jpg", "5278675408956104252.jpg", "5278675408956104253.jpg",
    "5278675408956104254.jpg", "5278675408956104255.jpg", "5278675408956104256.jpg",
    "5278675408956104257.jpg", "5278675408956104258.jpg", "5278675408956104259.jpg",
    "5278675408956104260.jpg", "5278675408956104261.jpg", "5278675408956104262.jpg",
    "5278675408956104263.jpg", "5278675408956104264.jpg", "5278675408956104265.jpg",
    "5278675408956104266.jpg", "5278675408956104267.jpg", "5278675408956104268.jpg",
    "5278675408956104269.jpg", "5278675408956104279.jpg", "5278675408956104280.jpg",
    "5278675408956104281.jpg", "5278675408956104282.jpg",
    # Новая партия фотографий: первая половина — дешёвый «хлам»-тир (< 100 M),
    # вторая половина — топовый «мифический» тир (от 2500 M).
    "5283179008583475148.jpg", "5283179008583475149.jpg", "5283179008583475150.jpg",
    "5283179008583475151.jpg", "5283179008583475152.jpg", "5283179008583475153.jpg",
    "5283179008583475154.jpg",
    "5283179008583475155.jpg", "5283179008583475156.jpg", "5283179008583475157.jpg",
    "5283179008583475158.jpg", "5283179008583475159.jpg", "5283179008583475160.jpg",
    "5283179008583475161.jpg",
    # Три новых самых дешёвых персонажа (10 / 20 / 30 M).
    "5283179008583475222.jpg", "5283179008583475224.jpg", "5283179008583475227.jpg",
]
CHARACTER_RARITIES = [
    "common", "common", "common", "common", "common", "common", "common", "common",
    "rare", "rare", "rare", "rare", "rare", "rare", "rare", "epic", "epic", "epic",
    "epic", "epic", "epic", "epic", "legendary", "legendary", "legendary", "legendary",
    "trash", "trash", "trash", "trash", "trash", "trash", "trash",
    "mythic", "mythic", "mythic", "mythic", "mythic", "mythic", "mythic",
    "trash", "trash", "trash",
]
CHARACTER_VALUES = [
    110, 130, 150, 170, 190, 210, 230, 250, 340, 390, 430, 470, 520,
    570, 620, 760, 830, 910, 990, 1080, 1170, 1260, 1450, 1650, 1850, 2200,
    40, 50, 60, 70, 80, 90, 95,
    2500, 2800, 3100, 3400, 3800, 4300, 5000,
    10, 20, 30,
]
CHARACTER_NAMES = [
    "Пиксель", "Кот Комета", "Байт", "Тихий Тролль", "Мистер Луп",
    "Капитан Мем", "Лунный Пёс", "Неоновый Жук", "Глитч", "Рэйв",
    "Мятный Хакер", "Доктор Вайб", "Шум", "Суперфрог", "Ночной Геймер",
    "Кибер Кот", "Фантом", "Лазерный Лис", "Синт", "Майор Бит",
    "Чад Нова", "Золотой Вайб", "Король Глитч", "Астра", "Оракул", "Легенда 404",
    "Тапок-Воин", "Заряд 1%", "Ноунейм Чел", "Дырявый Носок", "Соседский Кот",
    "Пельмень Underdog", "Огрызок Мечты",
    "Император Кринжа", "Бог Рофла", "Верховный Донат", "Чемпион Вайба",
    "Абсолют Legend", "Мега Чед X", "Финальный Босс",
    "Кермит-Крипер", "Пчелиный Лев", "Тихий Пёс",
]
for number, filename in enumerate(CHARACTER_IMAGES, start=1):
    ITEM_POOL.append({
        "id": f"character_{number}", "name": CHARACTER_NAMES[number - 1], "type": "Персонаж",
        "image": f"/static/characters/{filename}", "rarity": CHARACTER_RARITIES[number - 1],
        "value": CHARACTER_VALUES[number - 1],
    })

# Кейсы намеренно идут от самого доступного к самому дорогому.
# Диапазон выпадения — часть серверного правила, поэтому его нельзя подменить в браузере.
# Правило цены: цена кейса = минимально возможный дроп × 1.4 (кейс всегда стоит
# на 40% больше своего худшего исхода).
# Категории («теги») нужны фильтрам на странице кейсов: клиент фильтрует
# карточки именно по этому серверному списку, поэтому категории работают.
CASES = [
    {"id": "bomzh", "name": "«БОМЖ»", "price": 70, "color": "#8D8F9A", "icon": "◇", "min_value": 10, "max_value": 95, "tags": ["Недорогие", "Популярные"]},
    {"id": "school_lunch", "name": "«ШКОЛЬНЫЙ ОБЕД»", "price": 120, "color": "#FFB347", "icon": "◆", "min_value": 50, "max_value": 170, "tags": ["Недорогие", "Новые"]},
    {"id": "rovny_vas", "name": "«РОВНЫЙ ВАСЬ»", "price": 200, "color": "#55A7FF", "icon": "✦", "min_value": 90, "max_value": 250, "tags": ["Недорогие", "Популярные"]},
    {"id": "cool_slayer", "name": "«КРУТОЙ SLAYER»", "price":350, "color": "#8B5CFF", "icon": "⬡", "min_value": 150, "max_value": 430, "tags": ["Новые", "Популярные"]},
    {"id": "true_am_am", "name": "«TRUE AM AM»", "price": 500, "color": "#FF6FD8", "icon": "✹", "min_value": 230, "max_value": 620, "tags": ["Новые", "Особые"]},
    {"id": "mellstroy", "name": "«MELLSTROY»", "price": 750, "color": "#FF4D4D", "icon": "◈", "min_value": 340, "max_value": 990, "tags": ["Популярные", "Особые"]},
    {"id": "worker", "name": "«ВОРКЕР»", "price": 1200, "color": "#33D69F", "icon": "⚙", "min_value": 520, "max_value": 1650, "tags": ["Новые", "Особые"]},
    {"id": "meme_case", "name": "«MEME CASE»", "price": 3500, "color": "#FFD76A", "icon": "✪", "min_value": 990, "max_value": 5000, "tags": ["Особые", "Популярные"]},
]

# Игровой прогресс намеренно остаётся in-memory для демо.
GAME_DB = {}


# ======================================================================
# УЧЁТНЫЕ ЗАПИСИ
# ======================================================================

def db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_database():
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with db_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0,
                is_banned INTEGER NOT NULL DEFAULT 0,
                avatar_path TEXT
            )
        """)


def get_user(user_id):
    with db_connection() as conn:
        return conn.execute(
            "SELECT id, username, password_hash, is_admin, is_banned, avatar_path FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()


def user_public(user):
    return {"id": user["id"], "username": user["username"], "is_admin": bool(user["is_admin"]), "avatar_url": user["avatar_path"]}


def active_user():
    user_id = session.get("user_id")
    if not user_id:
        return None, "auth_required"
    user = get_user(user_id)
    if not user:
        session.clear()
        return None, "auth_required"
    if user["is_banned"]:
        session.clear()
        return None, "banned"
    return user, None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user, error = active_user()
        if error:
            return jsonify({"error": error}), 403 if error == "banned" else 401
        return view(user, *args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(user, *args, **kwargs):
        if not user["is_admin"]:
            return jsonify({"error": "admin_required"}), 403
        return view(user, *args, **kwargs)
    return wrapped


def valid_username(username):
    return bool(re.fullmatch(r"[\w-]{3,24}", username, flags=re.UNICODE))


def looks_like_image(file, extension):
    """Быстрая проверка сигнатуры, чтобы не сохранять произвольный файл под .jpg."""
    header = file.stream.read(12)
    file.stream.seek(0)
    signatures = {
        "jpg": header.startswith(b"\xff\xd8\xff"),
        "jpeg": header.startswith(b"\xff\xd8\xff"),
        "png": header.startswith(b"\x89PNG\r\n\x1a\n"),
        "gif": header.startswith((b"GIF87a", b"GIF89a")),
        "webp": header.startswith(b"RIFF") and header[8:12] == b"WEBP",
    }
    return signatures.get(extension, False)


# ======================================================================
# ИГРОВАЯ ЛОГИКА
# ======================================================================

def item_by_id(item_id):
    return next((item for item in ITEM_POOL if item["id"] == item_id), None)


def make_instance(item_template):
    inst = dict(item_template)
    inst["instance_id"] = str(uuid.uuid4())
    # Продажа возвращает 100% оценочной стоимости (комиссия отключена) — правило
    # одинаково на сервере и не зависит от данных, присланных браузером.
    inst["sell_value"] = max(1, round(inst["value"] * 1.0))
    return inst


def weighted_random_item(min_value=0, max_value=float("inf")):
    eligible = [item for item in ITEM_POOL if min_value <= item["value"] <= max_value]
    if not eligible:
        raise ValueError("No characters match the case range")
    total = sum(RARITY_WEIGHT[item["rarity"]] for item in eligible)
    roll = random.uniform(0, total)
    for item in eligible:
        roll -= RARITY_WEIGHT[item["rarity"]]
        if roll <= 0:
            return item
    return eligible[0]


def find_nearest_item(value):
    return min(ITEM_POOL, key=lambda item: abs(item["value"] - value))


def new_game_state():
    return {"coins": 0, "cases_opened": 0, "inventory": []}


def get_state(user):
    key = str(user["id"])
    if key not in GAME_DB:
        GAME_DB[key] = new_game_state()
    return GAME_DB[key]


def public_state(state, user):
    return {"coins": state["coins"], "cases_opened": state["cases_opened"], "inventory": state["inventory"], "user": user_public(user)}


# ======================================================================
# API: АВТОРИЗАЦИЯ И ПРОФИЛЬ
# ======================================================================

@app.route("/api/register", methods=["POST"])
def api_register():
    data = request.get_json(silent=True) or {}
    username, password = str(data.get("username", "")).strip(), str(data.get("password", ""))
    if not valid_username(username):
        return jsonify({"error": "invalid_username"}), 400
    if len(password) < 4 or len(password) > 128:
        return jsonify({"error": "invalid_password"}), 400
    # Для локальной демо-сборки роль закреплена за ником, который назвал пользователь.
    is_admin = int(username.casefold() == "owner")
    try:
        with db_connection() as conn:
            cursor = conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, ?)", (username, generate_password_hash(password), is_admin))
            user_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        return jsonify({"error": "username_taken"}), 409
    session.clear()
    session["user_id"] = user_id
    user = get_user(user_id)
    return jsonify(public_state(get_state(user), user)), 201


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(silent=True) or {}
    username, password = str(data.get("username", "")).strip(), str(data.get("password", ""))
    with db_connection() as conn:
        user = conn.execute("SELECT id, username, password_hash, is_admin, is_banned, avatar_path FROM users WHERE username = ?", (username,)).fetchone()
    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "invalid_credentials"}), 401
    if user["is_banned"]:
        return jsonify({"error": "banned"}), 403
    session.clear()
    session["user_id"] = user["id"]
    return jsonify(public_state(get_state(user), user))


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/avatar", methods=["POST"])
@login_required
def api_avatar(user):
    file = request.files.get("avatar")
    if not file or not file.filename:
        return jsonify({"error": "avatar_missing"}), 400
    extension = secure_filename(file.filename).rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if (
        extension not in ALLOWED_AVATAR_EXTENSIONS
        or (file.mimetype and not file.mimetype.startswith("image/"))
        or not looks_like_image(file, extension)
    ):
        return jsonify({"error": "avatar_format"}), 400
    filename = f"{uuid.uuid4().hex}.{extension}"
    file.save(UPLOAD_DIR / filename)
    avatar_path = f"/static/uploads/{filename}"
    with db_connection() as conn:
        conn.execute("UPDATE users SET avatar_path = ? WHERE id = ?", (avatar_path, user["id"]))
    updated_user = get_user(user["id"])
    return jsonify(public_state(get_state(updated_user), updated_user))


# ======================================================================
# API: ИГРА
# ======================================================================

@app.route("/api/state")
@login_required
def api_state(user):
    return jsonify(public_state(get_state(user), user))


@app.route("/api/open_case/<case_id>", methods=["POST"])
@login_required
def api_open_case(user, case_id):
    state = get_state(user)
    case = next((case for case in CASES if case["id"] == case_id), None)
    if not case:
        return jsonify({"error": "not_found"}), 404
    if state["coins"] < case["price"]:
        return jsonify({"error": "insufficient_funds"}), 400
    state["coins"] -= case["price"]
    won = make_instance(weighted_random_item(case["min_value"], case["max_value"]))
    state["inventory"].append(won)
    state["cases_opened"] += 1
    return jsonify({**public_state(state, user), "won": won})


@app.route("/api/upgrade", methods=["POST"])
@login_required
def api_upgrade(user):
    state, data = get_state(user), request.get_json(silent=True) or {}
    instance_id = data.get("instance_id")
    input_item = next((item for item in state["inventory"] if item["instance_id"] == instance_id), None)
    if not input_item:
        return jsonify({"error": "item_not_found"}), 400
    target_item = item_by_id(data.get("target_id"))
    if not target_item:
        return jsonify({"error": "target_required"}), 400
    if target_item["value"] <= input_item["value"]:
        return jsonify({"error": "target_not_higher"}), 400
    # Вероятность считается только на сервере из цены выбранной цели.
    # Шанс может доходить максимум до 75% (для близких по цене предметов),
    # а для больших скачков в цене — падать вплоть до 2%, чтобы апгрейд
    # оставался осмысленным риском, а не одинаковым числом для всех целей.
    chance = max(2.0, min(75.0, input_item["value"] / target_item["value"] * 100.0))
    success = random.uniform(0, 100) < chance
    state["inventory"] = [item for item in state["inventory"] if item["instance_id"] != instance_id]
    if success:
        result_item = make_instance(target_item)
        state["inventory"].append(result_item)
    else:
        result_item = input_item
    return jsonify({**public_state(state, user), "success": success, "item": result_item, "chance": chance})


@app.route("/api/sell", methods=["POST"])
@login_required
def api_sell(user):
    """Продать ровно один предмет из инвентаря по серверной цене."""
    state, data = get_state(user), request.get_json(silent=True) or {}
    instance_id = str(data.get("instance_id", ""))
    item = next((entry for entry in state["inventory"] if entry["instance_id"] == instance_id), None)
    if not item:
        return jsonify({"error": "item_not_found"}), 400
    earned = int(item.get("sell_value", max(1, round(item["value"] * 1.0))))
    state["inventory"] = [entry for entry in state["inventory"] if entry["instance_id"] != instance_id]
    state["coins"] += earned
    return jsonify({**public_state(state, user), "sold": item, "earned": earned})


@app.route("/api/sell_all", methods=["POST"])
@login_required
def api_sell_all(user):
    """Продать весь инвентарь одним действием по серверным ценам."""
    state = get_state(user)
    inventory = state["inventory"]
    if not inventory:
        return jsonify({"error": "inventory_empty"}), 400
    earned = sum(int(item.get("sell_value", max(1, round(item["value"] * 1.0)))) for item in inventory)
    sold_count = len(inventory)
    state["inventory"] = []
    state["coins"] += earned
    return jsonify({**public_state(state, user), "earned": earned, "sold_count": sold_count})


@app.route("/api/profiles")
@login_required
def api_profiles(user):
    """Публичная витрина профилей без паролей и других приватных данных."""
    with db_connection() as conn:
        rows = conn.execute(
            "SELECT id, username, is_admin, is_banned, avatar_path FROM users WHERE is_banned = 0 ORDER BY username COLLATE NOCASE"
        ).fetchall()
    profiles = []
    for row in rows:
        state = GAME_DB.get(str(row["id"]), {"cases_opened": 0, "inventory": []})
        inventory = state["inventory"]
        top_item = max(inventory, key=lambda item: item["value"], default=None)
        profiles.append({
            **user_public(row), "cases_opened": state["cases_opened"], "items": len(inventory),
            "total": sum(item["value"] for item in inventory), "top_item": top_item,
        })
    return jsonify({"profiles": profiles})


# ======================================================================
# API: АДМИНИСТРАТОР
# ======================================================================

@app.route("/api/admin/users")
@admin_required
def api_admin_users(user):
    with db_connection() as conn:
        rows = conn.execute("SELECT id, username, is_admin, is_banned FROM users ORDER BY username COLLATE NOCASE").fetchall()
    users = []
    for row in rows:
        state = GAME_DB.get(str(row["id"]), {"coins": 0, "inventory": []})
        users.append({"id": row["id"], "username": row["username"], "is_admin": bool(row["is_admin"]), "is_banned": bool(row["is_banned"]), "coins": state["coins"], "items": len(state["inventory"])})
    return jsonify({"users": users})


@app.route("/api/admin/action", methods=["POST"])
@admin_required
def api_admin_action(admin):
    data, action = request.get_json(silent=True) or {}, None
    action = data.get("action")
    try:
        target_id = int(data.get("target_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "target_required"}), 400

    # Единственное действие, которое админ может применить к самому себе, —
    # начисление монет себе. Всё остальное (списание, выдача предметов, бан)
    # по-прежнему запрещено для собственного аккаунта.
    if action == "self_coins":
        if target_id != admin["id"]:
            return jsonify({"error": "invalid_target"}), 400
        target = admin
    elif target_id == admin["id"]:
        return jsonify({"error": "self_action_forbidden"}), 400
    else:
        target = get_user(target_id)
        if not target:
            return jsonify({"error": "user_not_found"}), 404

    if action == "self_coins":
        try:
            amount = int(data.get("amount"))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid_amount"}), 400
        if not 1 <= amount <= 1_000_000:
            return jsonify({"error": "invalid_amount"}), 400
        get_state(target)["coins"] += amount
        message = f"Начислено себе {amount} M"
    elif action == "coins":
        try:
            amount = int(data.get("amount"))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid_amount"}), 400
        if not 1 <= amount <= 1_000_000:
            return jsonify({"error": "invalid_amount"}), 400
        get_state(target)["coins"] += amount
        message = f"Начислено {amount} M"
    elif action == "take_coins":
        try:
            amount = int(data.get("amount"))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid_amount"}), 400
        if not 1 <= amount <= 1_000_000:
            return jsonify({"error": "invalid_amount"}), 400
        target_state = get_state(target)
        taken = min(amount, target_state["coins"])
        target_state["coins"] -= taken
        message = f"Списано {taken} M"
    elif action == "take_all_coins":
        # Забирает весь баланс сразу: лимит в 1 000 000 M за действие здесь не применяется.
        target_state = get_state(target)
        taken = target_state["coins"]
        target_state["coins"] = 0
        message = f"Списан весь баланс: {taken} M"
    elif action == "character":
        item = item_by_id(data.get("item_id"))
        if not item:
            return jsonify({"error": "item_not_found"}), 400
        get_state(target)["inventory"].append(make_instance(item))
        message = f"Выдан предмет «{item['name']}»"
    elif action == "ban":
        banned = bool(data.get("banned", True))
        with db_connection() as conn:
            conn.execute("UPDATE users SET is_banned = ? WHERE id = ?", (int(banned), target_id))
        message = "Пользователь заблокирован" if banned else "Пользователь разблокирован"
    else:
        return jsonify({"error": "unknown_action"}), 400
    return jsonify({"ok": True, "message": message})


# ======================================================================
# СТРАНИЦА
# ======================================================================

@app.route("/")
def index():
    return render_template("index.html", cases=CASES, rarity=RARITY, item_pool=ITEM_POOL)


init_database()

if __name__ == "__main__":
    app.run(debug=True)
