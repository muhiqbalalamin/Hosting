from sqlalchemy import Column, Float, ForeignKey, Integer, String, TIMESTAMP
from datetime import datetime
from db import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True)
    email = Column(String, unique=True)
    password_hash = Column(String)
    role = Column(String, default="user")
    school_id = Column(Integer, ForeignKey("sekolah.sekolah_id"), nullable=True)
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    is_online     = Column(Integer, default=0)  # 0 = non-aktif, 1 = aktif


# ── Profil data untuk user umum ─────────────────────────────────
class UserProfile(Base):
    __tablename__ = "user_profiles"

    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    nama        = Column(String, nullable=True)
    telepon     = Column(String, nullable=True)
    alamat      = Column(String, nullable=True)
    home_lat   = Column(Float, nullable=True)   
    home_lng   = Column(Float, nullable=True)  
    kabupaten      = Column(String, nullable=True)   
    kecamatan      = Column(String, nullable=True) 
    kelurahan      = Column(String, nullable=True)   
    data_anak   = Column(String, nullable=True)
    updated_at  = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)


# ── Profil data untuk admin ──────────────────────────────────────
class AdminProfile(Base):
    __tablename__ = "admin_profiles"

    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    nama        = Column(String, nullable=True)
    telepon     = Column(String, nullable=True)
    afiliasi    = Column(String, nullable=True)
    kode        = Column(String, nullable=True)
    updated_at  = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)


# ── Profil data untuk operator sekolah ──────────────────────────
class OperatorProfile(Base):
    __tablename__ = "operator_profiles"

    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    nama        = Column(String, nullable=True)
    telepon     = Column(String, nullable=True)
    afiliasi    = Column(String, nullable=True)
    kode        = Column(String, nullable=True)
    updated_at  = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)


class School(Base):
    __tablename__ = "sekolah"

    sekolah_id   = Column(Integer, primary_key=True, index=True)
    nama_sekolah = Column(String)
    npsn         = Column(String, index=True, nullable=True)  # unique enforced via DB partial index
    jenjang      = Column(String)
    alamat       = Column(String)
    kecamatan    = Column(String)
    kabupaten    = Column(String) #9-05-2026
    latitude     = Column(Float)
    longitude    = Column(Float)
    kuota        = Column(Integer)
    daya_tampung = Column(Integer)
    status       = Column(String)
    akreditasi   = Column(String)


class Zonasi(Base):
    __tablename__ = "zonasi"

    zonasi_id = Column(Integer, primary_key=True, index=True)
    nama_zonasi = Column(String)
    radius_meter = Column(Float)
    wilayah = Column(String)
    keterangan = Column(String)


class BatasanWilayah(Base):
    __tablename__ = "batasan_wilayah"

    boundary_id = Column(Integer, primary_key=True, index=True)
    nama_zonasi = Column(String)
    radius_meter = Column(Float)
    wilayah = Column(String)
    keterangan = Column(String)
    objectid = Column(Integer)
    fcode = Column(String)
    metadata_value = Column("metadata", String)
    srs_id = Column(String)
    kode_kecamatan = Column(String)
    kode_desa = Column(String)
    kode_kabupaten = Column(String)
    kode_provinsi = Column(String)
    nama_kecamatan = Column(String)
    nama_desa = Column(String)
    nama_kabupaten = Column(String)
    nama_provinsi = Column(String)
    tipadm = Column(Integer)
    luaswh = Column(Float)
    uupp = Column(String)
    shape_length = Column(Float)
    shape_area = Column(Float)
    remark = Column(String)
 
class SekolahBiaya(Base):
    __tablename__ = "sekolah_biaya"
 
    id         = Column(Integer, primary_key=True, index=True)
    sekolah_id = Column(Integer, ForeignKey("sekolah.sekolah_id"), unique=True, nullable=False)
    gedung     = Column(Integer, default=0)
    seragam    = Column(Integer, default=0)
    buku       = Column(Integer, default=0)
    spp        = Column(Integer, default=0)
    komite     = Column(Integer, default=0)
    catatan    = Column(String, nullable=True)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)
 
 
class SekolahFasilitas(Base):
    __tablename__ = "sekolah_fasilitas"
 
    id         = Column(Integer, primary_key=True, index=True)
    sekolah_id = Column(Integer, ForeignKey("sekolah.sekolah_id"), nullable=False)
    nama       = Column(String, nullable=False)
    jumlah     = Column(Integer, default=1)
    kondisi    = Column(String, default="Baik")
    keterangan = Column(String, nullable=True)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)
