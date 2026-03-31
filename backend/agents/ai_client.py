"""
AI プロバイダー抽象化レイヤー
Gemini / Claude を切り替え可能にする共通モジュール
無料枠最大化: モデル自動ローテーション + リトライ機能
"""
import json
import os
import asyncio
from typing import AsyncGenerator, Callable

# ---- プロバイダー選択 ----
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

USE_GEMINI = bool(GOOGLE_API_KEY and "ここに" not in GOOGLE_API_KEY)
USE_CLAUDE = bool(ANTHROPIC_API_KEY and "ここに" not in ANTHROPIC_API_KEY) and not USE_GEMINI

PROVIDER = "gemini" if USE_GEMINI else "claude" if USE_CLAUDE else "none"

# ---- Gemini モデルローテーション設定 ----
# 各モデル1日20回の無料枠 → 合計60回/日
GEMINI_MODEL_POOL = [
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
]

# モデルごとの使用回数を追跡（サーバー再起動でリセット）
_model_usage = {m: 0 for m in GEMINI_MODEL_POOL}
_model_exhausted = set()  # 429が返ったモデル
_current_model_index = 0


def _get_next_model() -> str:
    """使用可能なモデルを順番に選択（ラウンドロビン）"""
    global _current_model_index

    available = [m for m in GEMINI_MODEL_POOL if m not in _model_exhausted]
    if not available:
        # 全モデル使い切り → None を返して呼び出し側で処理
        return None

    # ラウンドロビンで最も使用回数が少ないモデルを選ぶ
    available.sort(key=lambda m: _model_usage.get(m, 0))
    return available[0]


def _mark_model_used(model_name: str):
    """モデル使用回数を記録"""
    _model_usage[model_name] = _model_usage.get(model_name, 0) + 1


def _mark_model_exhausted(model_name: str):
    """モデルの日次クォータ超過を記録"""
    _model_exhausted.add(model_name)


# ========================================
#  Gemini 実装
# ========================================
_gemini_configured = False


def _ensure_gemini():
    global _gemini_configured
    if not _gemini_configured:
        import google.generativeai as genai
        genai.configure(api_key=GOOGLE_API_KEY)
        _gemini_configured = True


def _convert_tools_to_gemini(anthropic_tools: list[dict]):
    """Anthropic形式のツール定義をGemini形式に変換"""
    import google.generativeai as genai

    func_declarations = []
    for tool in anthropic_tools:
        schema = tool.get("input_schema", {})
        func_declarations.append(
            genai.protos.FunctionDeclaration(
                name=tool["name"],
                description=tool.get("description", ""),
                parameters=_convert_schema(schema) if schema.get("properties") else None
            )
        )
    return [genai.protos.Tool(function_declarations=func_declarations)]


def _convert_schema(schema: dict):
    """JSON Schema を Gemini の Schema proto に変換"""
    import google.generativeai as genai

    type_map = {
        "string": genai.protos.Type.STRING,
        "integer": genai.protos.Type.INTEGER,
        "number": genai.protos.Type.NUMBER,
        "boolean": genai.protos.Type.BOOLEAN,
        "array": genai.protos.Type.ARRAY,
        "object": genai.protos.Type.OBJECT,
    }

    schema_type = type_map.get(schema.get("type", "object"), genai.protos.Type.OBJECT)
    kwargs = {"type": schema_type}

    if "description" in schema:
        kwargs["description"] = schema["description"]
    if "enum" in schema:
        kwargs["enum"] = schema["enum"]
    if "properties" in schema:
        kwargs["properties"] = {
            k: _convert_schema(v) for k, v in schema["properties"].items()
        }
    if "required" in schema:
        kwargs["required"] = schema["required"]
    if "items" in schema:
        kwargs["items"] = _convert_schema(schema["items"])

    return genai.protos.Schema(**kwargs)


def _build_gemini_history(history: list[dict]):
    """チャット履歴をGemini形式に変換"""
    import google.generativeai as genai

    gemini_history = []
    for h in history:
        role = h.get("role", "user")
        content = h.get("content", "")
        if not content or role not in ("user", "assistant"):
            continue
        gemini_role = "model" if role == "assistant" else "user"
        gemini_history.append(
            genai.protos.Content(
                role=gemini_role,
                parts=[genai.protos.Part(text=content)]
            )
        )
    return gemini_history


async def gemini_chat_stream(
    message: str,
    history: list[dict],
    system_prompt: str,
    tools_schema: list[dict],
    dispatch_tool: Callable,
    model_name: str = None,
) -> AsyncGenerator[str, None]:
    """
    Gemini APIでチャット（ツール使用ループ対応）
    429エラー時は自動で別モデルにフォールバック
    """
    import google.generativeai as genai

    _ensure_gemini()

    # モデル選択（指定がなければローテーション）
    if model_name is None:
        model_name = _get_next_model()

    # 全モデル使い切りチェック
    if model_name is None:
        remaining = _get_quota_status()
        err_msg = "本日の無料枠（全モデル合計）を使い切りました。明日リセットされます。\n\n" + remaining
        yield f"data: {json.dumps({'type': 'error', 'error': err_msg}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
        return

    # ツール変換
    gemini_tools = _convert_tools_to_gemini(tools_schema) if tools_schema else None

    # モデル作成
    model = genai.GenerativeModel(
        model_name=model_name,
        system_instruction=system_prompt,
        tools=gemini_tools,
    )

    # 履歴構築
    gemini_history = _build_gemini_history(history)
    chat = model.start_chat(history=gemini_history)

    max_iterations = 5
    current_input = message

    for iteration in range(max_iterations):
        full_text = ""
        function_calls = []

        try:
            response = await chat.send_message_async(current_input)
            _mark_model_used(model_name)

            # レスポンスのパーツを処理
            for part in response.parts:
                if hasattr(part, 'text') and part.text:
                    full_text += part.text
                    text = part.text
                    chunk_size = 80
                    for i in range(0, len(text), chunk_size):
                        yield f"data: {json.dumps({'type': 'text', 'text': text[i:i+chunk_size]}, ensure_ascii=False)}\n\n"

                if hasattr(part, 'function_call') and part.function_call.name:
                    function_calls.append(part.function_call)

        except Exception as e:
            error_msg = str(e)

            # 429 レート制限エラー → 別モデルにフォールバック
            if "429" in error_msg or "quota" in error_msg.lower() or "resource" in error_msg.lower():
                _mark_model_exhausted(model_name)

                # 別のモデルを探す
                fallback = _get_next_model()
                if fallback is not None and fallback != model_name:
                    switch_msg = "（" + model_name + "の制限に達しました。" + fallback + "に切り替えます...）\n"
                    yield f"data: {json.dumps({'type': 'text', 'text': switch_msg}, ensure_ascii=False)}\n\n"

                    # フォールバックモデルで再試行（再帰ではなくループで処理）
                    async for chunk in gemini_chat_stream(
                        message, history, system_prompt, tools_schema, dispatch_tool, fallback
                    ):
                        yield chunk
                    return
                else:
                    # 全モデル使い切り
                    remaining = _get_quota_status()
                    err_msg = "本日の無料枠（全モデル合計）を使い切りました。明日リセットされます。\n\n" + remaining
                    yield f"data: {json.dumps({'type': 'error', 'error': err_msg}, ensure_ascii=False)}\n\n"
                    yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
                    return

            elif "API_KEY" in error_msg.upper():
                yield f"data: {json.dumps({'type': 'error', 'error': 'APIキーが無効です。GOOGLE_API_KEYを確認してください。'}, ensure_ascii=False)}\n\n"
            else:
                yield f"data: {json.dumps({'type': 'error', 'error': f'Gemini APIエラー: {error_msg}'}, ensure_ascii=False)}\n\n"
            return

        # ツール使用がなければ終了
        if not function_calls:
            break

        # ツールを実行して結果を返す
        function_responses = []
        for fc in function_calls:
            tool_name = fc.name
            tool_args = dict(fc.args) if fc.args else {}

            yield f"data: {json.dumps({'type': 'tool_use', 'tool': tool_name, 'input': tool_args}, ensure_ascii=False)}\n\n"

            try:
                result = dispatch_tool(tool_name, tool_args)
            except Exception as e:
                result = f"[ツール実行エラー] {str(e)}"

            yield f"data: {json.dumps({'type': 'tool_result', 'tool': tool_name}, ensure_ascii=False)}\n\n"

            function_responses.append(
                genai.protos.Part(
                    function_response=genai.protos.FunctionResponse(
                        name=tool_name,
                        response={"result": result}
                    )
                )
            )

        current_input = genai.protos.Content(parts=function_responses)

    yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"


def _get_quota_status() -> str:
    """現在のクォータ使用状況を返す"""
    lines = ["【本日の使用状況】"]
    for m in GEMINI_MODEL_POOL:
        used = _model_usage.get(m, 0)
        exhausted = "❌ 制限到達" if m in _model_exhausted else f"✅ {used}回使用"
        lines.append(f"  {m}: {exhausted}")
    total = sum(_model_usage.values())
    lines.append(f"\n合計: {total}回 / 約60回（1日上限）")
    return "\n".join(lines)


# ========================================
#  Claude 実装（Anthropic復旧後に使用）
# ========================================
async def claude_chat_stream(
    message: str,
    history: list[dict],
    system_prompt: str,
    tools_schema: list[dict],
    dispatch_tool: Callable,
    model_name: str = "claude-opus-4-6",
) -> AsyncGenerator[str, None]:
    """Claude APIでストリーミングチャット"""
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

    messages = []
    for h in history:
        if h.get("role") in ("user", "assistant") and h.get("content"):
            messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": message})

    max_iterations = 5
    iteration = 0

    while iteration < max_iterations:
        iteration += 1
        full_text = ""
        tool_uses = []
        stop_reason = None

        try:
            async with client.messages.stream(
                model=model_name,
                max_tokens=4096,
                thinking={"type": "adaptive"},
                system=system_prompt,
                messages=messages,
                tools=tools_schema,
            ) as stream:
                async for event in stream:
                    if (event.type == "content_block_delta"
                            and hasattr(event.delta, "type")
                            and event.delta.type == "text_delta"):
                        full_text += event.delta.text
                        yield f"data: {json.dumps({'type': 'text', 'text': event.delta.text}, ensure_ascii=False)}\n\n"
                    elif (event.type == "content_block_stop"
                          and hasattr(event, "content_block")
                          and hasattr(event.content_block, "type")
                          and event.content_block.type == "thinking"):
                        yield f"data: {json.dumps({'type': 'thinking', 'thinking': event.content_block.thinking[:300]}, ensure_ascii=False)}\n\n"

                msg = await stream.get_final_message()
                stop_reason = msg.stop_reason
                for block in msg.content:
                    if block.type == "tool_use":
                        tool_uses.append(block)

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'error': f'Claude APIエラー: {str(e)}'}, ensure_ascii=False)}\n\n"
            return

        if stop_reason != "tool_use" or not tool_uses:
            break

        assistant_content = []
        for block in msg.content:
            if block.type == "text":
                assistant_content.append({"type": "text", "text": block.text})
            elif block.type == "thinking":
                assistant_content.append({"type": "thinking", "thinking": block.thinking, "signature": block.signature})
            elif block.type == "tool_use":
                assistant_content.append({"type": "tool_use", "id": block.id, "name": block.name, "input": block.input})
        messages.append({"role": "assistant", "content": assistant_content})

        tool_results = []
        for tool_use in tool_uses:
            yield f"data: {json.dumps({'type': 'tool_use', 'tool': tool_use.name, 'input': tool_use.input}, ensure_ascii=False)}\n\n"
            result = dispatch_tool(tool_use.name, tool_use.input)
            yield f"data: {json.dumps({'type': 'tool_result', 'tool': tool_use.name}, ensure_ascii=False)}\n\n"
            tool_results.append({"type": "tool_result", "tool_use_id": tool_use.id, "content": result})

        messages.append({"role": "user", "content": tool_results})

    yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"


# ========================================
#  統一インターフェース
# ========================================
async def chat_stream(
    message: str,
    history: list[dict],
    system_prompt: str,
    tools_schema: list[dict],
    dispatch_tool: Callable,
) -> AsyncGenerator[str, None]:
    """プロバイダーを自動選択してチャットを実行"""
    if PROVIDER == "gemini":
        async for chunk in gemini_chat_stream(
            message, history, system_prompt, tools_schema, dispatch_tool
        ):
            yield chunk
    elif PROVIDER == "claude":
        async for chunk in claude_chat_stream(
            message, history, system_prompt, tools_schema, dispatch_tool
        ):
            yield chunk
    else:
        yield f"data: {json.dumps({'type': 'error', 'error': 'APIキーが設定されていません。backend/.env にGOOGLE_API_KEY または ANTHROPIC_API_KEY を設定してください。'}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
