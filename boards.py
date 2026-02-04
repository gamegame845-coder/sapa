from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import sqlite3
from pathlib import Path
import os

router = APIRouter()

# ✅ admin key: 환경변수 우선, 없으면 기본값
ADMIN_KEY = os.getenv("SAPA_ADMIN_KEY", "jsad1375!")

# Render에서 쓰기 가능한 경로를 기본으로 사용
# 1순위: SAPA_DB_DIR 환경변수
# 2순위: 프로젝트 내부 ./data 폴더 (항상 쓰기 가능)
DB_DIR = Path(os.getenv("SAPA_DB_DIR", str((Path(__file__).resolve().parent / "data"))))
DB_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DB_DIR / "boards.db"

def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _is_admin(x_admin_key: Optional[str]) -> bool:
    return bool(x_admin_key) and x_admin_key == ADMIN_KEY


def _validate_board(board: str):
    if board not in ("notice", "feedback"):
        raise HTTPException(status_code=404, detail="board not found")


def init_db():
    conn = _connect()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS board_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            board TEXT NOT NULL CHECK(board IN ('notice','feedback')),
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            author TEXT NOT NULL,
            owner_id TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS board_replies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            board TEXT NOT NULL CHECK(board IN ('notice','feedback')),
            post_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            author TEXT NOT NULL,
            owner_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(post_id) REFERENCES board_posts(id) ON DELETE CASCADE
        );
        """
    )

    cur.execute("CREATE INDEX IF NOT EXISTS idx_posts_board_id ON board_posts(board, id DESC);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_replies_board_post ON board_replies(board, post_id, id ASC);")

    conn.commit()
    conn.close()


# ---------- Schemas ----------
class PostIn(BaseModel):
    title: str
    content: str
    author: str = "익명"


class ReplyIn(BaseModel):
    content: str
    author: str = "익명"


# ---------- Posts ----------
@router.get("/boards/{board}/posts")
def list_posts(board: str, limit: int = 50):
    _validate_board(board)
    limit = max(1, min(limit, 200))

    conn = _connect()
    rows = conn.execute(
        """
        SELECT id, board, title, content, author, created_at
        FROM board_posts
        WHERE board = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (board, limit),
    ).fetchall()
    conn.close()

    return {"items": [dict(r) for r in rows]}


@router.post("/boards/{board}/posts")
def create_post(
    board: str,
    body: PostIn,
    x_admin_key: Optional[str] = Header(default=None),
    x_user_id: Optional[str] = Header(default=None),
):
    _validate_board(board)

    # ✅ 공지사항 글 등록 = 관리자만
    if board == "notice" and not _is_admin(x_admin_key):
        raise HTTPException(status_code=403, detail="admin key required")

    # ✅ 유저 식별 (피드백 글의 '본인 삭제'를 위해 필요)
    owner_id = (x_user_id or "").strip()
    if not owner_id:
        # 로그인 구현 전까지는 헤더로 받자
        raise HTTPException(status_code=400, detail="x-user-id header required")

    title = (body.title or "").strip()
    content = (body.content or "").strip()
    author = (body.author or "익명").strip() or "익명"
    if not title or not content:
        raise HTTPException(status_code=400, detail="title/content required")

    conn = _connect()
    cur = conn.cursor()
    created_at = _now()

    cur.execute(
        """
        INSERT INTO board_posts(board, title, content, author, owner_id, created_at)
        VALUES(?,?,?,?,?,?)
        """,
        (board, title, content, author, owner_id, created_at),
    )
    post_id = cur.lastrowid
    conn.commit()

    row = conn.execute(
        """
        SELECT id, board, title, content, author, created_at
        FROM board_posts
        WHERE board = ? AND id = ?
        """,
        (board, post_id),
    ).fetchone()
    conn.close()

    return {"ok": True, "post": dict(row)}


@router.get("/boards/{board}/posts/{post_id}")
def get_post(board: str, post_id: int):
    _validate_board(board)

    conn = _connect()
    post = conn.execute(
        """
        SELECT id, board, title, content, author, created_at
        FROM board_posts
        WHERE board = ? AND id = ?
        """,
        (board, post_id),
    ).fetchone()

    if not post:
        conn.close()
        raise HTTPException(status_code=404, detail="post not found")

    replies = conn.execute(
        """
        SELECT id, post_id, content, author, created_at
        FROM board_replies
        WHERE board = ? AND post_id = ?
        ORDER BY id ASC
        """,
        (board, post_id),
    ).fetchall()

    conn.close()
    return {"post": dict(post), "replies": [dict(r) for r in replies]}


@router.delete("/boards/{board}/posts/{post_id}")
def delete_post(
    board: str,
    post_id: int,
    x_admin_key: Optional[str] = Header(default=None),
    x_user_id: Optional[str] = Header(default=None),
):
    _validate_board(board)
    is_admin = _is_admin(x_admin_key)

    owner_id = (x_user_id or "").strip()
    if not owner_id and not is_admin:
        raise HTTPException(status_code=400, detail="x-user-id header required")

    conn = _connect()

    # ✅ board + id 같이 확인 (404 안정화)
    post = conn.execute(
        """
        SELECT id, owner_id
        FROM board_posts
        WHERE board = ? AND id = ?
        """,
        (board, post_id),
    ).fetchone()

    if not post:
        conn.close()
        raise HTTPException(status_code=404, detail="post not found")

    # ✅ 공지사항 삭제 = 관리자만
    if board == "notice" and not is_admin:
        conn.close()
        raise HTTPException(status_code=403, detail="admin key required")

    # ✅ 피드백 삭제 = 관리자 또는 본인만
    if board == "feedback" and not is_admin:
        if post["owner_id"] != owner_id:
            conn.close()
            raise HTTPException(status_code=403, detail="not your post")

    conn.execute("DELETE FROM board_posts WHERE board = ? AND id = ?", (board, post_id))
    conn.commit()
    conn.close()
    return {"ok": True, "deleted_post_id": post_id}


# ---------- Replies ----------
@router.post("/boards/{board}/posts/{post_id}/replies")
def create_reply(
    board: str,
    post_id: int,
    body: ReplyIn,
    x_admin_key: Optional[str] = Header(default=None),
    x_user_id: Optional[str] = Header(default=None),
):
    _validate_board(board)

    # ✅ 공지 댓글 = 관리자만
    if board == "notice" and not _is_admin(x_admin_key):
        raise HTTPException(status_code=403, detail="admin key required")

    owner_id = (x_user_id or "").strip()
    if not owner_id:
        raise HTTPException(status_code=400, detail="x-user-id header required")

    content = (body.content or "").strip()
    author = (body.author or "익명").strip() or "익명"
    if not content:
        raise HTTPException(status_code=400, detail="content required")

    conn = _connect()

    post = conn.execute(
        "SELECT id FROM board_posts WHERE board = ? AND id = ?",
        (board, post_id),
    ).fetchone()

    if not post:
        conn.close()
        raise HTTPException(status_code=404, detail="post not found")

    created_at = _now()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO board_replies(board, post_id, content, author, owner_id, created_at)
        VALUES(?,?,?,?,?,?)
        """,
        (board, post_id, content, author, owner_id, created_at),
    )
    reply_id = cur.lastrowid
    conn.commit()

    reply = conn.execute(
        """
        SELECT id, post_id, content, author, created_at
        FROM board_replies
        WHERE board = ? AND post_id = ? AND id = ?
        """,
        (board, post_id, reply_id),
    ).fetchone()

    conn.close()
    return {"ok": True, "reply": dict(reply)}


@router.delete("/boards/{board}/posts/{post_id}/replies/{reply_id}")
def delete_reply(
    board: str,
    post_id: int,
    reply_id: int,
    x_admin_key: Optional[str] = Header(default=None),
    x_user_id: Optional[str] = Header(default=None),
):
    _validate_board(board)
    is_admin = _is_admin(x_admin_key)

    owner_id = (x_user_id or "").strip()
    if not owner_id and not is_admin:
        raise HTTPException(status_code=400, detail="x-user-id header required")

    conn = _connect()

    row = conn.execute(
        """
        SELECT id, owner_id
        FROM board_replies
        WHERE board = ? AND post_id = ? AND id = ?
        """,
        (board, post_id, reply_id),
    ).fetchone()

    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="reply not found")

    # ✅ 공지 댓글 삭제 = 관리자만
    if board == "notice" and not is_admin:
        conn.close()
        raise HTTPException(status_code=403, detail="admin key required")

    # ✅ 피드백 댓글 삭제 = 관리자 또는 본인만
    if board == "feedback" and not is_admin:
        if row["owner_id"] != owner_id:
            conn.close()
            raise HTTPException(status_code=403, detail="not your reply")

    conn.execute(
        "DELETE FROM board_replies WHERE board = ? AND post_id = ? AND id = ?",
        (board, post_id, reply_id),
    )
    conn.commit()
    conn.close()

    return {"ok": True, "deleted_reply_id": reply_id}
