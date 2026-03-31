"""
所得税AIエージェント
Claude claude-opus-4-6 + Adaptive Thinking を使用したSSEストリーミング対応チャット
"""
import json
from typing import AsyncGenerator

from agents.ai_client import chat_stream

# ---- システムプロンプト ----
SHOTOKU_SYSTEM_PROMPT = """あなたは税理士事務所の所得税担当AIエージェントです。
【役割】確定申告サポート・各種控除チェック・申告書作成補助
【対応業務】給与・事業・不動産・譲渡・一時・雑所得、医療費控除・住宅ローン控除・ふるさと納税・寄附金控除・扶養控除・配偶者控除
【応答スタイル】控除漏れがないか積極的に確認、e-Tax対応の注意点も案内する"""

# ---- ツール定義 ----
SHOTOKU_TOOLS = [
    {
        "name": "check_deductions",
        "description": "所得控除・税額控除の適用可否をチェックし、必要書類と注意事項を一覧で返します。",
        "input_schema": {
            "type": "object",
            "properties": {
                "has_medical": {
                    "type": "boolean",
                    "description": "医療費控除の対象となる医療費があるか"
                },
                "has_housing_loan": {
                    "type": "boolean",
                    "description": "住宅ローン控除（住宅借入金等特別控除）の適用があるか"
                },
                "has_furusato": {
                    "type": "boolean",
                    "description": "ふるさと納税（寄附金控除）をしているか"
                },
                "has_disability": {
                    "type": "boolean",
                    "description": "障害者控除の対象者（本人・配偶者・扶養親族）がいるか"
                },
                "has_elderly_parent": {
                    "type": "boolean",
                    "description": "老人扶養親族（70歳以上の親等）がいるか"
                },
                "spouse_income": {
                    "type": "number",
                    "description": "配偶者の合計所得金額（円）。配偶者控除・配偶者特別控除の判定に使用。"
                }
            },
            "required": ["has_medical", "has_housing_loan", "has_furusato"]
        }
    },
    {
        "name": "calculate_medical_expense_deduction",
        "description": "医療費控除の控除額を計算し、申告書への記載方法と対象外費用の例を返します。",
        "input_schema": {
            "type": "object",
            "properties": {
                "total_medical": {
                    "type": "number",
                    "description": "1年間に支払った医療費の合計額（円）"
                },
                "income": {
                    "type": "number",
                    "description": "申告者の総所得金額等（円）"
                },
                "insurance_reimbursement": {
                    "type": "number",
                    "description": "保険金等で補填される金額（健康保険の高額療養費・生命保険の入院給付等）（円）"
                }
            },
            "required": ["total_medical", "income"]
        }
    },
    {
        "name": "generate_filing_checklist",
        "description": "所得の種類に応じた確定申告の必要書類・提出方法・申告期限・注意事項を返します。",
        "input_schema": {
            "type": "object",
            "properties": {
                "income_types": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["給与", "事業", "不動産", "譲渡", "年金", "その他"]
                    },
                    "description": "申告する所得の種類（複数選択可）"
                },
                "is_first_time": {
                    "type": "boolean",
                    "description": "初めて確定申告をする場合はtrue"
                }
            },
            "required": ["income_types"]
        }
    }
]


# ---- ツール実行関数 ----
def execute_check_deductions(
    has_medical: bool,
    has_housing_loan: bool,
    has_furusato: bool,
    has_disability: bool = False,
    has_elderly_parent: bool = False,
    spouse_income: float = None
) -> str:
    """所得控除・税額控除のチェックリストを生成"""
    result = "【所得控除・税額控除チェックリスト】\n\n"

    result += "■ 基本控除（全員確認）\n"
    result += "  □ 基礎控除: 48万円（合計所得2,400万円以下の場合）\n"
    result += "    必要書類: 申告書への記載のみ（書類不要）\n\n"

    result += "■ 社会保険料控除\n"
    result += "  □ 健康保険料・国民年金・厚生年金等の保険料\n"
    result += "  □ 国民年金基金・付加保険料\n"
    result += "  必要書類: 社会保険料控除証明書（国民年金は11月以降に届く）\n\n"

    result += "■ 生命保険料控除\n"
    result += "  □ 一般生命保険料控除（最大4万円）\n"
    result += "  □ 介護医療保険料控除（最大4万円）\n"
    result += "  □ 個人年金保険料控除（最大4万円）\n"
    result += "  必要書類: 生命保険料控除証明書（各保険会社から秋頃送付）\n\n"

    result += "■ 地震保険料控除\n"
    result += "  □ 地震保険料: 最大5万円\n"
    result += "  必要書類: 地震保険料控除証明書\n\n"

    # 配偶者関連
    if spouse_income is not None:
        result += "■ 配偶者控除・配偶者特別控除\n"
        if spouse_income <= 480_000:
            result += f"  配偶者の所得: {spouse_income:,.0f}円 → 配偶者控除（38万円）が適用可能です\n"
            result += "  ※ 配偶者の合計所得が48万円以下の場合は配偶者控除\n"
        elif spouse_income <= 1_330_000:
            result += f"  配偶者の所得: {spouse_income:,.0f}円 → 配偶者特別控除が適用可能です\n"
            result += "  ※ 配偶者の合計所得133万円以下まで段階的に控除あり\n"
        else:
            result += f"  配偶者の所得: {spouse_income:,.0f}円 → 配偶者控除・配偶者特別控除は適用不可\n"
        result += "  必要書類: 配偶者の源泉徴収票（または収入が分かる書類）\n\n"

    # 扶養控除
    result += "■ 扶養控除（一般扶養: 38万円、特定扶養16〜18歳: 63万円）\n"
    result += "  □ 生計を一にする16歳以上の扶養親族（合計所得48万円以下）\n"
    result += "  必要書類: 扶養親族の収入証明（源泉徴収票等）\n\n"

    if has_elderly_parent:
        result += "■ 老人扶養親族控除（追加控除）\n"
        result += "  □ 70歳以上の扶養親族: 同居老親等48万円、その他38万円\n"
        result += "  必要書類: 生年月日の確認（戸籍・住民票等）\n\n"

    if has_disability:
        result += "■ 障害者控除\n"
        result += "  □ 一般障害者: 27万円\n"
        result += "  □ 特別障害者: 40万円\n"
        result += "  □ 同居特別障害者（扶養・配偶者）: 75万円\n"
        result += "  必要書類: 障害者手帳の写し等\n\n"

    if has_medical:
        result += "■ 医療費控除 ⭐ 申告が必要\n"
        result += "  □ 医療費控除額 = 実際の医療費 - 保険補填額 - (総所得金額等 × 5% または10万円の低い方)\n"
        result += "  □ 最高控除額: 200万円\n"
        result += "  □ セルフメディケーション税制との選択適用（どちらか一方のみ）\n"
        result += "  必要書類: 医療費控除の明細書（領収書の代わりに明細書で申告可）\n"
        result += "  ⚠️ 2017年以降、医療費の領収書は提出不要だが5年間保存義務あり\n\n"

    if has_housing_loan:
        result += "■ 住宅ローン控除（住宅借入金等特別控除）⭐ 税額控除\n"
        result += "  □ 初年度: 確定申告が必須（2年目以降は年末調整で対応可）\n"
        result += "  □ 控除額: 年末残高 × 0.7%（2022年以降取得）\n"
        result += "  □ 控除期間: 13年（新築・中古住宅等の条件による）\n"
        result += "  必要書類（初年度）:\n"
        result += "    ・住宅取得資金に係る借入金の年末残高等証明書\n"
        result += "    ・土地・建物の登記事項証明書\n"
        result += "    ・売買契約書または建築請負契約書の写し\n"
        result += "    ・住民票の写し\n"
        result += "  ⚠️ 省エネ基準等の要件確認が必要（2022年以降取得）\n\n"

    if has_furusato:
        result += "■ 寄附金控除（ふるさと納税）⭐ 申告が必要（ワンストップ特例未利用の場合）\n"
        result += "  □ 控除額 = (寄附金額 - 2,000円) × 所得税率\n"
        result += "  □ ワンストップ特例を利用した場合でも、他の理由で確定申告する場合は申告に含める\n"
        result += "  □ 住民税からも控除（基本分＋特例分）\n"
        result += "  必要書類: 寄附金受領証明書（各自治体から送付）\n"
        result += "  ⚠️ ワンストップ特例と確定申告は二重申請に注意\n\n"

    result += "■ 小規模企業共済等掛金控除\n"
    result += "  □ iDeCo（個人型確定拠出年金）掛金: 全額控除\n"
    result += "  □ 小規模企業共済掛金: 全額控除\n"
    result += "  必要書類: 小規模企業共済等掛金控除証明書\n\n"

    result += "⚠️ 控除漏れを防ぐため、上記すべての項目を確認してください。\n"
    result += "　特に医療費・住宅ローン・ふるさと納税は申告漏れが多い控除です。"

    return result


def execute_calculate_medical_expense_deduction(
    total_medical: float,
    income: float,
    insurance_reimbursement: float = 0
) -> str:
    """医療費控除額を計算"""
    if insurance_reimbursement is None:
        insurance_reimbursement = 0

    result = "【医療費控除額の計算】\n\n"
    result += f"支払医療費の合計: {total_medical:,.0f}円\n"
    result += f"保険金等で補填される金額: {insurance_reimbursement:,.0f}円\n"
    result += f"総所得金額等: {income:,.0f}円\n\n"

    # 実際の医療費（補填後）
    net_medical = total_medical - insurance_reimbursement
    if net_medical < 0:
        net_medical = 0

    # 足切り額（総所得金額等の5%または10万円の低い方）
    threshold_5pct = income * 0.05
    threshold = min(threshold_5pct, 100_000)

    # 控除額
    deduction = max(net_medical - threshold, 0)
    deduction = min(deduction, 2_000_000)  # 上限200万円

    result += "■ 計算式\n"
    result += f"  医療費控除額 = (支払医療費 - 保険補填額) - 足切り額\n"
    result += f"  足切り額 = 総所得金額等 × 5% と 10万円のうち低い方\n\n"

    result += "■ 計算過程\n"
    result += f"  支払医療費 - 保険補填額 = {net_medical:,.0f}円\n"
    result += f"  足切り額: min({threshold_5pct:,.0f}円, 100,000円) = {threshold:,.0f}円\n"
    result += f"  医療費控除額: {net_medical:,.0f}円 - {threshold:,.0f}円 = {deduction:,.0f}円\n\n"

    if deduction <= 0:
        result += "⚠️ 医療費控除は適用されません（足切り額以下のため）\n\n"
        result += f"  医療費があと {threshold - net_medical:,.0f}円 以上あれば控除を受けられます。\n"
    else:
        result += f"✅ 医療費控除額: {deduction:,.0f}円\n\n"

    result += "■ 申告書への記載方法\n"
    result += "  ① 医療費控除の明細書を作成（医療を受けた方・病院名・金額等を記載）\n"
    result += "  ② 第一表「医療費控除」欄に控除額を記入\n"
    result += "  ③ 明細書を申告書に添付（領収書の提出は不要、5年間保存）\n\n"

    result += "■ 医療費控除の対象となる主な費用\n"
    result += "  ✅ 対象: 診察・治療費、薬局の処方薬、入院費（食事代含む）、\n"
    result += "         通院交通費（公共交通機関）、介護費用（一部）\n\n"

    result += "■ 医療費控除の対象外となる主な費用\n"
    result += "  ❌ 対象外: 健康診断（異常発見後の治療は対象）、\n"
    result += "            予防接種、美容整形、視力回復レーシック（治療目的でない場合）、\n"
    result += "            健康増進目的のサプリ・栄養食品、自家用車の交通費\n\n"

    result += "■ セルフメディケーション税制（選択制）\n"
    result += "  対象の市販薬（OTC薬）が12,000円超の場合に適用可\n"
    result += "  控除額 = 支払額 - 12,000円（上限88,000円）\n"
    result += "  ※ 通常の医療費控除との選択適用（どちらか一方のみ）"

    return result


def execute_generate_filing_checklist(
    income_types: list,
    is_first_time: bool = False
) -> str:
    """確定申告チェックリストを生成"""
    result = "【確定申告チェックリスト】\n\n"
    result += f"申告する所得: {', '.join(income_types)}\n\n"

    if is_first_time:
        result += "■ 初回申告の準備（初めての方）\n"
        result += "  □ e-Taxの利用者識別番号を取得（税務署またはe-Taxウェブサイト）\n"
        result += "  □ マイナンバーカードの取得（スマホでのe-Tax申告に利用可）\n"
        result += "  □ 確定申告会場（税務署・申告相談会場）の確認\n\n"

    result += "■ 共通の必要書類\n"
    result += "  □ マイナンバーカード（または通知カード＋本人確認書類）\n"
    result += "  □ 前年度の確定申告書の控え（2年目以降）\n"
    result += "  □ 印鑑（郵送・持参の場合）\n\n"

    # 所得種別ごとの必要書類
    if "給与" in income_types:
        result += "■ 給与所得\n"
        result += "  □ 源泉徴収票（勤務先から交付、1月下旬〜2月頃）\n"
        result += "  □ 複数の勤務先がある場合は全社分\n"
        result += "  ⚠️ 給与所得者でも確定申告が必要な場合:\n"
        result += "    ・給与収入2,000万円超\n"
        result += "    ・2か所以上から給与を受け取っている\n"
        result += "    ・年末調整未実施\n"
        result += "    ・医療費控除・住宅ローン控除（初年度）等の適用\n\n"

    if "事業" in income_types:
        result += "■ 事業所得\n"
        result += "  □ 事業収入・経費の帳簿（青色申告は複式簿記）\n"
        result += "  □ 青色申告決算書（青色申告の場合）または収支内訳書\n"
        result += "  □ 売上・経費の領収書・請求書（7年間保存）\n"
        result += "  □ 固定資産台帳（減価償却資産がある場合）\n"
        result += "  ⚠️ 青色申告特別控除:\n"
        result += "    ・e-Tax申告 + 複式簿記 + 貸借対照表添付: 65万円控除\n"
        result += "    ・複式簿記 + 貸借対照表添付（紙申告）: 55万円控除\n"
        result += "    ・簡易帳簿: 10万円控除\n\n"

    if "不動産" in income_types:
        result += "■ 不動産所得\n"
        result += "  □ 賃料収入の明細（振込明細・契約書）\n"
        result += "  □ 固定資産税・都市計画税の通知書\n"
        result += "  □ 管理費・修繕費・損害保険料の領収書\n"
        result += "  □ 借入金がある場合: 返済明細書（利息部分が経費）\n"
        result += "  □ 減価償却計算（建物・設備の取得価額・取得年月日）\n"
        result += "  ⚠️ 不動産の赤字は給与所得等との損益通算が可能（土地取得の借入利息を除く）\n\n"

    if "譲渡" in income_types:
        result += "■ 譲渡所得（株式・不動産・その他）\n"
        result += "  【株式・投資信託の場合】\n"
        result += "  □ 年間取引報告書（証券会社から1月〜2月頃送付）\n"
        result += "  □ 特定口座（源泉徴収あり）でも確定申告で有利な場合あり\n"
        result += "  □ 損失の繰越控除（最長3年、確定申告が必要）\n"
        result += "  【不動産の場合】\n"
        result += "  □ 売却時の売買契約書\n"
        result += "  □ 取得時の売買契約書・建築費用の領収書（取得費の証明）\n"
        result += "  □ 仲介手数料・登記費用等の領収書\n"
        result += "  ⚠️ マイホーム売却の3,000万円特別控除・軽減税率の特例要件を確認\n\n"

    if "年金" in income_types:
        result += "■ 雑所得（公的年金等）\n"
        result += "  □ 公的年金等の源泉徴収票（年金支払機関から送付）\n"
        result += "  □ 公的年金等控除額の確認（年齢・収入額による）\n"
        result += "  ⚠️ 年金受給者の確定申告不要制度:\n"
        result += "    ・公的年金収入400万円以下かつ他の所得20万円以下 → 申告不要\n"
        result += "    ・ただし、医療費控除等を受ける場合は申告が必要\n\n"

    if "その他" in income_types:
        result += "■ その他の所得\n"
        result += "  □ 一時所得（満期保険金・懸賞金等）: 支払通知書・契約書\n"
        result += "  □ 副業収入（業務委託・フリーランス）: 支払調書・収入明細\n"
        result += "  □ 暗号資産（仮想通貨）: 取引履歴・損益計算書\n\n"

    result += "■ 提出方法と申告期限\n"
    result += "  申告・納付期限: 翌年3月15日（所得税）\n"
    result += "  還付申告: 翌年1月1日から5年間いつでも申告可能\n\n"

    result += "  【e-Tax（電子申告）の利用推奨】\n"
    result += "  □ マイナポータル連携で源泉徴収票・控除証明書を自動取得可能\n"
    result += "  □ 青色申告特別控除が65万円（紙申告は55万円）\n"
    result += "  □ 還付金が約3週間で振込（紙申告は約1〜2ヶ月）\n"
    result += "  □ 国税庁「確定申告書等作成コーナー」から申告書を作成可能\n\n"

    result += "  【郵送・持参の場合】\n"
    result += "  □ 管轄の税務署へ提出（住所地の税務署）\n"
    result += "  □ 申告書の控えに収受印をもらう場合は控えを同封\n\n"

    result += "⚠️ 期限を過ぎた場合の注意:\n"
    result += "  ・無申告加算税（15〜20%）が課される場合があります\n"
    result += "  ・延滞税（年率最大14.6%）も加算されます\n"
    result += "  ・青色申告の場合、期限後申告は特別控除が10万円に制限されます"

    return result


# ---- ツール実行ディスパッチャ ----
def dispatch_tool(tool_name: str, tool_input: dict) -> str:
    if tool_name == "check_deductions":
        return execute_check_deductions(
            has_medical=tool_input["has_medical"],
            has_housing_loan=tool_input["has_housing_loan"],
            has_furusato=tool_input["has_furusato"],
            has_disability=tool_input.get("has_disability", False),
            has_elderly_parent=tool_input.get("has_elderly_parent", False),
            spouse_income=tool_input.get("spouse_income")
        )
    elif tool_name == "calculate_medical_expense_deduction":
        return execute_calculate_medical_expense_deduction(
            total_medical=tool_input["total_medical"],
            income=tool_input["income"],
            insurance_reimbursement=tool_input.get("insurance_reimbursement", 0)
        )
    elif tool_name == "generate_filing_checklist":
        return execute_generate_filing_checklist(
            income_types=tool_input["income_types"],
            is_first_time=tool_input.get("is_first_time", False)
        )
    else:
        return f"[エラー] 不明なツール: {tool_name}"


# ---- ツールラベルマッピング ----
TOOL_LABELS = {
    "check_deductions": "適用可能な控除を確認中...",
    "calculate_medical_expense_deduction": "医療費控除額を計算中...",
    "generate_filing_checklist": "確定申告チェックリストを生成中...",
}


# ---- SSEストリーミングジェネレータ ----
async def shotoku_chat_stream(
    message: str,
    history: list[dict]
) -> AsyncGenerator[str, None]:
    """SSEストリーミングチャット（Gemini/Claude自動切替）"""
    async for chunk in chat_stream(
        message=message,
        history=history,
        system_prompt=SHOTOKU_SYSTEM_PROMPT,
        tools_schema=SHOTOKU_TOOLS,
        dispatch_tool=dispatch_tool,
    ):
        yield chunk
