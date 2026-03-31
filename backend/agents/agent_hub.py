"""
エージェント間通信ハブ (Agent Hub)
統括管理AIが他の専門AIエージェントを内部的に呼び出し、
複数の回答を統合して最終回答を生成するための仕組み。
"""
import asyncio
import json
import importlib
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ---- エージェントモジュールマップ ----
# 各モジュールには {agent_id}_chat_stream(message, history) 関数がある
AGENT_MODULES = {
    "hojin":   "agents.hojin",
    "shohi":   "agents.shohi",
    "shotoku": "agents.shotoku",
    "sozoku":  "agents.sozoku",
    "tochi":   "agents.tochi",
    "kaikei":  "agents.kaikei",
    "roumu":   "agents.roumu",
    "hisho":   "agents.secretary",
    "kanri":   "agents.orchestrator",
}

# エージェントIDと chat_stream 関数名の対応
AGENT_FUNC_NAMES = {
    "hojin":   "hojin_chat_stream",
    "shohi":   "shohi_chat_stream",
    "shotoku": "shotoku_chat_stream",
    "sozoku":  "sozoku_chat_stream",
    "tochi":   "tochi_chat_stream",
    "kaikei":  "kaikei_chat_stream",
    "roumu":   "roumu_chat_stream",
    "hisho":   "secretary_chat_stream",
    "kanri":   "orchestrator_chat_stream",
}

# エージェント表示名
AGENT_DISPLAY_NAMES = {
    "hojin":   "法人税AI",
    "shohi":   "消費税AI",
    "shotoku": "所得税AI",
    "sozoku":  "相続税AI",
    "tochi":   "土地評価AI",
    "kaikei":  "会計入力AI",
    "roumu":   "労務・社保AI",
    "hisho":   "秘書AI",
    "kanri":   "統括管理AI",
}

# ---- キーワードルーティングルール ----
# (keywords, agent_ids) のリスト。先にマッチした方が優先。
# 複合キーワード（決算、新規顧問先）は先に判定する。
ROUTING_RULES = [
    # 複合ルール（複数エージェント連携が必要なケース）
    (["決算"],                          ["hojin", "shohi", "kaikei"]),
    (["新規顧問先"],                    ["kanri", "hisho", "kaikei"]),
    # 単一エージェントルール
    (["法人税", "別表", "法人"],        ["hojin"]),
    (["消費税", "インボイス"],          ["shohi"]),
    (["所得税", "確定申告", "控除"],    ["shotoku"]),
    (["相続", "贈与"],                  ["sozoku"]),
    (["土地", "路線価", "評価"],        ["tochi"]),
    (["会計", "仕訳", "試算表"],        ["kaikei"]),
    (["労務", "社保", "算定"],          ["roumu"]),
    (["メール", "スケジュール", "検索"],["hisho"]),
]

# ---- モジュールキャッシュ（遅延インポート用） ----
_module_cache: dict = {}


def _get_chat_stream_func(agent_id: str):
    """
    エージェントIDから chat_stream 関数を遅延ロードして返す。
    循環インポートを回避するため、初回呼び出し時にのみ importlib で読み込む。
    """
    if agent_id in _module_cache:
        return _module_cache[agent_id]

    module_path = AGENT_MODULES.get(agent_id)
    func_name = AGENT_FUNC_NAMES.get(agent_id)

    if not module_path or not func_name:
        raise ValueError(f"不明なエージェントID: {agent_id}")

    module = importlib.import_module(module_path)
    func = getattr(module, func_name)
    _module_cache[agent_id] = func
    return func


def _parse_sse_text(sse_chunk: str) -> str:
    """
    SSEチャンクから表示用テキストを抽出する。
    形式: 'data: {"type": "text", "text": "..."}\n\n'
    type が "text" のもののみ抽出し、それ以外（tool_use, done, error 等）は無視。
    """
    text = ""
    for line in sse_chunk.strip().split("\n"):
        line = line.strip()
        if not line.startswith("data: "):
            continue
        json_str = line[len("data: "):]
        try:
            data = json.loads(json_str)
            if data.get("type") == "text":
                text += data.get("text", "")
        except (json.JSONDecodeError, TypeError):
            continue
    return text


class AgentHub:
    """
    エージェント間通信ハブ。
    統括管理AIが専門AIを内部呼び出しし、回答を収集・統合する。
    """

    def __init__(self, timeout: float = 60.0):
        """
        Args:
            timeout: エージェント呼び出しのタイムアウト秒数（デフォルト60秒）
        """
        self.timeout = timeout

    async def call_agent(
        self,
        agent_id: str,
        question: str,
        context: str = "",
    ) -> str:
        """
        単一のエージェントを呼び出し、完全なテキスト応答を返す。

        Args:
            agent_id: エージェントID（例: "hojin", "shohi"）
            question: エージェントに送る質問文
            context: 追加コンテキスト（顧問先情報など）

        Returns:
            エージェントの完全なテキスト応答
        """
        chat_stream_func = _get_chat_stream_func(agent_id)
        display_name = AGENT_DISPLAY_NAMES.get(agent_id, agent_id)

        # コンテキストがあれば質問に前置する
        full_message = question
        if context:
            full_message = f"{context}\n\n{question}"

        # SSEストリームからテキストを収集
        collected_text = ""

        try:
            async with asyncio.timeout(self.timeout):
                async for chunk in chat_stream_func(
                    message=full_message,
                    history=[],
                ):
                    extracted = _parse_sse_text(chunk)
                    if extracted:
                        collected_text += extracted
        except TimeoutError:
            logger.warning(
                "エージェント %s (%s) がタイムアウトしました（%s秒）",
                display_name, agent_id, self.timeout,
            )
            if collected_text:
                collected_text += f"\n\n（※ {display_name}の応答がタイムアウトしました。途中までの回答です。）"
            else:
                collected_text = f"（{display_name}からの応答がタイムアウトしました。）"
        except Exception as e:
            logger.error(
                "エージェント %s (%s) の呼び出しでエラー: %s",
                display_name, agent_id, str(e),
            )
            collected_text = f"（{display_name}の呼び出しでエラーが発生しました: {str(e)}）"

        return collected_text

    async def call_multiple_agents(
        self,
        requests: list[dict],
    ) -> dict[str, str]:
        """
        複数のエージェントを並列に呼び出し、全回答を辞書で返す。

        Args:
            requests: エージェント呼び出しリスト。各要素は:
                {
                    "agent_id": "hojin",
                    "question": "法人税の別表四について...",
                    "context": "（任意）顧問先情報など"
                }

        Returns:
            {agent_id: response_text} の辞書
        """
        if not requests:
            return {}

        # 並列タスクを作成
        async def _call_one(req: dict) -> tuple[str, str]:
            agent_id = req["agent_id"]
            question = req["question"]
            context = req.get("context", "")
            response = await self.call_agent(agent_id, question, context)
            return agent_id, response

        tasks = [_call_one(req) for req in requests]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        response_dict: dict[str, str] = {}
        for i, result in enumerate(results):
            agent_id = requests[i]["agent_id"]
            display_name = AGENT_DISPLAY_NAMES.get(agent_id, agent_id)
            if isinstance(result, Exception):
                logger.error(
                    "エージェント %s の並列呼び出しで例外: %s",
                    agent_id, str(result),
                )
                response_dict[agent_id] = f"（{display_name}の呼び出しで例外が発生しました: {str(result)}）"
            else:
                aid, text = result
                response_dict[aid] = text

        return response_dict

    async def smart_route(self, message: str) -> list[str]:
        """
        ユーザーメッセージを分析し、相談すべきエージェントIDのリストを返す。

        Args:
            message: ユーザーからのメッセージ

        Returns:
            エージェントIDのリスト。該当なしの場合は空リスト
            （空リストの場合、統括管理AIが単独で対応する）
        """
        matched_agents: list[str] = []

        for keywords, agent_ids in ROUTING_RULES:
            for kw in keywords:
                if kw in message:
                    # このルールにマッチ → エージェントを追加
                    for aid in agent_ids:
                        if aid not in matched_agents:
                            matched_agents.append(aid)
                    break  # この1ルール内では1キーワードマッチで十分

        return matched_agents

    async def route_and_call(
        self,
        message: str,
        context: str = "",
    ) -> dict[str, str]:
        """
        smart_route でルーティングし、該当エージェントを一括呼び出しする便利メソッド。

        Args:
            message: ユーザーからのメッセージ
            context: 追加コンテキスト

        Returns:
            {agent_id: response_text} の辞書。ルーティング該当なしなら空辞書。
        """
        agent_ids = await self.smart_route(message)
        if not agent_ids:
            return {}

        requests = [
            {"agent_id": aid, "question": message, "context": context}
            for aid in agent_ids
        ]
        return await self.call_multiple_agents(requests)

    def format_multi_response(
        self,
        responses: dict[str, str],
        original_question: str = "",
    ) -> str:
        """
        複数エージェントの回答をまとめて1つのテキストに整形する。

        Args:
            responses: {agent_id: response_text} の辞書
            original_question: 元の質問（ヘッダー表示用、任意）

        Returns:
            整形済みの統合テキスト
        """
        if not responses:
            return ""

        parts = []
        if original_question:
            parts.append(f"【質問】{original_question}\n")

        parts.append("【各専門AIからの回答】\n")

        for agent_id, text in responses.items():
            display_name = AGENT_DISPLAY_NAMES.get(agent_id, agent_id)
            separator = "─" * 30
            parts.append(f"{separator}")
            parts.append(f"■ {display_name}（{agent_id}）")
            parts.append(f"{separator}")
            parts.append(text.strip())
            parts.append("")

        return "\n".join(parts)


# ---- 顧問先情報取得（将来のDB連携用） ----

# 暫定的なインメモリ顧問先データ
# 本格運用時はデータベース（SQLite / PostgreSQL等）に置き換える
_CLIENT_MASTER: list[dict] = [
    {
        "name": "山田株式会社",
        "type": "法人",
        "fiscal_year_end": "3月",
        "services": ["法人税", "消費税"],
        "memo": "インボイス登録済み。月次顧問契約。",
    },
    {
        "name": "佐藤商事株式会社",
        "type": "法人",
        "fiscal_year_end": "9月",
        "services": ["法人税", "消費税", "会計入力"],
        "memo": "JDL会計利用。決算2ヶ月前から準備開始。",
    },
    {
        "name": "田中太郎",
        "type": "個人",
        "fiscal_year_end": "12月",
        "services": ["所得税", "消費税"],
        "memo": "不動産所得あり。確定申告対応。",
    },
    {
        "name": "鈴木家",
        "type": "相続",
        "fiscal_year_end": "-",
        "services": ["相続税", "土地評価"],
        "memo": "被相続人：鈴木一郎。申告期限要確認。土地3筆あり。",
    },
    {
        "name": "高橋建設株式会社",
        "type": "法人",
        "fiscal_year_end": "6月",
        "services": ["法人税", "消費税", "労務・社保"],
        "memo": "従業員15名。算定基礎届対応要。",
    },
]


def get_client_context(client_name: str) -> str:
    """
    顧問先名で検索し、整形されたコンテキスト文字列を返す。

    Args:
        client_name: 顧問先名（部分一致で検索）

    Returns:
        "【顧問先情報】..." 形式の文字列。見つからない場合は空文字列。
    """
    if not client_name:
        return ""

    for client in _CLIENT_MASTER:
        if client_name in client["name"] or client["name"] in client_name:
            services_str = "・".join(client["services"])
            return (
                f"【顧問先情報】"
                f"{client['name']} / "
                f"{client['type']} / "
                f"{client['fiscal_year_end']}決算 / "
                f"{services_str} / "
                f"メモ: {client['memo']}"
            )

    return ""


# ---- モジュールレベルのシングルトン ----
_hub_instance: Optional[AgentHub] = None


def get_hub(timeout: float = 60.0) -> AgentHub:
    """AgentHub のシングルトンインスタンスを取得する。"""
    global _hub_instance
    if _hub_instance is None:
        _hub_instance = AgentHub(timeout=timeout)
    return _hub_instance
