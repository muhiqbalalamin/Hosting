from sqlalchemy.orm import Session
from models import BatasanWilayah, School, User, Zonasi
from utils import hash_password, verify_password
from typing import Optional
from sqlalchemy import text
import json
import math

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
    apply_sampling: bool = False,   # ← toggle sampling 
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
        return query.order_by(School.nama_sekolah.asc()).all()

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
from .models import UserProfile, AdminProfile, OperatorProfile

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
 
 
def get_simulasi_ppdb(db, sekolah_id: int, requesting_user_id=None):
    from .models import UserProfile
 
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
            "total_pendaftar": 0,
            "peserta":         [],
        }
 
    profiles   = db.query(UserProfile).all()
    candidates = []
    target     = school.nama_sekolah.strip().lower()
    seen_pairs = set()  # (user_id, nama_anak) agar tidak duplikat

    # Helper: normalisasi jenjang ke key sederhana untuk perbandingan
    def _norm_jenjang(j: str) -> str:
        j = (j or "").upper().strip()
        if any(x in j for x in ("SMK",)):           return "SMK"
        if any(x in j for x in ("SMA", "MA")):      return "SMA"
        if any(x in j for x in ("SMP", "MTS")):     return "SMP"
        if any(x in j for x in ("SD", "MI")):       return "SD"
        return ""

    sekolah_jenjang = _norm_jenjang(school.jenjang or "")

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

            dist_km = _haversine(
                profile.home_lat, profile.home_lng,
                school.latitude,  school.longitude,
            )
            candidates.append({
                "user_id":   profile.user_id,
                "nama_anak": (child.get("nama") or "").strip() or "—",
                "jenjang":   (child.get("jenjang") or "").strip() or "—",
                "jarak_km":  round(dist_km, 2),
                "is_me":     profile.user_id == requesting_user_id,
                "kecamatan": getattr(profile, "kecamatan", None) or "—",
                "kelurahan": getattr(profile, "kelurahan", None) or "—",
            })
            # Tidak break — biarkan anak lain dari user yg sama ikut jika ada
 
    candidates.sort(key=lambda x: x["jarak_km"])
 
    kuota          = school.kuota or 0
    peserta        = []
    peringkat_saya = None
    status_saya    = None
 
    for i, c in enumerate(candidates):
        rank   = i + 1
        status = "Lolos" if rank <= kuota else "Tidak Lolos"
        if c["is_me"]:
            peringkat_saya = rank
            status_saya    = status
        peserta.append({
            "peringkat": rank,
            "nama_anak": c["nama_anak"],
            "jenjang":   c["jenjang"],
            "jarak_km":  c["jarak_km"],
            "status":    status,
            "is_me":     c["is_me"],
            "kecamatan": c["kecamatan"],
            "kelurahan": c["kelurahan"],
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
    from .models import SekolahBiaya
    return db.query(SekolahBiaya).filter(SekolahBiaya.sekolah_id == sekolah_id).first()
 
def upsert_biaya(db, sekolah_id: int, data: dict):
    from .models import SekolahBiaya
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
    from .models import SekolahFasilitas
    return db.query(SekolahFasilitas).filter(
        SekolahFasilitas.sekolah_id == sekolah_id
    ).all()
 
def create_fasilitas(db, sekolah_id: int, data: dict):
    from .models import SekolahFasilitas
    f = SekolahFasilitas(sekolah_id=sekolah_id, **data)
    db.add(f)
    db.commit()
    db.refresh(f)
    return f
 
def update_fasilitas(db, fasilitas_id: int, data: dict):
    from .models import SekolahFasilitas
    f = db.query(SekolahFasilitas).filter(SekolahFasilitas.id == fasilitas_id).first()
    if not f:
        return None
    for k, v in data.items():
        setattr(f, k, v)
    db.commit()
    db.refresh(f)
    return f
 
def delete_fasilitas(db, fasilitas_id: int):
    from .models import SekolahFasilitas
    f = db.query(SekolahFasilitas).filter(SekolahFasilitas.id == fasilitas_id).first()
    if not f:
        return False
    db.delete(f)
    db.commit()
    return True
 
# ─── Pendaftar (reuse logika simulasi) ──────────────────────────
def get_pendaftar_sekolah(db, sekolah_id: int):
    "Daftar user yang salah satu anaknya memilih sekolah ini."
    from .models import UserProfile, User
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
 
            dist_km = None
            if (profile.home_lat and profile.home_lng and
                    school.latitude and school.longitude):
                dist_km = round(_haversine(
                    profile.home_lat, profile.home_lng,
                    school.latitude, school.longitude
                ), 2)
 
            # Ambil nama user (ortu)
            user = db.query(User).filter(User.id == profile.user_id).first()
 
            candidates.append({
                "user_id":   profile.user_id,
                "nama_anak": (child.get("nama") or "").strip() or "—",
                "nama_ortu": user.username if user else "—",
                "alamat":    getattr(profile, "alamat", None) or "—",
                "kecamatan": getattr(profile, "kecamatan", None) or "—",
                "jenjang":   (child.get("jenjang") or "").strip() or "—",
                "jarak_km":  dist_km,
            })
            break
 
    # Sort by jarak
    candidates.sort(key=lambda x: (x["jarak_km"] is None, x["jarak_km"] or 0))
 
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
            "jarak_km":  c["jarak_km"],
            "status":    "Lolos" if rank <= kuota else "Tidak Lolos",
        })
    return result
