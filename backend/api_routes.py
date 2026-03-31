"""
api_routes.py - 税理士事務所 AIエージェント管理システム 追加APIルート
FastAPI APIRouter を使用。main.py から include_router() で取り込む。
"""

from fastapi import APIRouter, HTTPException, UploadFile, File, Query, Depends, Header
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, date, timedelta
try:
    from dateutil.relativedelta import relativedelta
except ImportError:
    # dateutil がない場合の簡易実装
    class relativedelta:
        def __init__(self, months=0, days=0, years=0):
            self.months = months
            self.days = days
            self.years = years
        def __radd__(self, other):
            if not isinstance(other, date):
                return NotImplemented
            m = other.month + self.months
            y = other.year + self.years + (m - 1) // 12
            m = (m - 1) % 12 + 1
            import calendar
            max_day = calendar.monthrange(y, m)[1]
            d = min(other.day, max_day) + self.days
            result = date(y, m, 1) + timedelta(days=d - 1)
            return result
import sqlite3
import uuid
import hashlib
import secrets
import os
import json
import shutil

# ---------------------------------------------------------------------------
# データベース接続
# ---------------------------------------------------------------------------
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
DB_PATH = os.path.join(DATA_DIR, "tax_office.db")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)


def get_db() -> sqlite3.Connection:
    """SQLite接続を取得（row_factory=Row付き）"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ---------------------------------------------------------------------------
# api_routes専用テーブル（database.pyに無いもの）
# ---------------------------------------------------------------------------
def _ensure_extra_tables():
    """sessions / uploaded_files テーブルが無ければ作成"""
    conn = get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS sessions (
        token       TEXT PRIMARY KEY,
        user_id     INTEGER NOT NULL,
        created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS uploaded_files (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        original_name TEXT NOT NULL,
        stored_name TEXT NOT NULL,
        content_type TEXT,
        size_bytes  INTEGER,
        uploaded_by TEXT,
        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    conn.commit()
    conn.close()

_ensure_extra_tables()


# ---------------------------------------------------------------------------
# ユーティリティ
# ---------------------------------------------------------------------------
def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _hash_pw(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def _log_audit(action: str, detail: str = "", user_id: str = ""):
    conn = get_db()
    conn.execute(
        "INSERT INTO audit_log (action, detail, user_id, created_at) VALUES (?,?,?,?)",
        (action, detail, user_id, _now()),
    )
    conn.commit()
    conn.close()


def _row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


def _rows_to_list(rows) -> list[dict]:
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# 認証ヘルパー
# ---------------------------------------------------------------------------
def _get_current_user(authorization: Optional[str] = Header(None)) -> Optional[dict]:
    """Authorizationヘッダーからユーザーを取得。トークンが無い/無効なら None。"""
    if not authorization:
        return None
    token = authorization.replace("Bearer ", "")
    conn = get_db()
    row = conn.execute(
        """SELECT u.id, u.username, u.display_name, u.role
           FROM sessions s JOIN users u ON s.user_id = u.id
           WHERE s.token = ?""",
        (token,),
    ).fetchone()
    conn.close()
    if row:
        return dict(row)
    return None


def require_auth(authorization: Optional[str] = Header(None)) -> dict:
    user = _get_current_user(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="認証が必要です")
    return user


# ---------------------------------------------------------------------------
# Pydantic モデル
# ---------------------------------------------------------------------------
class ConversationMessage(BaseModel):
    role: str
    content: str


class ClientCreate(BaseModel):
    name: str
    client_type: str = "法人"
    representative: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    fiscal_year_end: Optional[str] = None
    memo: Optional[str] = None
    tax_types: Optional[str] = None
    contact_person: Optional[str] = None
    invoice_number: Optional[str] = None
    line_user_id: Optional[str] = None


class ClientUpdate(BaseModel):
    name: Optional[str] = None
    client_type: Optional[str] = None
    representative: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    fiscal_year_end: Optional[str] = None
    memo: Optional[str] = None
    tax_types: Optional[str] = None
    contact_person: Optional[str] = None
    invoice_number: Optional[str] = None
    line_user_id: Optional[str] = None


class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    agent_id: Optional[str] = None
    client_id: Optional[int] = None
    priority: str = "medium"
    deadline: Optional[str] = None
    created_by: Optional[str] = "user"


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    agent_id: Optional[str] = None
    client_id: Optional[int] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    deadline: Optional[str] = None


class ChecklistCreate(BaseModel):
    client_id: Optional[int] = None
    template_type: str
    title: str
    items: list[str] = []


class ChecklistFromTemplate(BaseModel):
    client_id: Optional[int] = None
    template_type: str


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    password: str
    display_name: Optional[str] = None


class ReportRequest(BaseModel):
    client_id: int
    year: Optional[int] = None
    month: Optional[int] = None


class LineWebhookEvent(BaseModel):
    events: list[dict] = []


# ---------------------------------------------------------------------------
# チェックリストテンプレート定義
# ---------------------------------------------------------------------------
CHECKLIST_TEMPLATES: dict[str, list[str]] = {
    "決算": [
        "決算整理仕訳の確認",
        "売掛金・買掛金の残高確認",
        "棚卸資産の評価・計上確認",
        "固定資産台帳と帳簿の照合",
        "減価償却費の計算確認",
        "引当金の計上確認（貸倒引当金等）",
        "未払費用・前払費用の計上確認",
        "消費税の仮受・仮払消費税の精算",
        "法人税・住民税・事業税の計算",
        "勘定科目内訳明細書の作成",
        "株主資本等変動計算書の作成",
        "注記表の作成",
        "税務申告書（別表）の作成",
        "電子申告データの確認",
        "決算報告書の最終レビュー",
    ],
    "確定申告": [
        "源泉徴収票の収集・確認",
        "各種控除証明書の収集（生命保険料・地震保険料等）",
        "医療費の集計・明細書作成",
        "事業所得の収支内訳書/青色決算書作成",
        "不動産所得の収支計算",
        "譲渡所得の計算確認",
        "住宅ローン控除の要件確認",
        "ふるさと納税の寄附金受領証確認",
        "所得税額の計算・確認",
        "復興特別所得税の計算",
        "申告書の最終確認・電子申告",
        "納付書の作成・納付期限確認",
    ],
    "年末調整": [
        "扶養控除等申告書の回収",
        "保険料控除申告書の回収",
        "配偶者控除等申告書の回収",
        "住宅借入金等特別控除申告書の回収",
        "前職源泉徴収票の確認（中途入社者）",
        "給与・賞与データの確定",
        "年税額の計算",
        "過不足額の精算",
        "源泉徴収票の作成・配布",
        "法定調書合計表の作成・提出",
    ],
    "月次": [
        "通帳・現金出納帳の照合",
        "売上・仕入の計上確認",
        "経費精算の確認",
        "消費税区分の確認",
        "試算表の作成・レビュー",
        "資金繰り表の更新",
        "源泉税の納付確認",
        "月次報告書の作成",
    ],
    "新規顧問先受入": [
        "顧問契約書の締結",
        "基本情報の登録（法人名・代表者・住所等）",
        "決算期・届出書の確認",
        "過去3期分の決算書・申告書の入手",
        "会計ソフトデータの移行",
        "届出書・申請書の確認（青色申告等）",
        "給与関係書類の確認（源泉所得税）",
        "社会保険加入状況の確認",
        "担当者の割り当て",
        "初回打ち合わせの実施",
    ],
}


# ===========================================================================
# ルーター定義
# ===========================================================================
router = APIRouter()


# ===========================================================================
# 1. Conversation History API
# ===========================================================================

@router.get("/api/conversations/search")
def search_conversations(q: str = Query(..., min_length=1)):
    """全会話履歴からキーワード検索"""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM conversations WHERE content LIKE ? ORDER BY created_at DESC LIMIT 100",
        (f"%{q}%",),
    ).fetchall()
    conn.close()
    return {"results": _rows_to_list(rows)}


@router.get("/api/conversations/{agent_id}")
def get_conversations(agent_id: str, limit: int = Query(50, ge=1, le=500)):
    """エージェントのチャット履歴を取得"""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM conversations WHERE agent_id = ? ORDER BY created_at DESC LIMIT ?",
        (agent_id, limit),
    ).fetchall()
    conn.close()
    return {"agent_id": agent_id, "messages": _rows_to_list(rows)}


@router.post("/api/conversations/{agent_id}")
def save_conversation(agent_id: str, msg: ConversationMessage):
    """エージェントのチャットメッセージを保存"""
    conn = get_db()
    now = _now()
    cur = conn.execute(
        "INSERT INTO conversations (agent_id, role, content, created_at) VALUES (?,?,?,?)",
        (agent_id, msg.role, msg.content, now),
    )
    msg_id = cur.lastrowid
    conn.commit()
    conn.close()
    _log_audit("chat", f"agent={agent_id} role={msg.role}")
    return {"id": msg_id, "agent_id": agent_id, "role": msg.role, "content": msg.content, "created_at": now}


@router.delete("/api/conversations/{agent_id}")
def clear_conversations(agent_id: str):
    """エージェントのチャット履歴を全削除"""
    conn = get_db()
    deleted = conn.execute("DELETE FROM conversations WHERE agent_id = ?", (agent_id,)).rowcount
    conn.commit()
    conn.close()
    _log_audit("chat_clear", f"agent={agent_id} deleted={deleted}")
    return {"deleted": deleted}


# ===========================================================================
# 2. Client (顧問先) Management API
# ===========================================================================

@router.get("/api/clients")
def list_clients(search: Optional[str] = None, client_type: Optional[str] = None):
    """顧問先一覧を取得"""
    conn = get_db()
    query = "SELECT * FROM clients WHERE 1=1"
    params: list = []
    if search:
        query += " AND (name LIKE ? OR representative LIKE ? OR address LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])
    if client_type:
        query += " AND client_type = ?"
        params.append(client_type)
    query += " ORDER BY created_at DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return {"clients": _rows_to_list(rows)}


@router.post("/api/clients")
def create_client(client: ClientCreate):
    """新規顧問先を作成"""
    conn = get_db()
    now = _now()
    cur = conn.execute(
        """INSERT INTO clients (name,client_type,representative,address,phone,email,fiscal_year_end,memo,tax_types,contact_person,invoice_number,line_user_id,created_at,updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (client.name, client.client_type, client.representative, client.address,
         client.phone, client.email, client.fiscal_year_end, client.memo,
         client.tax_types, client.contact_person, client.invoice_number, client.line_user_id, now, now),
    )
    client_id = cur.lastrowid
    conn.commit()
    conn.close()
    _log_audit("client_create", f"id={client_id} name={client.name}")
    return {"id": client_id, "name": client.name, "client_type": client.client_type, "created_at": now}


@router.get("/api/clients/{client_id}")
def get_client(client_id: int):
    """顧問先の詳細を取得"""
    conn = get_db()
    row = conn.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="顧問先が見つかりません")
    return dict(row)


@router.put("/api/clients/{client_id}")
def update_client(client_id: int, update: ClientUpdate):
    """顧問先を更新"""
    conn = get_db()
    existing = conn.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="顧問先が見つかりません")

    fields = {}
    for field_name in ["name", "client_type", "representative", "address", "phone", "email", "fiscal_year_end", "memo", "tax_types", "contact_person", "invoice_number", "line_user_id"]:
        val = getattr(update, field_name, None)
        if val is not None:
            fields[field_name] = val

    if not fields:
        conn.close()
        return {"message": "更新項目がありません"}

    fields["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [client_id]
    conn.execute(f"UPDATE clients SET {set_clause} WHERE id = ?", values)
    conn.commit()

    updated = conn.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
    conn.close()
    _log_audit("client_update", f"id={client_id} fields={list(fields.keys())}")
    return dict(updated)


@router.delete("/api/clients/{client_id}")
def delete_client(client_id: int):
    """顧問先を削除"""
    conn = get_db()
    existing = conn.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="顧問先が見つかりません")
    conn.execute("DELETE FROM clients WHERE id = ?", (client_id,))
    conn.commit()
    conn.close()
    _log_audit("client_delete", f"id={client_id}")
    return {"deleted": client_id}


@router.get("/api/clients/{client_id}/deadlines")
def get_client_deadlines(client_id: int):
    """顧問先の期限一覧を取得"""
    conn = get_db()
    client = conn.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
    if not client:
        conn.close()
        raise HTTPException(status_code=404, detail="顧問先が見つかりません")
    rows = conn.execute(
        "SELECT * FROM deadlines WHERE client_id = ? ORDER BY deadline_date ASC",
        (client_id,),
    ).fetchall()
    conn.close()
    return {"client_id": client_id, "deadlines": _rows_to_list(rows)}


@router.post("/api/clients/{client_id}/generate-deadlines")
def generate_deadlines(client_id: int):
    """顧問先の税務期限を自動生成"""
    conn = get_db()
    client_row = conn.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
    if not client_row:
        conn.close()
        raise HTTPException(status_code=404, detail="顧問先が見つかりません")

    client = dict(client_row)
    fiscal_end_str = client.get("fiscal_year_end")  # e.g. "3" or "03" (month)
    client_type = client.get("client_type", "法人")

    now = datetime.now()
    generated: list[dict] = []

    if client_type == "法人":
        # 決算月から法人税系期限を生成
        try:
            fiscal_month = int(fiscal_end_str) if fiscal_end_str else 3
        except (ValueError, TypeError):
            fiscal_month = 3

        # 直近の決算月末を求める
        year = now.year
        if fiscal_month < now.month:
            year += 1
        fiscal_end_date = date(year, fiscal_month, 1) + relativedelta(months=1) - timedelta(days=1)

        templates = [
            ("法人税・地方法人税 申告期限", fiscal_end_date + relativedelta(months=2)),
            ("法人住民税・事業税 申告期限", fiscal_end_date + relativedelta(months=2)),
            ("消費税 申告期限", fiscal_end_date + relativedelta(months=2)),
            ("法人税 中間申告期限", fiscal_end_date + relativedelta(months=8)),
            ("消費税 中間申告期限", fiscal_end_date + relativedelta(months=8)),
            ("決算書・勘定科目内訳書 作成期限", fiscal_end_date + relativedelta(months=1, days=15)),
            ("株主総会 開催期限", fiscal_end_date + relativedelta(months=3)),
        ]

        for deadline_type, due in templates:
            cur = conn.execute(
                "INSERT INTO deadlines (client_id, deadline_type, deadline_date, is_completed, memo, created_at) VALUES (?,?,?,?,?,?)",
                (client_id, deadline_type, due.isoformat(), 0, None, _now()),
            )
            dl_id = cur.lastrowid
            generated.append({"id": dl_id, "deadline_type": deadline_type, "deadline_date": due.isoformat()})

    else:
        # 個人 - 確定申告系
        year = now.year
        if now.month >= 4:
            year += 1

        templates = [
            ("所得税 確定申告期限", date(year, 3, 15)),
            ("消費税 確定申告期限（個人）", date(year, 3, 31)),
            ("住民税 申告期限", date(year, 3, 15)),
            ("予定納税 第1期", date(year, 7, 31)),
            ("予定納税 第2期", date(year, 11, 30)),
        ]

        for deadline_type, due in templates:
            cur = conn.execute(
                "INSERT INTO deadlines (client_id, deadline_type, deadline_date, is_completed, memo, created_at) VALUES (?,?,?,?,?,?)",
                (client_id, deadline_type, due.isoformat(), 0, None, _now()),
            )
            dl_id = cur.lastrowid
            generated.append({"id": dl_id, "deadline_type": deadline_type, "deadline_date": due.isoformat()})

    # 共通: 年末調整・法定調書
    common_templates = [
        ("年末調整 完了期限", date(now.year if now.month <= 11 else now.year + 1, 12, 25)),
        ("法定調書・給与支払報告書 提出期限", date(now.year if now.month == 1 else now.year + 1, 1, 31)),
        ("償却資産税 申告期限", date(now.year if now.month == 1 else now.year + 1, 1, 31)),
    ]

    for deadline_type, due in common_templates:
        cur = conn.execute(
            "INSERT INTO deadlines (client_id, deadline_type, deadline_date, is_completed, memo, created_at) VALUES (?,?,?,?,?,?)",
            (client_id, deadline_type, due.isoformat(), 0, None, _now()),
        )
        dl_id = cur.lastrowid
        generated.append({"id": dl_id, "deadline_type": deadline_type, "deadline_date": due.isoformat()})

    conn.commit()
    conn.close()
    _log_audit("deadline_generate", f"client={client_id} count={len(generated)}")
    return {"client_id": client_id, "generated": generated}


# ===========================================================================
# 3. Task Management API
# ===========================================================================

@router.get("/api/tasks/manage")
def list_tasks_manage(
    status: Optional[str] = None,
    agent_id: Optional[str] = None,
    client_id: Optional[int] = None,
    days: Optional[int] = None,
):
    """タスク一覧取得（フィルタ付き）"""
    conn = get_db()
    query = "SELECT * FROM tasks WHERE 1=1"
    params: list = []
    if status:
        query += " AND status = ?"
        params.append(status)
    if agent_id:
        query += " AND agent_id = ?"
        params.append(agent_id)
    if client_id:
        query += " AND client_id = ?"
        params.append(client_id)
    if days is not None:
        cutoff = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
        query += " AND deadline <= ? AND deadline IS NOT NULL"
        params.append(cutoff)
    query += " ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 WHEN 'low' THEN 2 ELSE 3 END, deadline ASC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return {"tasks": _rows_to_list(rows)}


@router.post("/api/tasks/manage")
def create_task_manage(task: TaskCreate):
    """タスクを作成"""
    conn = get_db()
    now = _now()
    cur = conn.execute(
        """INSERT INTO tasks (title,description,agent_id,client_id,priority,status,deadline,created_by,created_at,updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (task.title, task.description, task.agent_id, task.client_id,
         task.priority, "pending", task.deadline, task.created_by, now, now),
    )
    task_id = cur.lastrowid
    conn.commit()
    conn.close()
    _log_audit("task_create", f"id={task_id} title={task.title}")
    return {"id": task_id, "title": task.title, "status": "pending", "created_at": now}


@router.put("/api/tasks/manage/{task_id}")
def update_task_manage(task_id: int, update: TaskUpdate):
    """タスクを更新"""
    conn = get_db()
    existing = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="タスクが見つかりません")

    fields = {}
    for field_name in ["title", "description", "agent_id", "client_id", "priority", "status", "deadline"]:
        val = getattr(update, field_name, None)
        if val is not None:
            fields[field_name] = val

    if not fields:
        conn.close()
        return {"message": "更新項目がありません"}

    fields["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [task_id]
    conn.execute(f"UPDATE tasks SET {set_clause} WHERE id = ?", values)
    conn.commit()

    updated = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    conn.close()
    _log_audit("task_update", f"id={task_id}")
    return dict(updated)


@router.put("/api/tasks/manage/{task_id}/complete")
def complete_task(task_id: int):
    """タスクを完了にする"""
    conn = get_db()
    existing = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="タスクが見つかりません")
    now = _now()
    conn.execute(
        "UPDATE tasks SET status = 'done', completed_at = ?, updated_at = ? WHERE id = ?",
        (now, now, task_id),
    )
    conn.commit()
    updated = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    conn.close()
    _log_audit("task_complete", f"id={task_id}")
    return dict(updated)


@router.delete("/api/tasks/manage/{task_id}")
def delete_task(task_id: int):
    """タスクを削除"""
    conn = get_db()
    existing = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="タスクが見つかりません")
    conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()
    _log_audit("task_delete", f"id={task_id}")
    return {"deleted": task_id}


# ===========================================================================
# 4. Checklist API
# ===========================================================================

@router.get("/api/checklists")
def list_checklists(client_id: Optional[int] = None, template_type: Optional[str] = None):
    """チェックリスト一覧を取得"""
    conn = get_db()
    query = "SELECT * FROM checklists WHERE 1=1"
    params: list = []
    if client_id:
        query += " AND client_id = ?"
        params.append(client_id)
    if template_type:
        query += " AND template_type = ?"
        params.append(template_type)
    query += " ORDER BY created_at DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return {"checklists": _rows_to_list(rows)}


@router.post("/api/checklists")
def create_checklist(req: ChecklistCreate):
    """チェックリストを作成（アイテム付き）"""
    conn = get_db()
    now = _now()
    cur = conn.execute(
        "INSERT INTO checklists (client_id, template_type, title, created_at) VALUES (?,?,?,?)",
        (req.client_id, req.template_type, req.title, now),
    )
    cl_id = cur.lastrowid
    items_out: list[dict] = []
    for idx, item_text in enumerate(req.items):
        item_cur = conn.execute(
            "INSERT INTO checklist_items (checklist_id, sort_order, item_text, is_checked) VALUES (?,?,?,?)",
            (cl_id, idx, item_text, 0),
        )
        item_id = item_cur.lastrowid
        items_out.append({"id": item_id, "sort_order": idx, "item_text": item_text, "is_checked": 0})
    conn.commit()
    conn.close()
    _log_audit("checklist_create", f"id={cl_id} type={req.template_type}")
    return {"id": cl_id, "title": req.title, "template_type": req.template_type, "items": items_out}


@router.get("/api/checklists/{checklist_id}")
def get_checklist(checklist_id: int):
    """チェックリストと全アイテムを取得"""
    conn = get_db()
    cl = conn.execute("SELECT * FROM checklists WHERE id = ?", (checklist_id,)).fetchone()
    if not cl:
        conn.close()
        raise HTTPException(status_code=404, detail="チェックリストが見つかりません")
    items = conn.execute(
        "SELECT * FROM checklist_items WHERE checklist_id = ? ORDER BY sort_order ASC",
        (checklist_id,),
    ).fetchall()
    conn.close()
    result = dict(cl)
    result["items"] = _rows_to_list(items)
    return result


@router.put("/api/checklists/{checklist_id}/items/{item_id}/toggle")
def toggle_checklist_item(checklist_id: int, item_id: int):
    """チェックリストのアイテムのチェック状態をトグル"""
    conn = get_db()
    item = conn.execute(
        "SELECT * FROM checklist_items WHERE id = ? AND checklist_id = ?",
        (item_id, checklist_id),
    ).fetchone()
    if not item:
        conn.close()
        raise HTTPException(status_code=404, detail="チェックリストアイテムが見つかりません")

    current = dict(item)
    new_checked = 0 if current["is_checked"] else 1
    checked_at = _now() if new_checked else None
    conn.execute(
        "UPDATE checklist_items SET is_checked = ?, checked_at = ? WHERE id = ?",
        (new_checked, checked_at, item_id),
    )
    conn.commit()

    updated = conn.execute("SELECT * FROM checklist_items WHERE id = ?", (item_id,)).fetchone()
    conn.close()
    _log_audit("checklist_toggle", f"checklist={checklist_id} item={item_id} is_checked={new_checked}")
    return dict(updated)


@router.post("/api/checklists/from-template")
def create_from_template(req: ChecklistFromTemplate):
    """テンプレートからチェックリストを作成"""
    template_items = CHECKLIST_TEMPLATES.get(req.template_type)
    if template_items is None:
        available = list(CHECKLIST_TEMPLATES.keys())
        raise HTTPException(
            status_code=400,
            detail=f"テンプレートが見つかりません: {req.template_type}。利用可能: {available}",
        )

    title = f"{req.template_type}チェックリスト"
    conn = get_db()
    now = _now()
    cur = conn.execute(
        "INSERT INTO checklists (client_id, template_type, title, created_at) VALUES (?,?,?,?)",
        (req.client_id, req.template_type, title, now),
    )
    cl_id = cur.lastrowid
    items_out: list[dict] = []
    for idx, item_text in enumerate(template_items):
        item_cur = conn.execute(
            "INSERT INTO checklist_items (checklist_id, sort_order, item_text, is_checked) VALUES (?,?,?,?)",
            (cl_id, idx, item_text, 0),
        )
        item_id = item_cur.lastrowid
        items_out.append({"id": item_id, "sort_order": idx, "item_text": item_text, "is_checked": 0})
    conn.commit()
    conn.close()
    _log_audit("checklist_from_template", f"id={cl_id} type={req.template_type}")
    return {"id": cl_id, "title": title, "template_type": req.template_type, "items": items_out}


# ===========================================================================
# 5. Calendar/Deadline API
# ===========================================================================

@router.get("/api/calendar")
def get_calendar(days: int = Query(30, ge=1, le=365)):
    """今後の期限一覧を取得"""
    conn = get_db()
    today = date.today().isoformat()
    cutoff = (date.today() + timedelta(days=days)).isoformat()
    rows = conn.execute(
        """SELECT d.*, c.name AS client_name
           FROM deadlines d
           LEFT JOIN clients c ON d.client_id = c.id
           WHERE d.deadline_date >= ? AND d.deadline_date <= ? AND d.is_completed = 0
           ORDER BY d.deadline_date ASC""",
        (today, cutoff),
    ).fetchall()
    conn.close()
    return {"from": today, "to": cutoff, "deadlines": _rows_to_list(rows)}


@router.get("/api/calendar/month/{year}/{month}")
def get_calendar_month(year: int, month: int):
    """指定年月の期限一覧を取得"""
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="月は1〜12で指定してください")
    start = date(year, month, 1).isoformat()
    end = (date(year, month, 1) + relativedelta(months=1) - timedelta(days=1)).isoformat()
    conn = get_db()
    rows = conn.execute(
        """SELECT d.*, c.name AS client_name
           FROM deadlines d
           LEFT JOIN clients c ON d.client_id = c.id
           WHERE d.deadline_date >= ? AND d.deadline_date <= ?
           ORDER BY d.deadline_date ASC""",
        (start, end),
    ).fetchall()
    conn.close()
    return {"year": year, "month": month, "from": start, "to": end, "deadlines": _rows_to_list(rows)}


@router.put("/api/calendar/{deadline_id}/complete")
def complete_deadline(deadline_id: int):
    """期限を完了にする"""
    conn = get_db()
    existing = conn.execute("SELECT * FROM deadlines WHERE id = ?", (deadline_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="期限が見つかりません")
    now = _now()
    conn.execute(
        "UPDATE deadlines SET is_completed = 1, memo = COALESCE(memo, '') WHERE id = ?",
        (deadline_id,),
    )
    conn.commit()
    updated = conn.execute("SELECT * FROM deadlines WHERE id = ?", (deadline_id,)).fetchone()
    conn.close()
    _log_audit("deadline_complete", f"id={deadline_id}")
    return dict(updated)


# ===========================================================================
# 6. Audit Log API
# ===========================================================================

@router.get("/api/audit-log")
def get_audit_log(limit: int = Query(100, ge=1, le=1000), action: Optional[str] = None):
    """監査ログを取得"""
    conn = get_db()
    if action:
        rows = conn.execute(
            "SELECT * FROM audit_log WHERE action = ? ORDER BY created_at DESC LIMIT ?",
            (action, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    conn.close()
    return {"log": _rows_to_list(rows)}


# ===========================================================================
# 7. Auth API (simple token auth)
# ===========================================================================

@router.post("/api/auth/login")
def auth_login(req: LoginRequest):
    """ログイン（セッショントークンを返す）"""
    conn = get_db()
    pw_hash = _hash_pw(req.password)
    user = conn.execute(
        "SELECT * FROM users WHERE username = ? AND password_hash = ?",
        (req.username, pw_hash),
    ).fetchone()
    if not user:
        conn.close()
        raise HTTPException(status_code=401, detail="ユーザー名またはパスワードが正しくありません")

    token = secrets.token_hex(32)
    conn.execute(
        "INSERT INTO sessions (token, user_id, created_at) VALUES (?,?,?)",
        (token, dict(user)["id"], _now()),
    )
    conn.commit()
    conn.close()
    user_dict = dict(user)
    _log_audit("login", f"user={req.username}", str(user_dict["id"]))
    return {
        "token": token,
        "user": {
            "id": user_dict["id"],
            "username": user_dict["username"],
            "display_name": user_dict["display_name"],
            "role": user_dict["role"],
        },
    }


@router.post("/api/auth/register")
def auth_register(req: RegisterRequest):
    """ユーザー登録（最初のユーザーは自動的にadmin）"""
    conn = get_db()

    # ユーザー名の重複チェック
    existing = conn.execute("SELECT id FROM users WHERE username = ?", (req.username,)).fetchone()
    if existing:
        conn.close()
        raise HTTPException(status_code=409, detail="このユーザー名は既に使用されています")

    # 最初のユーザーかどうか確認
    count = conn.execute("SELECT COUNT(*) as cnt FROM users").fetchone()
    is_first = dict(count)["cnt"] == 0
    role = "admin" if is_first else "staff"

    pw_hash = _hash_pw(req.password)
    display_name = req.display_name or req.username
    now = _now()

    cur = conn.execute(
        "INSERT INTO users (username, password_hash, display_name, role, is_active, created_at) VALUES (?,?,?,?,?,?)",
        (req.username, pw_hash, display_name, role, 1, now),
    )
    user_id = cur.lastrowid
    conn.commit()
    conn.close()
    _log_audit("register", f"user={req.username} role={role}", str(user_id))
    return {
        "id": user_id,
        "username": req.username,
        "display_name": display_name,
        "role": role,
        "created_at": now,
    }


@router.get("/api/auth/me")
def auth_me(authorization: Optional[str] = Header(None)):
    """現在のユーザー情報を取得"""
    user = _get_current_user(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="認証が必要です")
    return user


# ===========================================================================
# 8. File Upload API
# ===========================================================================

@router.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    """ファイルをアップロード（PDF/画像）"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="ファイル名が必要です")

    allowed_types = {
        "application/pdf", "image/png", "image/jpeg", "image/gif", "image/webp",
        "text/csv", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
    if file.content_type and file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"対応していないファイル形式です: {file.content_type}。対応形式: PDF, PNG, JPEG, GIF, WebP, CSV, XLSX",
        )

    ext = os.path.splitext(file.filename)[1] if file.filename else ""
    stored_name = f"{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(UPLOAD_DIR, stored_name)

    contents = await file.read()
    size_bytes = len(contents)

    with open(file_path, "wb") as f:
        f.write(contents)

    conn = get_db()
    cur = conn.execute(
        """INSERT INTO uploaded_files (original_name, stored_name, content_type, size_bytes, created_at)
           VALUES (?,?,?,?,?)""",
        (file.filename, stored_name, file.content_type, size_bytes, _now()),
    )
    file_id = cur.lastrowid
    conn.commit()
    conn.close()
    _log_audit("file_upload", f"id={file_id} name={file.filename} size={size_bytes}")
    return {
        "file_id": file_id,
        "original_name": file.filename,
        "content_type": file.content_type,
        "size_bytes": size_bytes,
    }


@router.get("/api/upload/{file_id}")
def get_uploaded_file(file_id: int):
    """アップロード済みファイルの情報を取得"""
    conn = get_db()
    row = conn.execute("SELECT * FROM uploaded_files WHERE id = ?", (file_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="ファイルが見つかりません")
    result = dict(row)
    result["file_path"] = os.path.join(UPLOAD_DIR, result["stored_name"])
    result["exists"] = os.path.exists(os.path.join(UPLOAD_DIR, result["stored_name"]))
    return result


@router.post("/api/upload/{file_id}/analyze")
async def analyze_uploaded_file(file_id: int):
    """アップロード済みファイルをAIで分析"""
    conn = get_db()
    row = conn.execute("SELECT * FROM uploaded_files WHERE id = ?", (file_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="ファイルが見つかりません")

    file_info = dict(row)
    file_path = os.path.join(UPLOAD_DIR, file_info["stored_name"])
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="ファイルが物理的に見つかりません")

    # AI分析を秘書AIに依頼
    try:
        from agents.secretary import secretary_chat_stream
        prompt = (
            f"以下のファイルを分析してください。\n"
            f"ファイル名: {file_info['original_name']}\n"
            f"ファイル形式: {file_info['content_type']}\n"
            f"サイズ: {file_info['size_bytes']} bytes\n"
            f"ファイルパス: {file_path}\n\n"
            f"税理士事務所の業務に関連する内容があれば、要点をまとめてください。"
        )
        # ストリーミングではなく結果を集約
        chunks: list[str] = []
        async for chunk in secretary_chat_stream(prompt, []):
            if isinstance(chunk, str):
                chunks.append(chunk)
            elif isinstance(chunk, bytes):
                chunks.append(chunk.decode("utf-8", errors="replace"))
        analysis = "".join(chunks)
    except ImportError:
        analysis = (
            f"ファイル分析結果（プレースホルダー）:\n"
            f"ファイル名: {file_info['original_name']}\n"
            f"形式: {file_info['content_type']}\n"
            f"サイズ: {file_info['size_bytes']} bytes\n"
            f"※ 秘書AIモジュールが利用できないため、詳細分析は未実行です。"
        )
    except Exception as e:
        analysis = f"分析中にエラーが発生しました: {str(e)}"

    _log_audit("file_analyze", f"id={file_id}")
    return {
        "file_id": file_id,
        "original_name": file_info["original_name"],
        "analysis": analysis,
    }


# ===========================================================================
# 9. Report Generation API
# ===========================================================================

@router.post("/api/reports/monthly")
def generate_monthly_report(req: ReportRequest):
    """月次報告書PDFを生成"""
    conn = get_db()
    client = conn.execute("SELECT * FROM clients WHERE id = ?", (req.client_id,)).fetchone()
    if not client:
        conn.close()
        raise HTTPException(status_code=404, detail="顧問先が見つかりません")

    client_dict = dict(client)
    year = req.year or datetime.now().year
    month = req.month or datetime.now().month

    # タスク情報を取得
    tasks = conn.execute(
        "SELECT * FROM tasks WHERE client_id = ? ORDER BY created_at DESC LIMIT 50",
        (req.client_id,),
    ).fetchall()
    tasks_list = _rows_to_list(tasks)

    # 期限情報を取得
    month_start = date(year, month, 1).isoformat()
    month_end = (date(year, month, 1) + relativedelta(months=1) - timedelta(days=1)).isoformat()
    deadlines = conn.execute(
        "SELECT * FROM deadlines WHERE client_id = ? AND deadline_date >= ? AND deadline_date <= ?",
        (req.client_id, month_start, month_end),
    ).fetchall()
    deadlines_list = _rows_to_list(deadlines)
    conn.close()

    report_filename = f"monthly_report_{client_dict['name']}_{year}_{month:02d}.json"
    report_path = os.path.join(DATA_DIR, report_filename)

    report_data = {
        "report_type": "monthly",
        "client_name": client_dict["name"],
        "client_type": client_dict.get("client_type", ""),
        "year": year,
        "month": month,
        "generated_at": _now(),
        "tasks_summary": {
            "total": len(tasks_list),
            "completed": len([t for t in tasks_list if t["status"] == "done"]),
            "pending": len([t for t in tasks_list if t["status"] == "pending"]),
            "in_progress": len([t for t in tasks_list if t["status"] == "in_progress"]),
        },
        "deadlines_this_month": deadlines_list,
        "tasks": tasks_list,
    }

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2)

    _log_audit("report_monthly", f"client={req.client_id} {year}/{month}")
    return {"status": "generated", "path": report_path, "report": report_data}


@router.post("/api/reports/client-letter")
def generate_client_letter(req: ReportRequest):
    """顧問先向けレターPDFを生成"""
    conn = get_db()
    client = conn.execute("SELECT * FROM clients WHERE id = ?", (req.client_id,)).fetchone()
    if not client:
        conn.close()
        raise HTTPException(status_code=404, detail="顧問先が見つかりません")

    client_dict = dict(client)
    year = req.year or datetime.now().year
    month = req.month or datetime.now().month

    # 今後30日の期限を取得
    today = date.today().isoformat()
    cutoff = (date.today() + timedelta(days=30)).isoformat()
    upcoming = conn.execute(
        "SELECT * FROM deadlines WHERE client_id = ? AND deadline_date >= ? AND deadline_date <= ? AND is_completed = 0 ORDER BY deadline_date ASC",
        (req.client_id, today, cutoff),
    ).fetchall()
    upcoming_list = _rows_to_list(upcoming)
    conn.close()

    letter_filename = f"client_letter_{client_dict['name']}_{year}_{month:02d}.json"
    letter_path = os.path.join(DATA_DIR, letter_filename)

    letter_data = {
        "letter_type": "client_letter",
        "client_name": client_dict["name"],
        "representative": client_dict.get("representative", ""),
        "generated_at": _now(),
        "greeting": f"{client_dict['name']}　御中\n\nいつもお世話になっております。",
        "body": f"{year}年{month}月の税務・会計に関するご案内をお送りいたします。",
        "upcoming_deadlines": upcoming_list,
        "closing": "ご不明な点がございましたら、お気軽にお問い合わせください。\n\n敬具",
    }

    with open(letter_path, "w", encoding="utf-8") as f:
        json.dump(letter_data, f, ensure_ascii=False, indent=2)

    _log_audit("report_client_letter", f"client={req.client_id}")
    return {"status": "generated", "path": letter_path, "letter": letter_data}


# ===========================================================================
# 10. LINE Bot webhook enhancement
# ===========================================================================

@router.post("/api/line/webhook")
async def line_webhook_enhanced(body: LineWebhookEvent):
    """LINE Messaging API Webhook受信 - 秘書AIによる自動応答"""
    events = body.events
    results: list[dict] = []

    for event in events:
        event_type = event.get("type")
        if event_type != "message":
            continue

        message = event.get("message", {})
        if message.get("type") != "text":
            continue

        text = message.get("text", "")
        reply_token = event.get("replyToken", "")
        user_id = event.get("source", {}).get("userId", "unknown")

        # メッセージを会話履歴に保存
        conn = get_db()
        conn.execute(
            "INSERT INTO conversations (agent_id, role, content, created_at) VALUES (?,?,?,?)",
            ("line_bot", "user", text, _now()),
        )
        conn.commit()
        conn.close()

        # 秘書AIで応答を生成
        ai_response = ""
        try:
            from agents.secretary import secretary_chat_stream
            chunks: list[str] = []
            async for chunk in secretary_chat_stream(
                f"LINEから以下のメッセージを受信しました。税理士事務所の秘書として適切に返答してください。\n\nメッセージ: {text}",
                [],
            ):
                if isinstance(chunk, str):
                    chunks.append(chunk)
                elif isinstance(chunk, bytes):
                    chunks.append(chunk.decode("utf-8", errors="replace"))
            ai_response = "".join(chunks)
            # SSEフォーマットのクリーンアップ
            ai_response = ai_response.replace("data: ", "").replace("[DONE]", "").strip()
        except ImportError:
            ai_response = (
                "お問い合わせありがとうございます。"
                "担当者より折り返しご連絡いたしますので、少々お待ちください。"
            )
        except Exception as e:
            ai_response = (
                "お問い合わせありがとうございます。"
                "現在システムの一時的な不具合が発生しております。"
                "担当者より折り返しご連絡いたします。"
            )

        # AI応答も会話履歴に保存
        conn = get_db()
        conn.execute(
            "INSERT INTO conversations (agent_id, role, content, created_at) VALUES (?,?,?,?)",
            ("line_bot", "assistant", ai_response, _now()),
        )
        conn.commit()
        conn.close()

        # LINE Messaging API で応答を送信（チャンネルトークンが環境変数にある場合）
        channel_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
        reply_sent = False
        if channel_token and reply_token:
            try:
                import urllib.request
                import urllib.parse
                payload = json.dumps({
                    "replyToken": reply_token,
                    "messages": [{"type": "text", "text": ai_response}],
                }).encode("utf-8")
                req = urllib.request.Request(
                    "https://api.line.me/v2/bot/message/reply",
                    data=payload,
                    headers={
                        "Authorization": f"Bearer {channel_token}",
                        "Content-Type": "application/json",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    reply_sent = True
            except Exception:
                reply_sent = False

        results.append({
            "user_id": user_id,
            "received_text": text,
            "ai_response": ai_response,
            "reply_sent": reply_sent,
            "reply_token": reply_token,
        })

        _log_audit("line_webhook", f"user={user_id} text={text[:50]}")

    return {"status": "ok", "processed": len(results), "results": results}


# ===========================================================================
# 11. 一括通知 API（LINE + メール同時送信）
# ===========================================================================

class BulkNotifyRequest(BaseModel):
    client_ids: list[int]
    subject: str
    message: str
    channels: list[str] = ["email"]  # "email", "line", "both"
    channel_token: Optional[str] = None


@router.post("/api/notify/bulk")
async def bulk_notify(req: BulkNotifyRequest):
    """複数の顧問先にLINE・メール一括通知"""
    conn = get_db()
    results = []

    for cid in req.client_ids:
        row = conn.execute("SELECT * FROM clients WHERE id = ?", (cid,)).fetchone()
        if not row:
            results.append({"client_id": cid, "status": "not_found"})
            continue

        client = dict(row)
        result = {"client_id": cid, "name": client["name"], "email_sent": False, "line_sent": False}

        # メール送信
        if "email" in req.channels or "both" in req.channels:
            email_addr = client.get("email")
            if email_addr:
                try:
                    gmail_addr = os.environ.get("GMAIL_ADDRESS", "")
                    gmail_pass = os.environ.get("GMAIL_APP_PASSWORD", "")
                    if gmail_addr and gmail_pass:
                        import smtplib
                        from email.mime.text import MIMEText
                        from email.mime.multipart import MIMEMultipart
                        msg = MIMEMultipart()
                        msg["From"] = gmail_addr
                        msg["To"] = email_addr
                        msg["Subject"] = req.subject
                        msg.attach(MIMEText(req.message, "plain", "utf-8"))
                        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                            server.login(gmail_addr, gmail_pass)
                            server.send_message(msg)
                        result["email_sent"] = True
                except Exception as e:
                    result["email_error"] = str(e)

        # LINE送信
        if "line" in req.channels or "both" in req.channels:
            line_uid = client.get("line_user_id")
            token = req.channel_token or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
            if line_uid and token:
                try:
                    import urllib.request
                    payload = json.dumps({
                        "to": line_uid,
                        "messages": [{"type": "text", "text": f"【{req.subject}】\n\n{req.message}"}],
                    }).encode("utf-8")
                    r = urllib.request.Request(
                        "https://api.line.me/v2/bot/message/push",
                        data=payload,
                        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(r, timeout=10):
                        result["line_sent"] = True
                except Exception as e:
                    result["line_error"] = str(e)

        # 通知ログ保存
        channels_used = []
        if result["email_sent"]:
            channels_used.append("email")
        if result["line_sent"]:
            channels_used.append("line")
        if channels_used:
            conn.execute(
                "INSERT INTO notification_log (client_id, channel, subject, content, status, created_at) VALUES (?,?,?,?,?,?)",
                (cid, ",".join(channels_used), req.subject, req.message, "sent", _now()),
            )

        results.append(result)

    conn.commit()
    conn.close()
    _log_audit("bulk_notify", f"clients={req.client_ids} channels={req.channels}")
    return {"status": "ok", "results": results}


# ===========================================================================
# 12. メールテンプレート管理 API
# ===========================================================================

class EmailTemplateCreate(BaseModel):
    name: str
    subject: str
    body: str
    category: str = "一般"


@router.get("/api/email-templates")
def list_email_templates():
    """メールテンプレート一覧"""
    conn = get_db()
    rows = conn.execute("SELECT * FROM email_templates ORDER BY category, name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.post("/api/email-templates")
def create_email_template(tmpl: EmailTemplateCreate):
    """メールテンプレート作成"""
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO email_templates (name, subject, body, category, created_at) VALUES (?,?,?,?,?)",
        (tmpl.name, tmpl.subject, tmpl.body, tmpl.category, _now()),
    )
    conn.commit()
    tid = cur.lastrowid
    conn.close()
    return {"id": tid, "name": tmpl.name}


@router.delete("/api/email-templates/{template_id}")
def delete_email_template(template_id: int):
    """メールテンプレート削除"""
    conn = get_db()
    conn.execute("DELETE FROM email_templates WHERE id = ?", (template_id,))
    conn.commit()
    conn.close()
    return {"status": "deleted"}


# ===========================================================================
# 13. 通知履歴 API
# ===========================================================================

@router.get("/api/notification-log")
def list_notification_log():
    """通知履歴一覧"""
    conn = get_db()
    rows = conn.execute("""
        SELECT n.*, c.name as client_name
        FROM notification_log n
        LEFT JOIN clients c ON n.client_id = c.id
        ORDER BY n.created_at DESC
        LIMIT 100
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]
