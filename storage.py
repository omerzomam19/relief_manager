"""طبقة التخزين: ملفات JSON مع قفل وكتابة آمنة."""
import json, os, tempfile, threading
from datetime import datetime
from werkzeug.security import generate_password_hash

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
FILES = {n: os.path.join(DATA_DIR, n + ".json") for n in ("users", "inventory", "beneficiaries", "distributions")}
lock = threading.RLock()  # يُستخدم أيضاً لحماية عمليات قراءة-تعديل-كتابة


def load_data(name):
    with lock:
        try:
            with open(FILES[name], encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return []


def save_data(name, data):
    with lock:  # كتابة في ملف مؤقت ثم استبدال ذري
        fd, tmp = tempfile.mkstemp(dir=DATA_DIR, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, FILES[name])


def next_id(items):
    return max((i["id"] for i in items), default=0) + 1


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _seed():
    """بيانات تجريبية تُنشأ مرة واحدة عند أول تشغيل فقط."""
    from datetime import timedelta
    inv_rows = [("أرز", "غذاء", "كيس", 150), ("طحين", "غذاء", "كيس", 100), ("زيت طبخ", "غذاء", "عبوة", 60),
                ("سكر", "غذاء", "كيس", 8), ("بطانيات", "إيواء", "قطعة", 80), ("خيام", "إيواء", "خيمة", 12),
                ("حليب أطفال", "رعاية الأطفال", "علبة", 40), ("حقائب نظافة", "صحة", "حقيبة", 50),
                ("أدوية أساسية", "صحة", "صندوق", 6), ("مياه شرب", "مياه", "كرتون", 200)]
    ben_rows = [("أحمد محمد العلي", "مخيم الأمل - القطاع أ", "0501234567", 6, "أسرة نازحة، طفل رضيع"),
                ("فاطمة يوسف حسن", "حي الصفا - شارع 12", "0509876543", 4, "أرملة تعيل أسرتها"),
                ("خالد عبدالله سالم", "مخيم الأمل - القطاع ب", "0553334455", 8, ""),
                ("مريم إبراهيم نور", "حي المروة - بلوك 3", "0561122334", 5, "أحد الأفراد من ذوي الاحتياجات الخاصة"),
                ("عمر حسين الأحمد", "مخيم الرجاء - خيمة 41", "0544455667", 3, ""),
                ("سلمى ناصر الدين", "حي الصفا - شارع 5", "0597788990", 7, "أسرة كبيرة"),
                ("يوسف علي خليل", "مخيم الرجاء - خيمة 18", "0502233445", 2, "كبير سن يعيش وحيداً"),
                ("هدى محمود صالح", "حي المروة - بلوك 9", "0588899001", 5, "")]
    # (مستفيد, مادة, كمية, قبل كم يوم)
    dist_rows = [(1, 1, 10, 6), (1, 3, 4, 6), (2, 2, 8, 6), (3, 1, 15, 5), (3, 6, 2, 5), (4, 7, 6, 4),
                 (5, 5, 6, 4), (6, 1, 12, 3), (6, 4, 3, 3), (7, 8, 2, 2), (8, 9, 6, 1), (2, 6, 2, 1),
                 (4, 10, 20, 1), (1, 6, 2, 0), (5, 2, 5, 0)]
    stamp = datetime.now()
    inv = [dict(id=i, name=n, category=c, quantity=q, unit=u, created_at=now()) for i, (n, c, u, q) in enumerate(inv_rows, 1)]
    ben = [dict(id=i, name=n, address=a, phone=p, family_size=f, notes=nt, created_at=now()) for i, (n, a, p, f, nt) in enumerate(ben_rows, 1)]
    dist = []
    for k, (b, it, q, ago) in enumerate(dist_rows, 1):
        inv[it - 1]["quantity"] -= q  # خصم الكمية الموزعة من المخزون
        d = stamp - timedelta(days=ago, hours=k % 5)
        dist.append(dict(id=k, beneficiary_id=b, inventory_id=it, quantity=q, date=d.strftime("%Y-%m-%d %H:%M"), created_by="admin"))
    save_data("inventory", inv); save_data("beneficiaries", ben); save_data("distributions", dist)


def init_storage():
    os.makedirs(DATA_DIR, exist_ok=True)
    fresh = not os.path.exists(FILES["users"])
    for n, p in FILES.items():
        if not os.path.exists(p):
            save_data(n, [])
    if not load_data("users"):
        save_data("users", [
            dict(id=1, username="admin", password_hash=generate_password_hash("admin123"), role="admin", created_at=now()),
            dict(id=2, username="staff", password_hash=generate_password_hash("staff123"), role="staff", created_at=now())])
    if fresh:
        _seed()
