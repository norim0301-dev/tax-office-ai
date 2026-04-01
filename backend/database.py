"""
税理士事務所AIシステム - データベースモジュール

SQLiteを使用した永続化レイヤー。
会話履歴、顧問先管理、タスク管理、チェックリスト、
監査ログ、ユーザー管理、申告期限カレンダーを管理する。
"""

import sqlite3
import hashlib
import json
import os
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple

# データベースファイルパス
DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DB_PATH = os.path.join(DB_DIR, "tax_office.db")


def _get_connection() -> sqlite3.Connection:
    """データベース接続を取得する。ディレクトリが無ければ自動作成。"""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _now() -> str:
    """現在のISO形式タイムスタンプを返す。"""
    return datetime.now().isoformat()


def _hash_password(password: str) -> str:
    """SHA-256でパスワードをハッシュ化する。"""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


# ============================================================
# 初期化
# ============================================================

def init_db() -> None:
    """全テーブルを作成する。既存テーブルがあればスキップ。"""
    conn = _get_connection()
    try:
        cur = conn.cursor()

        # conversations - 会話履歴
        cur.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT,
                role TEXT,
                content TEXT,
                tool_name TEXT,
                tool_input TEXT,
                tool_result TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # clients - 顧問先マスタ
        cur.execute("""
            CREATE TABLE IF NOT EXISTS clients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                client_type TEXT,
                representative TEXT,
                fiscal_year_end TEXT,
                tax_types TEXT,
                address TEXT,
                phone TEXT,
                email TEXT,
                contact_person TEXT,
                memo TEXT,
                invoice_number TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # tasks - タスク管理
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                agent_id TEXT,
                client_id INTEGER,
                priority TEXT DEFAULT 'medium',
                status TEXT DEFAULT 'pending',
                deadline TEXT,
                created_by TEXT DEFAULT 'user',
                completed_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (client_id) REFERENCES clients(id)
            )
        """)

        # checklists - チェックリスト
        cur.execute("""
            CREATE TABLE IF NOT EXISTS checklists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER,
                client_id INTEGER,
                title TEXT,
                template_type TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (task_id) REFERENCES tasks(id),
                FOREIGN KEY (client_id) REFERENCES clients(id)
            )
        """)

        # checklist_items - チェック項目
        cur.execute("""
            CREATE TABLE IF NOT EXISTS checklist_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                checklist_id INTEGER,
                item_text TEXT,
                is_checked BOOLEAN DEFAULT 0,
                checked_at TIMESTAMP,
                sort_order INTEGER DEFAULT 0,
                FOREIGN KEY (checklist_id) REFERENCES checklists(id)
            )
        """)

        # audit_log - 監査ログ
        cur.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT DEFAULT 'default',
                action TEXT,
                target_type TEXT,
                target_id TEXT,
                detail TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # users - ユーザー管理
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                display_name TEXT,
                role TEXT DEFAULT 'staff',
                is_active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # deadlines - 申告期限カレンダー
        cur.execute("""
            CREATE TABLE IF NOT EXISTS deadlines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER,
                deadline_type TEXT,
                deadline_date TEXT,
                is_completed BOOLEAN DEFAULT 0,
                notified BOOLEAN DEFAULT 0,
                memo TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (client_id) REFERENCES clients(id)
            )
        """)

        # メールテンプレート
        cur.execute("""
            CREATE TABLE IF NOT EXISTS email_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                subject TEXT,
                body TEXT,
                category TEXT DEFAULT '一般',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 通知履歴
        cur.execute("""
            CREATE TABLE IF NOT EXISTS notification_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER,
                channel TEXT,
                subject TEXT,
                content TEXT,
                status TEXT DEFAULT 'sent',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (client_id) REFERENCES clients(id)
            )
        """)

        # document_templates - 書類テンプレート管理
        cur.execute("""
            CREATE TABLE IF NOT EXISTS document_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                category TEXT,
                source TEXT,
                file_type TEXT,
                file_path TEXT,
                field_schema TEXT,
                description TEXT,
                tags TEXT,
                is_active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # document_instances - 書類作成インスタンス
        cur.execute("""
            CREATE TABLE IF NOT EXISTS document_instances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                template_id INTEGER,
                client_id INTEGER,
                title TEXT NOT NULL,
                field_data TEXT,
                status TEXT DEFAULT 'draft',
                output_file_path TEXT,
                memo TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (template_id) REFERENCES document_templates(id),
                FOREIGN KEY (client_id) REFERENCES clients(id)
            )
        """)

        # template_field_mappings - テンプレートフィールドマッピング
        cur.execute("""
            CREATE TABLE IF NOT EXISTS template_field_mappings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                template_id INTEGER,
                field_name TEXT,
                client_column TEXT,
                transform TEXT,
                FOREIGN KEY (template_id) REFERENCES document_templates(id)
            )
        """)

        # clients テーブルに line_user_id カラムを追加（存在しなければ）
        try:
            cur.execute("ALTER TABLE clients ADD COLUMN line_user_id TEXT")
        except sqlite3.OperationalError:
            pass  # 既にカラムが存在する場合はスキップ

        # インデックス作成
        cur.execute("CREATE INDEX IF NOT EXISTS idx_conversations_agent ON conversations(agent_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_agent ON tasks(agent_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_deadline ON tasks(deadline)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_deadlines_date ON deadlines(deadline_date)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_deadlines_client ON deadlines(client_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_checklist_items_checklist ON checklist_items(checklist_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_document_templates_category ON document_templates(category)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_document_instances_template ON document_instances(template_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_document_instances_client ON document_instances(client_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_document_instances_status ON document_instances(status)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_template_field_mappings_template ON template_field_mappings(template_id)")

        conn.commit()
    except Exception as e:
        conn.rollback()
        raise RuntimeError(f"データベース初期化エラー: {e}")
    finally:
        conn.close()


# ============================================================
# conversations - 会話履歴
# ============================================================

def save_message(
    agent_id: str,
    role: str,
    content: str,
    tool_name: Optional[str] = None,
    tool_input: Optional[str] = None,
    tool_result: Optional[str] = None,
) -> int:
    """会話メッセージを保存する。

    Args:
        agent_id: エージェントID（kanri, hisho, hojin 等）
        role: ロール（user / assistant）
        content: メッセージ本文
        tool_name: 使用したツール名（任意）
        tool_input: ツール入力JSON（任意）
        tool_result: ツール実行結果（任意）

    Returns:
        挿入されたレコードのID
    """
    conn = _get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO conversations (agent_id, role, content, tool_name, tool_input, tool_result, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (agent_id, role, content, tool_name, tool_input, tool_result, _now()),
        )
        conn.commit()
        return cur.lastrowid
    except Exception as e:
        conn.rollback()
        raise RuntimeError(f"メッセージ保存エラー: {e}")
    finally:
        conn.close()


def get_history(agent_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """指定エージェントの会話履歴を取得する。

    Args:
        agent_id: エージェントID
        limit: 取得件数（デフォルト50）

    Returns:
        会話メッセージのリスト（古い順）
    """
    conn = _get_connection()
    try:
        rows = conn.execute(
            """SELECT * FROM conversations
               WHERE agent_id = ?
               ORDER BY created_at DESC
               LIMIT ?""",
            (agent_id, limit),
        ).fetchall()
        return [dict(r) for r in reversed(rows)]
    except Exception as e:
        raise RuntimeError(f"履歴取得エラー: {e}")
    finally:
        conn.close()


def search_conversations(query: str) -> List[Dict[str, Any]]:
    """会話内容をキーワード検索する。

    Args:
        query: 検索キーワード

    Returns:
        マッチした会話メッセージのリスト
    """
    conn = _get_connection()
    try:
        rows = conn.execute(
            """SELECT * FROM conversations
               WHERE content LIKE ?
               ORDER BY created_at DESC
               LIMIT 100""",
            (f"%{query}%",),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        raise RuntimeError(f"会話検索エラー: {e}")
    finally:
        conn.close()


# ============================================================
# clients - 顧問先マスタ
# ============================================================

def create_client(
    name: str,
    client_type: Optional[str] = None,
    representative: Optional[str] = None,
    fiscal_year_end: Optional[str] = None,
    tax_types: Optional[List[str]] = None,
    address: Optional[str] = None,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    contact_person: Optional[str] = None,
    memo: Optional[str] = None,
    invoice_number: Optional[str] = None,
) -> int:
    """顧問先を新規登録する。

    Args:
        name: 会社名または個人名（必須）
        client_type: "法人" or "個人"
        representative: 代表者名
        fiscal_year_end: 決算月（例: "3", "12"）
        tax_types: 税目リスト（例: ["法人税", "消費税"]）
        address: 住所
        phone: 電話番号
        email: メールアドレス
        contact_person: 担当者名
        memo: メモ
        invoice_number: インボイス登録番号

    Returns:
        作成されたクライアントのID
    """
    conn = _get_connection()
    try:
        now = _now()
        tax_types_json = json.dumps(tax_types, ensure_ascii=False) if tax_types else None
        cur = conn.execute(
            """INSERT INTO clients
               (name, client_type, representative, fiscal_year_end, tax_types,
                address, phone, email, contact_person, memo, invoice_number,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, client_type, representative, fiscal_year_end, tax_types_json,
             address, phone, email, contact_person, memo, invoice_number,
             now, now),
        )
        conn.commit()
        return cur.lastrowid
    except Exception as e:
        conn.rollback()
        raise RuntimeError(f"顧問先登録エラー: {e}")
    finally:
        conn.close()


def get_client(client_id: int) -> Optional[Dict[str, Any]]:
    """顧問先を1件取得する。

    Args:
        client_id: クライアントID

    Returns:
        クライアント情報の辞書。見つからない場合はNone。
    """
    conn = _get_connection()
    try:
        row = conn.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
        if row:
            d = dict(row)
            if d.get("tax_types"):
                d["tax_types"] = json.loads(d["tax_types"])
            return d
        return None
    except Exception as e:
        raise RuntimeError(f"顧問先取得エラー: {e}")
    finally:
        conn.close()


def get_all_clients() -> List[Dict[str, Any]]:
    """全顧問先を取得する。

    Returns:
        クライアント情報のリスト
    """
    conn = _get_connection()
    try:
        rows = conn.execute("SELECT * FROM clients ORDER BY name").fetchall()
        results = []
        for row in rows:
            d = dict(row)
            if d.get("tax_types"):
                d["tax_types"] = json.loads(d["tax_types"])
            results.append(d)
        return results
    except Exception as e:
        raise RuntimeError(f"顧問先一覧取得エラー: {e}")
    finally:
        conn.close()


def update_client(client_id: int, **kwargs) -> bool:
    """顧問先情報を更新する。

    Args:
        client_id: クライアントID
        **kwargs: 更新するフィールドと値

    Returns:
        更新成功ならTrue
    """
    if not kwargs:
        return False

    conn = _get_connection()
    try:
        # tax_typesがリストならJSON変換
        if "tax_types" in kwargs and isinstance(kwargs["tax_types"], list):
            kwargs["tax_types"] = json.dumps(kwargs["tax_types"], ensure_ascii=False)

        kwargs["updated_at"] = _now()
        set_clause = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [client_id]

        cur = conn.execute(
            f"UPDATE clients SET {set_clause} WHERE id = ?",
            values,
        )
        conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        conn.rollback()
        raise RuntimeError(f"顧問先更新エラー: {e}")
    finally:
        conn.close()


def delete_client(client_id: int) -> bool:
    """顧問先を削除する。

    Args:
        client_id: クライアントID

    Returns:
        削除成功ならTrue
    """
    conn = _get_connection()
    try:
        cur = conn.execute("DELETE FROM clients WHERE id = ?", (client_id,))
        conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        conn.rollback()
        raise RuntimeError(f"顧問先削除エラー: {e}")
    finally:
        conn.close()


def search_clients(query: str) -> List[Dict[str, Any]]:
    """顧問先をキーワード検索する。名前・住所・メモ等を対象。

    Args:
        query: 検索キーワード

    Returns:
        マッチした顧問先のリスト
    """
    conn = _get_connection()
    try:
        like = f"%{query}%"
        rows = conn.execute(
            """SELECT * FROM clients
               WHERE name LIKE ? OR representative LIKE ?
                  OR address LIKE ? OR memo LIKE ?
                  OR contact_person LIKE ? OR invoice_number LIKE ?
               ORDER BY name""",
            (like, like, like, like, like, like),
        ).fetchall()
        results = []
        for row in rows:
            d = dict(row)
            if d.get("tax_types"):
                d["tax_types"] = json.loads(d["tax_types"])
            results.append(d)
        return results
    except Exception as e:
        raise RuntimeError(f"顧問先検索エラー: {e}")
    finally:
        conn.close()


# ============================================================
# tasks - タスク管理
# ============================================================

def create_task(
    title: str,
    description: Optional[str] = None,
    agent_id: Optional[str] = None,
    client_id: Optional[int] = None,
    priority: str = "medium",
    status: str = "pending",
    deadline: Optional[str] = None,
    created_by: str = "user",
) -> int:
    """タスクを新規作成する。

    Args:
        title: タスクタイトル（必須）
        description: 説明
        agent_id: 担当エージェントID
        client_id: 関連する顧問先ID
        priority: 優先度（high/medium/low）
        status: ステータス（pending/in_progress/done）
        deadline: 期限（ISO日付）
        created_by: 作成者（user/ai）

    Returns:
        作成されたタスクのID
    """
    conn = _get_connection()
    try:
        now = _now()
        cur = conn.execute(
            """INSERT INTO tasks
               (title, description, agent_id, client_id, priority, status,
                deadline, created_by, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (title, description, agent_id, client_id, priority, status,
             deadline, created_by, now, now),
        )
        conn.commit()
        return cur.lastrowid
    except Exception as e:
        conn.rollback()
        raise RuntimeError(f"タスク作成エラー: {e}")
    finally:
        conn.close()


def get_task(task_id: int) -> Optional[Dict[str, Any]]:
    """タスクを1件取得する。

    Args:
        task_id: タスクID

    Returns:
        タスク情報の辞書。見つからない場合はNone。
    """
    conn = _get_connection()
    try:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row else None
    except Exception as e:
        raise RuntimeError(f"タスク取得エラー: {e}")
    finally:
        conn.close()


def get_all_tasks(
    status: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """タスク一覧を取得する。フィルタ条件指定可能。

    Args:
        status: ステータスでフィルタ（任意）
        agent_id: エージェントIDでフィルタ（任意）

    Returns:
        タスク情報のリスト
    """
    conn = _get_connection()
    try:
        query = "SELECT * FROM tasks WHERE 1=1"
        params: List[Any] = []

        if status:
            query += " AND status = ?"
            params.append(status)
        if agent_id:
            query += " AND agent_id = ?"
            params.append(agent_id)

        query += " ORDER BY CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 END, deadline ASC"

        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        raise RuntimeError(f"タスク一覧取得エラー: {e}")
    finally:
        conn.close()


def update_task(task_id: int, **kwargs) -> bool:
    """タスク情報を更新する。

    Args:
        task_id: タスクID
        **kwargs: 更新するフィールドと値

    Returns:
        更新成功ならTrue
    """
    if not kwargs:
        return False

    conn = _get_connection()
    try:
        kwargs["updated_at"] = _now()
        set_clause = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [task_id]

        cur = conn.execute(
            f"UPDATE tasks SET {set_clause} WHERE id = ?",
            values,
        )
        conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        conn.rollback()
        raise RuntimeError(f"タスク更新エラー: {e}")
    finally:
        conn.close()


def complete_task(task_id: int) -> bool:
    """タスクを完了にする。

    Args:
        task_id: タスクID

    Returns:
        更新成功ならTrue
    """
    conn = _get_connection()
    try:
        now = _now()
        cur = conn.execute(
            "UPDATE tasks SET status = 'done', completed_at = ?, updated_at = ? WHERE id = ?",
            (now, now, task_id),
        )
        conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        conn.rollback()
        raise RuntimeError(f"タスク完了エラー: {e}")
    finally:
        conn.close()


def get_tasks_by_deadline(days: int = 7) -> List[Dict[str, Any]]:
    """指定日数以内に期限が来るタスクを取得する。

    Args:
        days: 何日以内のタスクを取得するか（デフォルト7日）

    Returns:
        期限の近いタスクのリスト
    """
    conn = _get_connection()
    try:
        target_date = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
        today = datetime.now().strftime("%Y-%m-%d")
        rows = conn.execute(
            """SELECT * FROM tasks
               WHERE status != 'done'
                 AND deadline IS NOT NULL
                 AND deadline <= ?
                 AND deadline >= ?
               ORDER BY deadline ASC""",
            (target_date, today),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        raise RuntimeError(f"期限タスク取得エラー: {e}")
    finally:
        conn.close()


# ============================================================
# checklists - チェックリスト
# ============================================================

def create_checklist(
    title: str,
    task_id: Optional[int] = None,
    client_id: Optional[int] = None,
    template_type: Optional[str] = None,
) -> int:
    """チェックリストを新規作成する。

    Args:
        title: チェックリスト名
        task_id: 関連タスクID（任意）
        client_id: 関連顧問先ID（任意）
        template_type: テンプレート種類（"決算", "確定申告", "年末調整" 等）

    Returns:
        作成されたチェックリストのID
    """
    conn = _get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO checklists (task_id, client_id, title, template_type, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (task_id, client_id, title, template_type, _now()),
        )
        conn.commit()
        return cur.lastrowid
    except Exception as e:
        conn.rollback()
        raise RuntimeError(f"チェックリスト作成エラー: {e}")
    finally:
        conn.close()


def get_checklist(checklist_id: int) -> Optional[Dict[str, Any]]:
    """チェックリストを項目付きで取得する。

    Args:
        checklist_id: チェックリストID

    Returns:
        チェックリスト情報（items含む）。見つからない場合はNone。
    """
    conn = _get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM checklists WHERE id = ?", (checklist_id,)
        ).fetchone()
        if not row:
            return None

        checklist = dict(row)
        items = conn.execute(
            """SELECT * FROM checklist_items
               WHERE checklist_id = ?
               ORDER BY sort_order ASC, id ASC""",
            (checklist_id,),
        ).fetchall()
        checklist["items"] = [dict(item) for item in items]
        return checklist
    except Exception as e:
        raise RuntimeError(f"チェックリスト取得エラー: {e}")
    finally:
        conn.close()


def add_checklist_item(
    checklist_id: int,
    item_text: str,
    sort_order: int = 0,
) -> int:
    """チェックリストに項目を追加する。

    Args:
        checklist_id: チェックリストID
        item_text: チェック項目のテキスト
        sort_order: 表示順（デフォルト0）

    Returns:
        作成された項目のID
    """
    conn = _get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO checklist_items (checklist_id, item_text, sort_order)
               VALUES (?, ?, ?)""",
            (checklist_id, item_text, sort_order),
        )
        conn.commit()
        return cur.lastrowid
    except Exception as e:
        conn.rollback()
        raise RuntimeError(f"チェック項目追加エラー: {e}")
    finally:
        conn.close()


def toggle_checklist_item(item_id: int) -> bool:
    """チェック項目のON/OFFを切り替える。

    Args:
        item_id: チェック項目ID

    Returns:
        更新成功ならTrue
    """
    conn = _get_connection()
    try:
        row = conn.execute(
            "SELECT is_checked FROM checklist_items WHERE id = ?", (item_id,)
        ).fetchone()
        if not row:
            return False

        new_checked = 0 if row["is_checked"] else 1
        checked_at = _now() if new_checked else None
        conn.execute(
            "UPDATE checklist_items SET is_checked = ?, checked_at = ? WHERE id = ?",
            (new_checked, checked_at, item_id),
        )
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        raise RuntimeError(f"チェック項目切替エラー: {e}")
    finally:
        conn.close()


def get_checklists_by_client(client_id: int) -> List[Dict[str, Any]]:
    """顧問先に紐づくチェックリスト一覧を取得する。

    Args:
        client_id: クライアントID

    Returns:
        チェックリストのリスト（各項目含む）
    """
    conn = _get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM checklists WHERE client_id = ? ORDER BY created_at DESC",
            (client_id,),
        ).fetchall()

        results = []
        for row in rows:
            cl = dict(row)
            items = conn.execute(
                """SELECT * FROM checklist_items
                   WHERE checklist_id = ?
                   ORDER BY sort_order ASC, id ASC""",
                (cl["id"],),
            ).fetchall()
            cl["items"] = [dict(item) for item in items]
            results.append(cl)
        return results
    except Exception as e:
        raise RuntimeError(f"チェックリスト一覧取得エラー: {e}")
    finally:
        conn.close()


# ============================================================
# audit_log - 監査ログ
# ============================================================

def log_action(
    action: str,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    detail: Optional[str] = None,
    user_id: str = "default",
) -> int:
    """監査ログを記録する。

    Args:
        action: アクション種別（"chat", "task_create", "client_update" 等）
        target_type: 対象の種類（"conversation", "task", "client" 等）
        target_id: 対象のID
        detail: 詳細テキスト
        user_id: ユーザーID（デフォルト 'default'）

    Returns:
        作成されたログのID
    """
    conn = _get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO audit_log (user_id, action, target_type, target_id, detail, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, action, target_type, target_id, detail, _now()),
        )
        conn.commit()
        return cur.lastrowid
    except Exception as e:
        conn.rollback()
        raise RuntimeError(f"監査ログ記録エラー: {e}")
    finally:
        conn.close()


def get_audit_log(
    limit: int = 100,
    action: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """監査ログを取得する。

    Args:
        limit: 取得件数（デフォルト100）
        action: アクション種別でフィルタ（任意）

    Returns:
        監査ログのリスト（新しい順）
    """
    conn = _get_connection()
    try:
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
        return [dict(r) for r in rows]
    except Exception as e:
        raise RuntimeError(f"監査ログ取得エラー: {e}")
    finally:
        conn.close()


# ============================================================
# users - ユーザー管理
# ============================================================

def create_user(
    username: str,
    password: str,
    display_name: Optional[str] = None,
    role: str = "staff",
) -> int:
    """ユーザーを新規作成する。

    Args:
        username: ユーザー名（一意）
        password: パスワード（平文。SHA-256でハッシュ化して保存）
        display_name: 表示名
        role: 権限（admin/staff）

    Returns:
        作成されたユーザーのID
    """
    conn = _get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO users (username, password_hash, display_name, role, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (username, _hash_password(password), display_name, role, _now()),
        )
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        conn.rollback()
        raise ValueError(f"ユーザー名 '{username}' は既に使用されています")
    except Exception as e:
        conn.rollback()
        raise RuntimeError(f"ユーザー作成エラー: {e}")
    finally:
        conn.close()


def authenticate(username: str, password: str) -> Optional[Dict[str, Any]]:
    """ユーザー認証を行う。

    Args:
        username: ユーザー名
        password: パスワード（平文）

    Returns:
        認証成功時はユーザー情報（password_hash除く）。失敗時はNone。
    """
    conn = _get_connection()
    try:
        row = conn.execute(
            """SELECT * FROM users
               WHERE username = ? AND password_hash = ? AND is_active = 1""",
            (username, _hash_password(password)),
        ).fetchone()
        if row:
            user = dict(row)
            del user["password_hash"]
            return user
        return None
    except Exception as e:
        raise RuntimeError(f"認証エラー: {e}")
    finally:
        conn.close()


def get_user(user_id: int) -> Optional[Dict[str, Any]]:
    """ユーザー情報を取得する（password_hash除く）。

    Args:
        user_id: ユーザーID

    Returns:
        ユーザー情報の辞書。見つからない場合はNone。
    """
    conn = _get_connection()
    try:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row:
            user = dict(row)
            del user["password_hash"]
            return user
        return None
    except Exception as e:
        raise RuntimeError(f"ユーザー取得エラー: {e}")
    finally:
        conn.close()


# ============================================================
# deadlines - 申告期限カレンダー
# ============================================================

def create_deadline(
    client_id: int,
    deadline_type: str,
    deadline_date: str,
    memo: Optional[str] = None,
) -> int:
    """申告期限を新規登録する。

    Args:
        client_id: クライアントID
        deadline_type: 期限種別（"法人税申告", "消費税申告" 等）
        deadline_date: 期限日（ISO日付 YYYY-MM-DD）
        memo: メモ

    Returns:
        作成された期限のID
    """
    conn = _get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO deadlines (client_id, deadline_type, deadline_date, memo, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (client_id, deadline_type, deadline_date, memo, _now()),
        )
        conn.commit()
        return cur.lastrowid
    except Exception as e:
        conn.rollback()
        raise RuntimeError(f"期限登録エラー: {e}")
    finally:
        conn.close()


def get_upcoming_deadlines(days: int = 30) -> List[Dict[str, Any]]:
    """指定日数以内の未完了期限を取得する。顧問先名も含む。

    Args:
        days: 何日先までを取得するか（デフォルト30日）

    Returns:
        期限情報のリスト（顧問先名付き）
    """
    conn = _get_connection()
    try:
        target_date = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
        today = datetime.now().strftime("%Y-%m-%d")
        rows = conn.execute(
            """SELECT d.*, c.name AS client_name
               FROM deadlines d
               LEFT JOIN clients c ON d.client_id = c.id
               WHERE d.is_completed = 0
                 AND d.deadline_date <= ?
                 AND d.deadline_date >= ?
               ORDER BY d.deadline_date ASC""",
            (target_date, today),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        raise RuntimeError(f"期限取得エラー: {e}")
    finally:
        conn.close()


def mark_deadline_completed(deadline_id: int) -> bool:
    """期限を完了にする。

    Args:
        deadline_id: 期限ID

    Returns:
        更新成功ならTrue
    """
    conn = _get_connection()
    try:
        cur = conn.execute(
            "UPDATE deadlines SET is_completed = 1 WHERE id = ?",
            (deadline_id,),
        )
        conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        conn.rollback()
        raise RuntimeError(f"期限完了エラー: {e}")
    finally:
        conn.close()


def generate_deadlines_for_client(client_id: int) -> List[int]:
    """顧問先の決算月に基づき、標準的な税務申告期限を自動生成する。

    生成される期限:
        - 法人税申告: 決算日の2ヶ月後
        - 消費税申告: 決算日の2ヶ月後
        - 源泉所得税（納期の特例）: 7/10, 1/20
        - 住民税特別徴収: 毎月10日（12ヶ月分）
        - 法定調書: 1/31
        - 償却資産申告: 1/31
        - 算定基礎届: 7/10

    Args:
        client_id: クライアントID

    Returns:
        作成された期限IDのリスト
    """
    client = get_client(client_id)
    if not client:
        raise ValueError(f"顧問先ID {client_id} が見つかりません")

    fiscal_month = int(client.get("fiscal_year_end") or "3")
    now = datetime.now()
    current_year = now.year
    created_ids: List[int] = []

    conn = _get_connection()
    try:
        # --- 法人税申告: 決算日の2ヶ月後 ---
        fiscal_end_date = _fiscal_end_date(fiscal_month, current_year, now)
        hojinzei_deadline = _add_months(fiscal_end_date, 2)
        created_ids.append(_insert_deadline(
            conn, client_id, "法人税申告", hojinzei_deadline.strftime("%Y-%m-%d"),
            f"決算月: {fiscal_month}月"
        ))

        # --- 消費税申告: 決算日の2ヶ月後 ---
        created_ids.append(_insert_deadline(
            conn, client_id, "消費税申告", hojinzei_deadline.strftime("%Y-%m-%d"),
            f"決算月: {fiscal_month}月"
        ))

        # --- 源泉所得税（納期の特例）: 7/10, 1/20 ---
        for month, day, label in [(7, 10, "上半期分"), (1, 20, "下半期分")]:
            year = current_year if datetime(current_year, month, day) >= now else current_year + 1
            created_ids.append(_insert_deadline(
                conn, client_id, "源泉所得税（納期の特例）",
                f"{year}-{month:02d}-{day:02d}", label
            ))

        # --- 住民税特別徴収: 毎月10日（12ヶ月分） ---
        for i in range(12):
            target = datetime(current_year, now.month, 1) + timedelta(days=32 * i)
            target = datetime(target.year, target.month, 10)
            if target >= now:
                created_ids.append(_insert_deadline(
                    conn, client_id, "住民税特別徴収",
                    target.strftime("%Y-%m-%d"), f"{target.month}月分"
                ))

        # --- 法定調書: 1/31 ---
        year_for_jan = current_year if datetime(current_year, 1, 31) >= now else current_year + 1
        created_ids.append(_insert_deadline(
            conn, client_id, "法定調書",
            f"{year_for_jan}-01-31", None
        ))

        # --- 償却資産申告: 1/31 ---
        created_ids.append(_insert_deadline(
            conn, client_id, "償却資産申告",
            f"{year_for_jan}-01-31", None
        ))

        # --- 算定基礎届: 7/10 ---
        year_for_jul = current_year if datetime(current_year, 7, 10) >= now else current_year + 1
        created_ids.append(_insert_deadline(
            conn, client_id, "算定基礎届",
            f"{year_for_jul}-07-10", None
        ))

        conn.commit()
        return created_ids
    except Exception as e:
        conn.rollback()
        raise RuntimeError(f"期限自動生成エラー: {e}")
    finally:
        conn.close()


def _fiscal_end_date(fiscal_month: int, year: int, now: datetime) -> datetime:
    """決算月末日を算出する。過去の場合は翌年にする。"""
    import calendar
    last_day = calendar.monthrange(year, fiscal_month)[1]
    end = datetime(year, fiscal_month, last_day)
    if end < now:
        last_day = calendar.monthrange(year + 1, fiscal_month)[1]
        end = datetime(year + 1, fiscal_month, last_day)
    return end


def _add_months(dt: datetime, months: int) -> datetime:
    """指定月数を加算する。月末を考慮。"""
    import calendar
    month = dt.month + months
    year = dt.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return datetime(year, month, day)


def _insert_deadline(
    conn: sqlite3.Connection,
    client_id: int,
    deadline_type: str,
    deadline_date: str,
    memo: Optional[str],
) -> int:
    """期限を1件INSERTする内部ヘルパー。commitは呼び出し元で行う。"""
    cur = conn.execute(
        """INSERT INTO deadlines (client_id, deadline_type, deadline_date, memo, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (client_id, deadline_type, deadline_date, memo, _now()),
    )
    return cur.lastrowid


# ============================================================
# モジュール直接実行時の初期化
# ============================================================

if __name__ == "__main__":
    init_db()
    print(f"データベースを初期化しました: {DB_PATH}")
