"""
학생/원장 문의(Q&A) API — inquiries 테이블 기반
"""
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy import text
from datetime import datetime
import os
import uuid
import aiofiles

from app.core.database import get_db
from app.core.security import get_current_user
from app.schemas import ApiResponse

# 업로드 저장 경로 — main.py가 서빙하는 /app/uploads 와 일치해야 함 (404 방지)
# abspath(__file__) = /app/app/api/v1/inquiries.py
#   main.py: /app/app/main.py → UPLOADS_DIR = parent.parent/uploads = /app/uploads
#   따라서 4단계 상위(dname 4) → /app/uploads/inquiries 로 맞춰야 StaticFiles 서빙과 일치.
#   (기존 3단계 상위는 /app/app/uploads 로 저장돼 URL 접근 시 404 발생)
UPLOAD_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "uploads", "inquiries",
)
os.makedirs(UPLOAD_DIR, exist_ok=True)

router = APIRouter(prefix="/inquiries", tags=["Inquiries"])


@router.post("/create")
async def create_inquiry(
    title: str = Query(...),
    content: str = Query(...),
    image_path: str = Query(None),
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """학생 또는 원장이 문의 등록"""
    uid = user["id"]
    role = user.get("role", "")
    name = user.get("name", "")
    branch_id = user.get("branch_id")

    # student or director only
    if role not in ("student", "director"):
        raise HTTPException(403, "학생/원장만 문의를 등록할 수 있습니다.")

    async with db as conn:
        # Get branch name if exists
        branch_name = None
        if branch_id:
            row = await conn.execute(text("SELECT name FROM branches WHERE id=:bid"), {"bid": branch_id})
            br = row.fetchone()
            if br:
                branch_name = br[0]

        if role == "student":
            await conn.execute(
                text("""INSERT INTO inquiries 
                   (student_id, student_name, branch_id, branch_name, title, content, status, image_path)
                   VALUES (:uid, :name, :bid, :bname, :title, :content, 'pending', :img)"""),
                {"uid": uid, "name": name, "bid": branch_id, "bname": branch_name,
                 "title": title, "content": content, "img": image_path},
            )
        else:  # director
            await conn.execute(
                text("""INSERT INTO inquiries 
                   (director_id, director_name, branch_id, branch_name, title, content, status, image_path)
                   VALUES (:uid, :name, :bid, :bname, :title, :content, 'pending', :img)"""),
                {"uid": uid, "name": name, "bid": branch_id, "bname": branch_name,
                 "title": title, "content": content, "img": image_path},
            )
        await conn.commit()

    return ApiResponse(status="success", message="문의가 등록되었습니다.")


@router.post("/upload-image")
async def upload_inquiry_image(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    """Q&A 작성 시 이미지 업로드 (학생/원장만)"""
    role = user.get("role", "")
    if role not in ("student", "director"):
        raise HTTPException(403, "권한이 없습니다.")

    # Validate file type
    allowed = {"image/jpeg", "image/png", "image/gif", "image/webp"}
    if file.content_type not in allowed:
        raise HTTPException(400, "JPG, PNG, GIF, WEBP만 업로드 가능합니다.")

    # Generate unique filename
    ext = file.filename.rsplit(".", 1)[-1] if "." in file.filename else "jpg"
    filename = f"{uuid.uuid4().hex}.{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)

    # Save file
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:  # 10MB limit
        raise HTTPException(400, "파일 크기는 10MB 이하여야 합니다.")

    async with aiofiles.open(filepath, "wb") as f:
        await f.write(content)

    url = f"/uploads/inquiries/{filename}"
    return ApiResponse(status="success", data={"url": url})


@router.get("/my")
async def get_my_inquiries(
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """내 문의 목록 조회 (학생/원장)"""
    uid = user["id"]
    role = user.get("role", "")

    async with db as conn:
        if role == "student":
            rows = await conn.execute(text("SELECT * FROM inquiries WHERE student_id=:uid ORDER BY created_at DESC"), {"uid": uid})
        elif role == "director":
            rows = await conn.execute(text("SELECT * FROM inquiries WHERE director_id=:uid ORDER BY created_at DESC"), {"uid": uid})
        else:
            raise HTTPException(403, "권한이 없습니다.")

        items = []
        for r in rows.fetchall():
            item = {
                "id": r[0],
                "title": r[5] if len(r) > 5 else r[4],
                "content": r[6] if len(r) > 6 else r[5],
                "status": r[7] if len(r) > 7 else r[6],
                "answer": r[8] if len(r) > 8 else r[7],
                "answered_by_name": r[10] if len(r) > 10 else r[9],
                "answered_at": str(r[11]) if len(r) > 11 and r[11] else None,
                "created_at": str(r[12]) if len(r) > 12 and r[12] else None,
                # DB 컬럼 순서: ...12:created_at 13:student_id 14:student_name 15:image_path
                # (기존 r[13]은 student_id를 image_path로 잘못 매핑 → <img src="8"> → /pages/student/8 404)
                "student_id": r[13] if len(r) > 13 and r[13] else None,
                "image_path": r[15] if len(r) > 15 and r[15] else None,
            }
            # student_name + director_name
            if len(r) > 14:
               item["student_name"] = r[14] if len(r) > 14 else None
            items.append(item)

    return ApiResponse(status="success", data=items)


@router.get("/all")
async def get_all_inquiries(
    status: str = Query(None),
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """본사에서 모든 문의 조회 (admin/super_admin만)"""
    role = user.get("role", "")
    if role not in ("super_admin", "admin", "branch_admin"):
        raise HTTPException(403, "본사/관리자만 조회 가능합니다.")

    async with db as conn:
        if status:
            rows = await conn.execute(text("SELECT * FROM inquiries WHERE status=:st ORDER BY created_at DESC"), {"st": status})
        else:
            rows = await conn.execute(text("SELECT * FROM inquiries ORDER BY status ASC, created_at DESC"))

        items = []
        for r in rows.fetchall():
            items.append({
                "id": r[0],
                "director_id": r[1],
                "director_name": r[2],
                "branch_id": r[3],
                "branch_name": r[4],
                "title": r[5],
                "content": r[6],
                "status": r[7],
                "answer": r[8],
                "answered_by": r[9],
                "answered_by_name": r[10],
                "answered_at": str(r[11]) if len(r) > 11 and r[11] else None,
                "created_at": str(r[12]) if len(r) > 12 and r[12] else None,
                "student_id": r[13] if len(r) > 13 else None,
                "student_name": r[14] if len(r) > 14 else None,
                "image_path": r[15] if len(r) > 15 else None,
            })

    return ApiResponse(status="success", data=items)


@router.post("/answer/{inquiry_id}")
async def answer_inquiry(
    inquiry_id: int,
    answer: str = Query(...),
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """본사에서 문의 답변 (admin/super_admin만)"""
    role = user.get("role", "")
    if role not in ("super_admin", "admin", "branch_admin"):
        raise HTTPException(403, "본사/관리자만 답변 가능합니다.")

    admin_name = user.get("name", "본사")

    async with db as conn:
        row = await conn.execute(text("SELECT id FROM inquiries WHERE id=:iid"), {"iid": inquiry_id})
        if not row.fetchone():
            raise HTTPException(404, "문의를 찾을 수 없습니다.")

        stmt = text(
            """UPDATE inquiries 
               SET status='answered', answer=:answer, answered_by=:uid, answered_by_name=:aname, answered_at=:at
               WHERE id=:iid"""
        )
        await conn.execute(stmt, {
            "answer": answer,
            "uid": user["id"],
            "aname": admin_name,
            "at": datetime.now(),
            "iid": inquiry_id,
        })
        await conn.commit()

    return ApiResponse(status="success", message="답변이 등록되었습니다.")


@router.delete("/{inquiry_id}")
async def delete_inquiry(
    inquiry_id: int,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """문의 삭제 (자신의 글 또는 본사만)"""
    role = user.get("role", "")
    uid = user["id"]

    async with db as conn:
        row = await conn.execute(text("SELECT * FROM inquiries WHERE id=:iid"), {"iid": inquiry_id})
        item = row.fetchone()
        if not item:
            raise HTTPException(404, "문의를 찾을 수 없습니다.")

        # 본사이거나 작성자만 삭제 가능
        is_owner = (item[1] == uid or (len(item) > 13 and item[13] == uid))
        if role not in ("super_admin", "admin") and not is_owner:
            raise HTTPException(403, "삭제 권한이 없습니다.")

        await conn.execute(text("DELETE FROM inquiries WHERE id=:iid"), {"iid": inquiry_id})
        await conn.commit()

    return ApiResponse(status="success", message="삭제되었습니다.")
