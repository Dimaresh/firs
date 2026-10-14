"""Маржинальность заказов и контроль сроков по стадиям из выгрузки CRM.

Запуск:  python margin_tool.py data/orders_export.csv --out output --today 2026-10-14
Результат: output/report.xlsx (листы) и output/report.html (сводка для собственника).
"""
import argparse
import html
import re
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

STAGES = ["замер", "дизайн", "производство", "монтаж"]
MONEY_COLS = ["цена_продажи", "себестоимость_материалов", "ставка_замера",
              "ставка_дизайна", "ставка_монтажа", "стоимость_рекламации"]
PCT_COLS = ["скидка_проц", "комиссия_дилера_проц"]
RATE_COLS = ["ставка_замера", "ставка_дизайна", "ставка_монтажа"]
DATE_COLS = ["дата_заказа"] + [f"{s}_{k}" for s in STAGES for k in ("план", "факт")]
DATE_FORMATS = ["%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y", "%d/%m/%Y"]


# ---------- разбор значений ----------

def parse_number(value):
    """'1 250 000' / '206086,57' / '448000' -> float; пусто или текст -> NaN."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return np.nan
    s = str(value).replace(" ", "").replace(" ", "").replace(",", ".").strip()
    if not s:
        return np.nan
    try:
        return float(s)
    except ValueError:
        return np.nan


def parse_date(value):
    """Разбирает дату в одном из форматов выгрузки; несуществующая дата -> NaT."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return pd.NaT
    s = str(value).strip()
    if not s:
        return pd.NaT
    for fmt in DATE_FORMATS:
        try:
            return pd.Timestamp(datetime.strptime(s, fmt))
        except ValueError:
            continue
    return pd.NaT


def is_blank(value):
    return value is None or (isinstance(value, float) and np.isnan(value)) or str(value).strip() == ""


def normalize_channel(value):
    s = " ".join(str(value).split()).capitalize()
    return re.sub(r"(Дилер|Шоурум) ?(.*)", lambda m: f"{m[1]} {m[2].title()}".strip(), s)


# ---------- загрузка и очистка ----------

def load_raw(path):
    raw = pd.read_csv(path, sep=";", dtype=str, keep_default_na=False, encoding="utf-8-sig")
    raw.insert(0, "строка_csv", raw.index + 2)  # +1 заголовок, +1 нумерация с единицы
    return raw


def clean(raw):
    """Возвращает (очищенные заказы, список проблем в данных)."""
    issues = []

    def issue(row, order, field, problem, action):
        issues.append({"строка_csv": row, "номер_заказа": order, "поле": field,
                       "проблема": problem, "что сделано": action})

    # 1. Дубли по номеру заказа
    data_cols = [c for c in raw.columns if c != "строка_csv"]
    keep = []
    for order, grp in raw.groupby("номер_заказа", sort=False):
        first = grp.iloc[0]
        keep.append(first.name)
        for _, dup in grp.iloc[1:].iterrows():
            diff = [c for c in data_cols if dup[c] != first[c]]
            if diff:
                issue(dup["строка_csv"], order, ", ".join(diff),
                      f"дубль строки {first['строка_csv']} с расхождением: "
                      + "; ".join(f"{c}: {first[c]!r} vs {dup[c]!r}" for c in diff),
                      f"оставлена строка {first['строка_csv']}, проверить вручную")
            else:
                issue(dup["строка_csv"], order, "все", f"полный дубль строки {first['строка_csv']}", "удалена")
    df = raw.loc[sorted(keep)].copy()

    # 2. Числа
    for col in MONEY_COLS + PCT_COLS:
        parsed = df[col].map(parse_number)
        for idx in df.index[parsed.isna() & ~df[col].map(is_blank)]:
            issue(df.at[idx, "строка_csv"], df.at[idx, "номер_заказа"], col,
                  f"не число: {df.at[idx, col]!r}", "считается пустым")
        df[col] = parsed

    # 3. Даты
    for col in DATE_COLS:
        parsed = df[col].map(parse_date)
        for idx in df.index[parsed.isna() & ~df[col].map(is_blank)]:
            issue(df.at[idx, "строка_csv"], df.at[idx, "номер_заказа"], col,
                  f"неверная дата: {df.at[idx, col]!r}", "дата не учитывается")
        df[col] = pd.to_datetime(parsed)

    # 4. Справочные поля
    df["канал"] = df["канал"].map(normalize_channel)
    df["тип_канала"] = np.where(df["канал"].str.startswith("Дилер"), "Дилер", "Шоурум")
    for idx in df.index[df["менеджер"].str.strip() == ""]:
        issue(df.at[idx, "строка_csv"], df.at[idx, "номер_заказа"], "менеджер", "пусто", "«не указан»")
    df["менеджер"] = df["менеджер"].str.strip().replace("", "не указан")

    # 5. Скидка / комиссия вне 0..100 — расчёт маржи невозможен
    df["ошибка_расчёта"] = ""
    for col in PCT_COLS:
        bad = df[col].notna() & ~df[col].between(0, 100)
        for idx in df.index[bad]:
            issue(df.at[idx, "строка_csv"], df.at[idx, "номер_заказа"], col,
                  f"значение {df.at[idx, col]:g}% вне 0–100", "маржа не считается")
            df.at[idx, "ошибка_расчёта"] = f"{col} вне 0–100"
    df["комиссия_дилера_проц"] = df["комиссия_дилера_проц"].fillna(0)
    df["скидка_проц"] = df["скидка_проц"].fillna(0)

    # 6. Пустые ставки работ -> медиана по модели, с пометкой «оценка»
    df["оценка"] = ""
    for col in RATE_COLS:
        median = df.groupby("модель")[col].transform("median").fillna(df[col].median())
        for idx in df.index[df[col].isna()]:
            issue(df.at[idx, "строка_csv"], df.at[idx, "номер_заказа"], col, "пусто",
                  f"взята медиана по модели {median[idx]:,.0f} ₽".replace(",", " "))
            df.at[idx, "оценка"] = (df.at[idx, "оценка"] + f" {col}").strip()
        df[col] = df[col].fillna(median)

    # 7. Рекламации
    df["рекламация"] = df["рекламация"].str.strip().str.lower().eq("да")
    no_cost = df["рекламация"] & df["стоимость_рекламации"].isna()
    for idx in df.index[no_cost]:
        issue(df.at[idx, "строка_csv"], df.at[idx, "номер_заказа"], "стоимость_рекламации",
              "рекламация есть, сумма не указана", "учтено 0 ₽, уточнить сумму")
    df["стоимость_рекламации"] = df["стоимость_рекламации"].fillna(0)

    # 8. Нет цены или себестоимости — маржу не считаем (ноль дал бы ложную сверхмаржу)
    for col in ("цена_продажи", "себестоимость_материалов"):
        for idx in df.index[df[col].isna()]:
            if not any(i["строка_csv"] == df.at[idx, "строка_csv"] and i["поле"] == col for i in issues):
                issue(df.at[idx, "строка_csv"], df.at[idx, "номер_заказа"], col, "пусто", "маржа не считается")
            df.at[idx, "ошибка_расчёта"] = (df.at[idx, "ошибка_расчёта"] + f" нет {col}").strip()

    issues_df = pd.DataFrame(issues, columns=["строка_csv", "номер_заказа", "поле", "проблема", "что сделано"])
    return df.reset_index(drop=True), issues_df.sort_values("строка_csv", kind="stable").reset_index(drop=True)


# ---------- маржа ----------

def compute_margin(df):
    df = df.copy()
    df["выручка"] = df["цена_продажи"] * (1 - df["скидка_проц"] / 100)
    df["комиссия"] = df["выручка"] * df["комиссия_дилера_проц"] / 100
    df["работы"] = df["ставка_замера"] + df["ставка_дизайна"] + df["ставка_монтажа"]
    df["маржа_руб"] = (df["выручка"] - df["комиссия"] - df["себестоимость_материалов"]
                       - df["работы"] - df["стоимость_рекламации"])
    df["маржа_проц"] = df["маржа_руб"] / df["выручка"] * 100
    bad = df["ошибка_расчёта"] != ""
    df.loc[bad, ["выручка", "комиссия", "маржа_руб", "маржа_проц"]] = np.nan
    df["статус_маржи"] = np.select(
        [bad, df["маржа_руб"] < 0], ["нет данных", "убыток"], "прибыль")
    return df


def margin_by(df, key):
    ok = df[df["статус_маржи"] != "нет данных"]
    g = ok.groupby(key).agg(заказов=("номер_заказа", "count"), выручка=("выручка", "sum"),
                            маржа_руб=("маржа_руб", "sum"),
                            убыточных=("маржа_руб", lambda s: int((s < 0).sum())))
    g["маржа_проц"] = g["маржа_руб"] / g["выручка"] * 100
    g["без_данных"] = df[df["статус_маржи"] == "нет данных"].groupby(key).size()
    g["без_данных"] = g["без_данных"].fillna(0).astype(int)
    return g.sort_values("маржа_проц").reset_index()


# ---------- сроки ----------

def compute_deadlines(df, today):
    """Длинная таблица заказ × стадия: статус, задержка, где задержка возникла."""
    today = pd.Timestamp(today)
    rows = []
    for _, r in df.iterrows():
        prev_delay = 0
        for i, stage in enumerate(STAGES):
            plan, fact = r[f"{stage}_план"], r[f"{stage}_факт"]
            later_done = any(pd.notna(r[f"{s}_факт"]) for s in STAGES[i + 1:])
            if pd.isna(plan):
                status, delay = "нет плана", np.nan
            elif pd.notna(fact):
                delay = (fact - plan).days
                status = "просрочка" if delay > 0 else "в срок"
            elif later_done:
                # следующая стадия уже закрыта — значит, факт этой просто не внесён (или дата битая)
                status, delay = "нет факта", np.nan
            elif plan < today:
                delay = (today - plan).days
                status = "висит (просрочено)"
            else:
                status, delay = "в работе", np.nan
            # прирост задержки на этой стадии: показывает, где срыв возник, а не унаследован
            added = np.nan if np.isnan(delay) else max(0, delay - max(0, prev_delay))
            rows.append({"строка_csv": r["строка_csv"], "номер_заказа": r["номер_заказа"],
                         "канал": r["канал"], "модель": r["модель"], "стадия": stage,
                         "план": plan, "факт": fact, "статус": status,
                         "задержка_дн": delay, "прирост_задержки_дн": added})
            if not np.isnan(delay):
                prev_delay = delay
    return pd.DataFrame(rows)


def deadline_summary(dl):
    dl = dl.assign(просрочено=dl["статус"].isin(["просрочка", "висит (просрочено)"]),
                   срыв_возник=dl["прирост_задержки_дн"] > 0)
    known = dl[dl["статус"].isin(["просрочка", "в срок", "висит (просрочено)"])]
    g = known.groupby("стадия", sort=False).agg(
        оценено_заказов=("номер_заказа", "count"), просрочено=("просрочено", "sum"),
        срыв_возник_здесь=("срыв_возник", "sum"),
        висит=("статус", lambda s: int((s == "висит (просрочено)").sum())))
    g["доля_просрочки_проц"] = g["просрочено"] / g["оценено_заказов"] * 100
    late = known[known["просрочено"]]
    g["средняя_задержка_дн"] = late.groupby("стадия")["задержка_дн"].mean()
    g["средний_прирост_дн"] = known[known["срыв_возник"]].groupby("стадия")["прирост_задержки_дн"].mean()
    return g.reindex(STAGES).reset_index()


def orders_late(dl):
    """Заказ считается сорванным, если просрочен монтаж (или висит любая стадия)."""
    late = dl[dl["статус"].isin(["просрочка", "висит (просрочено)"])]
    return late.groupby("номер_заказа")["задержка_дн"].max()


# ---------- вывод ----------

def build_report(csv_path, today):
    raw = load_raw(csv_path)
    df, issues = clean(raw)
    df = compute_margin(df)
    dl = compute_deadlines(df, today)
    late = orders_late(dl)
    df["макс_задержка_дн"] = df["номер_заказа"].map(late)
    final = dl[dl["стадия"] == "монтаж"].set_index("номер_заказа")["статус"]
    df["статус_сроков"] = df["номер_заказа"].map(final)
    return {
        "raw_rows": len(raw), "orders": df, "issues": issues, "deadlines": dl,
        "loss": df[df["статус_маржи"] == "убыток"].sort_values("маржа_руб"),
        "by_channel": margin_by(df, "канал"), "by_channel_type": margin_by(df, "тип_канала"),
        "by_manager": margin_by(df, "менеджер"), "by_model": margin_by(df, "модель"),
        "stages": deadline_summary(dl),
        "late_by_channel": _late_share(dl, "канал"), "late_by_model": _late_share(dl, "модель"),
    }


def _late_share(dl, key):
    d = dl[dl["статус"] != "в работе"].assign(
        p=dl["статус"].isin(["просрочка", "висит (просрочено)"]))
    per_order = d.groupby(["номер_заказа", key])["p"].any().reset_index()
    g = per_order.groupby(key)["p"].agg(заказов="count", с_просрочкой="sum")
    g["доля_проц"] = g["с_просрочкой"] / g["заказов"] * 100
    return g.sort_values("доля_проц", ascending=False).reset_index()


ORDER_COLS = ["строка_csv", "номер_заказа", "канал", "менеджер", "модель", "цена_продажи",
              "скидка_проц", "выручка", "комиссия_дилера_проц", "комиссия", "себестоимость_материалов",
              "работы", "стоимость_рекламации", "маржа_руб", "маржа_проц", "статус_маржи",
              "ошибка_расчёта", "оценка", "статус_сроков", "макс_задержка_дн"]


def write_excel(rep, path):
    sheets = {
        "Заказы": rep["orders"][ORDER_COLS].sort_values("маржа_руб"),
        "Убыточные": rep["loss"][ORDER_COLS],
        "По каналам": rep["by_channel"], "По менеджерам": rep["by_manager"],
        "По моделям": rep["by_model"], "Сроки по стадиям": rep["stages"],
        "Сроки детально": rep["deadlines"], "Проблемы данных": rep["issues"],
    }
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        for name, data in sheets.items():
            data.to_excel(xw, sheet_name=name, index=False)
            ws = xw.sheets[name]
            ws.freeze_panes = "A2"
            for i, col in enumerate(data.columns, 1):
                letter = ws.cell(1, i).column_letter
                width = max([len(str(col))] + [len(str(v)) for v in data[col].head(200)])
                ws.column_dimensions[letter].width = min(max(10, width + 2), 60)
                fmt = ("0.0" if col.endswith("проц") else "dd.mm.yyyy" if col in ("план", "факт")
                       else "# ##0" if data[col].dtype.kind == "f" else None)
                if fmt:
                    for cell in ws[letter][1:]:
                        cell.number_format = fmt


def _rub(x):
    return "—" if pd.isna(x) else f"{x:,.0f}".replace(",", " ") + " ₽"


def _pct(x):
    return "—" if pd.isna(x) else f"{x:.1f}%"


def _table(df, cols, fmt):
    head = "".join(f"<th>{html.escape(c)}</th>" for c in cols)
    body = []
    for _, r in df.iterrows():
        cells = []
        for c in cols:
            v = r[c]
            text = fmt.get(c, lambda x: html.escape(str(x)))(v)
            neg = isinstance(v, (int, float)) and not pd.isna(v) and v < 0 and c.startswith("маржа")
            cells.append(f'<td class="{"neg" if neg else ""}">{text}</td>')
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><tr>{head}</tr>{''.join(body)}</table>"


def write_html(rep, path, today):
    o = rep["orders"]
    ok = o[o["статус_маржи"] != "нет данных"]
    total_rev, total_m = ok["выручка"].sum(), ok["маржа_руб"].sum()
    loss = rep["loss"]
    st = rep["stages"]
    late_orders = o["макс_задержка_дн"].notna().sum()
    worst_origin = st.sort_values("срыв_возник_здесь", ascending=False).iloc[0]
    money = {c: _rub for c in ("выручка", "маржа_руб", "цена_продажи")}
    money.update({c: _pct for c in ("маржа_проц", "доля_проц", "доля_просрочки_проц")})
    money.update({c: (lambda x: "—" if pd.isna(x) else f"{x:.1f}")
                  for c in ("средняя_задержка_дн", "средний_прирост_дн")})
    kpi = [("Заказов в выгрузке", f"{rep['raw_rows']} строк → {len(o)} заказов"),
           ("Выручка (после скидок)", _rub(total_rev)),
           ("Маржа по заказам", f"{_rub(total_m)} · {_pct(total_m / total_rev * 100)}"),
           ("Убыточных заказов", f"{len(loss)} на {_rub(loss['маржа_руб'].sum())}"),
           ("Заказов с просрочкой", f"{late_orders} из {len(o)} ({late_orders / len(o) * 100:.0f}%)"),
           ("Проблем в данных", f"{len(rep['issues'])} (без маржи: {(o['статус_маржи'] == 'нет данных').sum()} зак.)")]
    tiles = "".join(f'<div class="kpi"><div class="l">{k}</div><div class="v">{v}</div></div>' for k, v in kpi)
    page = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Маржа и сроки заказов</title>
<style>
body{{font:15px/1.45 system-ui,sans-serif;margin:0 auto;max-width:1000px;padding:16px;color:#1d1d1f;background:#fff}}
h1{{font-size:22px}} h2{{font-size:18px;margin-top:32px}} .muted{{color:#666}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px}}
.kpi{{border:1px solid #ddd;border-radius:8px;padding:10px}} .kpi .l{{color:#666;font-size:13px}}
.kpi .v{{font-size:18px;font-weight:600}}
table{{border-collapse:collapse;width:100%;font-size:14px;display:block;overflow-x:auto}}
th,td{{border-bottom:1px solid #eee;padding:5px 8px;text-align:left;white-space:nowrap}}
th{{background:#f6f6f6}} td.neg{{color:#c0392b;font-weight:600}}
.note{{background:#fff8e1;border-left:4px solid #f5b400;padding:8px 12px}}
</style></head><body>
<h1>Маржа и сроки заказов</h1>
<p class="muted">Отчёт на {pd.Timestamp(today):%d.%m.%Y}. Маржа = выручка после скидки − комиссия дилера −
материалы и фурнитура − замер, дизайн, монтаж − рекламации. Накладные фабрики не распределены.</p>
<div class="kpis">{tiles}</div>
<h2>Главное</h2><ul>
<li>Дилерский канал: маржа {_pct(rep['by_channel_type'].set_index('тип_канала').loc['Дилер', 'маржа_проц'])},
шоурумы: {_pct(rep['by_channel_type'].set_index('тип_канала').loc['Шоурум', 'маржа_проц'])}.
Все убыточные заказы — {', '.join(sorted(loss['тип_канала'].unique())) or '—'}.</li>
<li>Чаще всего срыв срока возникает на стадии «{worst_origin['стадия']}»
({int(worst_origin['срыв_возник_здесь'])} заказов, в среднем +{worst_origin['средний_прирост_дн']:.1f} дн.).</li>
<li>{(o['статус_маржи'] == 'нет данных').sum()} заказов без маржи из-за пустых или битых данных — список на листе «Проблемы данных».</li>
</ul>
<h2>Топ-10 убыточных заказов</h2>
{_table(loss.head(10), ['номер_заказа', 'канал', 'менеджер', 'модель', 'выручка', 'маржа_руб', 'маржа_проц'], money)}
<h2>Маржа по каналам</h2>
{_table(rep['by_channel'], ['канал', 'заказов', 'выручка', 'маржа_руб', 'маржа_проц', 'убыточных'], money)}
<h2>Маржа по моделям</h2>
{_table(rep['by_model'], ['модель', 'заказов', 'выручка', 'маржа_руб', 'маржа_проц', 'убыточных'], money)}
<h2>Маржа по менеджерам</h2>
{_table(rep['by_manager'], ['менеджер', 'заказов', 'выручка', 'маржа_руб', 'маржа_проц', 'убыточных'], money)}
<h2>Сроки по стадиям</h2>
<p class="muted">«Просрочено» — стадия закрыта позже плана или не закрыта, а план прошёл.
«Срыв возник здесь» — задержка выросла именно на этой стадии, а не унаследована от предыдущей.</p>
{_table(st, ['стадия', 'оценено_заказов', 'просрочено', 'доля_просрочки_проц', 'средняя_задержка_дн', 'срыв_возник_здесь', 'средний_прирост_дн', 'висит'], money)}
<h2>Просрочка по каналам</h2>
{_table(rep['late_by_channel'], ['канал', 'заказов', 'с_просрочкой', 'доля_проц'], money)}
<h2>Проблемы в данных</h2>
<p class="note">Номер строки — строка в исходном CSV (с учётом заголовка). Эти записи нужно поправить в CRM/таблицах.</p>
{_table(rep['issues'], ['строка_csv', 'номер_заказа', 'поле', 'проблема', 'что сделано'], {})}
</body></html>"""
    Path(path).write_text(page, encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("csv", nargs="?", default=Path(__file__).parent / "data" / "orders_export.csv")
    ap.add_argument("--out", default=Path(__file__).parent / "output")
    ap.add_argument("--today", default=date.today().isoformat(), help="дата отчёта, ГГГГ-ММ-ДД")
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rep = build_report(args.csv, args.today)
    write_excel(rep, out / "report.xlsx")
    write_html(rep, out / "report.html", args.today)
    o = rep["orders"]
    pd.set_option("display.width", 200)
    print(f"Строк: {rep['raw_rows']}, заказов после очистки: {len(o)}, проблем в данных: {len(rep['issues'])}")
    print("\nТоп-5 убыточных:\n", rep["loss"][["номер_заказа", "канал", "маржа_руб", "маржа_проц"]].head().round(1).to_string(index=False))
    print("\nМаржа по каналам:\n", rep["by_channel"][["канал", "заказов", "маржа_руб", "маржа_проц", "убыточных"]].round(1).to_string(index=False))
    print("\nСроки по стадиям:\n", rep["stages"].round(1).to_string(index=False))
    print(f"\nГотово: {out / 'report.xlsx'}, {out / 'report.html'}")
    return rep


if __name__ == "__main__":
    main()
