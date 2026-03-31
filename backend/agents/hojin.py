"""
法人税AIエージェント
Claude claude-opus-4-6 + Adaptive Thinking を使用したSSEストリーミング対応チャット
"""
import json
from typing import AsyncGenerator

from agents.ai_client import chat_stream

# ---- システムプロンプト ----
HOJIN_SYSTEM_PROMPT = """あなたは税理士事務所の法人税担当AIエージェントです。
【役割】法人税申告書作成サポート・別表チェック・決算対応
【対応業務】法人税申告書（別表一〜別表十七）、交際費・寄附金・減価償却の別表、法人事業概況説明書、修正申告・更正の請求
【使用システム】JDL会計ソフト連携
【応答スタイル】正確・簡潔、税務リスクがある場合は必ず警告、具体的な別表番号を明示する"""

# ---- ツール定義 ----
HOJIN_TOOLS = [
    {
        "name": "check_corporate_tax_items",
        "description": "法人税申告書の主要項目をチェックし、確認すべき別表と注意事項を一覧で返します。",
        "input_schema": {
            "type": "object",
            "properties": {
                "company_name": {
                    "type": "string",
                    "description": "会社名"
                },
                "fiscal_year_end": {
                    "type": "string",
                    "description": "決算期末日（例: 2024-03-31）"
                },
                "revenue": {
                    "type": "number",
                    "description": "売上高（円）"
                },
                "profit_loss": {
                    "type": "string",
                    "enum": ["黒字", "赤字", "ゼロ"],
                    "description": "当期損益区分"
                }
            },
            "required": ["company_name", "fiscal_year_end", "profit_loss"]
        }
    },
    {
        "name": "calculate_entertainment_expense",
        "description": "交際費の損金算入限度額を計算し、別表十五への記載内容を返します。",
        "input_schema": {
            "type": "object",
            "properties": {
                "total_entertainment": {
                    "type": "number",
                    "description": "支出交際費等の合計額（円）"
                },
                "capital": {
                    "type": "number",
                    "description": "期末資本金の額（円）"
                },
                "company_type": {
                    "type": "string",
                    "enum": ["中小法人", "大法人"],
                    "description": "法人区分（資本金1億円以下が中小法人）"
                }
            },
            "required": ["total_entertainment", "capital", "company_type"]
        }
    },
    {
        "name": "generate_tax_return_checklist",
        "description": "法人税申告書作成に必要な提出書類・チェック項目・提出期限・注意事項を返します。",
        "input_schema": {
            "type": "object",
            "properties": {
                "fiscal_year_end": {
                    "type": "string",
                    "description": "決算期末日（例: 2024-03-31）"
                },
                "has_real_estate": {
                    "type": "boolean",
                    "description": "不動産所得・固定資産がある場合はtrue"
                },
                "has_overseas": {
                    "type": "boolean",
                    "description": "海外取引・海外子会社がある場合はtrue"
                },
                "has_group_company": {
                    "type": "boolean",
                    "description": "グループ法人税制・連結納税に該当する場合はtrue"
                }
            },
            "required": ["fiscal_year_end"]
        }
    }
]


# ---- ツール実行関数 ----
def execute_check_corporate_tax_items(
    company_name: str,
    fiscal_year_end: str,
    profit_loss: str,
    revenue: float = None
) -> str:
    """法人税申告書の項目チェックリストを生成"""
    result = f"【法人税申告書チェックリスト】\n"
    result += f"会社名: {company_name}\n"
    result += f"決算期末: {fiscal_year_end}\n"
    result += f"損益区分: {profit_loss}\n"
    if revenue is not None:
        result += f"売上高: {revenue:,.0f}円\n"
    result += "\n"

    result += "■ 別表一（法人税額の計算）\n"
    result += "  □ 所得金額又は欠損金額の確認（別表四と一致）\n"
    result += "  □ 法人税額の計算（税率23.2%、中小法人800万円以下は15%）\n"
    result += "  □ 控除税額（源泉徴収税額・外国税額控除）の確認\n"
    result += "  □ 差引納付税額の確認\n\n"

    result += "■ 別表四（所得の金額の計算）\n"
    result += "  □ 加算項目: 損金不算入額（交際費・役員給与・寄附金等）\n"
    result += "  □ 減算項目: 益金不算入額（受取配当等）\n"
    result += "  □ 当期純利益（損失）との整合確認\n\n"

    result += "■ 別表五（一）（利益積立金額・資本金等）\n"
    result += "  □ 利益積立金額の期首・増減・期末の検証\n"
    result += "  □ 配当金との整合確認\n\n"

    result += "■ 交際費関連（別表十五）\n"
    result += "  □ 支出交際費の総額確認\n"
    result += "  □ 損金算入限度額の計算（中小法人: 800万円 or 飲食費50%の高い方）\n"
    result += "  □ 損金不算入額の別表四への反映\n\n"

    result += "■ 減価償却（別表十六）\n"
    result += "  □ 償却限度額の計算（定額法・定率法の確認）\n"
    result += "  □ 償却超過額の別表四加算\n"
    result += "  □ 少額減価償却資産（30万円未満）の特例適用確認\n\n"

    result += "■ 役員給与\n"
    result += "  □ 定期同額給与の確認（事前確定届出給与は届出書と照合）\n"
    result += "  □ 不相当に高額な役員給与の有無\n"
    result += "  □ 業績連動給与の要件確認\n\n"

    if profit_loss == "赤字":
        result += "⚠️ 【税務リスク警告: 欠損金関連】\n"
        result += "  □ 別表七（欠損金の繰越控除）の記載\n"
        result += "  □ 繰越欠損金の控除限度額（大法人は所得の50%）\n"
        result += "  □ 欠損金の繰戻還付（青色申告法人は前1年以内可能）の検討\n\n"

    if profit_loss == "黒字":
        result += "■ 税額控除・特別控除の確認\n"
        result += "  □ 中小企業向け所得拡大促進税制\n"
        result += "  □ 研究開発費税額控除（別表六）\n"
        result += "  □ 設備投資促進税制（中小企業経営強化税制等）\n\n"

    return result


def execute_calculate_entertainment_expense(
    total_entertainment: float,
    capital: float,
    company_type: str
) -> str:
    """交際費の損金算入限度額を計算"""
    result = f"【交際費の損金算入限度額計算（別表十五）】\n\n"
    result += f"支出交際費等の合計額: {total_entertainment:,.0f}円\n"
    result += f"期末資本金: {capital:,.0f}円\n"
    result += f"法人区分: {company_type}\n\n"

    if company_type == "中小法人":
        # 中小法人（資本金1億円以下）の判定
        limit_a = 8_000_000  # 800万円

        # 飲食費50%控除の場合（飲食費の金額は不明なので参考値として提示）
        result += "■ 損金算入限度額の選択（有利な方を選択可）\n"
        result += f"  ① 定額控除限度額方式: 800万円（年換算）\n"
        result += f"  ② 飲食費50%損金算入方式: 支出飲食費 × 50%\n\n"

        if total_entertainment <= limit_a:
            deductible = total_entertainment
            non_deductible = 0
            result += f"【計算結果】方式①適用\n"
            result += f"  損金算入限度額: {limit_a:,.0f}円\n"
            result += f"  支出交際費が限度額以内のため、全額損金算入可能\n"
            result += f"  損金算入額: {deductible:,.0f}円\n"
            result += f"  損金不算入額（別表四加算）: {non_deductible:,.0f}円\n"
        else:
            non_deductible = total_entertainment - limit_a
            result += f"【計算結果】方式①適用\n"
            result += f"  損金算入限度額: {limit_a:,.0f}円\n"
            result += f"  損金算入額: {limit_a:,.0f}円\n"
            result += f"  損金不算入額（別表四加算）: {non_deductible:,.0f}円\n"
            result += f"\n⚠️ 飲食費の内訳が判明している場合は、方式②との比較を必ず行ってください。\n"
    else:
        # 大法人（資本金1億円超）
        result += "■ 大法人の交際費処理\n"
        result += "  大法人は定額控除限度額の適用なし\n"
        result += "  飲食費の50%のみ損金算入可能（飲食費以外は全額損金不算入）\n\n"
        result += "  ※ 飲食費の金額を別途ご確認ください\n"
        result += f"  交際費全額を損金不算入とした場合: {total_entertainment:,.0f}円が別表四に加算\n"

    result += "\n■ 別表十五への記載事項\n"
    result += "  ① 支出交際費等の額の合計額\n"
    result += "  ② 損金算入限度額\n"
    result += "  ③ 損金不算入額（① - ②、または飲食費50%控除後の残額）\n"
    result += "  ④ 損金不算入額は別表四「交際費等の損金不算入額」欄に転記\n"

    return result


def execute_generate_tax_return_checklist(
    fiscal_year_end: str,
    has_real_estate: bool = False,
    has_overseas: bool = False,
    has_group_company: bool = False
) -> str:
    """法人税申告書作成チェックリストを生成"""
    from datetime import datetime, timedelta

    # 提出期限の計算（決算期末から2ヶ月後）
    try:
        end_date = datetime.strptime(fiscal_year_end, "%Y-%m-%d")
        # 2ヶ月後の末日
        month = end_date.month + 2
        year = end_date.year + (month - 1) // 12
        month = ((month - 1) % 12) + 1
        deadline = f"{year}年{month}月末日"
    except Exception:
        deadline = "決算期末から2ヶ月以内"

    result = f"【法人税申告書作成チェックリスト】\n"
    result += f"決算期末: {fiscal_year_end}\n"
    result += f"申告・納付期限: {deadline}\n\n"

    result += "■ 提出書類一覧（基本）\n"
    result += "  □ 別表一（法人税額の計算）\n"
    result += "  □ 別表一次葉（税額控除明細）\n"
    result += "  □ 別表二（同族会社等の判定）\n"
    result += "  □ 別表四（所得の金額の計算）\n"
    result += "  □ 別表五（一）（利益積立金額の計算）\n"
    result += "  □ 別表五（二）（租税公課の納付状況）\n"
    result += "  □ 別表六（一）（所得税額の控除）※源泉税がある場合\n"
    result += "  □ 別表七（欠損金の繰越控除）※繰越欠損金がある場合\n"
    result += "  □ 別表十五（交際費等）\n"
    result += "  □ 別表十六（一）または（二）（減価償却費の計算）\n"
    result += "  □ 法人事業概況説明書\n"
    result += "  □ 決算書（貸借対照表・損益計算書・製造原価報告書）\n"
    result += "  □ 勘定科目内訳明細書\n\n"

    result += "■ 地方税申告書\n"
    result += "  □ 法人都道府県民税申告書（第六号様式）\n"
    result += "  □ 法人事業税・特別法人事業税申告書\n"
    result += "  □ 法人市区町村民税申告書（第二十号様式）\n\n"

    if has_real_estate:
        result += "■ 不動産関連（追加書類）\n"
        result += "  □ 別表十六（固定資産の償却計算）の詳細確認\n"
        result += "  □ 土地再評価差額金の処理確認\n"
        result += "  □ 不動産取得税・登録免許税の費用計上確認\n\n"

    if has_overseas:
        result += "■ 海外取引・海外子会社関連（追加書類）\n"
        result += "  □ 別表六（二）（外国税額控除）\n"
        result += "  □ 国外関連者との取引明細（移転価格税制の検討）\n"
        result += "  □ タックスヘイブン対策税制（CFC税制）の適用確認\n"
        result += "  □ 国外財産調書（役員等が5,000万円超の場合）\n"
        result += "  ⚠️ 移転価格文書化義務（連結売上1,000億円以上等）の確認\n\n"

    if has_group_company:
        result += "■ グループ法人税制関連（追加書類）\n"
        result += "  □ 完全支配関係法人間の寄附金・受贈益の処理\n"
        result += "  □ グループ間資産譲渡（含み損益の繰延）\n"
        result += "  □ 連結納税を採用している場合は連結納税申告書\n\n"

    result += "■ 申告前最終確認事項\n"
    result += "  □ 別表四の所得金額と別表一の課税所得が一致しているか\n"
    result += "  □ 別表五（一）の期末利益積立金額と貸借対照表の整合\n"
    result += "  □ 地方税申告書の所得金額との整合\n"
    result += "  □ 消費税申告書との整合（消費税納付額の損金算入時期）\n"
    result += "  □ e-Taxによる電子申告の準備（法人番号・電子証明書）\n"
    result += "  □ 納付書または振替納税の準備\n\n"

    result += f"⚠️ 【提出期限】{deadline}（延長申請がない場合）\n"
    result += "  ※ 申告期限の延長（定款等の定め、会計監査人設置法人は最長6ヶ月）を確認してください。"

    return result


# ---- ツール実行ディスパッチャ ----
def dispatch_tool(tool_name: str, tool_input: dict) -> str:
    if tool_name == "check_corporate_tax_items":
        return execute_check_corporate_tax_items(
            company_name=tool_input["company_name"],
            fiscal_year_end=tool_input["fiscal_year_end"],
            profit_loss=tool_input["profit_loss"],
            revenue=tool_input.get("revenue")
        )
    elif tool_name == "calculate_entertainment_expense":
        return execute_calculate_entertainment_expense(
            total_entertainment=tool_input["total_entertainment"],
            capital=tool_input["capital"],
            company_type=tool_input["company_type"]
        )
    elif tool_name == "generate_tax_return_checklist":
        return execute_generate_tax_return_checklist(
            fiscal_year_end=tool_input["fiscal_year_end"],
            has_real_estate=tool_input.get("has_real_estate", False),
            has_overseas=tool_input.get("has_overseas", False),
            has_group_company=tool_input.get("has_group_company", False)
        )
    else:
        return f"[エラー] 不明なツール: {tool_name}"


# ---- ツールラベルマッピング ----
TOOL_LABELS = {
    "check_corporate_tax_items": "法人税申告書チェック中...",
    "calculate_entertainment_expense": "交際費限度額を計算中...",
    "generate_tax_return_checklist": "申告書チェックリストを生成中...",
}


# ---- SSEストリーミングジェネレータ ----
async def hojin_chat_stream(
    message: str,
    history: list[dict]
) -> AsyncGenerator[str, None]:
    """SSEストリーミングチャット（Gemini/Claude自動切替）"""
    async for chunk in chat_stream(
        message=message,
        history=history,
        system_prompt=HOJIN_SYSTEM_PROMPT,
        tools_schema=HOJIN_TOOLS,
        dispatch_tool=dispatch_tool,
    ):
        yield chunk
