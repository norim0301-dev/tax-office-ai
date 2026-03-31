"""
秘書AIエージェント（強化版）
検索・情報収集・国税庁HP検索・メール対応に特化
Gemini / Claude 自動切替対応
"""
import json
import smtplib
import imaplib
import email as email_lib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import decode_header
from typing import AsyncGenerator
from datetime import datetime
import os
import traceback

from agents.ai_client import chat_stream

# ---- メール設定（.envから読み込み） ----
GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

# ---- システムプロンプト ----
SECRETARY_SYSTEM_PROMPT = """あなたは税理士事務所の先生（所長）の右腕として働く、超優秀な秘書AIです。
名前は「秘書AI」です。先生のことは「先生」と呼んでください。

【最重要ルール】
- 「できません」「対応できません」とは絶対に言わない
- どんな依頼でも、まず「承知しました」と受け、できる範囲で最大限対応する
- 直接できないことも、代替案・手順・アドバイスを必ず提供する
- 先生の意図を汲み取り、聞かれていないことも先回りして提案する
- 雑談や相談にも親身に応じる。税務以外の話題もOK

【あなたができること（積極的に活用する）】
1. 📧 メール関連: 受信確認、下書き作成、送信、テンプレート活用
2. 🔍 情報収集: Web検索、国税庁HP検索、最新税制改正の調査
3. 📋 書類管理: 必要書類チェックリスト作成、書類案内文の作成
4. 📞 顧問先管理: 顧問先情報の検索・確認、連絡文の作成
5. 📅 スケジュール: 申告期限の確認、今後の予定整理
6. 📝 タスク管理: タスクの作成・確認・進捗管理
7. 💬 問い合わせ対応: 分類・整理・担当振り分け・回答案作成
8. 📄 文書作成: 案内状、お礼状、督促状、各種通知文の作成
9. 🧮 計算補助: 税額概算、期限計算、スケジュール作成
10. 💡 経営アドバイス: 業務効率化の提案、顧問先対応のアドバイス

【対応している税目・業務】
- 法人税、消費税（インボイス対応含む）、所得税（確定申告）
- 贈与税、相続税、土地評価（路線価）
- 会計入力（JDL会計ソフト連携）
- 社会保険取得届、算定基礎届、労働保険

【応答スタイル】
- 簡潔で実用的に。長い前置きは不要
- 先生に話しかけるように自然な敬語で
- 具体的なアウトプット（文面、リスト、表など）をすぐ出す
- 曖昧な指示でも意図を推測して動く
- 「○○もしておきましょうか？」と次のアクションを提案する
- 情報収集が必要なら、聞き返す前にまず検索してから回答する

【注意事項】
- 税務の最新情報は必ずweb_searchやsearch_nta_websiteで確認してから回答
- 不確実な情報は「念のためご確認ください」と添える
- 機密情報の取り扱いには注意を促す

先生の仕事が少しでも楽になるよう、全力でサポートしてください。"""

# ---- ツール定義 ----
SECRETARY_TOOLS = [
    # ===== 検索・情報収集系 =====
    {
        "name": "web_search",
        "description": "DuckDuckGoを使ってWeb検索を行います。税制改正、通達、法律の最新情報、一般的な税務質問の調査に使用します。",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "検索クエリ（例: '令和6年 税制改正 所得税', 'インボイス制度 経過措置 2026年'）"
                },
                "max_results": {
                    "type": "integer",
                    "description": "取得する検索結果の最大数（デフォルト: 5）",
                    "default": 5
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "search_nta_website",
        "description": "国税庁のホームページ（nta.go.jp）に特化した検索を行います。税務通達、申告書様式、税制改正、FAQ、タックスアンサーなどを検索します。",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "検索クエリ（例: '確定申告 医療費控除', '法人税 別表四', 'インボイス 登録番号 検索'）"
                },
                "max_results": {
                    "type": "integer",
                    "description": "取得する結果数（デフォルト: 5）",
                    "default": 5
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "fetch_webpage",
        "description": "指定URLのWebページの内容を取得します。国税庁のページや税務関連サイトの詳細情報を読み取る際に使用します。",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "取得するWebページのURL"
                }
            },
            "required": ["url"]
        }
    },
    # ===== 書類・分類系（既存強化版） =====
    {
        "name": "generate_document_checklist",
        "description": "税目・手続き種別に応じた必要書類チェックリストを生成します。顧客への書類案内や事前準備の確認に使用します。",
        "input_schema": {
            "type": "object",
            "properties": {
                "tax_type": {
                    "type": "string",
                    "description": "税目または手続き種別（例: 法人税, 消費税, 所得税確定申告, 相続税, 贈与税, 社会保険取得届, 算定基礎届）"
                },
                "client_type": {
                    "type": "string",
                    "enum": ["法人", "個人"],
                    "description": "顧客区分"
                },
                "notes": {
                    "type": "string",
                    "description": "特記事項（例: 不動産所得あり, インボイス登録済み, 相続人3名）"
                }
            },
            "required": ["tax_type", "client_type"]
        }
    },
    {
        "name": "classify_inquiry",
        "description": "顧客からの問い合わせ内容を分類・整理し、担当エージェント・優先度・対応方針を提示します。",
        "input_schema": {
            "type": "object",
            "properties": {
                "inquiry_text": {
                    "type": "string",
                    "description": "顧客からの問い合わせ文章"
                },
                "client_name": {
                    "type": "string",
                    "description": "顧客名（任意）"
                }
            },
            "required": ["inquiry_text"]
        }
    },
    # ===== メール系 =====
    {
        "name": "draft_email",
        "description": "顧客への連絡メールの下書きを作成します。件名・本文・宛先を含む完成度の高いメール文面を生成します。",
        "input_schema": {
            "type": "object",
            "properties": {
                "to_address": {
                    "type": "string",
                    "description": "宛先メールアドレス（任意。不明な場合は空欄）"
                },
                "recipient_name": {
                    "type": "string",
                    "description": "宛先名（顧客名・会社名）"
                },
                "subject": {
                    "type": "string",
                    "description": "メール件名"
                },
                "purpose": {
                    "type": "string",
                    "description": "メールの目的・内容（例: 確定申告の書類提出依頼, 算定基礎届の案内）"
                },
                "deadline": {
                    "type": "string",
                    "description": "期限日（任意）"
                },
                "tone": {
                    "type": "string",
                    "enum": ["丁寧", "標準", "簡潔"],
                    "description": "文体（デフォルト: 丁寧）"
                }
            },
            "required": ["recipient_name", "subject", "purpose"]
        }
    },
    {
        "name": "send_email",
        "description": "Gmailを使ってメールを送信します。事前にGMAIL_ADDRESSとGMAIL_APP_PASSWORDの設定が必要です。",
        "input_schema": {
            "type": "object",
            "properties": {
                "to_address": {
                    "type": "string",
                    "description": "送信先メールアドレス"
                },
                "subject": {
                    "type": "string",
                    "description": "メール件名"
                },
                "body": {
                    "type": "string",
                    "description": "メール本文"
                }
            },
            "required": ["to_address", "subject", "body"]
        }
    },
    {
        "name": "check_emails",
        "description": "Gmailの受信トレイから最新のメールを確認します。件名・差出人・日時・本文の概要を取得します。",
        "input_schema": {
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "description": "取得するメール数（デフォルト: 5）",
                    "default": 5
                },
                "search_query": {
                    "type": "string",
                    "description": "検索キーワード（任意。件名や差出人でフィルタ）"
                }
            },
            "required": []
        }
    },
    # ===== 顧問先・タスク管理系 =====
    {
        "name": "search_clients",
        "description": "顧問先データベースを検索します。会社名・個人名・メモなどで検索できます。",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "検索キーワード"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "get_upcoming_deadlines",
        "description": "今後の申告期限・提出期限を確認します。",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "何日先まで確認するか（デフォルト30日）", "default": 30}
            },
            "required": []
        }
    },
    # ===== タスク管理系 =====
    {
        "name": "create_task",
        "description": "新しいタスクを作成します。先生への作業リマインド、顧問先への対応予定、事務処理など何でも登録できます。",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "タスクのタイトル"},
                "description": {"type": "string", "description": "タスクの詳細説明"},
                "priority": {"type": "string", "enum": ["high", "medium", "low"], "description": "優先度"},
                "deadline": {"type": "string", "description": "期限（YYYY-MM-DD形式）"},
                "client_name": {"type": "string", "description": "関連する顧問先名（任意）"}
            },
            "required": ["title"]
        }
    },
    {
        "name": "list_tasks",
        "description": "現在のタスク一覧を確認します。未完了タスクや期限切れタスクの確認に使います。",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["all", "pending", "in_progress", "completed"], "description": "フィルタするステータス（デフォルト: pending）"}
            },
            "required": []
        }
    },
    {
        "name": "list_all_clients",
        "description": "全顧問先の一覧を取得します。顧問先の全体像把握や、特定条件の顧問先抽出に使います。",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "calculate_date",
        "description": "日付の計算を行います。期限の算出、営業日計算、月末日の確認などに使います。",
        "input_schema": {
            "type": "object",
            "properties": {
                "operation": {"type": "string", "description": "計算内容（例: '今日から30日後', '3月決算の法人税申告期限', '来月末'）"},
            },
            "required": ["operation"]
        }
    },
    {
        "name": "compose_document",
        "description": "各種ビジネス文書を作成します。案内状、お礼状、督促状、議事録、報告書など何でも作成できます。",
        "input_schema": {
            "type": "object",
            "properties": {
                "doc_type": {"type": "string", "description": "文書の種類（例: 案内状, お礼状, 督促状, 議事録, 報告書, 挨拶文, 通知文）"},
                "recipient": {"type": "string", "description": "宛先（顧問先名・個人名）"},
                "content": {"type": "string", "description": "文書に含める内容・要件"},
                "tone": {"type": "string", "enum": ["丁寧", "標準", "簡潔", "フォーマル"], "description": "文体"}
            },
            "required": ["doc_type", "content"]
        }
    },
    {
        "name": "get_today_summary",
        "description": "今日の業務サマリーを生成します。期限が近いタスク、今日の予定、対応が必要な事項をまとめます。",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    }
]


# ========================================
# ツール実行関数
# ========================================

def execute_web_search(query: str, max_results: int = 5) -> str:
    """DuckDuckGoでWeb検索を実行"""
    try:
        from duckduckgo_search import DDGS

        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, region="jp-jp", max_results=max_results):
                results.append(r)

        if not results:
            return f"「{query}」の検索結果は見つかりませんでした。"

        text = f"【Web検索結果】「{query}」\n\n"
        for i, r in enumerate(results, 1):
            text += f"[{i}] {r.get('title', '(タイトルなし)')}\n"
            text += f"    URL: {r.get('href', '')}\n"
            text += f"    概要: {r.get('body', '')[:200]}\n\n"

        return text

    except Exception as e:
        return f"[検索エラー] {str(e)}"


def execute_search_nta_website(query: str, max_results: int = 5) -> str:
    """国税庁HP（nta.go.jp）に特化した検索"""
    try:
        from duckduckgo_search import DDGS

        # site:nta.go.jp で国税庁に限定して検索
        nta_query = f"site:nta.go.jp {query}"

        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(nta_query, region="jp-jp", max_results=max_results):
                results.append(r)

        if not results:
            # 国税庁サイト内で見つからない場合、一般検索にフォールバック
            general_query = f"国税庁 {query}"
            with DDGS() as ddgs:
                for r in ddgs.text(general_query, region="jp-jp", max_results=max_results):
                    results.append(r)

        if not results:
            return f"国税庁HPで「{query}」に関する情報は見つかりませんでした。"

        text = f"【国税庁HP検索結果】「{query}」\n\n"
        for i, r in enumerate(results, 1):
            url = r.get('href', '')
            # 国税庁関連のURLかどうかを表示
            source = "🏛 国税庁" if "nta.go.jp" in url else "📄 関連サイト"
            text += f"[{i}] {source} {r.get('title', '(タイトルなし)')}\n"
            text += f"    URL: {url}\n"
            text += f"    概要: {r.get('body', '')[:250]}\n\n"

        # よく使う国税庁リンクを追加
        text += "\n【参考リンク】\n"
        text += "・タックスアンサー: https://www.nta.go.jp/taxes/shiraberu/taxanswer/index2.htm\n"
        text += "・確定申告特集: https://www.nta.go.jp/taxes/shiraberu/shinkoku/tokushu/index.htm\n"
        text += "・インボイス制度: https://www.nta.go.jp/taxes/shiraberu/zeimokubetsu/shohi/keigenzeiritsu/invoice.htm\n"

        return text

    except Exception as e:
        return f"[国税庁検索エラー] {str(e)}"


def execute_fetch_webpage(url: str) -> str:
    """Webページの内容を取得"""
    try:
        import requests
        from bs4 import BeautifulSoup

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        response = requests.get(url, headers=headers, timeout=15)
        response.encoding = response.apparent_encoding

        soup = BeautifulSoup(response.text, "html.parser")

        # 不要なタグを除去
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        # タイトル取得
        title = soup.title.string.strip() if soup.title and soup.title.string else "(タイトルなし)"

        # 本文テキストを取得
        text = soup.get_text(separator="\n", strip=True)

        # 長すぎる場合は切り詰め
        max_len = 3000
        if len(text) > max_len:
            text = text[:max_len] + "\n\n...(以下省略。全文はURLからご確認ください)"

        return f"【Webページ内容】\nタイトル: {title}\nURL: {url}\n\n{text}"

    except Exception as e:
        return f"[ページ取得エラー] {url}: {str(e)}"


def execute_generate_document_checklist(tax_type: str, client_type: str, notes: str = "") -> str:
    """税目別必要書類チェックリストを生成"""
    checklists = {
        "法人税": {
            "法人": [
                "決算書一式（貸借対照表・損益計算書・製造原価報告書）",
                "総勘定元帳（JDLデータまたはCSV）",
                "前年度法人税申告書（別表一〜）",
                "固定資産台帳",
                "法人税別表四・五（所得の金額の計算）",
                "役員報酬・役員借入金の明細",
                "交際費・寄附金の明細",
                "減価償却費の明細",
                "法人事業概況説明書の記載事項",
            ]
        },
        "消費税": {
            "法人": [
                "課税売上高・課税仕入高の集計",
                "インボイス（適格請求書）の保存状況確認",
                "免税・非課税取引の明細",
                "課税期間・納税義務者の確認",
                "前年度消費税申告書",
            ],
            "個人": [
                "事業収入・経費の集計（課税・非課税別）",
                "インボイス登録番号の確認",
                "帳簿の保存状況確認",
            ]
        },
        "所得税確定申告": {
            "個人": [
                "源泉徴収票（給与・退職）",
                "医療費の領収書・明細書",
                "社会保険料控除証明書",
                "生命保険料控除証明書",
                "地震保険料控除証明書",
                "寄附金控除の受領証（ふるさと納税含む）",
                "住宅借入金等特別控除（初年度は登記事項証明書）",
                "株式・投資信託の特定口座年間取引報告書",
                "不動産収入の場合: 賃料収入・経費明細・固定資産税通知書",
                "個人番号（マイナンバー）カード",
            ]
        },
        "相続税": {
            "個人": [
                "被相続人の戸籍謄本（出生〜死亡まで）",
                "相続人全員の戸籍謄本・住民票",
                "遺産分割協議書（作成済みの場合）",
                "不動産の登記事項証明書・固定資産評価証明書",
                "預貯金通帳・残高証明書（相続開始日時点）",
                "有価証券の残高証明書・取得費明細",
                "生命保険金の支払通知書",
                "借入金・負債の残高証明書",
                "葬儀費用の領収書",
                "過去3年内の贈与財産の確認",
            ]
        },
        "贈与税": {
            "個人": [
                "贈与契約書",
                "贈与財産の評価資料（不動産なら路線価図）",
                "贈与者・受贈者の個人番号",
                "相続時精算課税選択の場合: 届出書（初回）",
                "住宅取得資金の場合: 売買契約書・登記事項証明書",
            ]
        },
        "社会保険取得届": {
            "法人": [
                "被保険者資格取得届（様式）",
                "雇用契約書または辞令",
                "マイナンバー（個人番号）",
                "標準報酬月額の算定根拠（給与明細等）",
                "外国人の場合: パスポートまたは在留カード",
            ],
            "個人": [
                "被保険者資格取得届（様式）",
                "雇用契約書",
                "マイナンバー（個人番号）",
            ]
        },
        "算定基礎届": {
            "法人": [
                "4・5・6月の給与支払明細書（全従業員分）",
                "被保険者報酬月額算定基礎届（様式）",
                "昇給・降給があった場合: 月変届の検討用資料",
                "新入社員の資格取得届控え",
            ]
        },
    }

    matched_key = None
    for key in checklists:
        if key in tax_type or tax_type in key:
            matched_key = key
            break

    if matched_key and client_type in checklists[matched_key]:
        items = checklists[matched_key][client_type]
    elif matched_key and list(checklists[matched_key].values()):
        items = list(checklists[matched_key].values())[0]
    else:
        items = ["申告書類一式", "本人確認書類", "前年度申告書の控え", "収入・経費に関する書類"]

    checklist_text = f"【{tax_type}・{client_type}】必要書類チェックリスト\n\n"
    for i, item in enumerate(items, 1):
        checklist_text += f"□ {i}. {item}\n"

    if notes:
        checklist_text += f"\n【特記事項への追加対応】\n{notes} に関連する追加書類が必要な場合があります。担当者にご確認ください。"

    return checklist_text


def execute_classify_inquiry(inquiry_text: str, client_name: str = "") -> str:
    """問い合わせを分類・整理"""
    keywords = {
        "法人税AI": ["法人税", "決算", "別表", "法人", "会社", "確定申告（法人）"],
        "消費税AI": ["消費税", "インボイス", "適格請求書", "課税売上", "仕入税額控除"],
        "所得税AI": ["確定申告", "所得税", "医療費控除", "ふるさと納税", "住宅ローン控除", "不動産収入", "個人事業"],
        "相続税AI": ["相続", "相続税", "遺産", "被相続人", "相続人"],
        "贈与税AI": ["贈与", "贈与税", "生前贈与", "相続時精算課税"],
        "土地評価AI": ["土地", "路線価", "固定資産", "不動産評価", "評価額"],
        "会計入力AI": ["仕訳", "試算表", "帳簿", "JDL", "会計", "記帳"],
        "労務・社保AI": ["社会保険", "算定基礎", "健康保険", "厚生年金", "雇用保険", "労働保険", "入社", "退職"],
    }

    matched_agents = []
    for agent, kws in keywords.items():
        for kw in kws:
            if kw in inquiry_text:
                matched_agents.append(agent)
                break

    if not matched_agents:
        matched_agents = ["統括管理AI（要確認）"]

    urgent_keywords = ["至急", "急ぎ", "期限", "明日", "今日", "間に合う", "ペナルティ", "延滞"]
    is_urgent = any(kw in inquiry_text for kw in urgent_keywords)
    priority = "高（至急対応）" if is_urgent else "中（通常対応）"

    client_label = f"{client_name}様" if client_name else "顧客"

    result = f"【問い合わせ分類結果】\n"
    result += f"顧客: {client_label}\n"
    result += f"優先度: {priority}\n"
    result += f"担当エージェント: {', '.join(matched_agents)}\n\n"
    result += f"【問い合わせ内容の要約】\n{inquiry_text[:200]}{'...' if len(inquiry_text) > 200 else ''}\n\n"
    result += f"【対応方針】\n"
    if is_urgent:
        result += "至急対応が必要です。担当エージェントへ即時転送し、本日中に初期回答を実施してください。"
    else:
        result += "通常フローで対応します。担当エージェントに引き継ぎ、2営業日以内に回答を目指します。"

    return result


def execute_draft_email(
    recipient_name: str,
    subject: str,
    purpose: str,
    to_address: str = "",
    deadline: str = "",
    tone: str = "丁寧"
) -> str:
    """メール下書きを生成"""
    salutation = {
        "丁寧": "拝啓　時下ますますご清栄のこととお慶び申し上げます。\n平素より格別のご愛顧を賜り、厚くお礼申し上げます。",
        "標準": "いつもお世話になっております。",
        "簡潔": "お世話になっております。",
    }.get(tone, "お世話になっております。")

    deadline_text = f"\n\n■ ご提出期限：{deadline}" if deadline else ""
    to_text = f"\n宛先アドレス: {to_address}" if to_address else ""

    draft = f"""【メール下書き】
━━━━━━━━━━━━━━━━━━━━━
宛先: {recipient_name} 様{to_text}
件名: {subject}
━━━━━━━━━━━━━━━━━━━━━

{salutation}

{purpose}につきまして、ご案内申し上げます。{deadline_text}

つきましては、お手数ではございますが、下記をご確認・ご対応いただけますと幸いです。

【ご確認事項】
・（担当者が具体的な確認事項を追記してください）

ご不明な点やご質問がございましたら、お気軽にお申し付けください。
引き続きどうぞよろしくお願い申し上げます。

敬具

━━━━━━━━━━━━━━━━━━━━━
税理士事務所
担当: （署名欄に担当者名を入力）
TEL:
E-mail:
━━━━━━━━━━━━━━━━━━━━━

※ この文書は秘書AIが作成した下書きです。送信前に内容をご確認の上、必要に応じて修正してください。"""

    return draft


def execute_send_email(to_address: str, subject: str, body: str) -> str:
    """Gmailでメール送信"""
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        return """[メール送信エラー] Gmail設定が完了していません。

backend/.env に以下を追加してください：
GMAIL_ADDRESS=あなたのGmailアドレス@gmail.com
GMAIL_APP_PASSWORD=アプリパスワード（16文字）

【アプリパスワードの取得方法】
1. https://myaccount.google.com/security にアクセス
2. 「2段階認証プロセス」を有効化
3. 「アプリパスワード」を選択
4. 「メール」「Windowsパソコン」を選んで生成
5. 16文字のパスワードを GMAIL_APP_PASSWORD に設定"""

    try:
        msg = MIMEMultipart()
        msg["From"] = GMAIL_ADDRESS
        msg["To"] = to_address
        msg["Subject"] = subject

        msg.attach(MIMEText(body, "plain", "utf-8"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.send_message(msg)

        now = datetime.now().strftime("%Y/%m/%d %H:%M")
        return f"""【メール送信完了】
送信日時: {now}
宛先: {to_address}
件名: {subject}
ステータス: ✅ 送信成功"""

    except smtplib.SMTPAuthenticationError:
        return "[メール送信エラー] 認証に失敗しました。GMAIL_ADDRESSとGMAIL_APP_PASSWORDを確認してください。"
    except Exception as e:
        return f"[メール送信エラー] {str(e)}"


def execute_check_emails(count: int = 5, search_query: str = "") -> str:
    """Gmail受信トレイからメールを確認"""
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        return """[メール確認エラー] Gmail設定が完了していません。

backend/.env に以下を追加してください：
GMAIL_ADDRESS=あなたのGmailアドレス@gmail.com
GMAIL_APP_PASSWORD=アプリパスワード（16文字）"""

    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        mail.select("inbox")

        # 検索
        if search_query:
            status, messages = mail.search(None, f'(OR SUBJECT "{search_query}" FROM "{search_query}")')
        else:
            status, messages = mail.search(None, "ALL")

        if status != "OK" or not messages[0]:
            mail.logout()
            return "受信トレイにメールが見つかりませんでした。"

        mail_ids = messages[0].split()
        # 最新のcount件を取得
        latest_ids = mail_ids[-count:] if len(mail_ids) >= count else mail_ids
        latest_ids.reverse()  # 新しい順

        result = f"【受信メール一覧】（最新{len(latest_ids)}件）\n\n"

        for mid in latest_ids:
            status, msg_data = mail.fetch(mid, "(RFC822)")
            if status != "OK":
                continue

            msg = email_lib.message_from_bytes(msg_data[0][1])

            # 件名デコード
            subject_raw = msg["Subject"]
            if subject_raw:
                decoded_parts = decode_header(subject_raw)
                subject = ""
                for part, charset in decoded_parts:
                    if isinstance(part, bytes):
                        subject += part.decode(charset or "utf-8", errors="replace")
                    else:
                        subject += part
            else:
                subject = "(件名なし)"

            # 差出人デコード
            from_raw = msg["From"]
            if from_raw:
                decoded_from = decode_header(from_raw)
                from_addr = ""
                for part, charset in decoded_from:
                    if isinstance(part, bytes):
                        from_addr += part.decode(charset or "utf-8", errors="replace")
                    else:
                        from_addr += part
            else:
                from_addr = "(不明)"

            # 日時
            date_str = msg["Date"] or "(日時不明)"

            # 本文の先頭部分
            body_preview = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        payload = part.get_payload(decode=True)
                        if payload:
                            charset = part.get_content_charset() or "utf-8"
                            body_preview = payload.decode(charset, errors="replace")[:150]
                        break
            else:
                payload = msg.get_payload(decode=True)
                if payload:
                    charset = msg.get_content_charset() or "utf-8"
                    body_preview = payload.decode(charset, errors="replace")[:150]

            result += f"📧 件名: {subject}\n"
            result += f"   差出人: {from_addr}\n"
            result += f"   日時: {date_str}\n"
            if body_preview:
                result += f"   概要: {body_preview.strip()[:100]}...\n"
            result += "\n"

        mail.logout()
        return result

    except imaplib.IMAP4.error as e:
        return f"[メール確認エラー] IMAP認証失敗: {str(e)}"
    except Exception as e:
        return f"[メール確認エラー] {str(e)}"


def execute_create_task(title: str, description: str = "", priority: str = "medium", deadline: str = "", client_name: str = "") -> str:
    """タスクを作成"""
    try:
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from database import _get_connection, _now

        conn = _get_connection()
        # 顧問先名からIDを検索
        client_id = None
        if client_name:
            row = conn.execute("SELECT id FROM clients WHERE name LIKE ?", (f"%{client_name}%",)).fetchone()
            if row:
                client_id = row["id"]

        conn.execute(
            "INSERT INTO tasks (title, description, priority, status, deadline, client_id, agent_id, created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (title, description, priority, "pending", deadline or None, client_id, "hisho", "secretary_ai", _now(), _now()),
        )
        conn.commit()
        conn.close()

        result = f"✅ タスクを作成しました\n"
        result += f"  タイトル: {title}\n"
        result += f"  優先度: {priority}\n"
        if deadline:
            result += f"  期限: {deadline}\n"
        if client_name:
            result += f"  顧問先: {client_name}" + (f"（ID: {client_id}）" if client_id else "（未登録）") + "\n"
        return result
    except Exception as e:
        return f"[タスク作成エラー] {str(e)}"


def execute_list_tasks(status: str = "pending") -> str:
    """タスク一覧を取得"""
    try:
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from database import _get_connection

        conn = _get_connection()
        if status == "all":
            rows = conn.execute("""
                SELECT t.*, c.name as client_name FROM tasks t
                LEFT JOIN clients c ON t.client_id = c.id
                ORDER BY CASE t.priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, t.deadline
                LIMIT 30
            """).fetchall()
        else:
            rows = conn.execute("""
                SELECT t.*, c.name as client_name FROM tasks t
                LEFT JOIN clients c ON t.client_id = c.id
                WHERE t.status = ?
                ORDER BY CASE t.priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, t.deadline
                LIMIT 30
            """, (status,)).fetchall()
        conn.close()

        if not rows:
            return f"ステータス「{status}」のタスクはありません。"

        priority_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}
        status_label = {"pending": "未着手", "in_progress": "処理中", "completed": "完了"}

        result = f"【タスク一覧】（{status}）{len(rows)}件\n\n"
        for t in rows:
            td = dict(t)
            icon = priority_icon.get(td.get("priority", ""), "⚪")
            st = status_label.get(td.get("status", ""), td.get("status", ""))
            result += f"{icon} {td['title']}  [{st}]"
            if td.get("deadline"):
                result += f"  期限: {td['deadline']}"
            if td.get("client_name"):
                result += f"  ({td['client_name']})"
            result += "\n"
            if td.get("description"):
                result += f"   → {td['description'][:60]}\n"

        return result
    except Exception as e:
        return f"[タスク取得エラー] {str(e)}"


def execute_list_all_clients() -> str:
    """全顧問先一覧"""
    try:
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from database import _get_connection

        conn = _get_connection()
        rows = conn.execute("SELECT * FROM clients ORDER BY name").fetchall()
        conn.close()

        if not rows:
            return "顧問先は登録されていません。"

        result = f"【顧問先一覧】全{len(rows)}件\n\n"
        for c in rows:
            cd = dict(c)
            fiscal = f" / {cd['fiscal_year_end']}月決算" if cd.get('fiscal_year_end') else ""
            result += f"■ {cd['name']}（{cd.get('client_type', '')}）{fiscal}\n"
            contacts = []
            if cd.get('phone'):
                contacts.append(f"📞{cd['phone']}")
            if cd.get('email'):
                contacts.append(f"✉️{cd['email']}")
            if cd.get('line_user_id'):
                contacts.append("📱LINE")
            if contacts:
                result += f"  {' / '.join(contacts)}\n"
            if cd.get('contact_person'):
                result += f"  担当: {cd['contact_person']}\n"
            if cd.get('memo'):
                result += f"  メモ: {cd['memo']}\n"
            result += "\n"

        return result
    except Exception as e:
        return f"[顧問先取得エラー] {str(e)}"


def execute_calculate_date(operation: str) -> str:
    """日付計算"""
    from datetime import datetime, timedelta
    import calendar

    today = datetime.now()
    result = f"📅 今日: {today.strftime('%Y年%m月%d日（%A）')}\n\n"

    # よくある計算パターン
    result += "【計算結果】\n"

    # 日数後
    for days in [7, 14, 30, 60, 90]:
        future = today + timedelta(days=days)
        result += f"  {days}日後: {future.strftime('%Y年%m月%d日（%A）')}\n"

    result += "\n【今月・来月】\n"
    # 今月末
    last_day = calendar.monthrange(today.year, today.month)[1]
    month_end = today.replace(day=last_day)
    result += f"  今月末: {month_end.strftime('%Y年%m月%d日（%A）')}\n"

    # 来月末
    if today.month == 12:
        next_month_end = datetime(today.year + 1, 1, calendar.monthrange(today.year + 1, 1)[1])
    else:
        next_month_end = datetime(today.year, today.month + 1, calendar.monthrange(today.year, today.month + 1)[1])
    result += f"  来月末: {next_month_end.strftime('%Y年%m月%d日（%A）')}\n"

    result += "\n【主な申告期限の目安】\n"
    # 各決算月の法人税申告期限（決算月末から2ヶ月後）
    for month in range(1, 13):
        deadline_month = month + 2 if month + 2 <= 12 else month + 2 - 12
        deadline_year = today.year if month + 2 <= 12 else today.year + 1
        deadline_day = calendar.monthrange(deadline_year, deadline_month)[1]
        deadline_date = datetime(deadline_year, deadline_month, deadline_day)
        if deadline_date >= today and deadline_date <= today + timedelta(days=120):
            result += f"  {month}月決算法人 → 申告期限: {deadline_date.strftime('%Y年%m月%d日')}\n"

    result += f"\n依頼内容: {operation}\n"
    result += "上記の情報を参考にお答えします。"

    return result


def execute_compose_document(doc_type: str, content: str, recipient: str = "", tone: str = "丁寧") -> str:
    """各種文書を作成"""
    today_str = datetime.now().strftime("%Y年%m月%d日")
    recipient_text = f"{recipient} 様" if recipient else "○○ 様"

    templates = {
        "案内状": f"""━━━━━━━━━━━━━━━━━━━━━
{today_str}

{recipient_text}

{content}に関するご案内

拝啓　時下ますますご清祥のこととお慶び申し上げます。
平素より格別のご厚情を賜り、厚くお礼申し上げます。

さて、{content}につきまして、下記のとおりご案内申し上げます。

【ご案内事項】
（ここに詳細を記載）

ご不明な点がございましたら、お気軽にお問い合わせください。

敬具

税理士事務所
━━━━━━━━━━━━━━━━━━━━━""",
        "督促状": f"""━━━━━━━━━━━━━━━━━━━━━
{today_str}

{recipient_text}

書類ご提出のお願い（再通知）

いつもお世話になっております。

先日ご依頼いたしました{content}につきまして、
まだご提出を確認できておりません。

期限が迫っておりますので、お早めにご対応いただけますと幸いです。

【ご提出書類】
（ここに詳細を記載）

【提出期限】
（ここに期限を記載）

ご多忙のところ恐れ入りますが、何卒よろしくお願いいたします。

税理士事務所
━━━━━━━━━━━━━━━━━━━━━""",
        "お礼状": f"""━━━━━━━━━━━━━━━━━━━━━
{today_str}

{recipient_text}

拝啓　時下ますますご清祥のこととお慶び申し上げます。

このたびは{content}につきまして、ご対応いただき誠にありがとうございました。

今後とも変わらぬお引き立てのほど、よろしくお願い申し上げます。

敬具

税理士事務所
━━━━━━━━━━━━━━━━━━━━━""",
    }

    if doc_type in templates:
        return f"【{doc_type}】\n\n" + templates[doc_type]
    else:
        # 汎用テンプレート
        return f"""【{doc_type}】

━━━━━━━━━━━━━━━━━━━━━
{today_str}

{recipient_text}

{doc_type}

{content}

━━━━━━━━━━━━━━━━━━━━━
税理士事務所

※ この文書は秘書AIが作成した下書きです。必要に応じて修正してください。"""


def execute_get_today_summary() -> str:
    """今日の業務サマリー"""
    try:
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from database import _get_connection

        today = datetime.now()
        today_str = today.strftime("%Y-%m-%d")
        week_later = (today + __import__('datetime').timedelta(days=7)).strftime("%Y-%m-%d")

        conn = _get_connection()

        # 期限切れタスク
        overdue = conn.execute(
            "SELECT t.*, c.name as client_name FROM tasks t LEFT JOIN clients c ON t.client_id = c.id WHERE t.status != 'completed' AND t.deadline < ? AND t.deadline IS NOT NULL",
            (today_str,)
        ).fetchall()

        # 今週の期限タスク
        this_week = conn.execute(
            "SELECT t.*, c.name as client_name FROM tasks t LEFT JOIN clients c ON t.client_id = c.id WHERE t.status != 'completed' AND t.deadline >= ? AND t.deadline <= ?",
            (today_str, week_later)
        ).fetchall()

        # 未完了タスク数
        pending_count = conn.execute("SELECT COUNT(*) as cnt FROM tasks WHERE status = 'pending'").fetchone()["cnt"]
        in_progress_count = conn.execute("SELECT COUNT(*) as cnt FROM tasks WHERE status = 'in_progress'").fetchone()["cnt"]

        # 今週の申告期限
        deadlines = conn.execute("""
            SELECT d.*, c.name as client_name FROM deadlines d
            LEFT JOIN clients c ON d.client_id = c.id
            WHERE d.is_completed = 0 AND d.deadline_date >= ? AND d.deadline_date <= ?
            ORDER BY d.deadline_date
        """, (today_str, week_later)).fetchall()

        # 顧問先数
        client_count = conn.execute("SELECT COUNT(*) as cnt FROM clients").fetchone()["cnt"]

        conn.close()

        result = f"📋 **本日の業務サマリー** ({today.strftime('%Y年%m月%d日 %A')})\n"
        result += "━" * 30 + "\n\n"

        if overdue:
            result += f"🚨 **期限超過タスク: {len(overdue)}件**\n"
            for t in overdue:
                td = dict(t)
                result += f"  ⚠️ {td['title']} (期限: {td.get('deadline', '?')})"
                if td.get('client_name'):
                    result += f" - {td['client_name']}"
                result += "\n"
            result += "\n"

        if this_week:
            result += f"📅 **今週期限のタスク: {len(this_week)}件**\n"
            for t in this_week:
                td = dict(t)
                result += f"  • {td['title']} (期限: {td.get('deadline', '?')})"
                if td.get('client_name'):
                    result += f" - {td['client_name']}"
                result += "\n"
            result += "\n"

        if deadlines:
            result += f"🏛 **今週の申告期限: {len(deadlines)}件**\n"
            for d in deadlines:
                dd = dict(d)
                result += f"  • {dd.get('deadline_date', '')} {dd.get('deadline_type', '')}"
                if dd.get('client_name'):
                    result += f" ({dd['client_name']})"
                result += "\n"
            result += "\n"

        result += f"📊 **タスク状況**: 未着手 {pending_count}件 / 処理中 {in_progress_count}件\n"
        result += f"👥 **顧問先**: {client_count}件\n"

        if not overdue and not this_week and not deadlines:
            result += "\n✨ 今週は特に急ぎの案件はありません。\n"

        result += "\n何かお手伝いすることはありますか？"
        return result

    except Exception as e:
        return f"[サマリー生成エラー] {str(e)}"


# ---- ツール実行ディスパッチャ ----
def dispatch_tool(tool_name: str, tool_input: dict) -> str:
    try:
        if tool_name == "web_search":
            return execute_web_search(
                query=tool_input["query"],
                max_results=int(tool_input.get("max_results", 5))
            )
        elif tool_name == "search_nta_website":
            return execute_search_nta_website(
                query=tool_input["query"],
                max_results=int(tool_input.get("max_results", 5))
            )
        elif tool_name == "fetch_webpage":
            return execute_fetch_webpage(url=tool_input["url"])
        elif tool_name == "generate_document_checklist":
            return execute_generate_document_checklist(
                tax_type=tool_input["tax_type"],
                client_type=tool_input["client_type"],
                notes=tool_input.get("notes", "")
            )
        elif tool_name == "classify_inquiry":
            return execute_classify_inquiry(
                inquiry_text=tool_input["inquiry_text"],
                client_name=tool_input.get("client_name", "")
            )
        elif tool_name == "draft_email":
            return execute_draft_email(
                recipient_name=tool_input["recipient_name"],
                subject=tool_input["subject"],
                purpose=tool_input["purpose"],
                to_address=tool_input.get("to_address", ""),
                deadline=tool_input.get("deadline", ""),
                tone=tool_input.get("tone", "丁寧")
            )
        elif tool_name == "send_email":
            return execute_send_email(
                to_address=tool_input["to_address"],
                subject=tool_input["subject"],
                body=tool_input["body"]
            )
        elif tool_name == "check_emails":
            return execute_check_emails(
                count=int(tool_input.get("count", 5)),
                search_query=tool_input.get("search_query", "")
            )
        elif tool_name == "search_clients":
            return execute_search_clients_tool(query=tool_input["query"])
        elif tool_name == "get_upcoming_deadlines":
            return execute_get_upcoming_deadlines(days=int(tool_input.get("days", 30)))
        elif tool_name == "create_task":
            return execute_create_task(
                title=tool_input["title"],
                description=tool_input.get("description", ""),
                priority=tool_input.get("priority", "medium"),
                deadline=tool_input.get("deadline", ""),
                client_name=tool_input.get("client_name", "")
            )
        elif tool_name == "list_tasks":
            return execute_list_tasks(status=tool_input.get("status", "pending"))
        elif tool_name == "list_all_clients":
            return execute_list_all_clients()
        elif tool_name == "calculate_date":
            return execute_calculate_date(operation=tool_input["operation"])
        elif tool_name == "compose_document":
            return execute_compose_document(
                doc_type=tool_input["doc_type"],
                content=tool_input["content"],
                recipient=tool_input.get("recipient", ""),
                tone=tool_input.get("tone", "丁寧")
            )
        elif tool_name == "get_today_summary":
            return execute_get_today_summary()
        else:
            return f"[エラー] 不明なツール: {tool_name}"
    except Exception as e:
        return f"[ツール実行エラー] {tool_name}: {str(e)}\n{traceback.format_exc()}"


def execute_search_clients_tool(query: str) -> str:
    """顧問先データベース検索"""
    try:
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from database import search_clients
        clients = search_clients(query)
        if not clients:
            return "該当する顧問先が見つかりませんでした。"
        text = "【顧問先検索結果】\n"
        for c in clients:
            fiscal = c.get('fiscal_year_end', '')
            fiscal_text = f" / {fiscal}月決算" if fiscal else ""
            text += f"\n■ {c['name']}（{c.get('client_type', '')}）{fiscal_text}"
            if c.get('phone'):
                text += f"\n  TEL: {c['phone']}"
            if c.get('email'):
                text += f"\n  Email: {c['email']}"
            if c.get('contact_person'):
                text += f"\n  担当: {c['contact_person']}"
            if c.get('memo'):
                text += f"\n  メモ: {c['memo']}"
        return text
    except Exception as e:
        return f"[DB検索エラー] {str(e)}"


def execute_get_upcoming_deadlines(days: int = 30) -> str:
    """今後の期限を取得"""
    try:
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from database import get_upcoming_deadlines
        deadlines = get_upcoming_deadlines(days)
        if not deadlines:
            return f"今後{days}日間に期限はありません。"
        text = f"【今後{days}日間の期限】\n"
        for d in deadlines:
            text += f"\n・{d.get('deadline_date', '')} : {d.get('deadline_type', '')}"
            if d.get('client_name'):
                text += f"（{d['client_name']}）"
        return text
    except Exception as e:
        return f"[期限取得エラー] {str(e)}"


# ---- SSEストリーミングジェネレータ ----
async def secretary_chat_stream(
    message: str,
    history: list[dict]
) -> AsyncGenerator[str, None]:
    """SSEストリーミングチャット（Gemini/Claude自動切替）"""
    async for chunk in chat_stream(
        message=message,
        history=history,
        system_prompt=SECRETARY_SYSTEM_PROMPT,
        tools_schema=SECRETARY_TOOLS,
        dispatch_tool=dispatch_tool,
    ):
        yield chunk
