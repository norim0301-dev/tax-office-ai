"""
労務・社保AI エージェント (roumu.py)
社会保険届出・算定基礎届・労働保険・給与計算サポート
"""

import json
from typing import AsyncGenerator

from agents.ai_client import chat_stream

AGENT_ID = "roumu"

ROUMU_SYSTEM_PROMPT = """あなたは税理士事務所の労務・社会保険担当AIエージェントです。
【役割】社会保険届出・算定基礎届・労働保険・給与計算サポート
【対応業務】社会保険（健康保険・厚生年金）の取得届・喪失届、算定基礎届・月額変更届、労働保険年度更新、雇用保険手続き、給与計算確認
【応答スタイル】届出期限を必ず明示、提出先（年金事務所・ハローワーク等）を具体的に案内する"""

# ────────────────────────────────────────────────
# 標準報酬月額等級表（2024年度）
# (等級, 標準報酬月額, 健康保険料率9.98%/2, 厚生年金保険料率18.3%/2)
# 健康保険：協会けんぽ（東京）2024年度 9.98%
# 厚生年金：18.3%
# ────────────────────────────────────────────────
_HEALTH_RATE = 0.0998  # 健康保険料率（労使合計）協会けんぽ東京2024年度
_PENSION_RATE = 0.183   # 厚生年金保険料率（労使合計）

# 標準報酬月額等級表（健康保険：1〜50等級、厚生年金：1〜32等級）
# (health_grade, pension_grade, 下限, 標準報酬月額, 上限)
_GRADE_TABLE = [
    (1,  1,      0,   58000,   63000),
    (2,  1,  63000,   68000,   73000),
    (3,  1,  73000,   78000,   83000),
    (4,  1,  83000,   88000,   93000),
    (5,  1,  93000,   98000,  101000),
    (6,  1, 101000,  104000,  107000),
    (7,  2, 107000,  110000,  114000),
    (8,  3, 114000,  118000,  122000),
    (9,  4, 122000,  126000,  130000),
    (10, 5, 130000,  134000,  138000),
    (11, 6, 138000,  142000,  146000),
    (12, 7, 146000,  150000,  155000),
    (13, 8, 155000,  160000,  165000),
    (14, 9, 165000,  170000,  175000),
    (15, 10, 175000, 180000,  185000),
    (16, 11, 185000, 190000,  195000),
    (17, 12, 195000, 200000,  210000),
    (18, 13, 210000, 220000,  230000),
    (19, 14, 230000, 240000,  250000),
    (20, 15, 250000, 260000,  270000),
    (21, 16, 270000, 280000,  290000),
    (22, 17, 290000, 300000,  310000),
    (23, 18, 310000, 320000,  330000),
    (24, 19, 330000, 340000,  350000),
    (25, 20, 350000, 360000,  370000),
    (26, 21, 370000, 380000,  395000),
    (27, 22, 395000, 410000,  425000),
    (28, 23, 425000, 440000,  455000),
    (29, 24, 455000, 470000,  485000),
    (30, 25, 485000, 500000,  515000),
    (31, 26, 515000, 530000,  545000),
    (32, 27, 545000, 560000,  575000),
    (33, 28, 575000, 590000,  605000),
    (34, 29, 605000, 620000,  635000),
    (35, 30, 635000, 650000,  665000),
    (36, 31, 665000, 680000,  695000),
    (37, 32, 695000, 710000,  730000),
    (38, 32, 730000, 750000,  770000),
    (39, 32, 770000, 790000,  810000),
    (40, 32, 810000, 830000,  855000),
    (41, 32, 855000, 880000,  905000),
    (42, 32, 905000, 930000,  955000),
    (43, 32, 955000, 980000, 1005000),
    (44, 32, 1005000, 1030000, 1055000),
    (45, 32, 1055000, 1090000, 1115000),
    (46, 32, 1115000, 1150000, 1175000),
    (47, 32, 1175000, 1210000, 1235000),
    (48, 32, 1235000, 1270000, 1295000),
    (49, 32, 1295000, 1330000, 1355000),
    (50, 32, 1355000, 1390000, 9999999),
]


def _get_grade_by_amount(amount: float) -> dict:
    """報酬月額から等級情報を返す"""
    for health_grade, pension_grade, lower, standard, upper in _GRADE_TABLE:
        if lower <= amount < upper:
            return {
                "health_grade": health_grade,
                "pension_grade": pension_grade,
                "standard_remuneration": standard,
                "health_insurance_total": round(standard * _HEALTH_RATE),
                "health_insurance_employee": round(standard * _HEALTH_RATE / 2),
                "pension_total": round(standard * _PENSION_RATE),
                "pension_employee": round(standard * _PENSION_RATE / 2),
            }
    # 上限超え（等級50）
    row = _GRADE_TABLE[-1]
    standard = row[3]
    return {
        "health_grade": row[0],
        "pension_grade": row[1],
        "standard_remuneration": standard,
        "health_insurance_total": round(standard * _HEALTH_RATE),
        "health_insurance_employee": round(standard * _HEALTH_RATE / 2),
        "pension_total": round(standard * _PENSION_RATE),
        "pension_employee": round(standard * _PENSION_RATE / 2),
    }


def _grade_label(health_grade: int, pension_grade: int) -> str:
    return f"健保{health_grade}等級 / 厚年{pension_grade}等級"


# ────────────────────────────────────────────────
# ツール定義
# ────────────────────────────────────────────────
ROUMU_TOOLS = [
    {
        "name": "generate_social_insurance_procedure",
        "description": (
            "社会保険の各種手続きに必要な情報を案内する。"
            "手続き内容・必要書類・提出先・期限・注意事項を返す。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "procedure_type": {
                    "type": "string",
                    "enum": ["資格取得", "資格喪失", "算定基礎", "月額変更", "育児休業", "産前産後"],
                    "description": "手続き種別",
                },
                "employee_type": {
                    "type": "string",
                    "enum": ["正社員", "パート", "役員"],
                    "description": "従業員区分",
                },
                "deadline_date": {
                    "type": "string",
                    "description": "基準となる日付（資格取得日・喪失日等、省略可）",
                },
            },
            "required": ["procedure_type", "employee_type"],
        },
    },
    {
        "name": "calculate_remuneration_standard",
        "description": (
            "4〜6月の報酬をもとに標準報酬月額を算定する（算定基礎届）。"
            "3ヶ月平均・標準報酬月額等級・保険料（健康保険・厚生年金）・"
            "月額変更の要否を返す。2024年度保険料率適用。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "month4": {
                    "type": "number",
                    "description": "4月の報酬月額（円）",
                },
                "month5": {
                    "type": "number",
                    "description": "5月の報酬月額（円）",
                },
                "month6": {
                    "type": "number",
                    "description": "6月の報酬月額（円）",
                },
                "current_grade": {
                    "type": "string",
                    "description": "現在の標準報酬月額等級（省略可、例：健保20等級/厚年15等級）",
                },
                "payment_type": {
                    "type": "string",
                    "enum": ["月給", "日給", "時給"],
                    "description": "給与形態",
                },
            },
            "required": ["month4", "month5", "month6", "payment_type"],
        },
    },
    {
        "name": "check_monthly_change_requirement",
        "description": (
            "給与変動後の3ヶ月報酬をもとに月額変更届（随時改定）の要否を判定する。"
            "2等級以上の差異判定・月額変更届の要否・提出期限・記載内容を返す。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "current_grade": {
                    "type": "string",
                    "description": "現在の標準報酬月額等級（例：健保20等級）",
                },
                "new_month1": {
                    "type": "number",
                    "description": "変動後1ヶ月目の報酬（円）",
                },
                "new_month2": {
                    "type": "number",
                    "description": "変動後2ヶ月目の報酬（円）",
                },
                "new_month3": {
                    "type": "number",
                    "description": "変動後3ヶ月目の報酬（円）",
                },
                "change_reason": {
                    "type": "string",
                    "enum": ["昇給", "降給", "手当変更"],
                    "description": "変動理由",
                },
            },
            "required": ["current_grade", "new_month1", "new_month2", "new_month3", "change_reason"],
        },
    },
    {
        "name": "generate_labor_insurance_renewal",
        "description": (
            "労働保険年度更新の概算・確定保険料を計算する。"
            "概算保険料・確定保険料・差額・申告期限（6月1日〜7月10日）・必要書類を返す。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "total_wages": {
                    "type": "number",
                    "description": "年間賃金総額（円）",
                },
                "industry_type": {
                    "type": "string",
                    "enum": ["一般事業", "建設業", "農林水産業"],
                    "description": "事業の種類",
                },
                "employee_count": {
                    "type": "integer",
                    "description": "従業員数（省略可）",
                },
            },
            "required": ["total_wages", "industry_type"],
        },
    },
]

# ────────────────────────────────────────────────
# ツール実行関数
# ────────────────────────────────────────────────
def _execute_generate_social_insurance_procedure(inputs: dict) -> dict:
    procedure_type = inputs.get("procedure_type", "")
    employee_type = inputs.get("employee_type", "正社員")
    deadline_date = inputs.get("deadline_date", "")

    procedures = {
        "資格取得": {
            "手続き名": "健康保険・厚生年金保険 被保険者資格取得届",
            "期限": "資格取得日から5日以内",
            "提出先": "管轄の年金事務所（または健康保険組合）",
            "必要書類": [
                "被保険者資格取得届（様式第2号）",
                "雇用契約書または労働条件通知書（写し）",
                "マイナンバーが確認できる書類（マイナンバーカード等）",
            ],
            "注意事項": [
                f"従業員区分：{employee_type}",
                "試用期間中も社会保険加入義務あり（正社員と同等の労働条件の場合）",
                "パートは週30時間以上（または正社員の3/4以上）で加入義務",
                "役員は代表取締役・取締役等で報酬受領の場合に加入",
                "e-Govによる電子申請も可能",
            ],
        },
        "資格喪失": {
            "手続き名": "健康保険・厚生年金保険 被保険者資格喪失届",
            "期限": "資格喪失日（退職翌日）から5日以内",
            "提出先": "管轄の年金事務所（または健康保険組合）",
            "必要書類": [
                "被保険者資格喪失届（様式第4号）",
                "健康保険被保険者証（本人分・家族分）",
            ],
            "注意事項": [
                "退職日の翌日が喪失日（例：3/31退職→4/1喪失）",
                "健康保険証は速やかに回収すること",
                "任意継続を希望する場合は本人が喪失日から20日以内に手続き",
                "雇用保険の離職票と合わせて処理することが多い",
            ],
        },
        "算定基礎": {
            "手続き名": "健康保険・厚生年金保険 被保険者報酬月額算定基礎届",
            "期限": "毎年7月1日〜7月10日",
            "提出先": "管轄の年金事務所（または健康保険組合）",
            "必要書類": [
                "被保険者報酬月額算定基礎届（様式第3号）",
                "被保険者報酬月額算定基礎届/70歳以上被用者算定基礎届（総括表）",
            ],
            "注意事項": [
                "4・5・6月の報酬実績をもとに標準報酬月額を改定",
                "支払基礎日数が月給17日以上・日給・時給15日以上の月を算入",
                "産前産後・育児休業者は別途確認",
                "電子申請（e-Gov）の活用を推奨",
            ],
        },
        "月額変更": {
            "手続き名": "健康保険・厚生年金保険 被保険者報酬月額変更届",
            "期限": "固定的賃金変動後3ヶ月の報酬確定後、速やかに（翌月10日まで推奨）",
            "提出先": "管轄の年金事務所（または健康保険組合）",
            "必要書類": [
                "被保険者報酬月額変更届（様式第3号の2）",
            ],
            "注意事項": [
                "固定的賃金の変動（昇給・降給・手当変更等）が前提",
                "変動後3ヶ月間の報酬平均で2等級以上差がある場合に届出義務",
                "支払基礎日数は各月17日以上（日給・時給は15日以上）が必要",
            ],
        },
        "育児休業": {
            "手続き名": "育児休業等取得者申出書（新規・延長）",
            "期限": "育児休業開始後速やかに（保険料免除を受けるため）",
            "提出先": "管轄の年金事務所（または健康保険組合）",
            "必要書類": [
                "育児休業等取得者申出書",
                "育児休業取得を確認できる書類（母子手帳等）",
            ],
            "注意事項": [
                "育児休業期間中は健康保険・厚生年金の保険料が免除",
                "産後パパ育休（出生時育児休業）も対象",
                "延長する場合は延長申出書の提出が必要",
                "雇用保険の育児休業給付金は別途ハローワークへ申請",
            ],
        },
        "産前産後": {
            "手続き名": "産前産後休業取得者申出書",
            "期限": "産前産後休業中（保険料免除のため速やかに）",
            "提出先": "管轄の年金事務所（または健康保険組合）",
            "必要書類": [
                "産前産後休業取得者申出書",
                "出産予定日・出産日が確認できる書類（母子手帳等）",
            ],
            "注意事項": [
                "産前6週（多胎14週）・産後8週間が対象期間",
                "産前産後休業期間中は健康保険・厚生年金保険料が免除",
                "出産手当金は別途協会けんぽ（または健保組合）に申請",
                "出産一時金（50万円）の申請も忘れずに",
            ],
        },
    }

    info = procedures.get(
        procedure_type,
        {"error": f"未定義の手続き種別: {procedure_type}"},
    )

    return {
        "tool": "generate_social_insurance_procedure",
        "procedure_type": procedure_type,
        "employee_type": employee_type,
        "deadline_date": deadline_date if deadline_date else "（基準日未入力）",
        "result": info,
    }


def _execute_calculate_remuneration_standard(inputs: dict) -> dict:
    month4 = inputs.get("month4", 0)
    month5 = inputs.get("month5", 0)
    month6 = inputs.get("month6", 0)
    current_grade = inputs.get("current_grade", "不明")
    payment_type = inputs.get("payment_type", "月給")

    average = (month4 + month5 + month6) / 3
    grade_info = _get_grade_by_amount(average)

    return {
        "tool": "calculate_remuneration_standard",
        "result": {
            "入力報酬": {
                "4月": f"{month4:,.0f}円",
                "5月": f"{month5:,.0f}円",
                "6月": f"{month6:,.0f}円",
            },
            "3ヶ月平均報酬月額": f"{average:,.0f}円",
            "給与形態": payment_type,
            "算定結果": {
                "標準報酬月額": f"{grade_info['standard_remuneration']:,}円",
                "等級": _grade_label(
                    grade_info["health_grade"], grade_info["pension_grade"]
                ),
            },
            "保険料（2024年度）": {
                "健康保険料（労使合計）": f"{grade_info['health_insurance_total']:,}円/月",
                "健康保険料（本人負担）": f"{grade_info['health_insurance_employee']:,}円/月",
                "厚生年金保険料（労使合計）": f"{grade_info['pension_total']:,}円/月",
                "厚生年金保険料（本人負担）": f"{grade_info['pension_employee']:,}円/月",
            },
            "現在の等級": current_grade,
            "注意事項": [
                "健康保険料率：協会けんぽ東京都 9.98%（2024年度）",
                "厚生年金保険料率：18.3%（2024年度）",
                "介護保険料（40歳以上65歳未満）は別途加算",
                "支払基礎日数（月給17日以上・日給時給15日以上）を確認すること",
                "7月から新標準報酬月額が適用（算定基礎の場合）",
            ],
        },
    }


def _execute_check_monthly_change_requirement(inputs: dict) -> dict:
    current_grade = inputs.get("current_grade", "")
    new_month1 = inputs.get("new_month1", 0)
    new_month2 = inputs.get("new_month2", 0)
    new_month3 = inputs.get("new_month3", 0)
    change_reason = inputs.get("change_reason", "昇給")

    average = (new_month1 + new_month2 + new_month3) / 3
    new_grade_info = _get_grade_by_amount(average)
    new_grade_num = new_grade_info["health_grade"]

    # 現在等級番号をパース（例：「健保20等級」→20）
    current_grade_num = None
    try:
        import re
        match = re.search(r"健保(\d+)等級", current_grade)
        if match:
            current_grade_num = int(match.group(1))
    except Exception:
        pass

    if current_grade_num is not None:
        grade_diff = abs(new_grade_num - current_grade_num)
        needs_change = grade_diff >= 2
        diff_text = f"{grade_diff}等級差"
    else:
        needs_change = None
        diff_text = "現在等級が不明なため自動判定不可"

    return {
        "tool": "check_monthly_change_requirement",
        "result": {
            "変動後報酬": {
                "1ヶ月目": f"{new_month1:,.0f}円",
                "2ヶ月目": f"{new_month2:,.0f}円",
                "3ヶ月目": f"{new_month3:,.0f}円",
            },
            "3ヶ月平均": f"{average:,.0f}円",
            "変動理由": change_reason,
            "新標準報酬月額": f"{new_grade_info['standard_remuneration']:,}円",
            "新等級（健保）": f"{new_grade_num}等級",
            "現在等級": current_grade,
            "等級差": diff_text,
            "月額変更届の要否": (
                "必要（2等級以上の差異あり）"
                if needs_change is True
                else (
                    "不要（2等級未満の差異）"
                    if needs_change is False
                    else "判定不能（現在等級を等級番号形式で入力してください）"
                )
            ),
            "提出期限": "固定的賃金変動後3ヶ月の報酬確定後、翌月10日まで",
            "提出先": "管轄の年金事務所（または健康保険組合）",
            "記載内容": [
                "被保険者氏名・生年月日・被保険者番号",
                "固定的賃金の変動月・変動内容（昇給額等）",
                "変動後3ヶ月の報酬月額（通貨・現物別）",
                "支払基礎日数（各月17日以上の確認）",
                "改定後の標準報酬月額・等級",
            ],
            "随時改定の条件（いずれも必要）": [
                "① 固定的賃金（基本給・手当等）が変動したこと",
                "② 変動後の継続した3ヶ月間に支払基礎日数が各月17日（日給・時給は15日）以上あること",
                "③ 3ヶ月の報酬平均で現在の標準報酬月額と2等級以上の差が生じること",
                "④ 昇給の場合は2等級以上の増加、降給の場合は2等級以上の減少",
            ],
        },
    }


def _execute_generate_labor_insurance_renewal(inputs: dict) -> dict:
    total_wages = inputs.get("total_wages", 0)
    industry_type = inputs.get("industry_type", "一般事業")
    employee_count = inputs.get("employee_count")

    # 労働保険料率（2024年度概算）
    # 労災保険料率は業種により異なる（代表的な値を使用）
    # 雇用保険料率：一般事業 1.55%（労働者0.6%、事業主0.95%）
    insurance_rates = {
        "一般事業": {
            "rousai": 0.0030,   # 労災3/1000（一般的な事務業の場合）
            "koyo_total": 0.0155,  # 雇用保険1.55%（2024年度）
            "koyo_worker": 0.006,  # 雇用保険労働者負担0.6%
            "koyo_employer": 0.0095,  # 雇用保険事業主負担0.95%
        },
        "建設業": {
            "rousai": 0.0085,   # 労災8.5/1000
            "koyo_total": 0.0155,
            "koyo_worker": 0.006,
            "koyo_employer": 0.0095,
        },
        "農林水産業": {
            "rousai": 0.0013,   # 労災1.3/1000
            "koyo_total": 0.0175,  # 雇用保険1.75%（農林水産業）
            "koyo_worker": 0.007,
            "koyo_employer": 0.0105,
        },
    }

    rates = insurance_rates.get(industry_type, insurance_rates["一般事業"])
    rousai_premium = round(total_wages * rates["rousai"])
    koyo_total_premium = round(total_wages * rates["koyo_total"])
    koyo_worker_premium = round(total_wages * rates["koyo_worker"])
    koyo_employer_premium = round(total_wages * rates["koyo_employer"])
    total_premium = rousai_premium + koyo_employer_premium  # 事業主負担合計

    return {
        "tool": "generate_labor_insurance_renewal",
        "result": {
            "入力情報": {
                "年間賃金総額": f"{total_wages:,.0f}円",
                "事業種類": industry_type,
                "従業員数": f"{employee_count}人" if employee_count else "未入力",
            },
            "保険料計算（2024年度概算料率）": {
                "労災保険料率": f"{rates['rousai']*1000:.1f}/1000",
                "雇用保険料率（労使合計）": f"{rates['koyo_total']*100:.2f}%",
                "労災保険料（事業主全額負担）": f"{rousai_premium:,}円",
                "雇用保険料（労使合計）": f"{koyo_total_premium:,}円",
                "  うち労働者負担": f"{koyo_worker_premium:,}円",
                "  うち事業主負担": f"{koyo_employer_premium:,}円",
                "事業主負担合計（概算）": f"{total_premium:,}円",
            },
            "年度更新スケジュール": {
                "申告・納付期限": "6月1日〜7月10日",
                "対象期間": "前年4月1日〜当年3月31日（確定）／当年4月1日〜翌年3月31日（概算）",
                "延納制度": "概算保険料が40万円以上（または労災か雇用保険の一方が20万円以上）の場合、3回に分けて納付可能",
            },
            "必要書類": [
                "労働保険 概算・確定保険料申告書（様式第6号）",
                "賃金台帳・賃金集計表",
                "前年度の概算保険料申告書（控）",
                "労働者名簿",
            ],
            "提出・納付先": [
                "労働局・労働基準監督署（申告書の提出）",
                "金融機関・労働局・労働基準監督署（保険料の納付）",
                "e-Gov電子申請も利用可能",
            ],
            "注意事項": [
                "労災保険料率は業種・作業内容により異なる（実際の適用料率は最寄りの労働局に確認）",
                "雇用保険料率は毎年改定される場合があるため最新情報を確認すること",
                "建設業は元請工事の請負金額に基づく特別な計算が必要な場合あり",
                "雇用保険料の労働者負担分は給与から源泉控除すること",
            ],
        },
    }


def _execute_tool(tool_name: str, tool_input: dict) -> str:
    if tool_name == "generate_social_insurance_procedure":
        result = _execute_generate_social_insurance_procedure(tool_input)
    elif tool_name == "calculate_remuneration_standard":
        result = _execute_calculate_remuneration_standard(tool_input)
    elif tool_name == "check_monthly_change_requirement":
        result = _execute_check_monthly_change_requirement(tool_input)
    elif tool_name == "generate_labor_insurance_renewal":
        result = _execute_generate_labor_insurance_renewal(tool_input)
    else:
        result = {"error": f"未定義のツール: {tool_name}"}
    return json.dumps(result, ensure_ascii=False)


# ────────────────────────────────────────────────
# ツールラベル
# ────────────────────────────────────────────────
TOOL_LABELS = {
    "generate_social_insurance_procedure": "社会保険手続きガイドを生成中...",
    "calculate_remuneration_standard": "標準報酬月額を算定中...",
    "check_monthly_change_requirement": "月額変更届の要否を確認中...",
    "generate_labor_insurance_renewal": "労働保険年度更新を計算中...",
}


# ────────────────────────────────────────────────
# ツール実行ディスパッチャ（chat_stream 用）
# ────────────────────────────────────────────────
def dispatch_tool(tool_name: str, tool_input: dict) -> str:
    return _execute_tool(tool_name, tool_input)


# ────────────────────────────────────────────────
# SSEストリーミング関数
# ────────────────────────────────────────────────
async def roumu_chat_stream(
    message: str, history: list[dict]
) -> AsyncGenerator[str, None]:
    """SSEストリーミングチャット（Gemini/Claude自動切替）"""
    async for chunk in chat_stream(
        message=message,
        history=history,
        system_prompt=ROUMU_SYSTEM_PROMPT,
        tools_schema=ROUMU_TOOLS,
        dispatch_tool=dispatch_tool,
    ):
        yield chunk
