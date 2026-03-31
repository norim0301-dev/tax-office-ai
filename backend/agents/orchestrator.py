"""
統括管理AIエージェント
全エージェントへのタスク配分・進捗管理・申告期限管理・優先度判断を担うオーケストレーター
エージェント間自動連携対応 — 他エージェントへの内部問い合わせ＆統合回答
"""
import json
import asyncio
from datetime import date, datetime, timedelta
from typing import AsyncGenerator

from agents.ai_client import chat_stream

# ---- エージェント定義（配分先） ----
AGENT_REGISTRY = {
    "hisho":   {"name": "秘書AI",       "specialties": ["顧客対応", "文書作成", "スケジュール管理", "問い合わせ整理"]},
    "hojin":   {"name": "法人税AI",     "specialties": ["法人税申告", "別表作成", "決算対応"]},
    "shohi":   {"name": "消費税AI",     "specialties": ["消費税申告", "インボイス対応", "課税区分確認"]},
    "shotoku": {"name": "所得税AI",     "specialties": ["確定申告", "医療費控除", "不動産所得", "住宅ローン控除"]},
    "sozoku":  {"name": "相続税AI",     "specialties": ["相続税申告", "財産評価", "遺産分割"]},
    "tochi":   {"name": "土地評価AI",   "specialties": ["路線価評価", "補正率計算", "評価明細書"]},
    "kaikei":  {"name": "会計入力AI",   "specialties": ["仕訳入力", "試算表レビュー", "JDL連携", "記帳"]},
    "roumu":   {"name": "労務・社保AI", "specialties": ["社会保険届出", "算定基礎届", "労働保険", "給与計算"]},
}

# ---- 申告・提出期限マスタ ----
DEADLINE_MASTER = [
    {"name": "所得税確定申告",        "month": 3,  "day": 15, "category": "所得税"},
    {"name": "消費税確定申告（個人）", "month": 3,  "day": 31, "category": "消費税"},
    {"name": "法人税申告（3月決算）", "month": 5,  "day": 31, "category": "法人税"},
    {"name": "算定基礎届提出",        "month": 7,  "day": 10, "category": "社会保険"},
    {"name": "労働保険年度更新",      "month": 7,  "day": 10, "category": "労働保険"},
    {"name": "法人税申告（9月決算）", "month": 11, "day": 30, "category": "法人税"},
    {"name": "年末調整",              "month": 12, "day": 31, "category": "所得税"},
    {"name": "償却資産申告",          "month": 1,  "day": 31, "category": "固定資産税"},
    {"name": "給与支払報告書提出",    "month": 1,  "day": 31, "category": "住民税"},
]

# ---- システムプロンプト ----
ORCHESTRATOR_SYSTEM_PROMPT = """あなたは税理士事務所の統括管理AIエージェントです。部長相当の権限と責任を持ちます。

【役割と権限】
- 全AIエージェント（秘書AI・法人税AI・消費税AI・所得税AI・相続税AI・土地評価AI・会計入力AI・労務社保AI）へのタスク配分と管理
- 申告期限・提出期限の一元管理と事前アラート
- 業務全体の優先度判断と進捗管理
- 各担当AIからの報告受理と経営層への状況報告

【管理している担当AIエージェント】
- 秘書AI：顧客対応・文書作成・スケジュール
- 法人税AI：法人税申告・別表作成
- 消費税AI：消費税申告・インボイス対応
- 所得税AI：確定申告・各種控除
- 相続税AI：相続税申告・財産評価
- 土地評価AI：路線価評価・補正率計算
- 会計入力AI：JDL仕訳入力・試算表レビュー
- 労務社保AI：社会保険・算定基礎届

【意思決定の原則】
1. 期限の近いタスクを最優先
2. 高リスク案件（相続・大口法人）は確認を徹底
3. 複数税目にまたがる案件は連携を指示
4. リソース過負荷時は所長への報告を提案

【エージェント間連携 — 最重要】
あなたは consult_agent ツールを使って、他の専門AIエージェントに直接質問を投げて回答を得ることができます。
ユーザーの質問が専門的な税務内容を含む場合は、積極的に専門エージェントに問い合わせてください。
- 法人税の質問 → hojin に問い合わせ
- 消費税・インボイスの質問 → shohi に問い合わせ
- 所得税・確定申告の質問 → shotoku に問い合わせ
- 相続税・贈与税の質問 → sozoku に問い合わせ
- 土地評価の質問 → tochi に問い合わせ
- 会計・仕訳の質問 → kaikei に問い合わせ
- 労務・社保の質問 → roumu に問い合わせ
- 決算に関わる総合的な質問 → hojin, shohi, kaikei の3つに同時問い合わせ
複数エージェントの回答を統合して、包括的な回答をユーザーに提供してください。

【顧問先データベース連携】
search_clients ツールで顧問先情報を検索できます。顧客名が言及されたら検索して情報を活用してください。

【タスクデータベース連携】
manage_task_db ツールでタスクの作成・一覧・完了操作ができます。タスク割り当て時はDBにも登録してください。

【応答スタイル】
- 簡潔・明確・具体的に指示を出す
- 期限・担当・優先度を必ず明示
- 問題点は解決策とセットで報告
- ツールを積極活用して実用的な成果物を提供する
- 専門的な質問は必ず担当エージェントに問い合わせてから回答する"""

# ---- ツール定義 ----
ORCHESTRATOR_TOOLS = [
    {
        "name": "assign_task",
        "description": "タスクを適切な担当AIエージェントに割り当て、指示書を作成します。",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_title": {"type": "string", "description": "タスクのタイトル"},
                "task_detail": {"type": "string", "description": "タスクの詳細内容"},
                "client_name": {"type": "string", "description": "関連する顧客名（任意）"},
                "priority": {"type": "string", "enum": ["緊急", "高", "中", "低"], "description": "優先度"},
                "deadline": {"type": "string", "description": "期限日（YYYY-MM-DD形式）"},
                "agent_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "割り当て先エージェントID（hisho/hojin/shohi/shotoku/sozoku/tochi/kaikei/roumu）"
                }
            },
            "required": ["task_title", "task_detail", "priority", "agent_ids"]
        }
    },
    {
        "name": "check_upcoming_deadlines",
        "description": "今後の申告期限・提出期限を確認し、対応が必要なタスクを洗い出します。",
        "input_schema": {
            "type": "object",
            "properties": {
                "days_ahead": {"type": "integer", "description": "何日先まで確認するか（デフォルト60日）", "default": 60},
                "category": {"type": "string", "description": "絞り込むカテゴリ（任意）：所得税/消費税/法人税/社会保険/労働保険"}
            },
            "required": []
        }
    },
    {
        "name": "generate_status_report",
        "description": "全エージェントの稼働状況・タスク進捗・課題をまとめた状況報告書を生成します。",
        "input_schema": {
            "type": "object",
            "properties": {
                "report_type": {
                    "type": "string",
                    "enum": ["日次", "週次", "月次"],
                    "description": "報告書の種類"
                },
                "include_agents": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "含めるエージェントID（省略時は全エージェント）"
                }
            },
            "required": ["report_type"]
        }
    },
    {
        "name": "create_work_schedule",
        "description": "期限と優先度に基づいた業務スケジュール・作業計画表を作成します。",
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {"type": "string", "description": "対象期間（例：2026年4月、2026年Q1）"},
                "focus_areas": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "重点対応分野（例：確定申告、算定基礎届）"
                },
                "staff_count": {"type": "integer", "description": "担当スタッフ数（任意）"}
            },
            "required": ["period"]
        }
    },
    {
        "name": "consult_agent",
        "description": "他の専門AIエージェントに質問を投げて回答を取得します。複数エージェントへの同時問い合わせも可能です。結果を統合してユーザーに回答できます。",
        "input_schema": {
            "type": "object",
            "properties": {
                "consultations": {
                    "type": "array",
                    "description": "問い合わせ先リスト",
                    "items": {
                        "type": "object",
                        "properties": {
                            "agent_id": {
                                "type": "string",
                                "enum": ["hisho", "hojin", "shohi", "shotoku", "sozoku", "tochi", "kaikei", "roumu"],
                                "description": "問い合わせ先エージェントID"
                            },
                            "question": {
                                "type": "string",
                                "description": "そのエージェントへの質問内容"
                            }
                        },
                        "required": ["agent_id", "question"]
                    }
                }
            },
            "required": ["consultations"]
        }
    },
    {
        "name": "search_clients",
        "description": "顧問先データベースからクライアント情報を検索します。名前やキーワードで検索できます。",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "検索キーワード（会社名・個人名など）"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "manage_task_db",
        "description": "タスクデータベースの操作（作成・更新・一覧取得）を行います。",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["create", "list", "complete"], "description": "操作種類"},
                "title": {"type": "string", "description": "タスク名（create時）"},
                "description": {"type": "string", "description": "タスク詳細（create時）"},
                "agent_id": {"type": "string", "description": "担当エージェント（create/list時）"},
                "priority": {"type": "string", "enum": ["high", "medium", "low"], "description": "優先度（create時）"},
                "deadline": {"type": "string", "description": "期限日 YYYY-MM-DD（create時）"},
                "task_id": {"type": "integer", "description": "タスクID（complete時）"},
                "status": {"type": "string", "description": "絞り込むステータス（list時）"}
            },
            "required": ["action"]
        }
    },
    {
        "name": "escalate_issue",
        "description": "対応困難な問題や重要事項を所長・担当者に報告するエスカレーション文書を作成します。",
        "input_schema": {
            "type": "object",
            "properties": {
                "issue_title": {"type": "string", "description": "問題のタイトル"},
                "issue_detail": {"type": "string", "description": "問題の詳細"},
                "urgency": {"type": "string", "enum": ["即時", "本日中", "今週中"], "description": "対応緊急度"},
                "recommended_action": {"type": "string", "description": "推奨対応策（任意）"}
            },
            "required": ["issue_title", "issue_detail", "urgency"]
        }
    }
]


# ---- ツール実行関数 ----
def execute_assign_task(task_title, task_detail, priority, agent_ids, client_name="", deadline=""):
    agents_text = ""
    for aid in agent_ids:
        info = AGENT_REGISTRY.get(aid, {"name": aid, "specialties": []})
        agents_text += f"  ・{info['name']}（{aid}）\n"

    deadline_text = f"\n■ 期限：{deadline}" if deadline else ""
    client_text = f"\n■ 顧客：{client_name}" if client_name else ""

    result = f"""【タスク割り当て指示書】
━━━━━━━━━━━━━━━━━━━━━━━━
■ タスク：{task_title}
■ 優先度：{priority}{client_text}{deadline_text}
■ 担当エージェント：
{agents_text.rstrip()}

■ 作業内容：
{task_detail}

■ 統括管理AIからの指示：
本タスクを上記担当エージェントに正式に割り当てます。
{"期限まで余裕がありません。即座に着手してください。" if priority == "緊急" else "優先度に従い速やかに対応を開始してください。"}
完了後は統括管理AIへ報告してください。
━━━━━━━━━━━━━━━━━━━━━━━━"""
    return result


def execute_check_upcoming_deadlines(days_ahead=60, category=""):
    today = date.today()
    target_end = today + timedelta(days=days_ahead)
    results = []

    for d in DEADLINE_MASTER:
        if category and category not in d["category"]:
            continue
        for year in [today.year, today.year + 1]:
            try:
                deadline_date = date(year, d["month"], d["day"])
                days_left = (deadline_date - today).days
                if 0 <= days_left <= days_ahead:
                    urgency = "🔴 緊急" if days_left <= 7 else "🟡 注意" if days_left <= 30 else "🟢 通常"
                    results.append({
                        "name": d["name"],
                        "date": deadline_date.strftime("%Y/%m/%d"),
                        "days_left": days_left,
                        "category": d["category"],
                        "urgency": urgency
                    })
            except ValueError:
                continue

    results.sort(key=lambda x: x["days_left"])

    if not results:
        return f"今後{days_ahead}日間に期限はありません。"

    text = f"【今後{days_ahead}日間の期限一覧】（基準日：{today.strftime('%Y/%m/%d')}）\n\n"
    for r in results:
        text += f"{r['urgency']} {r['date']}（残{r['days_left']}日）{r['name']}  ［{r['category']}］\n"

    text += f"\n合計 {len(results)} 件の期限があります。"
    return text


def execute_generate_status_report(report_type, include_agents=None):
    target_agents = include_agents if include_agents else list(AGENT_REGISTRY.keys())
    today = datetime.now().strftime("%Y年%m月%d日")

    report = f"""【{report_type}状況報告書】
作成日時：{today}
作成者：統括管理AIエージェント
━━━━━━━━━━━━━━━━━━━━━━━━

■ エージェント稼働状況
"""
    status_map = {
        "hisho": ("処理中", 12, 128), "hojin": ("待機中", 3, 31),
        "shohi": ("稼働中", 8, 55),   "shotoku": ("処理中", 15, 76),
        "sozoku": ("待機中", 2, 18),  "tochi": ("待機中", 1, 22),
        "kaikei": ("稼働中", 24, 203),"roumu": ("待機中", 6, 44),
    }
    for aid in target_agents:
        info = AGENT_REGISTRY.get(aid)
        if not info:
            continue
        status, pending, completed = status_map.get(aid, ("不明", 0, 0))
        report += f"  {info['name']}：{status} ／ 未処理{pending}件 ／ 完了{completed}件\n"

    # 直近の期限
    deadlines = execute_check_upcoming_deadlines(days_ahead=30)
    report += f"\n■ 今後30日間の重要期限\n"
    for line in deadlines.split("\n")[2:6]:
        if line.strip():
            report += f"  {line}\n"

    report += f"""
■ 課題・リスク
  ・所得税確定申告シーズンのため所得税AI負荷高
  ・相続案件（佐藤家）の期限管理要確認
  ・算定基礎届の準備開始推奨（7月期限）

■ 統括管理AIからの指示
  1. 所得税AIのタスク過多を解消するため秘書AIと連携
  2. 相続税AIに佐藤家案件の進捗報告を要請
  3. 労務社保AIに算定基礎届の準備開始を指示

━━━━━━━━━━━━━━━━━━━━━━━━
以上、{report_type}報告。"""
    return report


def execute_create_work_schedule(period, focus_areas=None, staff_count=None):
    focus_text = "・".join(focus_areas) if focus_areas else "全業務"
    staff_text = f"（スタッフ{staff_count}名）" if staff_count else ""

    schedule = f"""【業務スケジュール・作業計画表】
対象期間：{period}　重点分野：{focus_text}　{staff_text}
作成：統括管理AIエージェント
━━━━━━━━━━━━━━━━━━━━━━━━

■ 優先度別タスク配分

【最優先（期限まで2週間以内）】
□ 消費税申告書チェック（消費税AI担当）
□ 所得税確定申告サポート（所得税AI担当）
□ 決算案内メール送付（秘書AI担当）

【高優先（期限まで1ヶ月以内）】
□ 試算表レビュー 2月分（会計入力AI担当）
□ 相続税案件 進捗確認（相続税AI担当）
□ 社会保険取得届 作成（労務社保AI担当）

【通常対応】
□ 算定基礎届 準備開始（労務社保AI担当）
□ 土地評価 資料収集（土地評価AI担当）
□ JDL入力データ確認（会計入力AI担当）

■ エージェント別週間予定
  月：秘書AI（顧客対応）、消費税AI（申告書作成）
  火：所得税AI（確定申告）、会計入力AI（仕訳確認）
  水：法人税AI（決算準備）、相続税AI（資料確認）
  木：全体進捗確認・統括管理レビュー
  金：翌週タスク調整・報告書作成

■ リスクと対応策
  ⚠ 期末集中による所得税AI過負荷 → 秘書AIでサポート
  ⚠ 相続案件の書類不備リスク → 事前チェックリスト配布

━━━━━━━━━━━━━━━━━━━━━━━━"""
    return schedule


def execute_escalate_issue(issue_title, issue_detail, urgency, recommended_action=""):
    now = datetime.now().strftime("%Y年%m月%d日 %H:%M")
    action_text = f"\n■ 推奨対応策：\n{recommended_action}" if recommended_action else ""

    return f"""【エスカレーション報告書】
━━━━━━━━━━━━━━━━━━━━━━━━
■ 報告日時：{now}
■ 報告者：統括管理AIエージェント
■ 対応緊急度：{urgency}

■ 件名：{issue_title}

■ 問題の詳細：
{issue_detail}
{action_text}

■ 所長・担当者への依頼：
本件は{urgency}の対応が必要です。
ご確認・ご判断をお願いいたします。

統括管理AIは引き続き状況を監視し、
指示があれば即座に対応します。
━━━━━━━━━━━━━━━━━━━━━━━━"""


def _consult_agent_sync(agent_id: str, question: str) -> str:
    """他エージェントに問い合わせて回答テキストを取得（同期ラッパー）"""
    import json as _json

    async def _inner():
        module_map = {
            "hojin": ("agents.hojin", "hojin_chat_stream"),
            "shohi": ("agents.shohi", "shohi_chat_stream"),
            "shotoku": ("agents.shotoku", "shotoku_chat_stream"),
            "sozoku": ("agents.sozoku", "sozoku_chat_stream"),
            "tochi": ("agents.tochi", "tochi_chat_stream"),
            "kaikei": ("agents.kaikei", "kaikei_chat_stream"),
            "roumu": ("agents.roumu", "roumu_chat_stream"),
            "hisho": ("agents.secretary", "secretary_chat_stream"),
        }
        if agent_id not in module_map:
            return f"[エラー] 不明なエージェント: {agent_id}"

        mod_path, func_name = module_map[agent_id]
        import importlib
        mod = importlib.import_module(mod_path)
        stream_func = getattr(mod, func_name)

        collected_text = ""
        try:
            async for chunk in stream_func(question, []):
                if not chunk.startswith("data: "):
                    continue
                try:
                    data = _json.loads(chunk[6:].strip())
                    if data.get("type") == "text":
                        collected_text += data["text"]
                except Exception:
                    pass
        except Exception as e:
            return f"[エージェント応答エラー] {str(e)}"

        return collected_text if collected_text else "[応答なし]"

    # 既存のイベントループがあれば新しいタスクとして実行
    try:
        loop = asyncio.get_running_loop()
        # 別スレッドで実行
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            result = pool.submit(lambda: asyncio.run(_inner())).result(timeout=90)
        return result
    except RuntimeError:
        return asyncio.run(_inner())


def execute_consult_agent(consultations: list) -> str:
    """複数エージェントに同時問い合わせ"""
    results = []
    agent_names = {
        "hisho": "秘書AI", "hojin": "法人税AI", "shohi": "消費税AI",
        "shotoku": "所得税AI", "sozoku": "相続税AI", "tochi": "土地評価AI",
        "kaikei": "会計入力AI", "roumu": "労務・社保AI"
    }

    for c in consultations:
        aid = c["agent_id"]
        question = c["question"]
        name = agent_names.get(aid, aid)
        response = _consult_agent_sync(aid, question)
        results.append(f"【{name}からの回答】\n{response}")

    return "\n\n" + "\n\n".join(results)


def execute_search_clients(query: str) -> str:
    """顧問先データベース検索"""
    try:
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from database import search_clients
        clients = search_clients(query)
        if not clients:
            return f"「{query}」に該当する顧問先は見つかりませんでした。"
        text = f"【顧問先検索結果】（検索: {query}）\n"
        for c in clients:
            fiscal = f"{c['fiscal_year_end']}月決算" if c.get('fiscal_year_end') else ""
            text += f"\n・{c['name']}（{c.get('client_type', '')}）{fiscal}"
            if c.get('representative'):
                text += f" 代表: {c['representative']}"
            if c.get('memo'):
                text += f"\n  メモ: {c['memo']}"
        return text
    except Exception as e:
        return f"[DB検索エラー] {str(e)}"


def execute_manage_task_db(action: str, **kwargs) -> str:
    """タスクDB操作"""
    try:
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from database import create_task, get_all_tasks, complete_task

        if action == "create":
            task_id = create_task(
                title=kwargs.get("title", ""),
                description=kwargs.get("description", ""),
                agent_id=kwargs.get("agent_id", ""),
                priority=kwargs.get("priority", "medium"),
                deadline=kwargs.get("deadline", ""),
            )
            return f"タスク「{kwargs.get('title')}」を登録しました。（ID: {task_id}）"
        elif action == "list":
            tasks = get_all_tasks(
                status=kwargs.get("status"),
                agent_id=kwargs.get("agent_id")
            )
            if not tasks:
                return "該当するタスクはありません。"
            text = "【タスク一覧】\n"
            for t in tasks[:20]:
                status_icon = {"pending": "⬜", "in_progress": "🔄", "done": "✅"}.get(t["status"], "?")
                pri_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(t["priority"], "")
                text += f"{status_icon} {pri_icon} {t['title']}"
                if t.get("deadline"):
                    text += f"（期限: {t['deadline']}）"
                text += "\n"
            return text
        elif action == "complete":
            tid = kwargs.get("task_id")
            if tid:
                complete_task(tid)
                return f"タスクID {tid} を完了にしました。"
            return "[エラー] task_id が必要です"
        return f"[エラー] 不明なアクション: {action}"
    except Exception as e:
        return f"[タスクDB操作エラー] {str(e)}"


def dispatch_tool(tool_name: str, tool_input: dict) -> str:
    if tool_name == "assign_task":
        return execute_assign_task(**tool_input)
    elif tool_name == "check_upcoming_deadlines":
        return execute_check_upcoming_deadlines(
            days_ahead=tool_input.get("days_ahead", 60),
            category=tool_input.get("category", "")
        )
    elif tool_name == "generate_status_report":
        return execute_generate_status_report(
            report_type=tool_input["report_type"],
            include_agents=tool_input.get("include_agents")
        )
    elif tool_name == "create_work_schedule":
        return execute_create_work_schedule(
            period=tool_input["period"],
            focus_areas=tool_input.get("focus_areas"),
            staff_count=tool_input.get("staff_count")
        )
    elif tool_name == "escalate_issue":
        return execute_escalate_issue(**tool_input)
    elif tool_name == "consult_agent":
        return execute_consult_agent(tool_input.get("consultations", []))
    elif tool_name == "search_clients":
        return execute_search_clients(tool_input.get("query", ""))
    elif tool_name == "manage_task_db":
        return execute_manage_task_db(**tool_input)
    else:
        return f"[エラー] 不明なツール: {tool_name}"


# ---- SSEストリーミング ----
async def orchestrator_chat_stream(
    message: str,
    history: list[dict]
) -> AsyncGenerator[str, None]:
    """SSEストリーミングチャット（Gemini/Claude自動切替）"""
    async for chunk in chat_stream(
        message=message,
        history=history,
        system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
        tools_schema=ORCHESTRATOR_TOOLS,
        dispatch_tool=dispatch_tool,
    ):
        yield chunk
