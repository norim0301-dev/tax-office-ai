"""
相続税AIエージェント
Claude claude-opus-4-6 + Adaptive Thinking を使用したSSEストリーミング対応チャット
"""
import json
from typing import AsyncGenerator

from agents.ai_client import chat_stream

# ---- システムプロンプト ----
SOZOKU_SYSTEM_PROMPT = """あなたは税理士事務所の相続税・贈与税担当AIエージェントです。
【役割】相続税申告書作成サポート・財産評価・遺産分割アドバイス
【対応業務】相続税申告書、財産評価（預貯金・有価証券・不動産・生命保険）、小規模宅地等の特例、配偶者の税額軽減、贈与税申告、相続時精算課税
【応答スタイル】期限（10ヶ月）を常に意識、財産評価は専門家確認を促す、節税対策は合法的な範囲で提案する"""

# ---- ツール定義 ----
SOZOKU_TOOLS = [
    {
        "name": "calculate_inheritance_tax_basic",
        "description": "相続税の基礎控除額・課税遺産総額を計算し、申告要否を判定します。",
        "input_schema": {
            "type": "object",
            "properties": {
                "heirs_count": {
                    "type": "integer",
                    "description": "法定相続人の数"
                },
                "total_assets": {
                    "type": "number",
                    "description": "相続財産の総額（円）"
                },
                "total_debts": {
                    "type": "number",
                    "description": "債務（借入金・未払い税金等）の合計（円）"
                },
                "funeral_expenses": {
                    "type": "number",
                    "description": "葬儀費用の合計（円）"
                }
            },
            "required": ["heirs_count", "total_assets"]
        }
    },
    {
        "name": "check_small_land_special_provision",
        "description": "小規模宅地等の特例の適用可否・減額割合・要件をチェックします。",
        "input_schema": {
            "type": "object",
            "properties": {
                "land_use": {
                    "type": "string",
                    "enum": ["自宅", "貸付事業用", "事業用"],
                    "description": "土地の利用区分"
                },
                "heir_type": {
                    "type": "string",
                    "enum": ["配偶者", "同居親族", "別居親族", "その他"],
                    "description": "相続人の種別"
                },
                "has_own_home": {
                    "type": "boolean",
                    "description": "相続人が自己所有の住宅を持っているか（家なき子特例の判定に使用）"
                }
            },
            "required": ["land_use", "heir_type"]
        }
    },
    {
        "name": "generate_estate_document_list",
        "description": "相続税申告に必要な書類一覧・収集先・優先順位・残り期限を生成します。",
        "input_schema": {
            "type": "object",
            "properties": {
                "has_real_estate": {
                    "type": "boolean",
                    "description": "不動産（土地・建物）を相続するか"
                },
                "has_stocks": {
                    "type": "boolean",
                    "description": "有価証券（株式・投資信託等）を相続するか"
                },
                "has_insurance": {
                    "type": "boolean",
                    "description": "生命保険金を受け取るか"
                },
                "heirs_count": {
                    "type": "integer",
                    "description": "相続人の人数"
                },
                "months_since_death": {
                    "type": "number",
                    "description": "相続開始（死亡）からの経過月数"
                }
            },
            "required": ["has_real_estate", "has_stocks", "has_insurance", "heirs_count"]
        }
    },
    {
        "name": "calculate_gift_tax",
        "description": "贈与税額を計算します（暦年課税・相続時精算課税、各種特例を考慮）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "gift_amount": {
                    "type": "number",
                    "description": "贈与金額（円）"
                },
                "method": {
                    "type": "string",
                    "enum": ["暦年課税", "相続時精算課税"],
                    "description": "課税方式"
                },
                "is_spouse": {
                    "type": "boolean",
                    "description": "配偶者からの贈与か（配偶者控除2,000万円の適用可否判定に使用）"
                },
                "is_housing": {
                    "type": "boolean",
                    "description": "住宅取得等資金の贈与か（住宅取得等資金の特例適用可否判定に使用）"
                }
            },
            "required": ["gift_amount", "method"]
        }
    }
]


# ---- ツール実行関数 ----
def execute_calculate_inheritance_tax_basic(
    heirs_count: int,
    total_assets: float,
    total_debts: float = 0.0,
    funeral_expenses: float = 0.0
) -> str:
    """相続税の基礎控除・課税遺産総額を計算"""
    # 基礎控除額（3,000万円 + 600万円 × 法定相続人数）
    basic_deduction = 3000_0000 + 600_0000 * heirs_count

    # 正味遺産額（総資産 - 債務 - 葬儀費用）
    net_assets = total_assets - total_debts - funeral_expenses

    # 課税遺産総額
    taxable_estate = net_assets - basic_deduction

    needs_filing = taxable_estate > 0

    result = f"【相続税 基礎計算結果】\n\n"
    result += f"■ 法定相続人数：{heirs_count}名\n"
    result += f"■ 相続財産総額：{total_assets:,.0f}円\n"
    if total_debts > 0:
        result += f"■ 債務合計：{total_debts:,.0f}円\n"
    if funeral_expenses > 0:
        result += f"■ 葬儀費用：{funeral_expenses:,.0f}円\n"
    result += f"\n■ 正味遺産額：{net_assets:,.0f}円\n"
    result += f"■ 基礎控除額：{basic_deduction:,.0f}円\n"
    result += f"  （3,000万円 ＋ 600万円 × {heirs_count}名）\n\n"

    if needs_filing:
        result += f"■ 課税遺産総額：{taxable_estate:,.0f}円\n"
        result += f"\n【判定】申告が必要です。\n"
        result += f"相続開始から10ヶ月以内に申告・納付が必要です。\n"
        result += f"※ 各相続人の法定相続分に応じた税額計算は別途必要です。"
    else:
        result += f"■ 課税遺産総額：0円（基礎控除以下）\n"
        result += f"\n【判定】申告不要（基礎控除内に収まります）。\n"
        result += f"※ 配偶者の税額軽減・小規模宅地等の特例を適用する場合は、特例適用のために申告が必要です。"

    return result


def execute_check_small_land_special_provision(
    land_use: str,
    heir_type: str,
    has_own_home: bool = False
) -> str:
    """小規模宅地等の特例の適用可否チェック"""
    result = f"【小規模宅地等の特例 適用チェック】\n\n"
    result += f"■ 土地利用区分：{land_use}\n"
    result += f"■ 相続人種別：{heir_type}\n\n"

    if land_use == "自宅":
        # 特定居住用宅地等（限度面積330㎡、減額割合80%）
        result += "▼ 特定居住用宅地等に該当する可能性があります\n"
        result += "  限度面積：330㎡　減額割合：80%\n\n"

        if heir_type == "配偶者":
            result += "【判定】適用可（配偶者は無条件で適用可）\n"
            result += "要件：特になし（配偶者は居住・保有要件なし）\n"
        elif heir_type == "同居親族":
            result += "【判定】適用可（同居要件あり）\n"
            result += "要件：\n"
            result += "  ・相続開始直前から引き続き居住していること\n"
            result += "  ・相続税の申告期限まで引き続き居住・保有すること\n"
        elif heir_type == "別居親族":
            if not has_own_home:
                result += "【判定】家なき子特例の適用可能性あり\n"
                result += "要件（家なき子特例）：\n"
                result += "  ・配偶者・同居相続人がいないこと\n"
                result += "  ・相続開始前3年以内に自己・配偶者・3親等内の親族・関係法人所有家屋に居住していないこと\n"
                result += "  ・相続開始時に居住している家屋を過去に所有したことがないこと\n"
                result += "  ・申告期限まで保有し続けること\n"
            else:
                result += "【判定】適用不可（自己所有住宅あり）\n"
                result += "家なき子特例の要件（自己・配偶者所有家屋に住んでいない）を満たしません。\n"
        else:
            result += "【判定】適用不可（その他の相続人）\n"
            result += "特定居住用宅地等は配偶者・同居親族・家なき子のみ適用可。\n"

    elif land_use == "貸付事業用":
        # 貸付事業用宅地等（限度面積200㎡、減額割合50%）
        result += "▼ 貸付事業用宅地等に該当する可能性があります\n"
        result += "  限度面積：200㎡　減額割合：50%\n\n"
        result += "【判定】要件確認が必要\n"
        result += "要件：\n"
        result += "  ・相続開始直前から貸付事業（不動産貸付業等）の用に供されていること\n"
        result += "  ・相続人が申告期限まで貸付事業を継続し、土地を保有すること\n"
        result += "注意事項：\n"
        result += "  ・相続開始前3年以内に新たに貸付事業に供されたものは原則対象外\n"
        result += "  ・事業的規模（5棟10室基準）に満たない場合も適用可（ただし3年規制あり）\n"

    elif land_use == "事業用":
        # 特定事業用宅地等（限度面積400㎡、減額割合80%）
        result += "▼ 特定事業用宅地等に該当する可能性があります\n"
        result += "  限度面積：400㎡　減額割合：80%\n\n"
        result += "【判定】要件確認が必要\n"
        result += "要件：\n"
        result += "  ・被相続人等の事業（不動産貸付業等を除く）の用に供されていること\n"
        result += "  ・相続人が申告期限まで事業を継続し、土地を保有すること\n"
        result += "注意事項：\n"
        result += "  ・相続開始前3年以内に新たに事業供用されたものは対象外\n"
        result += "  ・同族会社への貸付地は「特定同族会社事業用宅地等」として別途判定\n"

    result += "\n【根拠条文】租税特別措置法第69条の4\n"
    result += "※ 実際の適用には詳細な要件確認が必要です。必ず専門家にご確認ください。"

    return result


def execute_generate_estate_document_list(
    has_real_estate: bool,
    has_stocks: bool,
    has_insurance: bool,
    heirs_count: int,
    months_since_death: float = 0.0
) -> str:
    """相続税申告必要書類リストを生成"""
    remaining_months = max(0, 10 - months_since_death)

    result = f"【相続税申告 必要書類リスト】\n\n"
    result += f"申告期限まで残り約 {remaining_months:.1f} ヶ月\n\n"

    # 優先度A: 全件共通書類
    result += "【優先度A：全件必須書類】\n"
    common_docs = [
        ("被相続人の戸籍謄本（出生〜死亡まで連続）", "本籍地市区町村役場"),
        ("相続人全員の戸籍謄本", "各相続人の本籍地市区町村役場"),
        ("相続人全員の住民票", "各相続人の居住市区町村役場"),
        ("被相続人の住民票（除票）", "被相続人の居住市区町村役場"),
        ("預貯金通帳・残高証明書（相続開始日現在）", "各金融機関"),
        ("過去3年間の贈与に関する資料（贈与契約書等）", "相続人手元"),
    ]
    for i, (doc, source) in enumerate(common_docs, 1):
        result += f"  □ {i}. {doc}\n     収集先: {source}\n"

    result += f"\n【優先度A：遺産分割関連】\n"
    result += f"  □ 遺産分割協議書（相続人{heirs_count}名全員の実印・印鑑証明書添付）\n"
    result += f"     ※ 遺言書がある場合は原本または検認済み謄本\n"
    result += f"  □ 相続人全員の印鑑証明書（発行3ヶ月以内）\n     収集先: 各相続人の居住市区町村役場\n"

    # 優先度B: 財産種別
    if has_real_estate:
        result += f"\n【優先度B：不動産関係書類】\n"
        re_docs = [
            ("登記事項証明書（全部事項証明書）", "法務局"),
            ("固定資産税評価証明書（相続開始年度）", "市区町村役場 課税課"),
            ("公図・地積測量図・建物図面", "法務局"),
            ("路線価図（国税庁ウェブサイトでも取得可）", "税務署・国税庁HP"),
            ("賃貸物件の場合: 賃貸借契約書・賃料収入明細", "相続人手元"),
        ]
        for i, (doc, source) in enumerate(re_docs, 1):
            result += f"  □ {i}. {doc}\n     収集先: {source}\n"

    if has_stocks:
        result += f"\n【優先度B：有価証券関係書類】\n"
        stock_docs = [
            ("証券口座の残高証明書（相続開始日現在）", "各証券会社"),
            ("株式等の取得価額・配当金の履歴", "各証券会社"),
            ("非上場株式の場合: 法人税申告書・決算書（直近3期分）", "発行会社"),
        ]
        for i, (doc, source) in enumerate(stock_docs, 1):
            result += f"  □ {i}. {doc}\n     収集先: {source}\n"

    if has_insurance:
        result += f"\n【優先度B：生命保険関係書類】\n"
        ins_docs = [
            ("生命保険金支払通知書", "各保険会社"),
            ("保険証券（契約内容確認用）", "相続人手元"),
            ("死亡診断書（写し）", "相続人手元"),
        ]
        for i, (doc, source) in enumerate(ins_docs, 1):
            result += f"  □ {i}. {doc}\n     収集先: {source}\n"

    # 優先度C: 債務・その他
    result += f"\n【優先度C：債務・控除関連書類】\n"
    debt_docs = [
        ("借入金残高証明書（相続開始日現在）", "各金融機関"),
        ("未払い公租公課の明細（固定資産税・住民税等）", "市区町村役場"),
        ("葬儀費用の領収書・明細書", "相続人手元"),
    ]
    for i, (doc, source) in enumerate(debt_docs, 1):
        result += f"  □ {i}. {doc}\n     収集先: {source}\n"

    if remaining_months < 3:
        result += f"\n⚠️ 【警告】申告期限まで残り{remaining_months:.1f}ヶ月です。至急書類収集・申告書作成を進めてください。\n"
    elif remaining_months < 6:
        result += f"\n【注意】申告期限まで残り{remaining_months:.1f}ヶ月です。計画的に書類を収集してください。\n"

    return result


def execute_calculate_gift_tax(
    gift_amount: float,
    method: str,
    is_spouse: bool = False,
    is_housing: bool = False
) -> str:
    """贈与税額を計算"""
    result = f"【贈与税 計算結果】\n\n"
    result += f"■ 贈与金額：{gift_amount:,.0f}円\n"
    result += f"■ 課税方式：{method}\n\n"

    if method == "暦年課税":
        basic_deduction = 110_0000  # 基礎控除110万円

        # 配偶者控除（婚姻20年以上、居住用不動産または取得資金）
        spouse_deduction = 0
        if is_spouse and is_housing:
            spouse_deduction = min(gift_amount - basic_deduction, 2000_0000)
            result += f"■ 配偶者控除（居住用不動産）：{spouse_deduction:,.0f}円\n"
            result += f"  ※ 婚姻期間20年以上・居住用不動産または取得資金が条件\n"

        taxable_amount = max(0, gift_amount - basic_deduction - spouse_deduction)
        result += f"■ 基礎控除：{basic_deduction:,.0f}円\n"
        result += f"■ 課税価格：{taxable_amount:,.0f}円\n\n"

        if taxable_amount <= 0:
            result += "【税額】0円（基礎控除・各種控除以内）\n"
            result += "申告不要です。"
        else:
            # 贈与税の速算表（一般税率）
            tax_brackets = [
                (200_0000, 0.10, 0),
                (300_0000, 0.15, 10_0000),
                (400_0000, 0.20, 25_0000),
                (600_0000, 0.30, 65_0000),
                (1000_0000, 0.40, 125_0000),
                (1500_0000, 0.45, 175_0000),
                (3000_0000, 0.50, 250_0000),
                (float('inf'), 0.55, 400_0000),
            ]
            tax = 0
            rate = 0
            deduct = 0
            for limit, r, d in tax_brackets:
                if taxable_amount <= limit:
                    tax = taxable_amount * r - d
                    rate = r
                    deduct = d
                    break

            result += f"【税額計算】\n"
            result += f"  {taxable_amount:,.0f}円 × {rate*100:.0f}% − {deduct:,.0f}円 = {tax:,.0f}円\n\n"
            result += f"【贈与税額】{tax:,.0f}円\n"
            result += f"申告期限：翌年3月15日\n"

    elif method == "相続時精算課税":
        # 基礎控除110万円（2024年改正後）+ 特別控除2,500万円
        annual_deduction = 110_0000
        special_deduction = 2500_0000

        taxable_after_annual = max(0, gift_amount - annual_deduction)
        taxable_after_special = max(0, taxable_after_annual - special_deduction)

        result += f"■ 基礎控除（年間）：{annual_deduction:,.0f}円\n"
        result += f"  ※ 2024年（令和6年）1月1日以後の贈与から適用\n"
        result += f"■ 特別控除（累計2,500万円まで）：最大{special_deduction:,.0f}円\n\n"

        if taxable_after_special <= 0:
            result += f"【今回の贈与税額】0円（特別控除範囲内）\n"
            result += f"※ 特別控除残高から {min(taxable_after_annual, special_deduction):,.0f}円 を使用します。\n\n"
        else:
            tax = taxable_after_special * 0.20
            result += f"【税額計算】\n"
            result += f"  特別控除超過額：{taxable_after_special:,.0f}円 × 20% = {tax:,.0f}円\n\n"
            result += f"【贈与税額】{tax:,.0f}円\n\n"

        result += "【注意事項】\n"
        result += "・相続時精算課税を選択すると、以後の贈与は全て相続時精算課税となります（暦年課税に戻れません）\n"
        result += "・相続発生時に相続財産に加算して相続税を精算します\n"
        result += "・初回選択時は「相続時精算課税選択届出書」の提出が必要です\n"
        result += "申告期限：翌年3月15日\n"

    if is_housing and not is_spouse:
        result += f"\n【住宅取得等資金の非課税特例】\n"
        result += "直系尊属からの住宅取得等資金の贈与については、別途非課税特例の適用が可能な場合があります。\n"
        result += "要件・非課税限度額は取得する住宅の種類によって異なりますので、詳細はご確認ください。\n"

    return result


# ---- ツール実行ディスパッチャ ----
def dispatch_tool(tool_name: str, tool_input: dict) -> str:
    if tool_name == "calculate_inheritance_tax_basic":
        return execute_calculate_inheritance_tax_basic(
            heirs_count=tool_input["heirs_count"],
            total_assets=tool_input["total_assets"],
            total_debts=tool_input.get("total_debts", 0.0),
            funeral_expenses=tool_input.get("funeral_expenses", 0.0)
        )
    elif tool_name == "check_small_land_special_provision":
        return execute_check_small_land_special_provision(
            land_use=tool_input["land_use"],
            heir_type=tool_input["heir_type"],
            has_own_home=tool_input.get("has_own_home", False)
        )
    elif tool_name == "generate_estate_document_list":
        return execute_generate_estate_document_list(
            has_real_estate=tool_input["has_real_estate"],
            has_stocks=tool_input["has_stocks"],
            has_insurance=tool_input["has_insurance"],
            heirs_count=tool_input["heirs_count"],
            months_since_death=tool_input.get("months_since_death", 0.0)
        )
    elif tool_name == "calculate_gift_tax":
        return execute_calculate_gift_tax(
            gift_amount=tool_input["gift_amount"],
            method=tool_input["method"],
            is_spouse=tool_input.get("is_spouse", False),
            is_housing=tool_input.get("is_housing", False)
        )
    else:
        return f"[エラー] 不明なツール: {tool_name}"


# ---- ツールのラベル定義 ----
TOOL_LABELS = {
    "calculate_inheritance_tax_basic": "相続税 基礎控除・課税遺産総額を計算中...",
    "check_small_land_special_provision": "小規模宅地等の特例 適用要件を確認中...",
    "generate_estate_document_list": "相続税申告 必要書類リストを作成中...",
    "calculate_gift_tax": "贈与税額を計算中...",
}


# ---- SSEストリーミングジェネレータ ----
async def sozoku_chat_stream(
    message: str,
    history: list[dict]
) -> AsyncGenerator[str, None]:
    """SSEストリーミングチャット（Gemini/Claude自動切替）"""
    async for chunk in chat_stream(
        message=message,
        history=history,
        system_prompt=SOZOKU_SYSTEM_PROMPT,
        tools_schema=SOZOKU_TOOLS,
        dispatch_tool=dispatch_tool,
    ):
        yield chunk
