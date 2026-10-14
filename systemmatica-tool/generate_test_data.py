"""Генератор тестовой выгрузки заказов кухонь (с намеренно грязными данными).

Запуск: python generate_test_data.py  ->  data/orders_export.csv
Данные вымышленные, seed фиксирован — выгрузка воспроизводима.
"""
import csv
import random
from datetime import date, timedelta
from pathlib import Path

random.seed(42)
OUT = Path(__file__).parent / "data" / "orders_export.csv"
TODAY = date(2026, 10, 14)

CHANNELS = ["Шоурум 1", "Шоурум 2", "Шоурум 3",
            "Дилер Казань", "Дилер Самара", "Дилер Уфа", "Дилер Пермь", "Дилер Тюмень"]
MANAGERS = {"Шоурум 1": ["Иванова А.", "Петров С."], "Шоурум 2": ["Сидорова Е.", "Кузнецов Д."],
            "Шоурум 3": ["Смирнова О."], "Дилер": ["Орлов В.", "Волкова Н."]}
# модель: (база цены, доля материалов в цене)
MODELS = {"Модерн": (380_000, 0.42), "Классик": (520_000, 0.45), "Лофт": (450_000, 0.43),
          "Сканди": (310_000, 0.40), "Премиум Арт": (900_000, 0.47)}
# стадия: (плановая длительность, дней)
STAGES = [("замер", 5), ("дизайн", 10), ("производство", 30), ("монтаж", 5)]


def fmt_date(d, style):
    return {"iso": d.strftime("%Y-%m-%d"), "ru": d.strftime("%d.%m.%Y"),
            "short": d.strftime("%d.%m.%y"), "slash": d.strftime("%d/%m/%Y")}[style]


def fmt_money(x, style):
    if style == "space":
        return f"{x:,.0f}".replace(",", " ")
    if style == "comma":
        return f"{x:.2f}".replace(".", ",")
    return f"{x:.0f}"


def make_order(n):
    channel = random.choice(CHANNELS)
    is_dealer = channel.startswith("Дилер")
    manager = random.choice(MANAGERS["Дилер" if is_dealer else channel])
    model = random.choice(list(MODELS))
    base, mat_share = MODELS[model]
    price = round(base * random.uniform(0.85, 1.3), -3)
    discount = random.choice([0, 0, 3, 5, 7, 10]) if not is_dealer else random.choice([5, 10, 12, 15])
    commission = 0 if not is_dealer else random.choice([12, 15, 18, 20])
    materials = price * mat_share * random.uniform(0.9, 1.1)
    if is_dealer and random.random() < 0.3:  # убыточный дилерский заказ
        discount, commission = 15, 22
        materials = price * random.uniform(0.62, 0.72)
    zamer, design = random.choice([3000, 3500, 4000]), random.choice([8000, 10000, 12000])
    montage = round(price * random.uniform(0.06, 0.09), -2)

    start = date(2026, 2, 1) + timedelta(days=random.randint(0, 200))
    row = {"номер_заказа": f"К-{2600 + n}", "дата_заказа": start, "канал": channel,
           "менеджер": manager, "модель": model, "цена_продажи": price, "скидка_проц": discount,
           "комиссия_дилера_проц": commission, "себестоимость_материалов": round(materials, 2),
           "ставка_замера": zamer, "ставка_дизайна": design, "ставка_монтажа": montage}
    plan = fact = start
    for stage, days in STAGES:
        plan = plan + timedelta(days=days)
        # производство у дилерских и у «Премиум Арт» срывается чаще
        risk = 0.25 + (0.2 if stage == "производство" else 0) + (0.1 if model == "Премиум Арт" else 0)
        delay = random.randint(1, 15) if random.random() < risk else random.randint(-2, 0)
        fact_d = fact + timedelta(days=days + delay)
        row[f"{stage}_план"] = plan
        row[f"{stage}_факт"] = fact_d if fact_d <= TODAY else None  # ещё не закончено
        fact = fact_d
    if row["монтаж_факт"] and random.random() < 0.15:
        row["рекламация"] = "да"
        row["стоимость_рекламации"] = round(random.uniform(5_000, 60_000), -2)
    else:
        row["рекламация"], row["стоимость_рекламации"] = "нет", 0
    return row


def render(row):
    """Превращает чистую строку в «как из CRM»: разные форматы дат и чисел."""
    out = {}
    date_style = random.choice(["iso", "ru", "ru", "short", "slash"])  # формат «таблицы-источника»
    for k, v in row.items():
        if isinstance(v, date):
            out[k] = fmt_date(v, date_style)
        elif v is None:
            out[k] = ""
        elif k in ("цена_продажи", "себестоимость_материалов", "ставка_монтажа"):
            out[k] = fmt_money(v, random.choice(["plain", "space", "comma"]))
        else:
            out[k] = str(v)
    out["рекламация"] = random.choice({"да": ["да", "Да", "ДА"], "нет": ["нет", "Нет", ""]}[row["рекламация"]])
    return out


rows = [render(make_order(i)) for i in range(1, 61)]

# --- намеренная порча данных ---
rows[4]["себестоимость_материалов"] = ""            # пустая себестоимость
rows[17]["себестоимость_материалов"] = "н/д"        # битое значение
rows[9]["цена_продажи"] = "уточнить"                 # битая цена
rows[22]["скидка_проц"] = "150"                      # скидка вне диапазона
rows[30]["дизайн_факт"] = "31.02.2026"               # несуществующая дата
rows[41]["производство_план"] = "2026-13-05"         # несуществующий месяц
rows[12]["ставка_монтажа"] = ""                      # пустая ставка
rows[35]["менеджер"] = ""                            # нет менеджера
rows[50]["канал"] = "дилер  казань"                  # канал в другом регистре/пробелах
rows[27]["рекламация"] = "да"; rows[27]["стоимость_рекламации"] = ""  # рекламация без суммы
# дубли: два точных, один с расхождением в цене (поправили в одной из таблиц)
rows.append(dict(rows[7]))
rows.append(dict(rows[19]))
dup = dict(rows[33]); dup["цена_продажи"] = "999000"; rows.append(dup)
random.shuffle(rows)

OUT.parent.mkdir(exist_ok=True)
with OUT.open("w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]), delimiter=";")
    w.writeheader()
    w.writerows(rows)
print(f"Записано {len(rows)} строк в {OUT}")
