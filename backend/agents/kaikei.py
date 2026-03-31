"""
会計入力AI エージェント (kaikei.py)
JDL仕訳入力サポート・試算表レビュー・帳簿チェック
"""

import json
from typing import AsyncGenerator

from agents.ai_client import chat_stream

AGENT_ID = "kaikei"

KAIKEI_SYSTEM_PROMPT = """あなたは税理士事務所の会計入力担当AIエージェントです。
【役割】JDL仕訳入力サポート・試算表レビュー・帳簿チェック
【対応業務】仕訳入力の勘定科目提案、試算表の異常値検出、月次レビューポイント、決算整理仕訳、JDLのコード体系対応
【応答スタイル】勘定科目は必ず正式名称で答える、借方・貸方を明示する、消費税区分も合わせて提示する"""

# ────────────────────────────────────────────────
# ツール定義
# ────────────────────────────────────────────────
KAIKEI_TOOLS = [
    {
        "name": "suggest_journal_entry",
        "description": (
            "取引内容・金額・事業形態をもとに、仕訳の勘定科目・仕訳例を提案する。"
            "借方科目・貸方科目・消費税区分・JDL科目コード例・注意事項を返す。"
            "よくある取引パターン（売上、仕入、経費、固定資産、借入金等）を網羅する。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "transaction_description": {
                    "type": "string",
                    "description": "取引内容の説明（例：事務用品を現金で購入）",
                },
                "amount": {
                    "type": "number",
                    "description": "取引金額（税込または税抜）",
                },
                "company_type": {
                    "type": "string",
                    "enum": ["法人", "個人事業主"],
                    "description": "法人か個人事業主かの区分",
                },
                "tax_treatment": {
                    "type": "string",
                    "enum": ["課税", "非課税", "不課税", "免税"],
                    "description": "消費税の取扱い区分（省略可）",
                },
            },
            "required": ["transaction_description", "amount", "company_type"],
        },
    },
    {
        "name": "review_trial_balance",
        "description": (
            "月次試算表の数値を受け取り、異常値・確認ポイントをチェックする。"
            "異常値フラグ・前月比較コメント・要確認項目・決算整理仕訳の候補を返す。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "month": {
                    "type": "string",
                    "description": "対象月（例：2024-03）",
                },
                "revenue": {
                    "type": "number",
                    "description": "当月売上高（円）",
                },
                "expenses": {
                    "type": "number",
                    "description": "当月経費合計（円）",
                },
                "profit_rate": {
                    "type": "number",
                    "description": "当月利益率（%）（省略可）",
                },
                "previous_month_profit_rate": {
                    "type": "number",
                    "description": "前月利益率（%）（省略可）",
                },
                "cash_balance": {
                    "type": "number",
                    "description": "当月末現金残高（円）（省略可）",
                },
            },
            "required": ["month", "revenue", "expenses"],
        },
    },
    {
        "name": "generate_closing_entries",
        "description": (
            "決算期末に必要な決算整理仕訳リストを生成する。"
            "減価償却・棚卸・前払費用・未払費用・貸倒引当金等の仕訳一覧と"
            "JDL入力時の注意点を返す。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fiscal_year_end": {
                    "type": "string",
                    "description": "決算期末日（例：2024-03-31）",
                },
                "has_inventory": {
                    "type": "boolean",
                    "description": "棚卸資産あり（省略時false）",
                },
                "has_fixed_assets": {
                    "type": "boolean",
                    "description": "固定資産あり（省略時false）",
                },
                "has_prepaid": {
                    "type": "boolean",
                    "description": "前払費用あり（省略時false）",
                },
                "has_accrued": {
                    "type": "boolean",
                    "description": "未払費用あり（省略時false）",
                },
            },
            "required": ["fiscal_year_end"],
        },
    },
]

# ────────────────────────────────────────────────
# ツール実行関数
# ────────────────────────────────────────────────
def _execute_suggest_journal_entry(inputs: dict) -> dict:
    desc = inputs.get("transaction_description", "")
    amount = inputs.get("amount", 0)
    company_type = inputs.get("company_type", "法人")
    tax_treatment = inputs.get("tax_treatment", "課税")

    return {
        "tool": "suggest_journal_entry",
        "transaction_description": desc,
        "amount": amount,
        "company_type": company_type,
        "tax_treatment": tax_treatment,
        "result": {
            "summary": f"取引「{desc}」（{amount:,.0f}円）の仕訳提案",
            "仕訳例": {
                "借方": "（AIが取引内容を解析して勘定科目を提案します）",
                "貸方": "（AIが取引内容を解析して勘定科目を提案します）",
                "消費税区分": tax_treatment,
                "JDL科目コード例": "取引内容に応じてJDLコード体系から選定",
            },
            "注意事項": [
                f"会社形態：{company_type}",
                f"消費税区分：{tax_treatment}",
                "実際の仕訳は取引の詳細・契約内容・業種により異なります",
                "複数の仕訳パターンが考えられる場合は追加情報をご提供ください",
            ],
        },
    }


def _execute_review_trial_balance(inputs: dict) -> dict:
    month = inputs.get("month", "")
    revenue = inputs.get("revenue", 0)
    expenses = inputs.get("expenses", 0)
    profit_rate = inputs.get("profit_rate")
    prev_profit_rate = inputs.get("previous_month_profit_rate")
    cash_balance = inputs.get("cash_balance")

    profit = revenue - expenses
    calc_profit_rate = (profit / revenue * 100) if revenue > 0 else 0

    flags = []
    if revenue == 0:
        flags.append("売上高がゼロです。売上計上漏れがないか確認してください。")
    if expenses > revenue:
        flags.append("経費が売上を上回っています。赤字計上の確認が必要です。")
    if cash_balance is not None and cash_balance < 0:
        flags.append("現金残高がマイナスです。入出金記録を確認してください。")
    if profit_rate is not None and prev_profit_rate is not None:
        diff = profit_rate - prev_profit_rate
        if abs(diff) > 10:
            flags.append(
                f"利益率が前月比 {diff:+.1f}%pt 変動しています。要因分析が必要です。"
            )

    return {
        "tool": "review_trial_balance",
        "month": month,
        "result": {
            "集計": {
                "売上高": f"{revenue:,.0f}円",
                "経費合計": f"{expenses:,.0f}円",
                "利益": f"{profit:,.0f}円",
                "利益率（計算値）": f"{calc_profit_rate:.1f}%",
            },
            "異常値フラグ": flags if flags else ["特記すべき異常値は検出されませんでした"],
            "要確認項目": [
                "売上の計上時期（実現主義の適用）",
                "仮払金・仮受金の精算状況",
                "未収入金・未払金の残高確認",
                "源泉所得税の預り金残高",
                "消費税仮払・仮受の照合",
            ],
            "決算整理仕訳候補": [
                "減価償却費の計上",
                "前払費用・未払費用の整理",
                "棚卸資産の計上（該当の場合）",
                "貸倒引当金の設定（該当の場合）",
            ],
        },
    }


def _execute_generate_closing_entries(inputs: dict) -> dict:
    fiscal_year_end = inputs.get("fiscal_year_end", "")
    has_inventory = inputs.get("has_inventory", False)
    has_fixed_assets = inputs.get("has_fixed_assets", False)
    has_prepaid = inputs.get("has_prepaid", False)
    has_accrued = inputs.get("has_accrued", False)

    entries = []

    # 常に必要な仕訳
    entries.append({
        "仕訳番号": 1,
        "項目": "法人税等の計上",
        "借方科目": "法人税、住民税及び事業税",
        "貸方科目": "未払法人税等",
        "消費税": "不課税",
        "JDL注意": "科目コードは会社設定に準ずる",
    })

    if has_fixed_assets:
        entries.append({
            "仕訳番号": len(entries) + 1,
            "項目": "減価償却費の計上",
            "借方科目": "減価償却費",
            "貸方科目": "減価償却累計額（または固定資産直接減額）",
            "消費税": "不課税",
            "JDL注意": "固定資産台帳の償却計算と連動させること",
        })

    if has_inventory:
        entries.append({
            "仕訳番号": len(entries) + 1,
            "項目": "期末棚卸の計上",
            "借方科目": "商品（製品・仕掛品）",
            "貸方科目": "期末棚卸高（売上原価内振替）",
            "消費税": "不課税",
            "JDL注意": "棚卸評価方法（原価法・低価法）を確認",
        })

    if has_prepaid:
        entries.append({
            "仕訳番号": len(entries) + 1,
            "項目": "前払費用の振替",
            "借方科目": "前払費用",
            "貸方科目": "各費用科目（保険料・地代家賃等）",
            "消費税": "対応する費用の区分に準ずる",
            "JDL注意": "契約期間・支払日から計算すること",
        })

    if has_accrued:
        entries.append({
            "仕訳番号": len(entries) + 1,
            "項目": "未払費用の計上",
            "借方科目": "各費用科目（給料・支払利息等）",
            "貸方科目": "未払費用",
            "消費税": "対応する費用の区分に準ずる",
            "JDL注意": "給料の場合は未払給与で処理するケースも確認",
        })

    # 貸倒引当金（常に検討）
    entries.append({
        "仕訳番号": len(entries) + 1,
        "項目": "貸倒引当金の設定",
        "借方科目": "貸倒引当金繰入額",
        "貸方科目": "貸倒引当金",
        "消費税": "不課税",
        "JDL注意": "法定繰入率または個別評価、債権残高を確認",
    })

    return {
        "tool": "generate_closing_entries",
        "fiscal_year_end": fiscal_year_end,
        "result": {
            "決算整理仕訳一覧": entries,
            "JDL入力時の注意点": [
                "決算整理仕訳は期末日付（{}）で入力すること".format(fiscal_year_end),
                "自動仕訳（減価償却等）はJDL固定資産管理から連動させること",
                "消費税申告がある場合は消費税区分の確認を徹底すること",
                "前期末残高と当期首残高の一致を必ず確認すること",
                "役員報酬の未払計上は定款・議事録の確認が必要",
            ],
        },
    }


def _execute_tool(tool_name: str, tool_input: dict) -> str:
    if tool_name == "suggest_journal_entry":
        result = _execute_suggest_journal_entry(tool_input)
    elif tool_name == "review_trial_balance":
        result = _execute_review_trial_balance(tool_input)
    elif tool_name == "generate_closing_entries":
        result = _execute_generate_closing_entries(tool_input)
    else:
        result = {"error": f"未定義のツール: {tool_name}"}
    return json.dumps(result, ensure_ascii=False)


# ────────────────────────────────────────────────
# ツールラベル
# ────────────────────────────────────────────────
TOOL_LABELS = {
    "suggest_journal_entry": "仕訳提案を生成中...",
    "review_trial_balance": "試算表をレビュー中...",
    "generate_closing_entries": "決算整理仕訳リストを生成中...",
}


# ────────────────────────────────────────────────
# ツール実行ディスパッチャ（chat_stream 用）
# ────────────────────────────────────────────────
def dispatch_tool(tool_name: str, tool_input: dict) -> str:
    return _execute_tool(tool_name, tool_input)


# ────────────────────────────────────────────────
# SSEストリーミング関数
# ────────────────────────────────────────────────
async def kaikei_chat_stream(
    message: str, history: list[dict]
) -> AsyncGenerator[str, None]:
    """SSEストリーミングチャット（Gemini/Claude自動切替）"""
    async for chunk in chat_stream(
        message=message,
        history=history,
        system_prompt=KAIKEI_SYSTEM_PROMPT,
        tools_schema=KAIKEI_TOOLS,
        dispatch_tool=dispatch_tool,
    ):
        yield chunk
