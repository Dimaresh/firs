"""Автотесты: ручная сверка маржи и граничные случаи грязных данных.

Запуск: python -m pytest tests -q
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import margin_tool as mt  # noqa: E402

HEADER = ("номер_заказа;дата_заказа;канал;менеджер;модель;цена_продажи;скидка_проц;"
          "комиссия_дилера_проц;себестоимость_материалов;ставка_замера;ставка_дизайна;ставка_монтажа;"
          "замер_план;замер_факт;дизайн_план;дизайн_факт;производство_план;производство_факт;"
          "монтаж_план;монтаж_факт;рекламация;стоимость_рекламации")
DATES = "01.03.2026;06.03.2026;06.03.2026;16.03.2026;16.03.2026;15.04.2026;15.04.2026;20.04.2026;20.04.2026"


def row(num="К-1", price="500000", disc="0", comm="0", mat="200000", montage="30000",
        recl="нет", recl_cost="0", dates=DATES, channel="Шоурум 1", manager="Иванова А.", model="Модерн"):
    return (f"{num};{dates.split(';')[0]};{channel};{manager};{model};{price};{disc};{comm};{mat};"
            f"3000;10000;{montage};{';'.join(dates.split(';')[1:])};{recl};{recl_cost}")


def run(tmp_path, *rows, today="2026-10-14"):
    p = tmp_path / "x.csv"
    p.write_text("\n".join([HEADER, *rows]) + "\n", encoding="utf-8")
    return mt.build_report(p, today)


def order(rep, num):
    return rep["orders"].set_index("номер_заказа").loc[num]


# ---------- ручная сверка на реальной тестовой выгрузке ----------
# Расчёт вручную (см. README):
#   К-2620: 448000×0.90=403200; комиссия 20% = 80640;
#           403200−80640−206086.57−3500−10000−38800 = 64173.43 (15.92%)
#   К-2628: 636000×0.85=540600; комиссия 22% = 118932;
#           540600−118932−423875−4000−12000−45400−0 = −63607.00 (−11.77%)
#   К-2657: 398000×0.95=378100; 378100−181240−3500−12000−29000 = 152360.00 (40.30%)
#   К-2633: 588000×0.97=570360; 570360−273089.86−3000−8000−38300 = 247970.14 (43.48%)
MANUAL = {"К-2620": (64173.43, 15.92), "К-2628": (-63607.00, -11.77),
          "К-2657": (152360.00, 40.30), "К-2633": (247970.14, 43.48)}


@pytest.fixture(scope="module")
def real_report():
    return mt.build_report(ROOT / "data" / "orders_export.csv", "2026-10-14")


@pytest.mark.parametrize("num", MANUAL)
def test_manual_margin_matches(real_report, num):
    rub, pct = MANUAL[num]
    o = order(real_report, num)
    assert o["маржа_руб"] == pytest.approx(rub, abs=0.01)
    assert o["маржа_проц"] == pytest.approx(pct, abs=0.01)


def test_real_export_counts(real_report):
    assert real_report["raw_rows"] == 63
    assert len(real_report["orders"]) == 60
    assert real_report["orders"]["канал"].nunique() == 8  # «дилер  казань» склеен с «Дилер Казань»


# ---------- граничные случаи ----------

def test_empty_cost_gives_no_margin_not_zero_cost(tmp_path):
    rep = run(tmp_path, row(mat=""))
    o = order(rep, "К-1")
    assert np.isnan(o["маржа_руб"]) and o["статус_маржи"] == "нет данных"
    assert (rep["issues"]["поле"] == "себестоимость_материалов").sum() == 1


def test_text_in_cost_is_reported_once(tmp_path):
    rep = run(tmp_path, row(mat="н/д"))
    iss = rep["issues"][rep["issues"]["поле"] == "себестоимость_материалов"]
    assert len(iss) == 1 and "н/д" in iss.iloc[0]["проблема"]
    assert order(rep, "К-1")["статус_маржи"] == "нет данных"


def test_exact_duplicate_removed(tmp_path):
    rep = run(tmp_path, row(), row(), row(num="К-2"))
    assert len(rep["orders"]) == 2
    iss = rep["issues"]
    assert len(iss) == 1 and iss.iloc[0]["строка_csv"] == 3 and "полный дубль строки 2" in iss.iloc[0]["проблема"]


def test_conflicting_duplicate_keeps_first_and_reports(tmp_path):
    rep = run(tmp_path, row(price="500000"), row(price="999000"))
    assert len(rep["orders"]) == 1
    assert order(rep, "К-1")["цена_продажи"] == 500000
    assert "расхождением" in rep["issues"].iloc[0]["проблема"]


def test_rows_without_order_number_are_not_merged_as_duplicates(tmp_path):
    rep = run(tmp_path, row(num="", price="400000"), row(num="", price="600000"))
    assert len(rep["orders"]) == 2
    assert (rep["issues"]["поле"] == "номер_заказа").sum() == 2


@pytest.mark.parametrize("bad", ["31.02.2026", "2026-13-05", "вчера", "32/01/2026"])
def test_invalid_date_reported_and_not_counted_as_overdue(tmp_path, bad):
    d = DATES.split(";")
    d[4] = bad  # дизайн_факт
    rep = run(tmp_path, row(dates=";".join(d)))
    assert (rep["issues"]["поле"] == "дизайн_факт").sum() == 1
    st = rep["deadlines"].set_index("стадия").loc["дизайн", "статус"]
    assert st == "нет факта"  # производство закрыто — значит, дизайн тоже, просто дата битая


@pytest.mark.parametrize("raw,expected", [
    ("2026-03-15", "2026-03-15"), ("15.03.2026", "2026-03-15"),
    ("15.03.26", "2026-03-15"), ("15/03/2026", "2026-03-15"), (" 15.03.2026 ", "2026-03-15")])
def test_date_formats(raw, expected):
    assert mt.parse_date(raw) == pd.Timestamp(expected)


@pytest.mark.parametrize("raw,expected", [
    ("1 250 000", 1250000), ("206086,57", 206086.57), ("448000", 448000),
    ("1 250 000,50", 1250000.5)])
def test_number_formats(raw, expected):
    assert mt.parse_number(raw) == pytest.approx(expected)


def test_discount_out_of_range_blocks_margin(tmp_path):
    rep = run(tmp_path, row(disc="150"))
    assert order(rep, "К-1")["статус_маржи"] == "нет данных"


def test_full_discount_does_not_divide_by_zero(tmp_path):
    rep = run(tmp_path, row(disc="100"))
    o = order(rep, "К-1")
    assert o["выручка"] == 0 and o["маржа_руб"] < 0
    assert not np.isinf(o["маржа_проц"])


def test_dealer_negative_margin(tmp_path):
    rep = run(tmp_path, row(channel="Дилер Уфа", price="400000", disc="15", comm="22", mat="270000"))
    # 340000 − 74800 − 270000 − 3000 − 10000 − 30000 = −47800
    assert order(rep, "К-1")["маржа_руб"] == pytest.approx(-47800)
    assert len(rep["loss"]) == 1


def test_reclamation_without_cost_reported(tmp_path):
    rep = run(tmp_path, row(recl="ДА", recl_cost=""))
    assert order(rep, "К-1")["рекламация"]
    assert (rep["issues"]["поле"] == "стоимость_рекламации").sum() == 1


def test_empty_montage_rate_filled_with_model_median(tmp_path):
    rep = run(tmp_path, row(num="К-1", montage="20000"), row(num="К-2", montage="40000"),
              row(num="К-3", montage=""))
    o = order(rep, "К-3")
    assert o["ставка_монтажа"] == 30000 and "ставка_монтажа" in o["оценка"]


def test_overdue_open_stage_and_origin(tmp_path):
    # замер +4 дня, дизайн закрыт с тем же опозданием, производство не закрыто и план прошёл
    d = "01.03.2026;06.03.2026;10.03.2026;16.03.2026;20.03.2026;15.04.2026;;20.04.2026;"
    rep = run(tmp_path, row(dates=d))
    dl = rep["deadlines"].set_index("стадия")
    assert dl.loc["замер", "задержка_дн"] == 4 and dl.loc["замер", "прирост_задержки_дн"] == 4
    assert dl.loc["дизайн", "прирост_задержки_дн"] == 0  # задержка унаследована, не своя
    assert dl.loc["производство", "статус"] == "висит (просрочено)"
    assert dl.loc["монтаж", "статус"] == "висит (просрочено)"
