from sqlalchemy.orm import Session
from models import BatasanWilayah, School, User, Zonasi
from utils import hash_password, verify_password
from typing import Optional
from sqlalchemy import text
import json
import math
from routing import get_distances_many_to_one, get_distances_one_to_many, haversine_km

class UserAlreadyExistsError(Exception):
    pass


def create_user(db: Session, username, email, password, role="user", npsn=None):
    existing_username = db.query(User).filter(User.username == username).first()
    if existing_username:
        raise UserAlreadyExistsError("username sudah digunakan")

    existing_email = db.query(User).filter(User.email == email).first()
    if existing_email:
        raise UserAlreadyExistsError("email sudah digunakan")

    target_school_id = None
    if npsn and role == "sekolah":
        school = db.query(School).filter(School.npsn == npsn).first()
        if school:
            target_school_id = school.sekolah_id 
    hashed = hash_password(password)
    user = User(
        username=username,
        email=email,
        password_hash=hashed,
        role=role,
        school_id=target_school_id 
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    return user


def authenticate_user(db: Session, email, password):
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.password_hash):
        return None
    # Set online saat login
    user.is_online = 1
    db.commit()
    db.refresh(user)
    return user

def logout_user(db: Session, user_id: int):
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        user.is_online = 0
        db.commit()

# 09-05-2026
def get_schools(
    db: Session,
    jenjang: str | None = None,
    kecamatan: str | None = None,
    status: str | None = None,
    nama: str | None = None,
    apply_sampling: bool = False,
    page: int | None = None,     # ← pagination
    limit: int = 100,            # ← default 100 per halaman
):
    # Limit per jenjang per kabupaten
    LIMITS = {
        'SD':  50,
        'SMP': 50,
        'SMA': 100,
        'SMK': 100,
    }

    # Kondisi filter WHERE biasa
    conditions = []
    params = {}

    if jenjang:
        conditions.append("jenjang ILIKE :jenjang")
        params["jenjang"] = jenjang
    if kecamatan:
        conditions.append("kecamatan ILIKE :kecamatan")
        params["kecamatan"] = f"%{kecamatan}%"
    if status:
        conditions.append("status ILIKE :status")
        params["status"] = status
    if nama:
        conditions.append("nama_sekolah ILIKE :nama")
        params["nama"] = f"%{nama}%"

    where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    if not apply_sampling:
        # Query biasa tanpa sampling
        query = db.query(School)
        if jenjang:
            query = query.filter(School.jenjang.ilike(jenjang))
        if kecamatan:
            query = query.filter(School.kecamatan.ilike(f"%{kecamatan}%"))
        if status:
            query = query.filter(School.status.ilike(status))
        if nama:
            query = query.filter(School.nama_sekolah.ilike(f"%{nama}%"))
        query = query.order_by(School.nama_sekolah.asc())
        total = query.count()
        if page is not None:
            offset = (page - 1) * limit
            items  = query.offset(offset).limit(limit).all()
        else:
            items  = query.all()
        return {"items": items, "total": total}

    # ── Sampling dengan CTE + ROW_NUMBER ──────────────────────────
    sql = text(f"""
        WITH classified AS (
            SELECT *,
                CASE
                    WHEN jenjang ILIKE 'SD%%' OR jenjang ILIKE 'MI%%'  THEN 'SD'
                    WHEN jenjang ILIKE 'SMP%%' OR jenjang ILIKE 'MTS%%' OR jenjang ILIKE 'MT%%' THEN 'SMP'
                    WHEN jenjang ILIKE 'SMA%%' OR jenjang ILIKE 'MA%%'  THEN 'SMA'
                    WHEN jenjang ILIKE 'SMK%%'                           THEN 'SMK'
                    ELSE 'OTHER'
                END AS jenjang_group
            FROM sekolah
            {where_sql}
        ),
        ranked AS (
            SELECT *,
                ROW_NUMBER() OVER (
                    PARTITION BY kabupaten, jenjang_group
                    ORDER BY nama_sekolah ASC
                ) AS rn
            FROM classified
            WHERE jenjang_group != 'OTHER'
        )
        SELECT sekolah_id, nama_sekolah, npsn, jenjang, alamat,
               kecamatan, kabupaten, latitude, longitude,
               kuota, daya_tampung, status, akreditasi
        FROM ranked
        WHERE
            (jenjang_group = 'SD'  AND rn <= :lim_sd)  OR
            (jenjang_group = 'SMP' AND rn <= :lim_smp) OR
            (jenjang_group = 'SMA' AND rn <= :lim_sma) OR
            (jenjang_group = 'SMK' AND rn <= :lim_smk)
        ORDER BY nama_sekolah ASC
    """)

    params.update({
        "lim_sd":  LIMITS["SD"],
        "lim_smp": LIMITS["SMP"],
        "lim_sma": LIMITS["SMA"],
        "lim_smk": LIMITS["SMK"],
    })

    rows = db.execute(sql, params).mappings().all()

    # Konversi ke ORM object agar response_model tetap bekerja
    result = []
    for r in rows:
        s = School()
        for col in School.__table__.columns.keys():
            if col in r:
                setattr(s, col, r[col])
        result.append(s)

    return result        


def get_school_by_id(db: Session, school_id: int):
    return db.query(School).filter(School.sekolah_id == school_id).first()

def get_school_by_npsn(db: Session, npsn: str):
    return db.query(School).filter(School.npsn == npsn).first()

def get_zonasi(
    db: Session,
    jenjang: str | None = None,
    wilayah: str | None = None
):
    query = db.query(Zonasi)

    if jenjang:
        query = query.filter(Zonasi.nama_zonasi.ilike(jenjang))
    if wilayah:
        query = query.filter(Zonasi.wilayah.ilike(f"%{wilayah}%"))

    return query.order_by(Zonasi.nama_zonasi.asc(), Zonasi.wilayah.asc()).all()


def get_zonasi_by_id(db: Session, zonasi_id: int):
    return db.query(Zonasi).filter(Zonasi.zonasi_id == zonasi_id).first()


def get_batasan_wilayah(
    db: Session,
    wilayah: str | None = None,
    kecamatan: str | None = None,
    kabupaten: str | None = None,
    desa: str | None = None,
    kode_kecamatan: str | None = None,
    kode_kabupaten: str | None = None,
):
    query = db.query(BatasanWilayah)

    if wilayah:
        query = query.filter(BatasanWilayah.wilayah.ilike(f"%{wilayah}%"))
    if kecamatan:
        query = query.filter(BatasanWilayah.nama_kecamatan.ilike(f"%{kecamatan}%"))
    if kabupaten:
        query = query.filter(BatasanWilayah.nama_kabupaten.ilike(f"%{kabupaten}%"))
    if desa:
        query = query.filter(BatasanWilayah.nama_desa.ilike(f"%{desa}%"))
    if kode_kecamatan:
        query = query.filter(BatasanWilayah.kode_kecamatan == kode_kecamatan)
    if kode_kabupaten:
        query = query.filter(BatasanWilayah.kode_kabupaten == kode_kabupaten)

    return query.order_by(
        BatasanWilayah.nama_kabupaten.asc(),
        BatasanWilayah.nama_kecamatan.asc(),
        BatasanWilayah.nama_desa.asc(),
        BatasanWilayah.nama_zonasi.asc(),
    ).all()


def get_batasan_wilayah_by_id(db: Session, boundary_id: int):
    return db.query(BatasanWilayah).filter(BatasanWilayah.boundary_id == boundary_id).first()


def get_batasan_wilayah_geojson(
    db: Session,
    wilayah: str | None = None,
    kecamatan: str | None = None,
    kabupaten: str | None = None,
    desa: str | None = None,
    kode_kecamatan: str | None = None,
    kode_kabupaten: str | None = None,
):
    conditions = []
    params: dict[str, str] = {}

    if wilayah:
        conditions.append("wilayah ILIKE :wilayah")
        params["wilayah"] = f"%{wilayah}%"
    if kecamatan:
        conditions.append("""
            (
                nama_kecamatan ILIKE :kecamatan
                OR regexp_replace(lower(nama_kecamatan), '^(kec\\.?|kecamatan)\\s+', '') ILIKE :kecamatan_normalized
            )
        """)
        kecamatan_normalized = (
            str(kecamatan)
            .strip()
            .lower()
            .removeprefix("kecamatan ")
            .removeprefix("kec. ")
            .removeprefix("kec ")
            .strip()
        )
        params["kecamatan"] = f"%{kecamatan}%"
        params["kecamatan_normalized"] = f"%{kecamatan_normalized}%"
    if kabupaten:
        conditions.append("nama_kabupaten ILIKE :kabupaten")
        params["kabupaten"] = f"%{kabupaten}%"
    if desa:
        conditions.append("nama_desa ILIKE :desa")
        params["desa"] = f"%{desa}%"
    if kode_kecamatan:
        conditions.append("kode_kecamatan = :kode_kecamatan")
        params["kode_kecamatan"] = kode_kecamatan
    if kode_kabupaten:
        conditions.append("kode_kabupaten = :kode_kabupaten")
        params["kode_kabupaten"] = kode_kabupaten

    where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = text(f"""
        SELECT json_build_object(
            'type', 'FeatureCollection',
            'features', COALESCE(json_agg(
                json_build_object(
                    'type', 'Feature',
                    'id', boundary_id,
                    'geometry', ST_AsGeoJSON(geom)::json,
                    'properties', json_build_object(
                        'boundary_id', boundary_id,
                        'nama_zonasi', nama_zonasi,
                        'radius_meter', radius_meter,
                        'wilayah', wilayah,
                        'keterangan', keterangan,
                        'objectid', objectid,
                        'fcode', fcode,
                        'remark', remark,
                        'metadata', metadata,
                        'srs_id', srs_id,
                        'kode_kecamatan', kode_kecamatan,
                        'kode_desa', kode_desa,
                        'kode_kabupaten', kode_kabupaten,
                        'kode_provinsi', kode_provinsi,
                        'nama_kecamatan', nama_kecamatan,
                        'nama_desa', nama_desa,
                        'nama_kabupaten', nama_kabupaten,
                        'nama_provinsi', nama_provinsi,
                        'tipadm', tipadm,
                        'luaswh', luaswh,
                        'uupp', uupp,
                        'shape_length', shape_length,
                        'shape_area', shape_area
                    )
                )
                ORDER BY nama_kabupaten, nama_kecamatan, nama_desa, nama_zonasi
            ), '[]'::json)
        ) AS feature_collection
        FROM batasan_wilayah
        {where_sql}
    """)
    return db.execute(query, params).scalar()


def get_batasan_wilayah_geojson_by_id(db: Session, boundary_id: int):
    query = text("""
        SELECT json_build_object(
            'type', 'Feature',
            'id', boundary_id,
            'geometry', ST_AsGeoJSON(geom)::json,
            'properties', json_build_object(
                'boundary_id', boundary_id,
                'nama_zonasi', nama_zonasi,
                'radius_meter', radius_meter,
                'wilayah', wilayah,
                'keterangan', keterangan,
                'objectid', objectid,
                'fcode', fcode,
                'remark', remark,
                'metadata', metadata,
                'srs_id', srs_id,
                'kode_kecamatan', kode_kecamatan,
                'kode_desa', kode_desa,
                'kode_kabupaten', kode_kabupaten,
                'kode_provinsi', kode_provinsi,
                'nama_kecamatan', nama_kecamatan,
                'nama_desa', nama_desa,
                'nama_kabupaten', nama_kabupaten,
                'nama_provinsi', nama_provinsi,
                'tipadm', tipadm,
                'luaswh', luaswh,
                'uupp', uupp,
                'shape_length', shape_length,
                'shape_area', shape_area
            )
        ) AS feature
        FROM batasan_wilayah
        WHERE boundary_id = :boundary_id
    """)
    return db.execute(query, {"boundary_id": boundary_id}).scalar()

# --- School CRUD ---
 
def create_school(db: Session, data) -> "School":
    result = db.execute(
        text("""
            INSERT INTO sekolah 
                (nama_sekolah, npsn, jenjang, alamat, kecamatan,
                 latitude, longitude, location,
                 kuota, daya_tampung, status, akreditasi)
            VALUES 
                (:nama_sekolah, :npsn, :jenjang, :alamat, :kecamatan,
                 :latitude, :longitude,
                 ST_SetSRID(ST_Point(:longitude, :latitude), 4326)::geography,
                 :kuota, :daya_tampung, :status, :akreditasi)
            RETURNING sekolah_id
        """),
        {
            "nama_sekolah": data.nama_sekolah,
            "npsn":         data.npsn or None,
            "jenjang":      data.jenjang,
            "alamat":       data.alamat,
            "kecamatan":    data.kecamatan,
            "latitude":     data.latitude,
            "longitude":    data.longitude,
            "kuota":        data.kuota,
            "daya_tampung": data.daya_tampung,
            "status":       data.status,
            "akreditasi":   data.akreditasi,
        }
    )
    db.commit()
    new_id = result.scalar()
    return db.query(School).filter(School.sekolah_id == new_id).first()
 
 
def update_school(db: Session, school_id: int, data) -> Optional["School"]:
    school = db.query(School).filter(School.sekolah_id == school_id).first()
    if not school:
        return None

    update_data = data.model_dump(exclude_unset=True)
    
    # Pisahkan lat/lng dari field biasa
    lat = update_data.pop("latitude", None)
    lng = update_data.pop("longitude", None)

    # Update field biasa via ORM
    for key, value in update_data.items():
        setattr(school, key, value)

    # Update lat, lng, dan location sekaligus
    if lat is not None and lng is not None:
        db.execute(
            text("""
                UPDATE sekolah 
                SET latitude = :lat, longitude = :lng,
                    location = ST_SetSRID(ST_Point(:lng, :lat), 4326)::geography
                WHERE sekolah_id = :id
            """),
            {"lat": lat, "lng": lng, "id": school_id}
        )
    
    db.commit()
    return db.query(School).filter(School.sekolah_id == school_id).first()
 
 
def delete_school(db: Session, school_id: int) -> bool:
    school = db.query(School).filter(School.sekolah_id == school_id).first()
    if not school:
        return False
    db.delete(school)
    db.commit()
    return True
 
 
# --- Zonasi CRUD ---
 
def create_zonasi(db: Session, data) -> "Zonasi":
    zonasi = Zonasi(
        nama_zonasi=data.nama_zonasi,
        radius_meter=data.radius_meter,
        wilayah=data.wilayah,
        keterangan=data.keterangan,
    )
    db.add(zonasi)
    db.commit()
    db.refresh(zonasi)
    return zonasi
 
 
def update_zonasi(db: Session, zonasi_id: int, data) -> Optional["Zonasi"]:
    zonasi = db.query(Zonasi).filter(Zonasi.zonasi_id == zonasi_id).first()
    if not zonasi:
        return None
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(zonasi, key, value)
    db.commit()
    db.refresh(zonasi)
    return zonasi
 
 
def delete_zonasi(db: Session, zonasi_id: int) -> bool:
    zonasi = db.query(Zonasi).filter(Zonasi.zonasi_id == zonasi_id).first()
    if not zonasi:
        return False
    db.delete(zonasi)
    db.commit()
    return True
 
 
# --- Operator: ambil sekolah afiliasi berdasarkan user ---
 
def get_school_by_user(db: Session, user_id: int) -> Optional["School"]:
    """Ambil sekolah yang diasosiasikan ke akun operator."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.school_id:
        return None
    return db.query(School).filter(School.sekolah_id == user.school_id).first()
# ─── Profile CRUD ────────────────────────────────────────────────
from models import UserProfile, AdminProfile, OperatorProfile

def _get_profile_model(role: str):
    if role == "admin":    return AdminProfile
    if role == "sekolah":  return OperatorProfile
    return UserProfile

def get_profile(db: Session, user_id: int, role: str):
    Model = _get_profile_model(role)
    return db.query(Model).filter(Model.user_id == user_id).first()

def upsert_profile(db: Session, user_id: int, role: str, data: dict):
    Model = _get_profile_model(role)
    profile = db.query(Model).filter(Model.user_id == user_id).first()
    if profile:
        for k, v in data.items():
            setattr(profile, k, v)
    else:
        profile = Model(user_id=user_id, **data)
        db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile

def get_all_users(db: Session):
    return db.query(User).order_by(User.id.asc()).all()

# 10-05-2026
def _haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Hitung jarak dua koordinat (km) — haversine formula."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlng / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
 
 
# ── Normalisasi jenjang ke key sederhana (SD/SMP/SMA/SMK) ─────────
def _norm_jenjang(j: str) -> str:
    j = (j or "").upper().strip()
    if any(x in j for x in ("SMK",)):           return "SMK"
    if any(x in j for x in ("SMA", "MA")):      return "SMA"
    if any(x in j for x in ("SMP", "MTS")):     return "SMP"
    if any(x in j for x in ("SD", "MI")):       return "SD"
    return ""


# ── Jalur Prestasi: bobot poin berdasarkan tingkat pencapaian ────
TINGKAT_POIN_PRESTASI = {
    "nasional":  100,
    "provinsi":  75,
    "kabupaten": 50,
    "sekolah":   25,
}


def _poin_prestasi_tertinggi(prestasi_list) -> int:
    """Ambil poin tertinggi dari semua prestasi yang diinput (skala 0-100)."""
    if not prestasi_list or not isinstance(prestasi_list, list):
        return 0
    poin = 0
    for p in prestasi_list:
        if not isinstance(p, dict):
            continue
        tingkat = (p.get("tingkat") or "").strip().lower()
        poin = max(poin, TINGKAT_POIN_PRESTASI.get(tingkat, 0))
    return poin


# ── Rekomendasi Sekolah: radius zona per jenjang ──────────────────
DEFAULT_RADIUS_KM = {"SD": 3, "SMP": 5, "SMA": 8, "SMK": 8}
MAX_RADIUS_KM     = 15   # batas maksimum absolut, walau radius zonasi > ini


def get_rekomendasi_sekolah(db: Session, home_lat: float, home_lng: float,
                             jenjang_anak: str, nilai_rapor, prestasi_list):
    """
    Cari Top 10 sekolah dengan Skor Kelayakan tertinggi untuk anak ini.

    Skor Kelayakan = Skor Jarak * 0.7 + Skor Akademik * 0.3
      - Skor Jarak: 100 jika jarak=0, menurun linear ke 0 di radius zona
      - Skor Akademik: nilai_rapor * 0.6 + poin_prestasi * 0.4

    Radius pencarian mengikuti tabel Zonasi (admin-configurable) untuk
    jenjang terkait, dibatasi maksimum MAX_RADIUS_KM.
    """
    jenjang_norm = _norm_jenjang(jenjang_anak)
    if not jenjang_norm:
        return {"error": "Jenjang anak belum diisi di profil"}

    if home_lat is None or home_lng is None:
        return {"error": "Lokasi rumah belum diisi di profil"}

    # ── Tentukan radius pencarian dari tabel Zonasi (fallback default) ──
    radius_km = DEFAULT_RADIUS_KM.get(jenjang_norm, 8)
    for z in db.query(Zonasi).all():
        nz = (z.nama_zonasi or "").upper()
        if jenjang_norm in nz and z.radius_meter:
            radius_km = z.radius_meter / 1000
            break
    radius_km = min(radius_km, MAX_RADIUS_KM)

    # ── Bounding box query (mempersempit sebelum hitung haversine) ──
    lat_delta = radius_km / 111.0
    lng_delta = radius_km / (111.0 * max(math.cos(math.radians(home_lat)), 0.1))

    rows = (
        db.query(School)
        .filter(School.latitude.isnot(None), School.longitude.isnot(None))
        .filter(School.latitude.between(home_lat - lat_delta, home_lat + lat_delta))
        .filter(School.longitude.between(home_lng - lng_delta, home_lng + lng_delta))
        .all()
    )

    # ── Skor akademik (konstan untuk anak ini) ──────────────────────
    try:
        nilai_rapor_f = float(nilai_rapor) if nilai_rapor is not None else None
    except (TypeError, ValueError):
        nilai_rapor_f = None

    poin_prestasi = _poin_prestasi_tertinggi(prestasi_list)
    skor_akademik = round((nilai_rapor_f or 0) * 0.6 + poin_prestasi * 0.4, 1)

    results = []
    for s in rows:
        if _norm_jenjang(s.jenjang or "") != jenjang_norm:
            continue
        dist_km = _haversine(home_lat, home_lng, s.latitude, s.longitude)
        if dist_km > radius_km:
            continue

        skor_jarak     = max(0.0, round((1 - dist_km / radius_km) * 100, 1))
        skor_kelayakan = round(skor_jarak * 0.7 + skor_akademik * 0.3, 1)

        results.append({
            "sekolah_id":     s.sekolah_id,
            "nama_sekolah":   s.nama_sekolah,
            "jenjang":        s.jenjang,
            "kecamatan":      s.kecamatan,
            "alamat":         s.alamat,
            "akreditasi":     s.akreditasi,
            "status":         s.status,
            "kuota":          s.kuota,
            "daya_tampung":   s.daya_tampung,
            "lat":            s.latitude,
            "lng":            s.longitude,
            "jarak_lurus_km": round(dist_km, 2),
            "skor_jarak":     skor_jarak,
            "skor_akademik":  skor_akademik,
            "skor_kelayakan": skor_kelayakan,
        })

    results.sort(key=lambda x: x["skor_kelayakan"], reverse=True)
    top10 = results[:10]

    # ── Jarak via jalan untuk Top 10 saja (1 panggilan ORS, hemat kuota) ──
    if top10:
        destinations = [
            {"sekolah_id": r["sekolah_id"], "lat": r["lat"], "lng": r["lng"]}
            for r in top10
        ]
        dual = get_distances_one_to_many(db, home_lat, home_lng, destinations)
        for r in top10:
            info = dual.get(r["sekolah_id"])
            if info:
                r["jarak_jalan_km"]     = info["jarak_jalan_km"]
                r["durasi_jalan_menit"] = info["durasi_jalan_menit"]
                r["jalan_tersedia"]     = info["jalan_tersedia"]
            r.pop("lat", None)
            r.pop("lng", None)

    return {
        "jenjang":        jenjang_norm,
        "radius_km":      radius_km,
        "nilai_rapor":    nilai_rapor_f,
        "poin_prestasi":  poin_prestasi,
        "skor_akademik":  skor_akademik,
        "total_kandidat": len(results),
        "rekomendasi":    top10,
    }


def get_simulasi_ppdb(db, sekolah_id: int, requesting_user_id=None, anak_idx=None):
    from models import UserProfile
 
    school = db.query(School).filter(School.sekolah_id == sekolah_id).first()
    if not school:
        return None
 
    if school.latitude is None or school.longitude is None:
        return {
            "sekolah_id":      school.sekolah_id,
            "nama_sekolah":    school.nama_sekolah,
            "kuota":           school.kuota,
            "akreditasi":      school.akreditasi,
            "kecamatan":       school.kecamatan,
            "alamat":          school.alamat,
            "jenjang_sekolah": school.jenjang,
            "status_sekolah":  school.status,
            "school_lat":      None,
            "school_lng":      None,
            "peringkat_saya":  None,
            "status_saya":     None,
            "kuota_prestasi":          None,
            "peringkat_prestasi_saya": None,
            "status_prestasi_saya":    None,
            "skor_prestasi_saya":      None,
            "total_pendaftar": 0,
            "peserta":         [],
        }
 
    profiles   = db.query(UserProfile).all()
    candidates = []
    target     = school.nama_sekolah.strip().lower()
    seen_pairs = set()  # (user_id, nama_anak) agar tidak duplikat

    sekolah_jenjang = _norm_jenjang(school.jenjang or "")

    def _make_candidate(profile, child):
        """Bangun dict kandidat dari (profile, child). Return None jika data tidak lengkap."""
        if profile.home_lat is None or profile.home_lng is None:
            return None

        dist_km = _haversine(
            profile.home_lat, profile.home_lng,
            school.latitude,  school.longitude,
        )

        # ── Jalur Prestasi: nilai rapor + poin prestasi ──────────
        nilai_rapor = child.get("nilaiRapor")
        try:
            nilai_rapor = float(nilai_rapor) if nilai_rapor is not None else None
        except (TypeError, ValueError):
            nilai_rapor = None

        poin_prestasi = _poin_prestasi_tertinggi(child.get("prestasi"))
        skor_prestasi = round((nilai_rapor or 0) * 0.6 + poin_prestasi * 0.4, 2)

        return {
            "user_id":   profile.user_id,
            "nama_anak": (child.get("nama") or "").strip() or "—",
            "jenjang":   (child.get("jenjang") or "").strip() or "—",
            "jarak_lurus_km": round(dist_km, 2),
            "home_lat":  profile.home_lat,
            "home_lng":  profile.home_lng,
            "is_me":     profile.user_id == requesting_user_id,
            "kecamatan": getattr(profile, "kecamatan", None) or "—",
            "kelurahan": getattr(profile, "kelurahan", None) or "—",
            "nilai_rapor":   nilai_rapor,
            "skor_prestasi": skor_prestasi,
        }

    for profile in profiles:
        if profile.home_lat is None or profile.home_lng is None:
            continue
        if not profile.data_anak:
            continue

        try:
            children = json.loads(profile.data_anak)
            if not isinstance(children, list):
                continue
        except (json.JSONDecodeError, TypeError):
            continue

        for child in children:
            # sekolahTujuan bisa string (lama) atau array (baru)
            raw = child.get("sekolahTujuan") or ""
            if isinstance(raw, list):
                tujuan_list = [t.strip().lower() for t in raw if t]
            else:
                tujuan_list = [raw.strip().lower()] if raw.strip() else []

            if target not in tujuan_list:
                continue

            # Validasi jenjang anak harus sesuai jenjang sekolah (jalur zonasi)
            child_jenjang = _norm_jenjang(child.get("jenjang") or "")
            if sekolah_jenjang and child_jenjang and child_jenjang != sekolah_jenjang:
                continue  # jenjang tidak cocok, lewati

            # Hindari duplikat anak yang sama dari user yang sama
            pair_key = (profile.user_id, (child.get("nama") or "").strip().lower())
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)

            candidate = _make_candidate(profile, child)
            if candidate is None:
                continue
            candidates.append(candidate)
            # Tidak break — biarkan anak lain dari user yg sama ikut jika ada

    # ── Fallback: user memilih sekolah dari Top 10 Rekomendasi ───────
    # Sekolah Top 10 dipilih berdasarkan jarak/skor, bukan dari
    # sekolahTujuan — jadi user tidak akan masuk kandidat dari loop di
    # atas. Kalau user belum ada di list, tambahkan anak mereka sekarang.
    if requesting_user_id is not None and anak_idx is not None:
        already_in = any(c["user_id"] == requesting_user_id for c in candidates)
        if not already_in:
            req_profile = db.query(UserProfile).filter(
                UserProfile.user_id == requesting_user_id
            ).first()
            if req_profile and req_profile.data_anak:
                try:
                    req_children = json.loads(req_profile.data_anak)
                    if isinstance(req_children, list) and anak_idx < len(req_children):
                        c = _make_candidate(req_profile, req_children[anak_idx])
                        if c is not None:
                            candidates.append(c)
                except (json.JSONDecodeError, TypeError):
                    pass

    # ── Peringkat & status zonasi resmi: berbasis JARAK LURUS ────────
    candidates.sort(key=lambda x: x["jarak_lurus_km"])

    # ── Jarak via jalan: info tambahan, dihitung berdampingan ────────
    if candidates:
        origins = [
            {"key": idx, "lat": c["home_lat"], "lng": c["home_lng"]}
            for idx, c in enumerate(candidates)
        ]
        dual = get_distances_many_to_one(
            db, origins, school.latitude, school.longitude, school.sekolah_id
        )
        for idx, c in enumerate(candidates):
            info = dual.get(idx)
            if info:
                c["jarak_jalan_km"]     = info["jarak_jalan_km"]
                c["durasi_jalan_menit"] = info["durasi_jalan_menit"]
                c["jalan_tersedia"]     = info["jalan_tersedia"]

    kuota          = school.kuota or 0

    # ── Jalur Prestasi: ranking berdasarkan skor (nilai rapor + prestasi) ──
    # Kuota jalur prestasi diasumsikan 20% dari kuota total (min. 1 jika kuota>0),
    # mengikuti proporsi umum jalur prestasi pada PPDB.
    kuota_prestasi = max(1, round(kuota * 0.2)) if kuota else 0

    candidates_by_prestasi = sorted(candidates, key=lambda x: x["skor_prestasi"], reverse=True)
    for i, c in enumerate(candidates_by_prestasi):
        c["peringkat_prestasi"] = i + 1
        c["status_prestasi"] = "Lolos" if c["peringkat_prestasi"] <= kuota_prestasi else "Tidak Lolos"

    peserta        = []
    peringkat_saya = None
    status_saya    = None
    peringkat_prestasi_saya = None
    status_prestasi_saya    = None
    skor_prestasi_saya      = None

    for i, c in enumerate(candidates):
        rank   = i + 1
        status = "Lolos" if rank <= kuota else "Tidak Lolos"
        if c["is_me"]:
            peringkat_saya = rank
            status_saya    = status
            peringkat_prestasi_saya = c.get("peringkat_prestasi")
            status_prestasi_saya    = c.get("status_prestasi")
            skor_prestasi_saya      = c.get("skor_prestasi")
        peserta.append({
            "peringkat": rank,
            "nama_anak": c["nama_anak"],
            "jenjang":   c["jenjang"],
            "jarak_lurus_km":     c["jarak_lurus_km"],
            "jarak_jalan_km":     c.get("jarak_jalan_km"),
            "durasi_jalan_menit": c.get("durasi_jalan_menit"),
            "jalan_tersedia":     c.get("jalan_tersedia", False),
            "status":    status,
            "is_me":     c["is_me"],
            "kecamatan": c["kecamatan"],
            "kelurahan": c["kelurahan"],
            "nilai_rapor":        c.get("nilai_rapor"),
            "skor_prestasi":      c.get("skor_prestasi"),
            "peringkat_prestasi": c.get("peringkat_prestasi"),
            "status_prestasi":    c.get("status_prestasi"),
        })
 
    return {
        "sekolah_id":      school.sekolah_id,
        "nama_sekolah":    school.nama_sekolah,
        "kuota":           school.kuota,
        "akreditasi":      school.akreditasi,
        "kecamatan":       school.kecamatan,
        "alamat":          school.alamat,
        "jenjang_sekolah": school.jenjang,
        "status_sekolah":  school.status,
        "school_lat":      school.latitude,    # ← untuk map di frontend
        "school_lng":      school.longitude,   # ← untuk map di frontend
        "peringkat_saya":  peringkat_saya,
        "status_saya":     status_saya,
        "kuota_prestasi":          kuota_prestasi,
        "peringkat_prestasi_saya": peringkat_prestasi_saya,
        "status_prestasi_saya":    status_prestasi_saya,
        "skor_prestasi_saya":      skor_prestasi_saya,
        "total_pendaftar": len(candidates),
        "peserta":         peserta,
    }

def get_wilayah_kabupaten(db):
    """Daftar kabupaten/kota unik dari batasan_wilayah, sorted."""
    rows = db.execute(
        text("""
            SELECT DISTINCT nama_kabupaten
            FROM batasan_wilayah
            WHERE nama_kabupaten IS NOT NULL AND nama_kabupaten != ''
            ORDER BY nama_kabupaten ASC
        """)
    ).fetchall()
    return [r[0] for r in rows]
 
 
def get_wilayah_kecamatan(db, kabupaten: str):
    """Daftar kecamatan unik untuk kabupaten tertentu."""
    rows = db.execute(
        text("""
            SELECT DISTINCT nama_kecamatan
            FROM batasan_wilayah
            WHERE nama_kabupaten ILIKE :kab
              AND nama_kecamatan IS NOT NULL AND nama_kecamatan != ''
            ORDER BY nama_kecamatan ASC
        """),
        {"kab": kabupaten}
    ).fetchall()
    return [r[0] for r in rows]
 
 
def get_wilayah_kelurahan(db, kabupaten: str, kecamatan: str):
    """Daftar desa/kelurahan unik untuk kecamatan tertentu."""
    rows = db.execute(
        text("""
            SELECT DISTINCT nama_desa
            FROM batasan_wilayah
            WHERE nama_kabupaten ILIKE :kab
              AND nama_kecamatan ILIKE :kec
              AND nama_desa IS NOT NULL AND nama_desa != ''
            ORDER BY nama_desa ASC
        """),
        {"kab": kabupaten, "kec": kecamatan}
    ).fetchall()
    return [r[0] for r in rows]

# ─── Biaya CRUD ──────────────────────────────────────────────────
def get_biaya(db, sekolah_id: int):
    from models import SekolahBiaya
    return db.query(SekolahBiaya).filter(SekolahBiaya.sekolah_id == sekolah_id).first()
 
def upsert_biaya(db, sekolah_id: int, data: dict):
    from models import SekolahBiaya
    biaya = db.query(SekolahBiaya).filter(SekolahBiaya.sekolah_id == sekolah_id).first()
    if biaya:
        for k, v in data.items():
            setattr(biaya, k, v)
    else:
        biaya = SekolahBiaya(sekolah_id=sekolah_id, **data)
        db.add(biaya)
    db.commit()
    db.refresh(biaya)
    return biaya
 
# ─── Fasilitas CRUD ──────────────────────────────────────────────
def get_fasilitas(db, sekolah_id: int):
    from models import SekolahFasilitas
    return db.query(SekolahFasilitas).filter(
        SekolahFasilitas.sekolah_id == sekolah_id
    ).all()
 
def create_fasilitas(db, sekolah_id: int, data: dict):
    from models import SekolahFasilitas
    f = SekolahFasilitas(sekolah_id=sekolah_id, **data)
    db.add(f)
    db.commit()
    db.refresh(f)
    return f
 
def update_fasilitas(db, fasilitas_id: int, data: dict):
    from models import SekolahFasilitas
    f = db.query(SekolahFasilitas).filter(SekolahFasilitas.id == fasilitas_id).first()
    if not f:
        return None
    for k, v in data.items():
        setattr(f, k, v)
    db.commit()
    db.refresh(f)
    return f
 
def delete_fasilitas(db, fasilitas_id: int):
    from models import SekolahFasilitas
    f = db.query(SekolahFasilitas).filter(SekolahFasilitas.id == fasilitas_id).first()
    if not f:
        return False
    db.delete(f)
    db.commit()
    return True
 
# ─── Pendaftar (reuse logika simulasi) ──────────────────────────
def get_pendaftar_sekolah(db, sekolah_id: int):
    "Daftar user yang salah satu anaknya memilih sekolah ini."
    from models import UserProfile, User
    school = db.query(School).filter(School.sekolah_id == sekolah_id).first()
    if not school:
        return []
 
    profiles  = db.query(UserProfile).all()
    candidates = []
    target    = school.nama_sekolah.strip().lower()
 
    for profile in profiles:
        if not profile.data_anak:
            continue
        try:
            children = json.loads(profile.data_anak)
            if not isinstance(children, list):
                continue
        except (json.JSONDecodeError, TypeError):
            continue
 
        for child in children:
            raw = child.get("sekolahTujuan") or ""
            if isinstance(raw, list):
                tujuan_list = [t.strip().lower() for t in raw if t]
            else:
                tujuan_list = [raw.strip().lower()] if raw.strip() else []
 
            if target not in tujuan_list:
                continue
 
            # Ambil nama user (ortu)
            user = db.query(User).filter(User.id == profile.user_id).first()
 
            candidates.append({
                "user_id":   profile.user_id,
                "nama_anak": (child.get("nama") or "").strip() or "—",
                "nama_ortu": user.username if user else "—",
                "alamat":    getattr(profile, "alamat", None) or "—",
                "kecamatan": getattr(profile, "kecamatan", None) or "—",
                "jenjang":   (child.get("jenjang") or "").strip() or "—",
                "home_lat":  profile.home_lat,
                "home_lng":  profile.home_lng,
                "jarak_lurus_km": None,
            })
            break

    # ── Jarak lurus (selalu) + jarak jalan (info tambahan) ───────────
    if school.latitude and school.longitude:
        origins = [
            {"key": idx, "lat": c["home_lat"], "lng": c["home_lng"]}
            for idx, c in enumerate(candidates) if c["home_lat"] and c["home_lng"]
        ]
        if origins:
            dual = get_distances_many_to_one(
                db, origins, school.latitude, school.longitude, school.sekolah_id
            )
            for idx, c in enumerate(candidates):
                info = dual.get(idx)
                if info:
                    c["jarak_lurus_km"]     = info["jarak_lurus_km"]
                    c["jarak_jalan_km"]     = info["jarak_jalan_km"]
                    c["durasi_jalan_menit"] = info["durasi_jalan_menit"]
                    c["jalan_tersedia"]     = info["jalan_tersedia"]

    # ── Peringkat & status zonasi resmi: berbasis JARAK LURUS ────────
    candidates.sort(key=lambda x: (x["jarak_lurus_km"] is None, x["jarak_lurus_km"] or 0))

    kuota   = school.kuota or 0
    result  = []
    for i, c in enumerate(candidates):
        rank = i + 1
        result.append({
            "peringkat": rank,
            "nama_anak": c["nama_anak"],
            "nama_ortu": c["nama_ortu"],
            "alamat":    c["alamat"],
            "kecamatan": c["kecamatan"],
            "jenjang":   c["jenjang"],
            "jarak_lurus_km":     c["jarak_lurus_km"],
            "jarak_jalan_km":     c.get("jarak_jalan_km"),
            "durasi_jalan_menit": c.get("durasi_jalan_menit"),
            "jalan_tersedia":     c.get("jalan_tersedia", False),
            "status":    "Lolos" if rank <= kuota else "Tidak Lolos",
        })
    return result
