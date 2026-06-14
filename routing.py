"""
routing.py — Hitung jarak garis lurus (Haversine) DAN jarak via jalan
(OpenRouteService), ditampilkan berdampingan.

Setiap fungsi mengembalikan KEDUA nilai untuk setiap pasangan titik:
  - jarak_lurus_km   : selalu tersedia (Haversine, tanpa API eksternal)
  - jarak_jalan_km   : via OpenRouteService + cache, None jika tidak tersedia
  - durasi_jalan_menit
  - jalan_tersedia   : bool

Jarak lurus dipakai sebagai basis PERINGKAT/STATUS zonasi resmi (konsisten,
tidak tergantung kuota API eksternal). Jarak jalan ditampilkan sebagai
informasi tambahan estimasi rute riil.

Env var yang dibutuhkan untuk jarak jalan:
  ORS_API_KEY — daftar gratis di https://openrouteservice.org/dev/#/signup
  (jika kosong, jarak_jalan_km = None & jalan_tersedia = False di semua hasil)
"""

import math
import os

import requests
from sqlalchemy.orm import Session

from models import JarakCache

ORS_API_KEY        = os.getenv("ORS_API_KEY", "")
ORS_MATRIX_URL     = "https://api.openrouteservice.org/v2/matrix/driving-car"
ORS_DIRECTIONS_URL = "https://api.openrouteservice.org/v2/directions/driving-car/geojson"
BATCH_SIZE         = 49   # aman di bawah limit lokasi per request ORS free tier


def haversine_km(lat1, lng1, lat2, lng2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _round_coord(v: float) -> float:
    return round(v, 4)


def _ors_call(body: dict):
    resp = requests.post(
        ORS_MATRIX_URL,
        json=body,
        headers={"Authorization": ORS_API_KEY, "Content-Type": "application/json"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def _empty_jalan():
    return {"jarak_jalan_km": None, "durasi_jalan_menit": None, "jalan_tersedia": False}


# ───────────────────────────────────────────────────────────────────
# Kasus 1: SATU origin → BANYAK destinasi (halaman Zonasi, Top 10 rekomendasi)
# ───────────────────────────────────────────────────────────────────
def get_distances_one_to_many(db: Session, origin_lat: float, origin_lng: float, destinations: list[dict]) -> dict:
    """
    destinations: [{"sekolah_id": int, "lat": float, "lng": float}, ...]
    return: {
      sekolah_id: {
        "jarak_lurus_km": float,
        "jarak_jalan_km": float | None,
        "durasi_jalan_menit": float | None,
        "jalan_tersedia": bool,
      }
    }
    """
    result = {}

    # ── Jarak lurus: selalu dihitung, instan ─────────────────────────
    for d in destinations:
        result[d["sekolah_id"]] = {
            "jarak_lurus_km": round(haversine_km(origin_lat, origin_lng, d["lat"], d["lng"]), 2),
            **_empty_jalan(),
        }

    # ── Jarak jalan: cache dulu, lalu ORS untuk sisanya ──────────────
    o_lat, o_lng = _round_coord(origin_lat), _round_coord(origin_lng)
    uncached = []
    for d in destinations:
        hit = (
            db.query(JarakCache)
            .filter_by(origin_lat=o_lat, origin_lng=o_lng, sekolah_id=d["sekolah_id"])
            .first()
        )
        if hit:
            result[d["sekolah_id"]]["jarak_jalan_km"]      = round(hit.jarak_meter / 1000, 2)
            result[d["sekolah_id"]]["durasi_jalan_menit"]  = round(hit.durasi_detik / 60, 1) if hit.durasi_detik else None
            result[d["sekolah_id"]]["jalan_tersedia"]      = True
        else:
            uncached.append(d)

    if not uncached or not ORS_API_KEY:
        return result

    for i in range(0, len(uncached), BATCH_SIZE):
        batch     = uncached[i:i + BATCH_SIZE]
        locations = [[origin_lng, origin_lat]] + [[d["lng"], d["lat"]] for d in batch]
        body = {
            "locations":    locations,
            "sources":      [0],
            "destinations": list(range(1, len(locations))),
            "metrics":      ["distance", "duration"],
            "units":        "m",
        }
        try:
            data      = _ors_call(body)
            distances = data["distances"][0]
            durations = data["durations"][0]
            for idx, d in enumerate(batch):
                jarak_m, durasi_s = distances[idx], durations[idx]
                if jarak_m is None:
                    continue
                result[d["sekolah_id"]]["jarak_jalan_km"]     = round(jarak_m / 1000, 2)
                result[d["sekolah_id"]]["durasi_jalan_menit"] = round(durasi_s / 60, 1)
                result[d["sekolah_id"]]["jalan_tersedia"]     = True
                db.add(JarakCache(
                    origin_lat=o_lat, origin_lng=o_lng, sekolah_id=d["sekolah_id"],
                    jarak_meter=jarak_m, durasi_detik=durasi_s,
                ))
            db.commit()
        except Exception as e:
            print(f"[ORS] one_to_many error: {e}")
            # jarak_jalan tetap None/tersedia=False untuk batch ini

    return result


# ───────────────────────────────────────────────────────────────────
# Kasus 2: BANYAK origin → SATU destinasi (Simulasi PPDB, Pendaftar)
# ───────────────────────────────────────────────────────────────────
def get_distances_many_to_one(db: Session, origins: list[dict], dest_lat: float, dest_lng: float, sekolah_id: int) -> dict:
    """
    origins: [{"key": <hashable>, "lat": float, "lng": float}, ...]
    return: {
      key: {
        "jarak_lurus_km": float,
        "jarak_jalan_km": float | None,
        "durasi_jalan_menit": float | None,
        "jalan_tersedia": bool,
      }
    }
    """
    result = {}

    # ── Jarak lurus: selalu dihitung, instan ─────────────────────────
    for o in origins:
        result[o["key"]] = {
            "jarak_lurus_km": round(haversine_km(o["lat"], o["lng"], dest_lat, dest_lng), 2),
            **_empty_jalan(),
        }

    # ── Jarak jalan: cache dulu, lalu ORS untuk sisanya ──────────────
    uncached = []
    for o in origins:
        o_lat, o_lng = _round_coord(o["lat"]), _round_coord(o["lng"])
        hit = (
            db.query(JarakCache)
            .filter_by(origin_lat=o_lat, origin_lng=o_lng, sekolah_id=sekolah_id)
            .first()
        )
        if hit:
            result[o["key"]]["jarak_jalan_km"]     = round(hit.jarak_meter / 1000, 2)
            result[o["key"]]["durasi_jalan_menit"] = round(hit.durasi_detik / 60, 1) if hit.durasi_detik else None
            result[o["key"]]["jalan_tersedia"]     = True
        else:
            uncached.append(o)

    if not uncached or not ORS_API_KEY:
        return result

    for i in range(0, len(uncached), BATCH_SIZE):
        batch     = uncached[i:i + BATCH_SIZE]
        locations = [[o["lng"], o["lat"]] for o in batch] + [[dest_lng, dest_lat]]
        dest_idx  = len(locations) - 1
        body = {
            "locations":    locations,
            "sources":      list(range(0, dest_idx)),
            "destinations": [dest_idx],
            "metrics":      ["distance", "duration"],
            "units":        "m",
        }
        try:
            data      = _ors_call(body)
            distances = data["distances"]
            durations = data["durations"]
            for idx, o in enumerate(batch):
                jarak_m  = distances[idx][0]
                durasi_s = durations[idx][0]
                if jarak_m is None:
                    continue
                result[o["key"]]["jarak_jalan_km"]     = round(jarak_m / 1000, 2)
                result[o["key"]]["durasi_jalan_menit"] = round(durasi_s / 60, 1)
                result[o["key"]]["jalan_tersedia"]     = True
                o_lat, o_lng = _round_coord(o["lat"]), _round_coord(o["lng"])
                db.add(JarakCache(
                    origin_lat=o_lat, origin_lng=o_lng, sekolah_id=sekolah_id,
                    jarak_meter=jarak_m, durasi_detik=durasi_s,
                ))
            db.commit()
        except Exception as e:
            print(f"[ORS] many_to_one error: {e}")

    return result


# ───────────────────────────────────────────────────────────────────
# Geometri rute (untuk digambar di peta): garis lurus DAN rute jalan
# ───────────────────────────────────────────────────────────────────
def get_route_geometry(origin_lat: float, origin_lng: float, dest_lat: float, dest_lng: float) -> dict:
    """
    return: {
      "lurus": {"coords": [[lat,lng],[lat,lng]], "jarak_km": float},
      "jalan": {"coords": [[lat,lng],...], "jarak_km": float, "durasi_menit": float} | None
    }
    "jalan" bernilai None jika ORS_API_KEY kosong atau request gagal.
    """
    result = {
        "lurus": {
            "coords":   [[origin_lat, origin_lng], [dest_lat, dest_lng]],
            "jarak_km": round(haversine_km(origin_lat, origin_lng, dest_lat, dest_lng), 2),
        },
        "jalan": None,
    }

    if not ORS_API_KEY:
        return result

    try:
        resp = requests.post(
            ORS_DIRECTIONS_URL,
            json={"coordinates": [[origin_lng, origin_lat], [dest_lng, dest_lat]]},
            headers={"Authorization": ORS_API_KEY, "Content-Type": "application/json"},
            timeout=10,
        )
        resp.raise_for_status()
        data    = resp.json()
        feature = data["features"][0]
        coords_lnglat = feature["geometry"]["coordinates"]
        props   = feature["properties"]["summary"]
        result["jalan"] = {
            "coords":       [[lat, lng] for lng, lat in coords_lnglat],
            "jarak_km":     round(props["distance"] / 1000, 2),
            "durasi_menit": round(props["duration"] / 60, 1),
        }
    except Exception as e:
        print(f"[ORS] directions error: {e}")

    return result