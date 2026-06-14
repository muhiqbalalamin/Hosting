from pydantic import BaseModel, Field
from typing import Optional


class RegisterSchema(BaseModel):
    username: str
    email: str
    password: str
    role: str = "user"
    admin_code: Optional[str] = None
    operator_code: Optional[str] = None
    npsn: Optional[str] = None

class LoginSchema(BaseModel):
    email: str
    password: str


class SchoolResponse(BaseModel):
    sekolah_id: int
    nama_sekolah: str
    jenjang: str | None = None
    alamat: str | None = None
    kecamatan: str | None = None
    kabupaten:    str | None = None    # 09-05-2026
    latitude: float | None = None
    longitude: float | None = None
    kuota: int | None = None
    daya_tampung: int | None = None
    status: str | None = None
    akreditasi: str | None = None


class SchoolMapResponse(BaseModel):
    sekolah_id: int
    nama_sekolah: str
    jenjang: str | None = None
    kecamatan: str | None = None
    kabupaten:    str | None = None    # 09-05-2026
    latitude: float | None = None
    longitude: float | None = None
    status: str | None = None
    alamat: str | None = None
    kuota: int | None = None
    daya_tampung: int | None = None
    akreditasi: str | None = None


class ZonasiResponse(BaseModel):
    zonasi_id: int
    nama_zonasi: str
    radius_meter: float | None = None
    wilayah: str | None = None
    keterangan: str | None = None


class BatasanWilayahResponse(BaseModel):
    boundary_id: int
    nama_zonasi: str | None = None
    radius_meter: float | None = None
    wilayah: str | None = None
    keterangan: str | None = None
    objectid: int | None = None
    fcode: str | None = None
    remark: str | None = None
    metadata: str | None = Field(default=None, validation_alias="metadata_value")
    srs_id: str | None = None
    kode_kecamatan: str | None = None
    kode_desa: str | None = None
    kode_kabupaten: str | None = None
    kode_provinsi: str | None = None
    nama_kecamatan: str | None = None
    nama_desa: str | None = None
    nama_kabupaten: str | None = None
    nama_provinsi: str | None = None
    tipadm: int | None = None
    luaswh: float | None = None
    uupp: str | None = None
    shape_length: float | None = None
    shape_area: float | None = None

    class Config:
        from_attributes = True

# --- School CRUD schemas ---
class SchoolCreate(BaseModel):
    nama_sekolah: str
    npsn:         Optional[str] = None
    jenjang:      Optional[str] = None
    alamat:       Optional[str] = None
    kecamatan:    Optional[str] = None
    latitude:     Optional[float] = None
    longitude:    Optional[float] = None
    kuota:        Optional[int] = None
    daya_tampung: Optional[int] = None
    status:       Optional[str] = None   
    akreditasi:   Optional[str] = None
 
class SchoolUpdate(SchoolCreate):
    nama_sekolah: Optional[str] = None  
 
# --- Zonasi CRUD schemas ---
class ZonasiCreate(BaseModel):
    nama_zonasi:  str
    radius_meter: Optional[float] = None
    wilayah:      Optional[str]   = None
    keterangan:   Optional[str]   = None
 
class ZonasiUpdate(ZonasiCreate):
    nama_zonasi: Optional[str] = None
# ─── Profile schemas ────────────────────────────────────────────
class UserProfileSchema(BaseModel):
    nama:           Optional[str] = None
    telepon:        Optional[str] = None
    alamat:         Optional[str] = None
    kota:           Optional[str] = None
    nama_anak:      Optional[str] = None
    jenjang_anak:   Optional[str] = None
    sekolah_tujuan: Optional[str] = None

class StaffProfileSchema(BaseModel):
    nama:     Optional[str] = None
    telepon:  Optional[str] = None
    afiliasi: Optional[str] = None
    kode:     Optional[str] = None

class UserProfileResponse(UserProfileSchema):
    id:      int
    user_id: int
    class Config: from_attributes = True

class StaffProfileResponse(StaffProfileSchema):
    id:      int
    user_id: int
    class Config: from_attributes = True

# ─── Simulasi PPDB Schemas ───────────────────────────────────────
class SimulasiPeserta(BaseModel):
    peringkat:  int
    nama_anak:  str
    jenjang:    str
    jarak_lurus_km:     float | None
    jarak_jalan_km:     float | None = None
    durasi_jalan_menit: float | None = None
    jalan_tersedia:     bool = False
    status:     str   # "Lolos" | "Tidak Lolos"
    is_me:      bool  # True jika ini adalah user yang sedang login
    kecamatan:  str | None   # ← tambah
    kelurahan:  str | None   # ← tambah
    nilai_rapor:        float | None = None
    skor_prestasi:      float | None = None
    peringkat_prestasi: int   | None = None
    status_prestasi:    str   | None = None
 
class SimulasiResult(BaseModel):
    sekolah_id:      int
    nama_sekolah:    str
    kuota:           int | None
    akreditasi:      str | None
    kecamatan:       str | None
    alamat:          str | None
    jenjang_sekolah: str | None
    status_sekolah:  str | None
    peringkat_saya:  int | None   # None jika user belum set lokasi / tidak mendaftar
    status_saya:     str | None
    kuota_prestasi:          int | None = None
    peringkat_prestasi_saya: int | None = None
    status_prestasi_saya:    str | None = None
    skor_prestasi_saya:      float | None = None
    total_pendaftar: int
    peserta:         list[SimulasiPeserta]
    
# ─── Biaya ───────────────────────────────────────────────────────
class BiayaUpsert(BaseModel):
    gedung:   Optional[int] = 0
    seragam:  Optional[int] = 0
    buku:     Optional[int] = 0
    spp:      Optional[int] = 0
    komite:   Optional[int] = 0
    catatan:  Optional[str] = None
 
class BiayaResponse(BiayaUpsert):
    id:         int
    sekolah_id: int
    class Config: from_attributes = True
 
# ─── Fasilitas ───────────────────────────────────────────────────
class FasilitasCreate(BaseModel):
    nama:       str
    jumlah:     Optional[int] = 1
    kondisi:    Optional[str] = "Baik"
    keterangan: Optional[str] = None
 
class FasilitasResponse(FasilitasCreate):
    id:         int
    sekolah_id: int
    class Config: from_attributes = True
 
# ─── Pendaftar (untuk operator) ──────────────────────────────────
class PendaftarItem(BaseModel):
    nama_anak:  str
    nama_ortu:  str | None
    alamat:     str | None
    kecamatan:  str | None
    jenjang:    str | None
    jarak_lurus_km:     float | None
    jarak_jalan_km:     float | None = None
    durasi_jalan_menit: float | None = None
    jalan_tersedia:     bool = False
    status:     str            # Lolos / Tidak Lolos
    peringkat:  int
