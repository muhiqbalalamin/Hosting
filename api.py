import json
import os
import re
from typing import Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from db import SessionLocal

# ── Kode registrasi dari env variable (set di Railway Variables) ──
ADMIN_CODE    = os.getenv("ADMIN_CODE")
OPERATOR_CODE = os.getenv("OPERATOR_CODE")

# ── Guard sederhana untuk endpoint sensitif ──────────────────────
def require_admin(x_role: str = Header(default="", alias="X-Role")):
    if x_role != "admin":
        raise HTTPException(status_code=403, detail="Akses ditolak: hanya admin")

def require_operator_or_admin(x_role: str = Header(default="", alias="X-Role")):
    if x_role not in ("admin", "sekolah"):
        raise HTTPException(status_code=403, detail="Akses ditolak")
from schemas import (
    BatasanWilayahResponse,
    LoginSchema, RegisterSchema,
    SchoolMapResponse,
    SchoolResponse,ZonasiResponse,
    SchoolCreate, SchoolUpdate, 
    ZonasiCreate, ZonasiUpdate,
    BiayaUpsert,  BiayaResponse,
    FasilitasCreate, FasilitasResponse,
)
from crud import (
    UserAlreadyExistsError,
    authenticate_user, logout_user, create_user,
    get_school_by_npsn, get_school_by_id, get_schools,
    get_batasan_wilayah, get_batasan_wilayah_by_id,
    get_batasan_wilayah_geojson, get_batasan_wilayah_geojson_by_id,
    get_zonasi, get_zonasi_by_id, get_simulasi_ppdb, get_rekomendasi_sekolah,
    get_sekolah_dalam_radius,
    get_biaya, upsert_biaya,
    get_fasilitas, create_fasilitas, update_fasilitas, delete_fasilitas,
    create_school, update_school, delete_school,
    create_zonasi, update_zonasi, delete_zonasi,
    get_school_by_user, get_profile,
    upsert_profile, get_all_users,
    get_wilayah_kabupaten, get_wilayah_kecamatan,get_wilayah_kelurahan,
    get_pendaftar_sekolah,
)
from models import (School, SekolahBiaya, SekolahFasilitas, UserProfile)
from routing import get_distances_one_to_many, get_route_geometry

router = APIRouter()

# dependency DB
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

from sqlalchemy import text

@router.get("/profile/{user_id}")
def get_user_profile(user_id: int, role: str, db: Session = Depends(get_db)):
    """Ambil profil berdasarkan user_id dan role."""
    profile = get_profile(db, user_id, role)
    if not profile:
        return {}
    data = {c.name: getattr(profile, c.name) for c in profile.__table__.columns}
    return data


@router.put("/profile/{user_id}")
def save_user_profile(
    user_id: int,
    role: str,
    data: dict = Body(...),
    db: Session = Depends(get_db)
):
    """Simpan/update profil berdasarkan role."""
    for key in ("id", "user_id", "updated_at"):
        data.pop(key, None)
    upsert_profile(db, user_id, role, data)
    return {"message": "Profil berhasil disimpan", "user_id": user_id}


# Register
@router.post("/auth/register")
def register(data: RegisterSchema, db: Session = Depends(get_db)):
    if data.role == "admin":
        if data.admin_code != ADMIN_CODE:
            raise HTTPException(status_code=403, detail="Kode registrasi Admin tidak valid")
    elif data.role == "sekolah":
        if data.operator_code != OPERATOR_CODE:
            raise HTTPException(status_code=403, detail="Kode registrasi Operator tidak valid")
        if not data.npsn:
            raise HTTPException(status_code=400, detail="NPSN / ID Sekolah wajib diisi untuk Instansi Sekolah")

        sekolah = get_school_by_npsn(db, data.npsn)
        if not sekolah:
            raise HTTPException(status_code=404, detail="NPSN / ID Sekolah tidak ditemukan")

    try:
        user = create_user(db, data.username, data.email, data.password, data.role, data.npsn if data.role == "sekolah" else None)
    except UserAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc)
        ) from exc

    return {
        "message": "User berhasil dibuat",
        "username": user.username,
        "email": user.email,
        "role": user.role
    }


# Login
@router.post("/auth/login")
def login(data: LoginSchema, db: Session = Depends(get_db)):
    user = authenticate_user(db, data.email, data.password)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="email atau password salah"
        )

    return {
        "message": "Login berhasil",
        "user_id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role
    }

@router.post("/auth/logout")
def logout(user_id: int = Body(..., embed=True), db: Session = Depends(get_db)):
    logout_user(db, user_id)
    return {"message": "Logout berhasil"}


@router.get("/users")
def list_users(db: Session = Depends(get_db)):
    """Daftar semua pengguna terdaftar."""
    users = get_all_users(db)
    return [
        {
            "id":        u.id,
            "username":  u.username,
            "email":     u.email,
            "role":      u.role,
            "school_id": u.school_id,
            "is_online": u.is_online,   # 09-05-2026
        }
        for u in users
    ]

@router.get("/schools", response_model=dict)
def list_schools(
    jenjang:       Optional[str] = Query(default=None),
    kecamatan:     Optional[str] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    nama:          Optional[str] = Query(default=None),
    page:          int           = Query(default=1, ge=1),
    limit:         int           = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db)
):
    result = get_schools(
        db,
        jenjang=jenjang,
        kecamatan=kecamatan,
        status=status_filter,
        nama=nama,
        apply_sampling=False,
        page=page,
        limit=limit,
    )
    return {
        "items": [SchoolResponse.model_validate(s, from_attributes=True) for s in result["items"]],
        "total": result["total"],
        "page":  page,
        "limit": limit,
        "pages": -(-result["total"] // limit),
    }


@router.get("/schools/{school_id}", response_model=SchoolResponse)
def school_detail(school_id: int, db: Session = Depends(get_db)):
    school = get_school_by_id(db, school_id)
    if not school:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="data sekolah tidak ditemukan"
        )
    return school


@router.get("/zonasi", response_model=list[ZonasiResponse])
def list_zonasi(
    jenjang: Optional[str] = Query(default=None),
    wilayah: Optional[str] = Query(default=None),
    db: Session = Depends(get_db)
):
    return get_zonasi(db, jenjang=jenjang, wilayah=wilayah)


@router.get("/zonasi/{zonasi_id}", response_model=ZonasiResponse)
def zonasi_detail(zonasi_id: int, db: Session = Depends(get_db)):
    zonasi = get_zonasi_by_id(db, zonasi_id)
    if not zonasi:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="data zonasi tidak ditemukan"
        )
    return zonasi


@router.get("/batasan-wilayah", response_model=list[BatasanWilayahResponse])
def list_batasan_wilayah(
    wilayah: Optional[str] = Query(default=None),
    kecamatan: Optional[str] = Query(default=None),
    kabupaten: Optional[str] = Query(default=None),
    desa: Optional[str] = Query(default=None),
    kode_kecamatan: Optional[str] = Query(default=None),
    kode_kabupaten: Optional[str] = Query(default=None),
    db: Session = Depends(get_db)
):
    return get_batasan_wilayah(
        db,
        wilayah=wilayah,
        kecamatan=kecamatan,
        kabupaten=kabupaten,
        desa=desa,
        kode_kecamatan=kode_kecamatan,
        kode_kabupaten=kode_kabupaten,
    )


@router.get("/batasan-wilayah/geojson")
def list_batasan_wilayah_geojson(
    wilayah: Optional[str] = Query(default=None),
    kecamatan: Optional[str] = Query(default=None),
    kabupaten: Optional[str] = Query(default=None),
    desa: Optional[str] = Query(default=None),
    kode_kecamatan: Optional[str] = Query(default=None),
    kode_kabupaten: Optional[str] = Query(default=None),
    db: Session = Depends(get_db)
):
    return get_batasan_wilayah_geojson(
        db,
        wilayah=wilayah,
        kecamatan=kecamatan,
        kabupaten=kabupaten,
        desa=desa,
        kode_kecamatan=kode_kecamatan,
        kode_kabupaten=kode_kabupaten,
    )


@router.get("/batasan-wilayah/{boundary_id}", response_model=BatasanWilayahResponse)
def batasan_wilayah_detail(boundary_id: int, db: Session = Depends(get_db)):
    batasan_wilayah = get_batasan_wilayah_by_id(db, boundary_id)
    if not batasan_wilayah:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="data batasan wilayah tidak ditemukan"
        )
    return batasan_wilayah


@router.get("/batasan-wilayah/{boundary_id}/geojson")
def batasan_wilayah_geojson_detail(boundary_id: int, db: Session = Depends(get_db)):
    feature = get_batasan_wilayah_geojson_by_id(db, boundary_id)
    if not feature:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="data batasan wilayah tidak ditemukan"
        )
    return feature


@router.get("/map/schools", response_model=list[SchoolMapResponse])
def map_schools(
    jenjang: Optional[str] = Query(default=None),
    kecamatan: Optional[str] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    nama: Optional[str] = Query(default=None),
    db: Session = Depends(get_db)
):
    schools = get_schools(
        db,
        jenjang=jenjang,
        kecamatan=kecamatan,
        status=status_filter,
        nama=nama,
        apply_sampling=False
    )
    return schools["items"]


@router.get("/map/zonasi", response_model=list[ZonasiResponse])
def map_zonasi(
    jenjang: Optional[str] = Query(default=None),
    wilayah: Optional[str] = Query(default=None),
    db: Session = Depends(get_db)
):
    return get_zonasi(db, jenjang=jenjang, wilayah=wilayah)


# ── Sekolah dalam radius (untuk halaman Zonasi) ───────────────────
@router.get("/map/zonasi-schools", response_model=list[SchoolMapResponse])
def map_zonasi_schools(
    lat:       float           = Query(...),
    lng:       float           = Query(...),
    radius_km: float           = Query(5.0, ge=0.1, le=50.0),
    extra_km:  float           = Query(5.0, ge=0.0, le=20.0),
    jenjang:   Optional[str]   = Query(default=None),
    nama:      Optional[str]   = Query(default=None),
    db: Session = Depends(get_db),
):
    """
    Kembalikan sekolah dalam (radius_km + extra_km) dari koordinat user.
    Jauh lebih sedikit datanya dibanding /map/schools — ideal untuk Zonasi.
    """
    schools = get_sekolah_dalam_radius(
        db, lat, lng, radius_km, extra_km, jenjang=jenjang, nama=nama
    )
    return schools

# ── Jarak via jalan untuk halaman Zonasi ──────────────────────────
class JarakJalanRequest(BaseModel):
    lat: float
    lng: float
    sekolah_ids: list[int]


@router.post("/zonasi/jarak-jalan", response_model=dict)
def zonasi_jarak_jalan(data: JarakJalanRequest, db: Session = Depends(get_db)):
    """
    Hitung jarak lurus DAN jarak via jalan dari satu titik (lokasi user)
    ke beberapa sekolah. Dipanggil setelah penyaringan awal di frontend
    (sekolah_ids sebaiknya sudah berupa kandidat yang sudah disaring, max ~50).

    Hasil: { sekolah_id: { jarak_lurus_km, jarak_jalan_km, durasi_jalan_menit, jalan_tersedia } }
    """
    if not data.sekolah_ids:
        return {}

    schools = (
        db.query(School)
        .filter(School.sekolah_id.in_(data.sekolah_ids))
        .filter(School.latitude.isnot(None), School.longitude.isnot(None))
        .all()
    )
    destinations = [
        {"sekolah_id": s.sekolah_id, "lat": s.latitude, "lng": s.longitude}
        for s in schools
    ]
    return get_distances_one_to_many(db, data.lat, data.lng, destinations)


# ── Geometri rute via jalan (untuk peta) ──────────────────────────
@router.get("/rute-jalan", response_model=dict)
def rute_jalan(
    from_lat: float = Query(...),
    from_lng: float = Query(...),
    to_lat:   float = Query(...),
    to_lng:   float = Query(...),
):
    """
    Ambil geometri rute via jalan antara dua titik untuk digambar di peta.
    Tidak butuh DB session — tidak di-cache (geometri jarang dipanggil ulang
    untuk kombinasi titik yang sama persis).
    """
    return get_route_geometry(from_lat, from_lng, to_lat, to_lng)

# ──────────────────────────────────────────────
# SCHOOL — Create (Admin only)
# ──────────────────────────────────────────────
@router.post("/schools", response_model=dict, status_code=201)
def create_school_endpoint(data: "SchoolCreate", db: "Session" = Depends(get_db), _=Depends(require_admin)):
    school = create_school(db, data)
    return {"message": "Sekolah berhasil ditambahkan", "sekolah_id": school.sekolah_id}
 
 
# ──────────────────────────────────────────────
# SCHOOL — Update (Admin atau Operator sekolah sendiri)
# ──────────────────────────────────────────────
@router.put("/schools/{school_id}", response_model=SchoolResponse)
def update_school_endpoint(
    school_id: int,
    data: "SchoolUpdate",
    db: "Session" = Depends(get_db),
    _=Depends(require_operator_or_admin),
):
    school = update_school(db, school_id, data)
    if not school:
        raise HTTPException(status_code=404, detail="Sekolah tidak ditemukan")
    return school
 
 
# ──────────────────────────────────────────────
# SCHOOL — Delete (Admin only)
# ──────────────────────────────────────────────
@router.delete("/schools/{school_id}", response_model=dict)
def delete_school_endpoint(school_id: int, db: "Session" = Depends(get_db), _=Depends(require_admin)):
    deleted = delete_school(db, school_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Sekolah tidak ditemukan")
    return {"message": "Sekolah berhasil dihapus"}
 
 
# ──────────────────────────────────────────────
# ZONASI — Create
# ──────────────────────────────────────────────
@router.post("/zonasi", response_model=dict, status_code=201)
def create_zonasi_endpoint(data: "ZonasiCreate", db: "Session" = Depends(get_db), _=Depends(require_admin)):
    z = create_zonasi(db, data)
    return {"message": "Zonasi berhasil ditambahkan", "zonasi_id": z.zonasi_id}
 
 
# ──────────────────────────────────────────────
# ZONASI — Update
# ──────────────────────────────────────────────
@router.put("/zonasi/{zonasi_id}", response_model=ZonasiResponse)
def update_zonasi_endpoint(zonasi_id: int, data: "ZonasiUpdate", db: "Session" = Depends(get_db), _=Depends(require_admin)):
    z = update_zonasi(db, zonasi_id, data)
    if not z:
        raise HTTPException(status_code=404, detail="Zonasi tidak ditemukan")
    return z
 
 
# ──────────────────────────────────────────────
# ZONASI — Delete
# ──────────────────────────────────────────────
@router.delete("/zonasi/{zonasi_id}", response_model=dict)
def delete_zonasi_endpoint(zonasi_id: int, db: "Session" = Depends(get_db), _=Depends(require_admin)):
    deleted = delete_zonasi(db, zonasi_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Zonasi tidak ditemukan")
    return {"message": "Zonasi berhasil dihapus"}
 
 
# ──────────────────────────────────────────────
# OPERATOR — Ambil sekolah afiliasi sendiri
# Header: X-User-Id: <user_id>
# ──────────────────────────────────────────────
@router.get("/operator/my-school", response_model=SchoolResponse)
def get_my_school(
    x_user_id: int = Header(..., alias="X-User-Id"),
    db: "Session" = Depends(get_db),
):
    school = get_school_by_user(db, x_user_id)
    if not school:
        raise HTTPException(
            status_code=404,
            detail="Sekolah afiliasi tidak ditemukan. Hubungi admin untuk mengaitkan akun."
        )
    return school

# 10-05-2026
@router.get("/simulasi/ppdb/{sekolah_id}")
def simulasi_ppdb(
    sekolah_id: int,
    user_id:   Optional[int] = Query(default=None),
    anak_idx:  int           = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    result = get_simulasi_ppdb(
        db, sekolah_id,
        requesting_user_id=user_id,
        anak_idx=anak_idx,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sekolah tidak ditemukan")
    return result


@router.get("/simulasi/rekomendasi/{user_id}")
def simulasi_rekomendasi(
    user_id: int,
    anak_idx: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """
    Top 10 rekomendasi sekolah berdasarkan profil anak (jarak rumah,
    nilai rapor, prestasi) — dipakai di langkah awal Simulasi PPDB
    sebelum Penilaian Diri.
    """
    profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profil tidak ditemukan")

    try:
        children = json.loads(profile.data_anak or "[]")
    except (json.JSONDecodeError, TypeError):
        children = []

    if not isinstance(children, list) or anak_idx >= len(children):
        raise HTTPException(status_code=400, detail="Data anak tidak ditemukan")

    anak = children[anak_idx]
    result = get_rekomendasi_sekolah(
        db, profile.home_lat, profile.home_lng,
        anak.get("jenjang") or "", anak.get("nilaiRapor"), anak.get("prestasi"),
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/simulasi/cari-sekolah")
def cari_sekolah_simulasi(
    nama: str = Query(...),
    db: Session = Depends(get_db),
):
    """
    Cari sekolah by nama untuk kebutuhan simulasi dari halaman profil.
    Mengembalikan daftar sekolah yang namanya mengandung kata kunci.
    Dipakai frontend untuk resolve sekolahTujuan (string) → sekolah_id.
    """
    results = (
        db.query(School)
        .filter(School.nama_sekolah.ilike(f"%{nama}%"))
        .limit(5)
        .all()
    )
    return [
        {
            "sekolah_id":   s.sekolah_id,
            "nama_sekolah": s.nama_sekolah,
            "kecamatan":    s.kecamatan,
            "jenjang":      s.jenjang,
        }
        for s in results
    ]
 

@router.post("/auth/beacon-logout")
async def beacon_logout(request: Request, db: Session = Depends(get_db)):
    """Endpoint khusus untuk sendBeacon tanpa dependency multipart tambahan."""
    raw_body = await request.body()
    user_id = None

    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            payload = json.loads(raw_body.decode("utf-8"))
            user_id = payload.get("user_id")
        except (json.JSONDecodeError, UnicodeDecodeError):
            user_id = None
    else:
        try:
            body_text = raw_body.decode("utf-8", errors="ignore")
            match = re.search(r'name="user_id"\r\n\r\n(\d+)', body_text)
            if match:
                user_id = int(match.group(1))
        except ValueError:
            user_id = None

    if user_id is None:
        raise HTTPException(status_code=400, detail="user_id tidak valid")

    logout_user(db, user_id)
    return {"ok": True}

@router.get("/wilayah/kabupaten")
def list_kabupaten(db: Session = Depends(get_db)):
    """Daftar semua kabupaten/kota yang ada di database."""
    return get_wilayah_kabupaten(db)


@router.get("/wilayah/kecamatan")
def list_kecamatan(
    kabupaten: str = Query(...),
    db: Session = Depends(get_db)
):
    """Daftar kecamatan berdasarkan kabupaten."""
    return get_wilayah_kecamatan(db, kabupaten)


@router.get("/wilayah/kelurahan")
def list_kelurahan(
    kabupaten: str = Query(...),
    kecamatan: str = Query(...),
    db: Session = Depends(get_db)
):
    """Daftar kelurahan/desa berdasarkan kabupaten + kecamatan."""
    return get_wilayah_kelurahan(db, kabupaten, kecamatan)

# 12-05-2026
# ── Biaya ────────────────────────────────────────────────────────
@router.get("/schools/{sekolah_id}/biaya")
def get_school_biaya(sekolah_id: int, db: Session = Depends(get_db)):
    biaya = get_biaya(db, sekolah_id)
    if not biaya:
        return {"id": None, "sekolah_id": sekolah_id,
                "gedung":0,"seragam":0,"buku":0,"spp":0,"komite":0,"catatan":None}
    return {c.name: getattr(biaya, c.name) for c in biaya.__table__.columns}
 
@router.put("/schools/{sekolah_id}/biaya")
def save_school_biaya(
    sekolah_id: int,
    data: BiayaUpsert,
    db: Session = Depends(get_db)
):
    biaya = upsert_biaya(db, sekolah_id, data.model_dump(exclude_none=False))
    return {"message": "Biaya berhasil disimpan", "sekolah_id": sekolah_id}
 
 
# ── Fasilitas ────────────────────────────────────────────────────
@router.get("/schools/{sekolah_id}/fasilitas", response_model=list[FasilitasResponse])
def list_school_fasilitas(sekolah_id: int, db: Session = Depends(get_db)):
    return get_fasilitas(db, sekolah_id)
 
@router.post("/schools/{sekolah_id}/fasilitas", response_model=FasilitasResponse, status_code=201)
def add_fasilitas(sekolah_id: int, data: FasilitasCreate, db: Session = Depends(get_db)):
    return create_fasilitas(db, sekolah_id, data.model_dump())
 
@router.put("/fasilitas/{fasilitas_id}", response_model=FasilitasResponse)
def edit_fasilitas(fasilitas_id: int, data: FasilitasCreate, db: Session = Depends(get_db)):
    f = update_fasilitas(db, fasilitas_id, data.model_dump())
    if not f:
        raise HTTPException(status_code=404, detail="Fasilitas tidak ditemukan")
    return f
 
@router.delete("/fasilitas/{fasilitas_id}")
def remove_fasilitas(fasilitas_id: int, db: Session = Depends(get_db)):
    if not delete_fasilitas(db, fasilitas_id):
        raise HTTPException(status_code=404, detail="Fasilitas tidak ditemukan")
    return {"message": "Fasilitas berhasil dihapus"}
 
 
# ── Pendaftar (Operator view) ─────────────────────────────────────
@router.get("/schools/{sekolah_id}/pendaftar")
def list_pendaftar(sekolah_id: int, db: Session = Depends(get_db)):
    return get_pendaftar_sekolah(db, sekolah_id)
