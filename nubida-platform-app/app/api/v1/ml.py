"""
누비다머신 — 이미지 머신러닝 학습 시스템 API

- 학생: 프로젝트 생성/조회, 샘플 업로드, 모델 저장/조회, 아두이노 자동 송신(본사 프리셋)
- 이미지를 먼저, 추후 음성/포즈/텍스트로 확장 가능 (model_type 필드)
- 브라우저(TensorFlow.js) 학습 — 서버는 모델·샘플·메타만 저장
"""
import os
import uuid
import json
import shutil

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query, Body
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_role
from app.schemas import ApiResponse
from app.models import MlProject, MlSample, MlArduinoMapping, AppSetting, User

router = APIRouter(prefix="/ml", tags=["Nubida Machine (ML)"])


async def _ensure_ml_unlocked(
    current_user: dict = Depends(require_role("student")),
    db: AsyncSession = Depends(get_db),
):
    """누비다머신 사용 가능 여부 검사 — 소속 원장이 잠금 설정 시 403 차단"""
    me = (await db.execute(
        select(User).where(User.id == current_user["id"])
    )).scalar_one_or_none()
    if me and me.director_id:
        director = (await db.execute(
            select(User).where(User.id == me.director_id)
        )).scalar_one_or_none()
        if director and director.nubida_machine_locked:
            raise HTTPException(
                status_code=403,
                detail="누비다머신 사용이 일시 정지되었습니다. 원장님께 문의해 주세요.",
            )
    return current_user

# 업로드 저장 경로
ML_UPLOAD_BASE = os.environ.get(
    "ML_UPLOAD_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "uploads", "ml"),
)


def _project_dir(project_id: int) -> str:
    d = os.path.join(ML_UPLOAD_BASE, f"project_{project_id}", "samples")
    os.makedirs(d, exist_ok=True)
    return d


# ============================================================
# 프로젝트
# ============================================================

class MlProjectCreate(BaseModel):
    """프로젝트 생성 요청 — 프론트 api()가 JSON으로 전송하므로 Form이 아닌 Body로 수신"""
    title: str = "새 프로젝트"
    description: str = ""
    model_type: str = "image"


class MlProjectUpdate(BaseModel):
    """프로젝트 수정 요청 — create와 동일하게 프론트 apiPatch(JSON)에 맞춰 Body로 수신.
    (기존 Form 수신은 JSON 바디가 status=None으로 파싱돼 무변경 200 버그 유발)"""
    title: str | None = None
    status: str | None = None


@router.post("/projects")
async def create_project(
    body: MlProjectCreate = Body(...),
    current_user: dict = Depends(_ensure_ml_unlocked),
    db: AsyncSession = Depends(get_db),
):
    """이미지/음성 ML 학습 프로젝트 생성"""
    p = MlProject(
        student_id=current_user["id"],
        title=body.title or "새 프로젝트",
        description=body.description,
        status="collecting",
        model_type=body.model_type,
        sample_count=0,
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)
    _project_dir(p.id)  # 업로드 디렉토리 미리 생성
    return ApiResponse(status="success", data={"id": p.id, "status": p.status})


@router.get("/projects")
async def list_projects(
    current_user: dict = Depends(_ensure_ml_unlocked),
    db: AsyncSession = Depends(get_db),
):
    """내 ML 프로젝트 목록"""
    rows = (
        await db.execute(
            select(MlProject)
            .where(MlProject.student_id == current_user["id"])
            .order_by(MlProject.created_at.desc())
        )
    ).scalars().all()
    return ApiResponse(status="success", data=[
        {
            "id": p.id, "title": p.title, "description": p.description,
            "status": p.status, "model_type": p.model_type,
            "sample_count": p.sample_count,
            "created_at": str(p.created_at) if p.created_at else None,
        }
        for p in rows
    ])


@router.get("/projects/{project_id}")
async def get_project(
    project_id: int,
    current_user: dict = Depends(_ensure_ml_unlocked),
    db: AsyncSession = Depends(get_db),
):
    project = await db.get(MlProject, project_id)
    if not project or project.student_id != current_user["id"]:
        raise HTTPException(404, "프로젝트를 찾을 수 없습니다.")
    # 전체 샘플 (클래스별)
    samples = (await db.execute(
        select(MlSample).where(MlSample.project_id == project_id).order_by(MlSample.id)  # 클래스 추가(생성) 순서 → 번호 [1][2][3]과 일치
    )).scalars().all()
    classes = {}
    for s in samples:
        classes.setdefault(s.class_name, []).append({
            "id": s.id, "file_path": s.file_path, "width": s.width, "height": s.height,
            "media_type": s.media_type,
        })
    return ApiResponse(status="success", data={
        "id": project.id, "title": project.title, "description": project.description,
        "status": project.status, "model_type": project.model_type,
        "sample_count": project.sample_count,
        "model_path": project.model_path, "model_export_path": project.model_export_path,
        "classes": classes,
    })


@router.patch("/projects/{project_id}")
async def update_project(
    project_id: int,
    body: MlProjectUpdate = Body(...),
    current_user: dict = Depends(_ensure_ml_unlocked),
    db: AsyncSession = Depends(get_db),
):
    project = await db.get(MlProject, project_id)
    if not project or project.student_id != current_user["id"]:
        raise HTTPException(404, "프로젝트를 찾을 수 없습니다.")
    if body.title is not None:
        project.title = body.title
    if body.status is not None and body.status in ("collecting", "learning", "ready", "exported"):
        project.status = body.status
    await db.commit()
    return ApiResponse(status="success", message="프로젝트가 업데이트되었습니다.")


@router.delete("/projects/{project_id}")
async def delete_project(
    project_id: int,
    current_user: dict = Depends(_ensure_ml_unlocked),
    db: AsyncSession = Depends(get_db),
):
    project = await db.get(MlProject, project_id)
    if not project or project.student_id != current_user["id"]:
        raise HTTPException(404, "프로젝트를 찾을 수 없습니다.")
    # 샘플 삭제
    samples = (await db.execute(select(MlSample).where(MlSample.project_id == project_id))).scalars().all()
    for s in samples:
        try:
            # lstrip("/uploads/ml/")는 문자 집합 제거라 'project_5'의 'p'까지 잘림 → removeprefix 사용
            os.remove(os.path.join(ML_UPLOAD_BASE, s.file_path.removeprefix("/uploads/ml/")))
        except Exception:
            pass
        await db.delete(s)
    # 빈 디렉토리 구조 정리
    shutil.rmtree(os.path.join(ML_UPLOAD_BASE, f"project_{project_id}"), ignore_errors=True)
    # 매핑 삭제
    maps = (await db.execute(select(MlArduinoMapping).where(MlArduinoMapping.project_id == project_id))).scalars().all()
    for m in maps:
        await db.delete(m)
    await db.delete(project)
    await db.commit()
    return ApiResponse(status="success", message="프로젝트가 삭제되었습니다.")


# ============================================================
# 샘플 이미지
# ============================================================

@router.post("/projects/{project_id}/samples")
async def upload_sample(
    project_id: int,
    class_name: str = Form(...),
    file: UploadFile = File(...),
    width: int = Form(0),
    height: int = Form(0),
    media_type: str = Form("image"),   # image(카메라/파일) / audio(음성 스펙트로그램)
    current_user: dict = Depends(_ensure_ml_unlocked),
    db: AsyncSession = Depends(get_db),
):
    project = await db.get(MlProject, project_id)
    if not project or project.student_id != current_user["id"]:
        raise HTTPException(404, "프로젝트를 찾을 수 없습니다.")

    # 파일 타입/크기 검증 (audio 모드도 스펙트로그램 PNG로 저장)
    allowed = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp"}
    ctype = file.content_type or ""
    if ctype and ctype not in allowed:
        raise HTTPException(400, "JPG/PNG/WEBP/GIF/BMP 이미지만 업로드 가능합니다.")

    # 저장
    ext = file.filename.rsplit(".", 1)[-1] if "." in file.filename else "jpg"
    if ext.lower() not in ("jpg", "jpeg", "png", "webp", "gif", "bmp"):
        ext = "jpg"
    fname = f"{class_name.replace(' ','_')}_{uuid.uuid4().hex[:12]}.{ext.lower()}"
    # 디렉토리: project_{id}/samples/class_{n}
    cls_dir = os.path.join(_project_dir(project_id), class_name.replace(" ", "_"))
    os.makedirs(cls_dir, exist_ok=True)
    fpath = os.path.join(cls_dir, fname)

    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(400, "파일 크기는 5MB 이하여야 합니다.")
    with open(fpath, "wb") as fh:
        fh.write(content)

    rel_path = f"/uploads/ml/project_{project_id}/samples/{class_name.replace(' ','_')}/{fname}"

    sample = MlSample(
        project_id=project_id, class_name=class_name,
        file_path=rel_path, width=width, height=height, media_type=media_type,
    )
    db.add(sample)
    # sample_count 갱신
    cnt = (await db.execute(select(func.count(MlSample.id)).where(MlSample.project_id == project_id))).scalar()
    project.sample_count = cnt or 0
    await db.commit()
    await db.refresh(sample)

    return ApiResponse(status="success", data={"id": sample.id, "file_path": sample.file_path, "media_type": sample.media_type})


@router.post("/projects/{project_id}/samples/batch")
async def upload_samples_batch(
    project_id: int,
    class_name: str = Form(...),
    current_user: dict = Depends(_ensure_ml_unlocked),
    db: AsyncSession = Depends(get_db),
):
    """다중(파일) 업로드 — Form으로 여러 파일. 간단 버전은 단일 루프."""
    raise HTTPException(501, "멀티 업로드는 별도 구현 (클라우드 직접 업로드 권장)")


@router.delete("/projects/{project_id}/samples/{sample_id}")
async def delete_sample(
    project_id: int,
    sample_id: int,
    current_user: dict = Depends(_ensure_ml_unlocked),
    db: AsyncSession = Depends(get_db),
):
    project = await db.get(MlProject, project_id)
    if not project or project.student_id != current_user["id"]:
        raise HTTPException(404, "프로젝트를 찾을 수 없습니다.")
    sample = await db.get(MlSample, sample_id)
    if not sample or sample.project_id != project_id:
        raise HTTPException(404, "샘플을 찾을 수 없습니다.")
    try:
        # lstrip("/uploads/ml/")는 문자 집합 제거라 'project_5'의 'p'까지 잘림 → removeprefix 사용
        os.remove(os.path.join(ML_UPLOAD_BASE, sample.file_path.removeprefix("/uploads/ml/")))
    except Exception:
        pass
    await db.delete(sample)
    cnt = (await db.execute(select(func.count(MlSample.id)).where(MlSample.project_id == project_id))).scalar()
    project.sample_count = cnt or 0
    await db.commit()
    return ApiResponse(status="success", message="샘플이 삭제되었습니다.")


# ============================================================
# 모델 저장 / 조회
# ============================================================

def _model_dir(project_id: int) -> str:
    d = os.path.join(ML_UPLOAD_BASE, f"project_{project_id}", "model")
    os.makedirs(d, exist_ok=True)
    return d


@router.post("/projects/{project_id}/model")
async def save_model(
    project_id: int,
    current_user: dict = Depends(_ensure_ml_unlocked),
    db: AsyncSession = Depends(get_db),
    model_json: str = Form(None),
    weights_b64: str = Form(None),
    labels: str = Form(None),
    model_type: str = Form("image"),
):
    """브라우저(TF.js) 학습 완료 모델 저장 — model.json + weights.bin + labels

    model_json: TF.js 모델 아키텍처 JSON (str)
    weights_b64: weights 바이너리 base64 (str)
    labels: JSON 배열 문자열 (클래스 라벨)
    """
    project = await db.get(MlProject, project_id)
    if not project or project.student_id != current_user["id"]:
        raise HTTPException(404, "프로젝트를 찾을 수 없습니다.")

    model_dir = _model_dir(project_id)
    if model_json:
        # weightsManifest의 경로를 실제 저장 파일명으로 교체
        try:
            manifest = json.loads(model_json)
            for w in manifest.get("weightsManifest", []):
                for p in w.get("paths", []):
                    if p != "model.weights.bin":
                        w["paths"] = ["model.weights.bin"]
            with open(os.path.join(model_dir, "model.json"), "w", encoding="utf-8") as fh:
                json.dump(manifest, fh, ensure_ascii=False)
        except Exception:
            with open(os.path.join(model_dir, "model.json"), "w", encoding="utf-8") as fh:
                fh.write(model_json)
    if weights_b64:
        import base64
        try:
            raw = base64.b64decode(weights_b64)
            with open(os.path.join(model_dir, "model.weights.bin"), "wb") as fh:
                fh.write(raw)
        except Exception:
            raise HTTPException(400, "weights 바이너리(base64) 형식이 올바르지 않습니다.")
    if labels:
        try:
            with open(os.path.join(model_dir, "labels.json"), "w", encoding="utf-8") as fh:
                fh.write(labels)
        except Exception:
            pass

    project.status = "ready"
    project.model_type = model_type
    project.model_path = f"/uploads/ml/project_{project_id}/model"
    await db.commit()
    return ApiResponse(status="success", message="모델이 저장되었습니다.")


@router.get("/projects/{project_id}/model")
async def get_model_meta(
    project_id: int,
    current_user: dict = Depends(_ensure_ml_unlocked),
    db: AsyncSession = Depends(get_db),
):
    project = await db.get(MlProject, project_id)
    if not project or project.student_id != current_user["id"]:
        raise HTTPException(404, "프로젝트를 찾을 수 없습니다.")
    return ApiResponse(status="success", data={
        "status": project.status, "model_type": project.model_type,
        "model_path": project.model_path,
        "model_export_path": project.model_export_path,
        "labels": await _get_labels(db, project_id),
    })


@router.get("/projects/{project_id}/model/file")
async def download_model_file(
    project_id: int,
    file: str = Query("model.json"),
    current_user: dict = Depends(_ensure_ml_unlocked),
    db: AsyncSession = Depends(get_db),
):
    """학습 완료 모델 파일 다운로드 (model.json / model.weights.bin / labels.json)

    ?file=model.json | model.weights.bin | labels.json
    """
    from fastapi.responses import FileResponse
    project = await db.get(MlProject, project_id)
    if not project or project.student_id != current_user["id"]:
        raise HTTPException(404, "프로젝트를 찾을 수 없습니다.")
    fname = os.path.basename(file)  # 경로 탈출 방지
    fpath = os.path.join(_model_dir(project_id), fname)
    if not os.path.isfile(fpath):
        raise HTTPException(404, "모델 파일을 찾을 수 없습니다.")
    return FileResponse(fpath, filename=fname)


@router.get("/projects/{project_id}/model/files")
async def list_model_files(
    project_id: int,
    current_user: dict = Depends(_ensure_ml_unlocked),
    db: AsyncSession = Depends(get_db),
):
    """모델 파일 목록 (파일명/크기)"""
    project = await db.get(MlProject, project_id)
    if not project or project.student_id != current_user["id"]:
        raise HTTPException(404, "프로젝트를 찾을 수 없습니다.")
    model_dir = _model_dir(project_id)
    files = []
    if os.path.isdir(model_dir):
        for name in sorted(os.listdir(model_dir)):
            fp = os.path.join(model_dir, name)
            if os.path.isfile(fp):
                files.append({"name": name, "size": os.path.getsize(fp)})
    return ApiResponse(status="success", data={"files": files, "model_path": project.model_path})


async def _get_labels(db, project_id):
    rows = await db.execute(select(MlSample.class_name).where(MlSample.project_id == project_id).distinct())
    return [r[0] for r in rows]


# ============================================================
# 아두이노 연동 — 본사 지정 동작 프리셋 (2026-09-08 재설계)
# 학생별 임의 매핑(MlArduinoMapping)은 폐기 → 본사가 ml_bt 설정에
# 지정한 클래스별 프리셋(1~10번)을 읽어 자동 송신한다.
# ============================================================

_PRESET_ACTIONS = {"led_on", "led_off", "servo", "buzzer", "none"}
_DEFAULT_PRESETS = [{"action": "none", "target_value": ""} for _ in range(10)]


def _normalize_presets(presets):
    """서버 저장용 프리셋 정규화 — 항상 10개 배열 (class 1~10 = index 0~9)."""
    if not isinstance(presets, list):
        return _DEFAULT_PRESETS
    out = []
    for i in range(10):
        p = presets[i] if i < len(presets) else {}
        if not isinstance(p, dict):
            p = {}
        action = str(p.get("action") or "none").strip()
        if action not in _PRESET_ACTIONS:
            action = "none"
        tv = str(p.get("target_value") or "").strip()[:60]
        out.append({"action": action, "target_value": tv})
    return out


@router.get("/preset")
async def get_ml_preset(
    current_user: dict = Depends(_ensure_ml_unlocked),
    db: AsyncSession = Depends(get_db),
):
    """학생 — 본사 지정 동작 프리셋 조회 (index 0 = 클래스 1번). 읽기 전용."""
    result = await db.execute(select(AppSetting).where(AppSetting.key == "ml_bt"))
    row = result.scalar_one_or_none()
    presets = _DEFAULT_PRESETS
    if row and row.value:
        try:
            data = row.value if isinstance(row.value, dict) else json.loads(row.value)
            presets = _normalize_presets(data.get("presets"))
        except Exception:
            pass
    return ApiResponse(status="success", data={"presets": presets})


@router.get("/bt-prefix")
async def get_bt_prefix(
    current_user: dict = Depends(_ensure_ml_unlocked),
    db: AsyncSession = Depends(get_db),
):
    """[보안] 접두어 평문 노출 금지 (260913 윤비스 지시).

    기존에는 본사 설정 접두어(예: 'NubidaAi')를 그대로 반환했으나,
    학생 브라우저의 개발자도구에서 통신값을 확인할 수 있었다.
    이제 접두어는 서버 밖으로 나가지 않는다. 값이 필요하면
    POST /ml/bt-command 로 클래스 번호만 보내 난독화 프레임을 받는다.
    """
    return ApiResponse(status="success", data={"bt_prefix": ""})


def _nubida_bt_encode(plain: str) -> str:
    """NubidaBT v1 난독화 — frontend common/js/nubida-bt.js 와 동일 규격.

    프레임 = 'x' + hex(seed ^ KEY) + 각바이트 hex(byte ^ seed)
    펌웨어(누비다머신 .ino)의 NB_KEY 와 KEY 가 일치해야 한다.
    """
    import random
    KEY = 0x2F
    seed = random.randint(1, 255)
    out = "x" + format(seed ^ KEY, "02x")
    for b in plain.encode("utf-8"):
        out += format(b ^ seed, "02x")
    return out


class BtCommandIn(BaseModel):
    class_no: int


@router.post("/bt-command")
async def post_bt_command(
    body: BtCommandIn,
    current_user: dict = Depends(_ensure_ml_unlocked),
    db: AsyncSession = Depends(get_db),
):
    """클래스 번호 → 아두이노 전송용 난독화 프레임 (접두어는 서버에서만 결합).

    브라우저는 접두어를 모른 채 이 프레임을 BLE 로 그대로 쓰기만 한다.
    """
    if body.class_no < 1 or body.class_no > 99:
        raise HTTPException(status_code=400, detail="클래스 번호가 올바르지 않습니다.")

    result = await db.execute(select(AppSetting).where(AppSetting.key == "ml_bt"))
    row = result.scalar_one_or_none()
    prefix = "NubidaAi"
    if row and row.value:
        try:
            data = row.value if isinstance(row.value, dict) else json.loads(row.value)
            prefix = ((data.get("bt_prefix") or "NubidaAi").strip() or "NubidaAi")[:20]
        except Exception:
            pass

    plain = "{}{}".format(body.class_no, prefix)
    frame = _nubida_bt_encode(plain)
    # 프레임만 반환 — 접두어/평문은 응답에 포함하지 않는다.
    return ApiResponse(status="success", data={"frame": frame})
