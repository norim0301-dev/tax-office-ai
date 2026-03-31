"""
消費税AIエージェント
Claude claude-opus-4-6 + Adaptive Thinking を使用したSSEストリーミング対応チャット
"""
import json
from typing import AsyncGenerator

from agents.ai_client import chat_stream

# ---- システムプロンプト ----
SHOHI_SYSTEM_PROMPT = """あなたは税理士事務所の消費税担当AIエージェントです。
【役割】消費税申告書チェック・インボイス対応・課税区分確認
【対応業務】消費税申告書（一般課税・簡易課税）、インボイス制度対応、課税・非課税・免税・不課税の区分、輸出免税、電子申告
【応答スタイル】インボイス番号・課税区分は必ず確認を促す、簡易課税のみなし仕入率を正確に適用する"""

# ---- ツール定義 ----
SHOHI_TOOLS = [
    {
        "name": "check_invoice_registration",
        "description": "インボイス（適格請求書発行事業者）の登録状況を確認し、登録の必要性・影響・対応策を返します。",
        "input_schema": {
            "type": "object",
            "properties": {
                "is_registered": {
                    "type": "boolean",
                    "description": "インボイス登録済みかどうか"
                },
                "annual_sales": {
                    "type": "number",
                    "description": "年間売上高（円）"
                },
                "customer_type": {
                    "type": "string",
                    "enum": ["法人のみ", "個人のみ", "混在"],
                    "description": "主な取引先の区分"
                }
            },
            "required": ["is_registered", "annual_sales", "customer_type"]
        }
    },
    {
        "name": "calculate_consumption_tax",
        "description": "一般課税または簡易課税方式で消費税額を計算し、申告書への記載内容を返します。",
        "input_schema": {
            "type": "object",
            "properties": {
                "method": {
                    "type": "string",
                    "enum": ["一般課税", "簡易課税"],
                    "description": "消費税の計算方式"
                },
                "taxable_sales": {
                    "type": "number",
                    "description": "課税売上高（税抜き・円）"
                },
                "taxable_purchases": {
                    "type": "number",
                    "description": "課税仕入高（税抜き・円）。一般課税の場合に使用。"
                },
                "business_type": {
                    "type": "string",
                    "enum": ["第一種", "第二種", "第三種", "第四種", "第五種", "第六種"],
                    "description": "簡易課税の事業区分（簡易課税の場合に必須）"
                }
            },
            "required": ["method", "taxable_sales"]
        }
    },
    {
        "name": "classify_tax_treatment",
        "description": "取引内容から消費税の課税区分（課税/非課税/免税/不課税）を判定し、根拠と注意事項を返します。",
        "input_schema": {
            "type": "object",
            "properties": {
                "transaction_description": {
                    "type": "string",
                    "description": "取引の内容・説明（例: 土地の賃貸料、医療費、輸出売上）"
                },
                "amount": {
                    "type": "number",
                    "description": "取引金額（円）"
                }
            },
            "required": ["transaction_description"]
        }
    }
]


# ---- ツール実行関数 ----
def execute_check_invoice_registration(
    is_registered: bool,
    annual_sales: float,
    customer_type: str
) -> str:
    """インボイス登録状況確認・対応アドバイスを生成"""
    result = f"【インボイス登録状況確認】\n\n"
    result += f"登録状況: {'登録済み' if is_registered else '未登録'}\n"
    result += f"年間売上高: {annual_sales:,.0f}円\n"
    result += f"主な取引先: {customer_type}\n\n"

    is_taxable = annual_sales > 10_000_000  # 1,000万円超は課税事業者

    if is_registered:
        result += "■ 登録済みの場合の対応事項\n"
        result += "  □ 適格請求書（インボイス）の記載事項を満たしているか確認\n"
        result += "    ・登録番号（T + 13桁）\n"
        result += "    ・取引年月日\n"
        result += "    ・取引内容（軽減税率対象品目は「※」等で明示）\n"
        result += "    ・税率ごとに区分した対価の額と消費税額\n"
        result += "    ・書類の交付を受ける事業者の名称\n"
        result += "  □ 登録番号の国税庁サイトでの公表確認\n"
        result += "  □ 免税事業者に戻る場合は「登録取消届出書」の提出（効力は翌課税期間）\n\n"
        result += "  ✅ 登録済みのため、取引先は仕入税額控除が可能です。\n"
    else:
        result += "■ 未登録の場合の影響分析\n"

        if customer_type == "法人のみ":
            result += "  ⚠️ 【高リスク】法人取引先は仕入税額控除ができません。\n"
            result += "  　取引先から値引き交渉・取引停止のリスクが高い状況です。\n"
            result += "  　登録を強く推奨します。\n\n"
        elif customer_type == "個人のみ":
            result += "  △ 個人消費者との取引のみのため、仕入税額控除への影響は限定的です。\n"
            result += "  　ただし、消費者向けビジネスでも登録の検討が必要な場合があります。\n\n"
        else:
            result += "  ⚠️ 法人取引先が含まれる場合、仕入税額控除の問題が生じています。\n"
            result += "  　法人取引先の割合に応じてリスクを評価し、登録を検討してください。\n\n"

        result += "■ 経過措置（2割特例・80%控除）\n"
        result += "  ・免税事業者からの仕入れは一定期間、仕入税額の一定割合を控除可能\n"
        result += "  ・2026年9月30日まで: 仕入税額相当額の50%控除可能\n\n"

        if not is_taxable:
            result += "■ 免税事業者の登録判断（売上高1,000万円以下）\n"
            result += "  ・登録すると課税事業者となり消費税の納税義務が発生します\n"
            result += "  ・登録しない場合: 取引先への影響を考慮した上で判断\n"
            result += "  ・2割特例: 登録した免税事業者は当面、消費税納税額を売上税額の20%に軽減可能\n"
        else:
            result += "  ⚠️ 課税事業者（売上高1,000万円超）であるため、登録を強く推奨します。\n"

    result += "\n■ インボイス番号確認先\n"
    result += "  国税庁「適格請求書発行事業者公表サイト」\n"
    result += "  URL: https://www.invoice-kohyo.nta.go.jp/"

    return result


def execute_calculate_consumption_tax(
    method: str,
    taxable_sales: float,
    taxable_purchases: float = None,
    business_type: str = None
) -> str:
    """消費税額を計算"""
    TAX_RATE = 0.10  # 標準税率10%
    REDUCED_TAX_RATE = 0.08  # 軽減税率8%

    # みなし仕入率（簡易課税）
    DEEMED_PURCHASE_RATES = {
        "第一種": 0.90,  # 卸売業
        "第二種": 0.80,  # 小売業・農林漁業（飲食料品）
        "第三種": 0.70,  # 製造業・農林漁業（飲食料品以外）・建設業
        "第四種": 0.60,  # その他（飲食店業等）
        "第五種": 0.50,  # サービス業・金融業・保険業
        "第六種": 0.40,  # 不動産業
    }

    result = f"【消費税額計算（{method}）】\n\n"
    result += f"課税売上高（税抜）: {taxable_sales:,.0f}円\n"

    # 課税標準額（千円未満切捨て）
    taxable_base = int(taxable_sales // 1000) * 1000
    sales_tax = taxable_base * TAX_RATE

    result += f"課税標準額（千円未満切捨）: {taxable_base:,.0f}円\n"
    result += f"課税売上に係る消費税額（10%）: {sales_tax:,.0f}円\n\n"

    if method == "一般課税":
        if taxable_purchases is None:
            taxable_purchases = 0
        purchase_tax_credit = taxable_purchases * TAX_RATE
        tax_payable = sales_tax - purchase_tax_credit

        result += f"■ 一般課税（本則課税）\n"
        result += f"  課税仕入高（税抜）: {taxable_purchases:,.0f}円\n"
        result += f"  仕入税額控除額: {purchase_tax_credit:,.0f}円\n\n"

        # 課税売上割合の確認
        result += "  ⚠️ 課税売上割合が95%未満の場合、仕入税額控除に按分計算が必要です。\n"
        result += "  　（個別対応方式または一括比例配分方式を選択）\n\n"

        result += f"  差引納付税額（百円未満切捨）: {int(max(tax_payable, 0) // 100) * 100:,.0f}円\n"
        if tax_payable < 0:
            result += f"  ※ 還付税額: {abs(int(tax_payable // 100) * 100):,.0f}円（還付申告となります）\n"

        result += "\n■ 申告書への記載箇所\n"
        result += "  ・第一表「課税標準額」欄\n"
        result += "  ・第一表「消費税額」欄\n"
        result += "  ・第一表「控除対象仕入税額」欄\n"
        result += "  ・第一表「差引税額」欄\n"
        result += "  ・付表2「課税仕入れに係る消費税額の計算」\n"

    elif method == "簡易課税":
        if business_type is None:
            return "エラー: 簡易課税の場合は事業区分（第一種〜第六種）を指定してください。"

        deemed_rate = DEEMED_PURCHASE_RATES.get(business_type, 0.60)
        deemed_purchase_tax = sales_tax * deemed_rate
        tax_payable = sales_tax - deemed_purchase_tax

        business_descriptions = {
            "第一種": "卸売業",
            "第二種": "小売業・農林漁業（飲食料品）",
            "第三種": "製造業・農林漁業（飲食料品以外）・建設業",
            "第四種": "その他（飲食店業等）",
            "第五種": "サービス業・金融業・保険業",
            "第六種": "不動産業",
        }

        result += f"■ 簡易課税\n"
        result += f"  事業区分: {business_type}（{business_descriptions.get(business_type, '')}）\n"
        result += f"  みなし仕入率: {deemed_rate * 100:.0f}%\n"
        result += f"  みなし仕入税額: {deemed_purchase_tax:,.0f}円\n\n"
        result += f"  差引納付税額（百円未満切捨）: {int(max(tax_payable, 0) // 100) * 100:,.0f}円\n\n"

        result += "  ⚠️ 注意事項\n"
        result += "  ・簡易課税は前々年度の課税売上高が5,000万円以下の場合に適用可能\n"
        result += "  ・簡易課税選択届出書を提出した課税期間から適用（事前届出が必要）\n"
        result += "  ・2年間の継続適用義務あり（2年間は一般課税に変更不可）\n"
        result += "  ・2事業以上ある場合は原則として最低のみなし仕入率を適用（特例あり）\n\n"

        result += "■ 申告書への記載箇所\n"
        result += "  ・第一表「課税標準額」欄\n"
        result += "  ・第二表（簡易課税制度選択）\n"
        result += "  ・付表4または付表6（みなし仕入率の計算）\n"

    return result


def execute_classify_tax_treatment(
    transaction_description: str,
    amount: float = None
) -> str:
    """取引の課税区分を判定"""

    # キーワードベースの判定ロジック
    desc = transaction_description

    # 判定パターン定義
    patterns = [
        # 非課税取引
        {
            "keywords": ["土地", "土地の売却", "土地の譲渡"],
            "classification": "非課税",
            "basis": "消費税法別表第一第1号（土地の譲渡・貸付）",
            "notes": "土地の上に建物がある場合、建物部分は課税となります。土地と建物の按分が必要です。"
        },
        {
            "keywords": ["家賃", "居住用", "住宅の賃貸", "住宅賃貸"],
            "classification": "非課税",
            "basis": "消費税法別表第一第13号（住宅の貸付）",
            "notes": "1ヶ月以上の居住用賃貸のみ非課税。事務所・店舗・1ヶ月未満は課税。"
        },
        {
            "keywords": ["医療費", "診療", "治療", "医療", "病院"],
            "classification": "非課税",
            "basis": "消費税法別表第一第6号（医療・介護等）",
            "notes": "健康保険が適用される保険診療のみ非課税。自由診療・美容整形・健康診断（一部）は課税。"
        },
        {
            "keywords": ["社会保険", "介護保険", "介護サービス"],
            "classification": "非課税",
            "basis": "消費税法別表第一第7号（社会福祉事業）",
            "notes": "法定の社会保険・介護保険サービスのみ。上乗せサービスは課税となる場合があります。"
        },
        {
            "keywords": ["利息", "貸付金利息", "受取利息", "保険料"],
            "classification": "非課税",
            "basis": "消費税法別表第一第3号・第4号（金融・保険取引）",
            "notes": "融資の手数料（事務手数料等）は課税となる場合があります。"
        },
        {
            "keywords": ["有価証券", "株式", "国債", "社債"],
            "classification": "非課税",
            "basis": "消費税法別表第一第2号（有価証券等の譲渡）",
            "notes": "有価証券の売却は非課税。証券会社の手数料は課税。"
        },
        {
            "keywords": ["切手", "印紙", "商品券", "プリペイドカード"],
            "classification": "非課税",
            "basis": "消費税法別表第一第5号（郵便切手類・印紙等）",
            "notes": "切手・印紙は購入時が非課税。使用時に課税仕入となる場合があります（切手）。"
        },
        # 免税取引
        {
            "keywords": ["輸出", "輸出売上", "海外向け", "export"],
            "classification": "免税（輸出免税）",
            "basis": "消費税法第7条（輸出免税）",
            "notes": "輸出証明書（輸出許可証等）の保存が要件。インボイス（適格請求書）不要。"
        },
        {
            "keywords": ["国際輸送", "国際郵便"],
            "classification": "免税（輸出免税）",
            "basis": "消費税法第7条（国際輸送・通信）",
            "notes": "国際輸送は免税。国内輸送部分は課税となる場合があります。"
        },
        # 不課税取引
        {
            "keywords": ["給与", "賃金", "人件費", "役員報酬"],
            "classification": "不課税",
            "basis": "消費税の課税対象外（不課税取引）",
            "notes": "給与・賃金は消費税の課税対象外。源泉所得税の処理が必要。"
        },
        {
            "keywords": ["損害賠償", "賠償金", "補償金"],
            "classification": "不課税（原則）",
            "basis": "対価性がない場合は不課税",
            "notes": "損害賠償・補償金は原則不課税。ただし資産の損害に対する補填でも課税となる場合あり。個別判定が必要。"
        },
        {
            "keywords": ["寄附金", "寄付", "補助金", "助成金"],
            "classification": "不課税",
            "basis": "対価性がない取引は不課税",
            "notes": "補助金・助成金は対価性がなく不課税。ただし特定の役務提供等の対価性がある場合は課税。"
        },
        # 軽減税率
        {
            "keywords": ["飲食料品", "食品", "食料品", "軽減税率"],
            "classification": "課税（軽減税率8%）",
            "basis": "消費税法附則第34条（軽減税率制度）",
            "notes": "飲食料品（酒類・外食を除く）は軽減税率8%。外食・ケータリングは標準税率10%。"
        },
        {
            "keywords": ["新聞", "定期購読"],
            "classification": "課税（軽減税率8%）",
            "basis": "消費税法附則第34条（新聞の定期購読）",
            "notes": "週2回以上発行される定期購読新聞のみ8%。スポーツ新聞・電子版は10%の場合あり。"
        },
    ]

    # マッチング
    matched_pattern = None
    for pattern in patterns:
        for keyword in pattern["keywords"]:
            if keyword in desc:
                matched_pattern = pattern
                break
        if matched_pattern:
            break

    result = f"【課税区分判定】\n\n"
    result += f"取引内容: {transaction_description}\n"
    if amount is not None:
        result += f"取引金額: {amount:,.0f}円\n"
    result += "\n"

    if matched_pattern:
        result += f"判定結果: 【{matched_pattern['classification']}】\n\n"
        result += f"根拠法令: {matched_pattern['basis']}\n\n"
        result += f"注意事項:\n{matched_pattern['notes']}\n"
    else:
        # デフォルトは課税
        result += "判定結果: 【課税（標準税率10%）】（暫定判定）\n\n"
        result += "根拠: 非課税・免税・不課税のいずれにも該当しない取引は、消費税の課税対象となります（消費税法第4条）。\n\n"
        result += "注意事項:\n"
        result += "・上記は暫定判定です。取引の詳細（契約内容・相手方等）により区分が変わる場合があります。\n"
        result += "・特殊な取引は税理士に個別確認することを推奨します。\n"

    result += "\n■ 課税区分の整理\n"
    result += "  課税取引:     消費税が課税される（標準10%・軽減8%）\n"
    result += "  非課税取引:   消費税が課税されない（法律で限定列挙）\n"
    result += "  免税取引:     消費税率0%（輸出等。仕入税額控除は可能）\n"
    result += "  不課税取引:   消費税の対象外（給与・補助金・損害賠償等）\n\n"
    result += "⚠️ インボイス制度下では、課税仕入の際に適格請求書（インボイス）の保存が仕入税額控除の要件です。"

    return result


# ---- ツール実行ディスパッチャ ----
def dispatch_tool(tool_name: str, tool_input: dict) -> str:
    if tool_name == "check_invoice_registration":
        return execute_check_invoice_registration(
            is_registered=tool_input["is_registered"],
            annual_sales=tool_input["annual_sales"],
            customer_type=tool_input["customer_type"]
        )
    elif tool_name == "calculate_consumption_tax":
        return execute_calculate_consumption_tax(
            method=tool_input["method"],
            taxable_sales=tool_input["taxable_sales"],
            taxable_purchases=tool_input.get("taxable_purchases"),
            business_type=tool_input.get("business_type")
        )
    elif tool_name == "classify_tax_treatment":
        return execute_classify_tax_treatment(
            transaction_description=tool_input["transaction_description"],
            amount=tool_input.get("amount")
        )
    else:
        return f"[エラー] 不明なツール: {tool_name}"


# ---- ツールラベルマッピング ----
TOOL_LABELS = {
    "check_invoice_registration": "インボイス登録状況を確認中...",
    "calculate_consumption_tax": "消費税額を計算中...",
    "classify_tax_treatment": "課税区分を判定中...",
}


# ---- SSEストリーミングジェネレータ ----
async def shohi_chat_stream(
    message: str,
    history: list[dict]
) -> AsyncGenerator[str, None]:
    """SSEストリーミングチャット（Gemini/Claude自動切替）"""
    async for chunk in chat_stream(
        message=message,
        history=history,
        system_prompt=SHOHI_SYSTEM_PROMPT,
        tools_schema=SHOHI_TOOLS,
        dispatch_tool=dispatch_tool,
    ):
        yield chunk
