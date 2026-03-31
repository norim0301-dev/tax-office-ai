"""
土地評価AIエージェント
Claude claude-opus-4-6 + Adaptive Thinking を使用したSSEストリーミング対応チャット
"""
import json
from typing import AsyncGenerator

from agents.ai_client import chat_stream

# ---- システムプロンプト ----
TOCHI_SYSTEM_PROMPT = """あなたは税理士事務所の土地評価担当AIエージェントです。
【役割】路線価評価・補正率計算・評価明細書作成補助
【対応業務】路線価方式による土地評価、奥行価格補正・側方路線影響加算・不整形地補正・規模格差補正、評価明細書、固定資産税評価額方式
【応答スタイル】補正率は必ず根拠（財産評価基本通達）を示す、評価額に影響する地形・利用状況は必ず確認する"""

# ---- ツール定義 ----
TOCHI_TOOLS = [
    {
        "name": "calculate_land_value_route_price",
        "description": "路線価方式による土地評価額を計算します。奥行価格補正率・各種補正を考慮した評価額を算出します。",
        "input_schema": {
            "type": "object",
            "properties": {
                "route_price": {
                    "type": "number",
                    "description": "路線価（千円/㎡）。路線価図に記載された数値"
                },
                "area": {
                    "type": "number",
                    "description": "地積（㎡）"
                },
                "depth": {
                    "type": "number",
                    "description": "奥行距離（m）。間口から最も遠い部分までの距離"
                },
                "frontage": {
                    "type": "number",
                    "description": "間口距離（m）。道路に接する部分の長さ"
                },
                "shape": {
                    "type": "string",
                    "enum": ["整形地", "不整形地", "旗竿地"],
                    "description": "土地の形状"
                },
                "road_sides": {
                    "type": "integer",
                    "enum": [1, 2, 3, 4],
                    "description": "接道面数（1:一方路、2:二方路・角地、3:三方路、4:四方路）"
                }
            },
            "required": ["route_price", "area"]
        }
    },
    {
        "name": "check_land_correction_factors",
        "description": "土地の利用区分・地形・用途に応じた各種補正率をチェックし、評価明細書への記載ポイントを提示します。",
        "input_schema": {
            "type": "object",
            "properties": {
                "land_type": {
                    "type": "string",
                    "enum": ["自用地", "貸宅地", "貸家建付地", "借地権"],
                    "description": "土地の利用区分"
                },
                "area": {
                    "type": "number",
                    "description": "地積（㎡）"
                },
                "has_irregular_shape": {
                    "type": "boolean",
                    "description": "不整形地（正方形・長方形以外）か否か"
                },
                "has_private_road": {
                    "type": "boolean",
                    "description": "私道部分が含まれるか否か"
                },
                "usage": {
                    "type": "string",
                    "enum": ["住宅地", "商業地", "工業地"],
                    "description": "土地の用途地域区分（路線価図の地区区分）"
                }
            },
            "required": ["land_type", "area", "has_irregular_shape"]
        }
    },
    {
        "name": "generate_land_evaluation_memo",
        "description": "土地評価メモ・現地確認事項・収集すべき資料リスト・評価上の注意点を生成します。",
        "input_schema": {
            "type": "object",
            "properties": {
                "client_name": {
                    "type": "string",
                    "description": "顧客名"
                },
                "address": {
                    "type": "string",
                    "description": "土地の所在地（住所）"
                },
                "land_area": {
                    "type": "number",
                    "description": "地積（㎡）"
                },
                "purpose": {
                    "type": "string",
                    "enum": ["相続税申告", "贈与税申告", "売買参考", "その他"],
                    "description": "評価目的"
                }
            },
            "required": ["client_name", "address", "land_area", "purpose"]
        }
    }
]


# ---- ツール実行関数 ----
def execute_calculate_land_value_route_price(
    route_price: float,
    area: float,
    depth: float = None,
    frontage: float = None,
    shape: str = "整形地",
    road_sides: int = 1
) -> str:
    """路線価方式による土地評価額を計算"""

    # 奥行価格補正率表（財産評価基本通達15）
    # 地区区分: 普通住宅地区の補正率（代表値）
    # 奥行距離（m）: 補正率
    depth_correction_table = [
        (4, 0.90),
        (6, 0.92),
        (8, 0.95),
        (10, 0.97),
        (12, 1.00),
        (14, 1.00),
        (16, 1.00),
        (20, 1.00),
        (24, 0.99),
        (28, 0.98),
        (32, 0.98),
        (36, 0.97),
        (40, 0.96),
        (44, 0.95),
        (48, 0.94),
        (52, 0.93),
        (56, 0.92),
        (60, 0.91),
        (64, 0.90),
        (68, 0.89),
        (72, 0.88),
        (76, 0.87),
        (80, 0.87),
        (float('inf'), 0.87),
    ]

    # 奥行価格補正率を取得
    depth_correction = 1.00
    depth_correction_str = "1.00（奥行距離未入力のため補正なし）"
    if depth is not None:
        for limit, rate in depth_correction_table:
            if depth <= limit:
                depth_correction = rate
                depth_correction_str = f"{rate:.2f}（奥行{depth}m）"
                break

    # 補正後路線価（千円/㎡）
    adjusted_route_price = route_price * depth_correction

    # 間口狭小補正率（財産評価基本通達20）
    frontage_correction = 1.00
    frontage_correction_str = "1.00（間口距離未入力のため補正なし）"
    if frontage is not None:
        if frontage < 4:
            frontage_correction = 0.85
            frontage_correction_str = f"0.85（間口{frontage}m、4m未満）"
        elif frontage < 6:
            frontage_correction = 0.90
            frontage_correction_str = f"0.90（間口{frontage}m、4m以上6m未満）"
        elif frontage < 8:
            frontage_correction = 0.95
            frontage_correction_str = f"0.95（間口{frontage}m、6m以上8m未満）"
        else:
            frontage_correction_str = f"1.00（間口{frontage}m、8m以上）"

    # 不整形地・旗竿地補正
    shape_correction = 1.00
    shape_correction_str = "1.00（整形地）"
    if shape == "不整形地":
        # 簡易的な補正率（実際は想定整形地との面積比等で算定）
        shape_correction = 0.90
        shape_correction_str = "0.90〜（不整形地補正・詳細計算要）"
    elif shape == "旗竿地":
        shape_correction = 0.80
        shape_correction_str = "0.80〜（旗竿地・間口狭小と組み合わせ）"

    # 側方路線影響加算率（財産評価基本通達16）
    side_road_addition = 0.0
    side_road_str = "なし"
    if road_sides == 2:
        side_road_addition = route_price * 0.03  # 角地の場合 3%（普通住宅地区）
        side_road_str = f"側方路線影響加算：路線価 × 3% = {side_road_addition:,.1f}千円/㎡（角地・二方路）"
    elif road_sides == 3:
        side_road_addition = route_price * 0.05
        side_road_str = f"側方路線影響加算：路線価 × 5% = {side_road_addition:,.1f}千円/㎡（三方路）"
    elif road_sides == 4:
        side_road_addition = route_price * 0.07
        side_road_str = f"側方路線影響加算：路線価 × 7% = {side_road_addition:,.1f}千円/㎡（四方路）"

    # 最終的な1㎡あたり評価額（千円）
    final_unit_price = (adjusted_route_price + side_road_addition) * frontage_correction * shape_correction

    # 評価額（円）
    evaluation_value = final_unit_price * 1000 * area

    result = f"【路線価方式 土地評価額計算】\n\n"
    result += f"■ 路線価：{route_price:,.0f}千円/㎡（{route_price*1000:,.0f}円/㎡）\n"
    result += f"■ 地積：{area:,.1f}㎡\n\n"

    result += f"【適用補正率】\n"
    result += f"  ① 奥行価格補正率：{depth_correction_str}\n"
    result += f"     根拠：財産評価基本通達15\n"
    result += f"  ② 間口狭小補正率：{frontage_correction_str}\n"
    result += f"     根拠：財産評価基本通達20\n"
    result += f"  ③ 不整形地等補正：{shape_correction_str}\n"
    result += f"     根拠：財産評価基本通達20-2〜20-6\n"
    result += f"  ④ 側方路線影響加算：{side_road_str}\n"
    result += f"     根拠：財産評価基本通達16\n\n"

    result += f"【計算過程】\n"
    result += f"  補正後路線価：{route_price:,.1f} × {depth_correction:.2f}（奥行補正）+ {side_road_addition:,.1f}（側方加算）\n"
    result += f"              = {adjusted_route_price + side_road_addition:,.1f}千円/㎡\n"
    result += f"  間口・形状補正後：{adjusted_route_price + side_road_addition:,.1f} × {frontage_correction:.2f} × {shape_correction:.2f}\n"
    result += f"              = {final_unit_price:,.2f}千円/㎡\n\n"

    result += f"【評価額】\n"
    result += f"  {final_unit_price:,.2f}千円/㎡ × {area:,.1f}㎡ = {evaluation_value:,.0f}円\n"
    result += f"  （{evaluation_value/10000:,.1f}万円）\n\n"

    result += f"【注意事項】\n"
    result += f"  ・上記は簡易計算です。実際の申告では評価明細書（第11表）への正式記載が必要です。\n"
    result += f"  ・不整形地・旗竿地の補正率は想定整形地・かげ地割合・地積区分により異なります。詳細計算が必要です。\n"
    result += f"  ・側方路線影響加算率は地区区分（路線価図の記号）によって異なります。\n"
    result += f"  ・規模格差補正（三大都市圏500㎡以上・その他750㎡以上）が適用できる場合があります。\n"

    return result


def execute_check_land_correction_factors(
    land_type: str,
    area: float,
    has_irregular_shape: bool,
    has_private_road: bool = False,
    usage: str = "住宅地"
) -> str:
    """土地の各種補正率チェック"""
    result = f"【土地評価 補正率チェック】\n\n"
    result += f"■ 利用区分：{land_type}\n"
    result += f"■ 地積：{area:,.1f}㎡\n"
    result += f"■ 形状：{'不整形地' if has_irregular_shape else '整形地'}\n"
    result += f"■ 用途地域：{usage}\n\n"

    result += "【適用すべき補正率一覧】\n\n"

    # 自用地・貸宅地・貸家建付地・借地権の補正
    result += f"▼ 利用区分補正（財産評価基本通達）\n"
    if land_type == "自用地":
        result += "  補正率：1.00（自用地は補正なし・評価額そのまま）\n"
        result += "  根拠：財産評価基本通達25\n"
    elif land_type == "貸宅地":
        result += "  補正率：1.00 − 借地権割合（通常0.30〜0.70）\n"
        result += "  例）借地権割合60%の場合：1.00 − 0.60 = 0.40\n"
        result += "  根拠：財産評価基本通達25\n"
        result += "  ※ 借地権割合は路線価図に記載（A〜Gの記号で示される）\n"
    elif land_type == "貸家建付地":
        result += "  補正率：1.00 − 借地権割合 × 借家権割合 × 賃貸割合\n"
        result += "  例）借地権割合60%・借家権割合30%・賃貸割合100%の場合：\n"
        result += "       1.00 − 0.60 × 0.30 × 1.00 = 0.82\n"
        result += "  根拠：財産評価基本通達26\n"
        result += "  ※ 借家権割合は全国一律30%（令和2年以降）\n"
    elif land_type == "借地権":
        result += "  評価額：自用地評価額 × 借地権割合\n"
        result += "  例）自用地1億円・借地権割合60%の場合：1億円 × 0.60 = 6,000万円\n"
        result += "  根拠：財産評価基本通達27\n"

    # 不整形地補正
    if has_irregular_shape:
        result += f"\n▼ 不整形地補正（財産評価基本通達20-2）\n"
        result += "  補正率：かげ地割合・地積区分・地区区分から算出\n"
        if area < 500:
            result += f"  地積区分：A（{area:,.0f}㎡、500㎡未満）\n"
        elif area < 750:
            result += f"  地積区分：B（{area:,.0f}㎡、500〜750㎡未満）\n"
        else:
            result += f"  地積区分：C（{area:,.0f}㎡、750㎡以上）\n"
        result += "  ※ 実際の補正率は想定整形地の面積を測定し、かげ地割合を算出して確定します\n"
        result += "  ※ 不整形地補正率は間口狭小補正率との組み合わせで適用（低い方の補正率を採用）\n"

    # 私道補正
    if has_private_road:
        result += f"\n▼ 私道の評価（財産評価基本通達24）\n"
        result += "  補正率：0.30（不特定多数が利用する私道は0（評価しない））\n"
        result += "  根拠：財産評価基本通達24\n"
        result += "  ※ 通り抜け私道（公衆用道路）は原則として評価しない\n"

    # 規模格差補正
    if usage == "住宅地":
        threshold = 500 if True else 750  # 簡易的に三大都市圏想定
        if area >= threshold:
            result += f"\n▼ 規模格差補正（財産評価基本通達20-2）\n"
            result += f"  地積：{area:,.1f}㎡（{threshold}㎡以上のため適用検討要）\n"
            result += f"  補正率：地積・地区区分により0.60〜0.85程度\n"
            result += f"  根拠：財産評価基本通達20-2（広大地通達の廃止後、規模格差補正に移行）\n"
            result += f"  ※ 三大都市圏：500㎡以上、その他地域：1,000㎡以上から適用\n"

    # 評価明細書への記載ポイント
    result += f"\n【評価明細書（第11・11の2表）記載ポイント】\n"
    result += f"  ① 土地の所在・地番・地目・地積を正確に転記\n"
    result += f"  ② 路線価図の写しを添付（路線価・借地権割合記号を確認）\n"
    result += f"  ③ 補正率は根拠通達番号と対応する付表番号を明記\n"
    result += f"  ④ 不整形地の場合は想定整形地の図面を作成・添付\n"
    if land_type in ("貸宅地", "貸家建付地"):
        result += f"  ⑤ 賃貸借契約書の写しを添付（賃貸割合の根拠として）\n"

    return result


def execute_generate_land_evaluation_memo(
    client_name: str,
    address: str,
    land_area: float,
    purpose: str
) -> str:
    """土地評価メモ・確認事項リスト生成"""
    result = f"【土地評価メモ】\n"
    result += f"━━━━━━━━━━━━━━━━━━━━━\n"
    result += f"顧客名：{client_name} 様\n"
    result += f"所在地：{address}\n"
    result += f"地積　：{land_area:,.1f}㎡\n"
    result += f"評価目的：{purpose}\n"
    result += f"━━━━━━━━━━━━━━━━━━━━━\n\n"

    result += "【収集すべき資料一覧】\n\n"
    docs = [
        ("公図（地図に準ずる図面）", "法務局", "A"),
        ("地積測量図（あれば）", "法務局", "A"),
        ("登記事項証明書（全部事項証明書）", "法務局", "A"),
        ("固定資産税評価証明書（評価年度）", "市区町村役場 課税課", "A"),
        ("路線価図（国税庁財産評価基準書）", "国税庁ウェブサイト / 税務署", "A"),
        ("住宅地図・ゼンリン地図", "市販・図書館", "B"),
        ("都市計画図（用途地域・建ぺい率・容積率）", "市区町村役場 都市計画課", "B"),
    ]

    if purpose in ("相続税申告", "贈与税申告"):
        docs += [
            ("被相続人（贈与者）の登記識別情報・権利証", "依頼人手元", "A"),
        ]

    result += "  優先度A：必須書類\n"
    for doc, source, priority in docs:
        if priority == "A":
            result += f"  □ {doc}\n     収集先：{source}\n"

    result += "\n  優先度B：確認推奨書類\n"
    for doc, source, priority in docs:
        if priority == "B":
            result += f"  □ {doc}\n     収集先：{source}\n"

    result += "\n【現地確認事項】\n\n"
    result += "  □ 1. 土地の形状・実際の間口・奥行の確認（公図との照合）\n"
    result += "  □ 2. 接道状況の確認（道路の種類：公道/私道、幅員、接道面数）\n"
    result += "  □ 3. 建物の有無・利用状況（自宅/賃貸/空き地等）\n"
    result += "  □ 4. 隣地との高低差・擁壁の有無\n"
    result += "  □ 5. 電柱・ガスメーター等の設備の位置\n"
    result += "  □ 6. 旗竿地・不整形地・角地等の特殊形状の有無\n"
    result += "  □ 7. 私道・通路部分が含まれていないか\n"
    result += "  □ 8. 土地の境界標の有無・隣地との境界確定状況\n"
    if land_area >= 500:
        result += f"  □ 9. 地積が{land_area:,.0f}㎡（規模格差補正対象の可能性）→ 規模格差補正の適用検討\n"

    result += "\n【評価上の注意点】\n\n"

    if purpose == "相続税申告":
        result += "  ・評価時点は相続開始日（被相続人の死亡日）の路線価を使用\n"
        result += "  ・路線価が設定されていない地域は固定資産税評価額 × 倍率方式を採用\n"
        result += "  ・小規模宅地等の特例の適用可否を必ず検討すること\n"
    elif purpose == "贈与税申告":
        result += "  ・評価時点は贈与契約日（贈与の効力発生日）の路線価を使用\n"
        result += "  ・相続時精算課税を選択している場合は特に評価額の正確性が重要\n"
    elif purpose == "売買参考":
        result += "  ・路線価評価額は実勢価格の目安（路線価は公示価格の80%水準が目安）\n"
        result += "  ・売買価格の参考として使用する際は不動産鑑定評価と併用を推奨\n"

    result += "  ・地目は登記地目と現況地目が異なる場合は現況地目で評価\n"
    result += "  ・建築基準法上の道路（2項道路のセットバック部分）がある場合は評価面積から除外\n"
    result += "  ・土壌汚染・埋設物等がある場合は評価減の適用を検討\n"
    result += "  ・評価明細書（相続税の場合：第11表・11の2表）に全補正根拠を記載すること\n\n"

    result += "【担当者メモ欄】\n"
    result += "  （現地確認日：　　　　　担当：　　　　　）\n"
    result += "  特記事項：\n\n"
    result += "※ このメモはAIが作成した評価補助資料です。実際の申告前に必ず専門家が内容を確認してください。"

    return result


# ---- ツール実行ディスパッチャ ----
def dispatch_tool(tool_name: str, tool_input: dict) -> str:
    if tool_name == "calculate_land_value_route_price":
        return execute_calculate_land_value_route_price(
            route_price=tool_input["route_price"],
            area=tool_input["area"],
            depth=tool_input.get("depth"),
            frontage=tool_input.get("frontage"),
            shape=tool_input.get("shape", "整形地"),
            road_sides=tool_input.get("road_sides", 1)
        )
    elif tool_name == "check_land_correction_factors":
        return execute_check_land_correction_factors(
            land_type=tool_input["land_type"],
            area=tool_input["area"],
            has_irregular_shape=tool_input["has_irregular_shape"],
            has_private_road=tool_input.get("has_private_road", False),
            usage=tool_input.get("usage", "住宅地")
        )
    elif tool_name == "generate_land_evaluation_memo":
        return execute_generate_land_evaluation_memo(
            client_name=tool_input["client_name"],
            address=tool_input["address"],
            land_area=tool_input["land_area"],
            purpose=tool_input["purpose"]
        )
    else:
        return f"[エラー] 不明なツール: {tool_name}"


# ---- ツールのラベル定義 ----
TOOL_LABELS = {
    "calculate_land_value_route_price": "路線価方式で土地評価額を計算中...",
    "check_land_correction_factors": "土地の各種補正率を確認中...",
    "generate_land_evaluation_memo": "土地評価メモ・確認事項リストを作成中...",
}


# ---- SSEストリーミングジェネレータ ----
async def tochi_chat_stream(
    message: str,
    history: list[dict]
) -> AsyncGenerator[str, None]:
    """SSEストリーミングチャット（Gemini/Claude自動切替）"""
    async for chunk in chat_stream(
        message=message,
        history=history,
        system_prompt=TOCHI_SYSTEM_PROMPT,
        tools_schema=TOCHI_TOOLS,
        dispatch_tool=dispatch_tool,
    ):
        yield chunk
