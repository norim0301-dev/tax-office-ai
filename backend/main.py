from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from datetime import datetime
from typing import Optional
import random
import os
import urllib.request
import urllib.parse
import json

# データベース初期化
from database import init_db
init_db()

app = FastAPI(title="税理士事務所 AIエージェント管理API", version="0.2.0")

# 新しいAPIルートを登録
from api_routes import router as api_router
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # LAN内の任意のIPからアクセス可能
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- モデル ----
class Agent(BaseModel):
    id: str
    name: str
    role: str
    status: str  # active / idle / busy
    color: str
    tasks_completed: int
    tasks_pending: int
    description: str

class Task(BaseModel):
    id: str
    title: str
    agent_id: str
    agent_name: str
    priority: str  # high / medium / low
    deadline: Optional[str]
    status: str  # pending / in_progress / done

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []

class LineNotifyRequest(BaseModel):
    message: str
    token: str  # LINE Notifyアクセストークン

class LineMessageRequest(BaseModel):
    to: str          # LINE ユーザーID または グループID
    message: str
    channel_token: str  # LINE Messaging API チャンネルアクセストークン

# ---- データ ----
AGENTS: list[Agent] = [
    Agent(id="kanri", name="統括管理AI", role="部長相当", status="active",
          color="#1F4E79", tasks_completed=42, tasks_pending=5,
          description="全エージェントへのタスク配分・進捗管理・申告期限管理"),
    Agent(id="hisho", name="秘書AI", role="秘書", status="busy",
          color="#2E75B6", tasks_completed=128, tasks_pending=12,
          description="顧客対応・文書作成・スケジュール管理"),
    Agent(id="hojin", name="法人税AI", role="法人税担当", status="idle",
          color="#1A5276", tasks_completed=31, tasks_pending=3,
          description="法人税申告書作成サポート・別表チェック"),
    Agent(id="shohi", name="消費税AI", role="消費税担当", status="active",
          color="#117A65", tasks_completed=55, tasks_pending=8,
          description="消費税申告書チェック・インボイス対応"),
    Agent(id="shotoku", name="所得税AI", role="所得税担当", status="busy",
          color="#6E2FBB", tasks_completed=76, tasks_pending=15,
          description="確定申告サポート・各種控除チェック"),
    Agent(id="sozoku", name="相続税AI", role="相続・贈与税担当", status="idle",
          color="#7B241C", tasks_completed=18, tasks_pending=2,
          description="相続税申告書作成・財産評価サポート"),
    Agent(id="tochi", name="土地評価AI", role="土地評価担当", status="idle",
          color="#784212", tasks_completed=22, tasks_pending=1,
          description="路線価評価・補正率計算・評価明細書補助"),
    Agent(id="kaikei", name="会計入力AI", role="会計入力担当", status="active",
          color="#1B6CA8", tasks_completed=203, tasks_pending=24,
          description="JDL仕訳入力サポート・試算表レビュー"),
    Agent(id="roumu", name="労務・社保AI", role="労務担当", status="idle",
          color="#17A589", tasks_completed=44, tasks_pending=6,
          description="社会保険届出・算定基礎届・労働保険"),
]

TASKS: list[Task] = [
    Task(id="t1", title="山田株式会社 消費税申告書チェック", agent_id="shohi", agent_name="消費税AI",
         priority="high", deadline="2026-03-31", status="in_progress"),
    Task(id="t2", title="田中太郎 確定申告（不動産所得）", agent_id="shotoku", agent_name="所得税AI",
         priority="high", deadline="2026-03-15", status="in_progress"),
    Task(id="t3", title="全関与先 算定基礎届スケジュール作成", agent_id="kanri", agent_name="統括管理AI",
         priority="medium", deadline="2026-06-01", status="pending"),
    Task(id="t4", title="鈴木商事 試算表レビュー（2月分）", agent_id="kaikei", agent_name="会計入力AI",
         priority="medium", deadline="2026-03-10", status="in_progress"),
    Task(id="t5", title="佐藤家 相続税申告（10ヶ月期限確認）", agent_id="sozoku", agent_name="相続税AI",
         priority="high", deadline="2026-08-15", status="pending"),
    Task(id="t6", title="ABC商会 社会保険取得届作成", agent_id="roumu", agent_name="労務・社保AI",
         priority="low", deadline="2026-04-05", status="pending"),
    Task(id="t7", title="顧客への決算案内メール下書き（3月決算）", agent_id="hisho", agent_name="秘書AI",
         priority="medium", deadline="2026-04-01", status="in_progress"),
    Task(id="t8", title="高橋様 土地評価（路線価計算）", agent_id="tochi", agent_name="土地評価AI",
         priority="medium", deadline="2026-05-01", status="pending"),
]

# ---- エンドポイント ----
@app.get("/")
def root():
    return {"message": "税理士事務所 AIエージェント管理API", "version": "0.1.0"}

@app.get("/api/agents", response_model=list[Agent])
def get_agents():
    return AGENTS

@app.get("/api/agents/{agent_id}", response_model=Agent)
def get_agent(agent_id: str):
    for agent in AGENTS:
        if agent.id == agent_id:
            return agent
    return {"error": "not found"}

@app.get("/api/tasks", response_model=list[Task])
def get_tasks(status: Optional[str] = None):
    if status:
        return [t for t in TASKS if t.status == status]
    return TASKS

@app.get("/api/stats")
def get_stats():
    total_completed = sum(a.tasks_completed for a in AGENTS)
    total_pending = sum(a.tasks_pending for a in AGENTS)
    active_count = len([a for a in AGENTS if a.status == "active"])
    busy_count = len([a for a in AGENTS if a.status == "busy"])
    return {
        "total_agents": len(AGENTS),
        "active_agents": active_count,
        "busy_agents": busy_count,
        "idle_agents": len(AGENTS) - active_count - busy_count,
        "tasks_completed_total": total_completed,
        "tasks_pending_total": total_pending,
        "last_updated": datetime.now().isoformat(),
    }

@app.post("/api/line/notify")
async def line_notify(req: LineNotifyRequest):
    """LINE Notify でメッセージを送信する"""
    if not req.token:
        raise HTTPException(status_code=400, detail="LINE Notify トークンが必要です")
    if not req.message:
        raise HTTPException(status_code=400, detail="メッセージが必要です")

    try:
        data = urllib.parse.urlencode({"message": req.message}).encode("utf-8")
        request = urllib.request.Request(
            "https://notify-api.line.me/api/notify",
            data=data,
            headers={
                "Authorization": f"Bearer {req.token}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST"
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            result = json.loads(response.read().decode("utf-8"))
            return {"success": True, "status": result.get("status"), "message": result.get("message")}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        raise HTTPException(status_code=e.code, detail=f"LINE Notify エラー: {body}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"送信エラー: {str(e)}")


@app.post("/api/line/push")
async def line_push_message(req: LineMessageRequest):
    """LINE Messaging API でプッシュメッセージを送信する"""
    if not req.channel_token:
        raise HTTPException(status_code=400, detail="チャンネルアクセストークンが必要です")

    payload = {
        "to": req.to,
        "messages": [{"type": "text", "text": req.message}]
    }
    try:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            "https://api.line.me/v2/bot/message/push",
            data=data,
            headers={
                "Authorization": f"Bearer {req.channel_token}",
                "Content-Type": "application/json",
            },
            method="POST"
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            return {"success": True, "status_code": response.status}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        raise HTTPException(status_code=e.code, detail=f"LINE Messaging API エラー: {body}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"送信エラー: {str(e)}")


@app.post("/api/line/webhook")
async def line_webhook(request_body: dict):
    """LINE Messaging API Webhook受信（メッセージ受信→秘書AI応答）"""
    # 本番環境では署名検証が必要です
    events = request_body.get("events", [])
    results = []
    for event in events:
        if event.get("type") == "message" and event.get("message", {}).get("type") == "text":
            text = event["message"]["text"]
            reply_token = event.get("replyToken")
            results.append({"event": "text_message", "text": text, "reply_token": reply_token})
    return {"status": "ok", "processed": len(results)}


@app.post("/api/agents/hojin/chat")
async def chat_hojin(request: ChatRequest):
    from agents.hojin import hojin_chat_stream
    return StreamingResponse(hojin_chat_stream(request.message, [h.model_dump() for h in request.history]),
        media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@app.post("/api/agents/shohi/chat")
async def chat_shohi(request: ChatRequest):
    from agents.shohi import shohi_chat_stream
    return StreamingResponse(shohi_chat_stream(request.message, [h.model_dump() for h in request.history]),
        media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@app.post("/api/agents/shotoku/chat")
async def chat_shotoku(request: ChatRequest):
    from agents.shotoku import shotoku_chat_stream
    return StreamingResponse(shotoku_chat_stream(request.message, [h.model_dump() for h in request.history]),
        media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@app.post("/api/agents/sozoku/chat")
async def chat_sozoku(request: ChatRequest):
    from agents.sozoku import sozoku_chat_stream
    return StreamingResponse(sozoku_chat_stream(request.message, [h.model_dump() for h in request.history]),
        media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@app.post("/api/agents/tochi/chat")
async def chat_tochi(request: ChatRequest):
    from agents.tochi import tochi_chat_stream
    return StreamingResponse(tochi_chat_stream(request.message, [h.model_dump() for h in request.history]),
        media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@app.post("/api/agents/kaikei/chat")
async def chat_kaikei(request: ChatRequest):
    from agents.kaikei import kaikei_chat_stream
    return StreamingResponse(kaikei_chat_stream(request.message, [h.model_dump() for h in request.history]),
        media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@app.post("/api/agents/roumu/chat")
async def chat_roumu(request: ChatRequest):
    from agents.roumu import roumu_chat_stream
    return StreamingResponse(roumu_chat_stream(request.message, [h.model_dump() for h in request.history]),
        media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@app.post("/api/agents/kanri/chat")
async def chat_orchestrator(request: ChatRequest):
    """統括管理AIエージェントとのチャット（SSEストリーミング）"""
    from agents.orchestrator import orchestrator_chat_stream
    return StreamingResponse(
        orchestrator_chat_stream(
            message=request.message,
            history=[h.model_dump() for h in request.history]
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@app.post("/api/agents/hisho/chat")
async def chat_secretary(request: ChatRequest):
    """秘書AIエージェントとのチャット（SSEストリーミング）"""
    from agents.secretary import secretary_chat_stream
    return StreamingResponse(
        secretary_chat_stream(
            message=request.message,
            history=[h.model_dump() for h in request.history]
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )

@app.get("/api/quota")
def get_quota():
    """Gemini API 無料枠の使用状況を確認"""
    try:
        from agents.ai_client import _model_usage, _model_exhausted, GEMINI_MODEL_POOL, PROVIDER
        models = []
        for m in GEMINI_MODEL_POOL:
            models.append({
                "model": m,
                "used": _model_usage.get(m, 0),
                "exhausted": m in _model_exhausted
            })
        return {
            "provider": PROVIDER,
            "models": models,
            "total_used": sum(_model_usage.values()),
            "daily_limit_approx": len(GEMINI_MODEL_POOL) * 20,
        }
    except Exception:
        return {"provider": "unknown", "models": [], "total_used": 0}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
