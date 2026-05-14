"""
VedaVision — Celestial Noir calculation backend.

Uses Swiss Ephemeris (via pyswisseph) for sidereal positions.
Output JSON matches the VedaVision SAMPLE_CHART data contract.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

import swisseph as swe
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Optional geocoding/timezone resolution (graceful fallback if not installed)
try:
    from geopy.geocoders import Nominatim
    from timezonefinder import TimezoneFinder
    import pytz
    _GEO_AVAILABLE = True
except ImportError:
    _GEO_AVAILABLE = False

# ---------------------------------------------------------------------------
# Constants — classical Jyotish reference data
# ---------------------------------------------------------------------------

SIGNS = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"
]

SIGN_LORDS = {
    "Aries": "Mars", "Taurus": "Venus", "Gemini": "Mercury", "Cancer": "Moon",
    "Leo": "Sun", "Virgo": "Mercury", "Libra": "Venus", "Scorpio": "Mars",
    "Sagittarius": "Jupiter", "Capricorn": "Saturn", "Aquarius": "Saturn", "Pisces": "Jupiter"
}

# Vimshottari Dasha sequence and years (classical Parashari)
VIMSHOTTARI_SEQ = [
    ("Ketu", 7),
    ("Venus", 20),
    ("Sun", 6),
    ("Moon", 10),
    ("Mars", 7),
    ("Rahu", 18),
    ("Jupiter", 16),
    ("Saturn", 19),
    ("Mercury", 17),
]
VIMSHOTTARI_TOTAL = 120

# The 27 Nakshatras — name, lord (for Vimshottari), deity, symbol, classical theme
NAKSHATRAS = [
    ("Ashwini", "Ketu", "Ashwini Kumaras", "Horse's head", "Swift beginnings, healing, the rush of new energy."),
    ("Bharani", "Venus", "Yama", "Yoni", "Bearing, restraint, the crucible of transformation."),
    ("Krittika", "Sun", "Agni", "Razor / flame", "Cutting clarity, purification through fire."),
    ("Rohini", "Moon", "Brahma", "Ox-cart", "Growth, beauty, and the act of creating something lasting in the material world."),
    ("Mrigashira", "Mars", "Soma", "Deer's head", "Seeking, gentle pursuit, the restlessness of the curious mind."),
    ("Ardra", "Rahu", "Rudra", "Teardrop", "Storm and renewal, the necessity of breaking down to rebuild."),
    ("Punarvasu", "Jupiter", "Aditi", "Bow and quiver", "Return, recovery, the soul's perennial homecoming."),
    ("Pushya", "Saturn", "Brihaspati", "Cow's udder", "Nourishment, providing, the discipline of care."),
    ("Ashlesha", "Mercury", "Nagas", "Coiled serpent", "Penetrating insight, the wisdom that arrives through entanglement."),
    ("Magha", "Ketu", "Pitrs", "Throne", "Ancestral inheritance, the weight and gift of lineage."),
    ("Purva Phalguni", "Venus", "Bhaga", "Front legs of a bed", "Enjoyment, creative partnership, the pleasure that fuels work."),
    ("Uttara Phalguni", "Sun", "Aryaman", "Back legs of a bed", "Generous patronage, dependable partnership, the steady gift."),
    ("Hasta", "Moon", "Savitr", "Hand", "Skill, craft, the precise grasp of the world."),
    ("Chitra", "Mars", "Tvashtar", "Bright jewel", "Brilliance, design, the gem cut to catch the light."),
    ("Swati", "Rahu", "Vayu", "Young shoot in the wind", "Independence, the flexibility that survives the storm."),
    ("Vishakha", "Jupiter", "Indra-Agni", "Triumphal arch", "Goal-oriented intensity, the focused will of ambition."),
    ("Anuradha", "Saturn", "Mitra", "Lotus", "Friendship, devotion, the bonds that organise a life."),
    ("Jyeshtha", "Mercury", "Indra", "Earring / umbrella", "Eldership, authority, the burden of being the one who knows."),
    ("Mula", "Ketu", "Nirriti", "Bunch of roots", "Root-cutting, the search beneath surfaces."),
    ("Purva Ashadha", "Venus", "Apas", "Elephant tusk", "Invincibility, the conviction of one's own water."),
    ("Uttara Ashadha", "Sun", "Vishvadevas", "Elephant tusk", "Lasting victory, the slow accumulation of unassailable position."),
    ("Shravana", "Moon", "Vishnu", "Ear", "Listening, learning, the receptivity that becomes wisdom."),
    ("Dhanishta", "Mars", "Vasus", "Drum", "Rhythm, abundance, the music of accomplishment."),
    ("Shatabhisha", "Rahu", "Varuna", "Empty circle", "Healing through mystery, the secret medicine."),
    ("Purva Bhadrapada", "Jupiter", "Aja Ekapada", "Two-faced man", "Spiritual fire, the heat that transforms."),
    ("Uttara Bhadrapada", "Saturn", "Ahir Budhnya", "Two-faced man", "Deep waters, the wisdom of stillness."),
    ("Revati", "Mercury", "Pushan", "Fish", "Safe passage, the kindly guide to the next shore."),
]

# Planet identifiers in pyswisseph
PLANETS = {
    "Sun": swe.SUN,
    "Moon": swe.MOON,
    "Mars": swe.MARS,
    "Mercury": swe.MERCURY,
    "Jupiter": swe.JUPITER,
    "Venus": swe.VENUS,
    "Saturn": swe.SATURN,
    "Rahu": swe.MEAN_NODE,  # North Node — Mean is more traditional for Jyotish
    # Ketu is computed from Rahu (opposite point)
}

PLANET_ABBR = {
    "Sun": "Su", "Moon": "Mo", "Mars": "Ma", "Mercury": "Me",
    "Jupiter": "Ju", "Venus": "Ve", "Saturn": "Sa", "Rahu": "Ra", "Ketu": "Ke"
}

PLANET_GLYPHS = {
    "Sun": "☉", "Moon": "☽", "Mars": "♂", "Mercury": "☿",
    "Jupiter": "♃", "Venus": "♀", "Saturn": "♄", "Rahu": "☊", "Ketu": "☋"
}

PLANET_SKT = {
    "Sun": "Surya", "Moon": "Chandra", "Mars": "Mangal", "Mercury": "Budha",
    "Jupiter": "Guru", "Venus": "Shukra", "Saturn": "Shani", "Rahu": "Rahu", "Ketu": "Ketu"
}

PLANET_COLORS = {
    "Sun": "#F59E0B", "Moon": "#94A3B8", "Mars": "#EF4444", "Mercury": "#10B981",
    "Jupiter": "#F97316", "Venus": "#EC4899", "Saturn": "#6366F1",
    "Rahu": "#8B5CF6", "Ketu": "#78716C"
}

# Dignity reference data
EXALTATION_SIGNS = {
    "Sun": "Aries", "Moon": "Taurus", "Mars": "Capricorn", "Mercury": "Virgo",
    "Jupiter": "Cancer", "Venus": "Pisces", "Saturn": "Libra"
}

DEBILITATION_SIGNS = {
    "Sun": "Libra", "Moon": "Scorpio", "Mars": "Cancer", "Mercury": "Pisces",
    "Jupiter": "Capricorn", "Venus": "Virgo", "Saturn": "Aries"
}

OWN_SIGNS = {
    "Sun": ["Leo"],
    "Moon": ["Cancer"],
    "Mars": ["Aries", "Scorpio"],
    "Mercury": ["Gemini", "Virgo"],
    "Jupiter": ["Sagittarius", "Pisces"],
    "Venus": ["Taurus", "Libra"],
    "Saturn": ["Capricorn", "Aquarius"],
}

# Ayanamsa options
AYANAMSAS = {
    "Lahiri": swe.SIDM_LAHIRI,
    "Raman": swe.SIDM_RAMAN,
    "KP": swe.SIDM_KRISHNAMURTI,
}

# Karaka order (planets considered for Jaimini karakas — Rahu reversed degree, Ketu excluded)
KARAKA_PLANETS = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu"]
KARAKA_ROLES = [
    ("atmakaraka", "Soul indicator"),
    ("amatyakaraka", "Vocational minister"),
    ("bhratrukaraka", "Sibling indicator"),
    ("matrukaraka", "Mother indicator"),
    ("putrakaraka", "Child / creative indicator"),
    ("gnatikaraka", "Cousin / spiritual struggle indicator"),
    ("darakaraka", "Spouse indicator"),
]

# Leadership type by AK planet
LEADERSHIP_MAP = {
    "Sun": "Commander",
    "Moon": "Commander",
    "Mars": "Commander",
    "Mercury": "Specialist",
    "Jupiter": "Founder",
    "Venus": "Founder",
    "Saturn": "Specialist",
    "Rahu": "Founder",
    "Ketu": "Specialist",
}

# ---------------------------------------------------------------------------
# Swiss Ephemeris setup
# ---------------------------------------------------------------------------

_EPHE_PATH = os.environ.get("SWE_EPHE_PATH", "")
if _EPHE_PATH:
    swe.set_ephe_path(_EPHE_PATH)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def degree_to_sign(longitude: float) -> tuple[str, float]:
    """Convert a 0-360 sidereal longitude to (sign_name, degrees_within_sign)."""
    longitude = longitude % 360
    sign_idx = int(longitude // 30)
    deg_in_sign = longitude - sign_idx * 30
    return SIGNS[sign_idx], deg_in_sign


def format_degree(deg: float) -> str:
    """Format degrees as DD°MM'SS"."""
    d = int(deg)
    m_full = (deg - d) * 60
    m = int(m_full)
    s = int((m_full - m) * 60)
    return f"{d}°{m:02d}'{s:02d}\""


def longitude_to_nakshatra(longitude: float) -> dict:
    """Map a sidereal longitude (Moon's, typically) to its Nakshatra + pada."""
    longitude = longitude % 360
    nak_idx = int(longitude // (360 / 27))
    nak_deg = longitude - nak_idx * (360 / 27)
    pada = int(nak_deg // (360 / 27 / 4)) + 1
    name, lord, deity, symbol, theme = NAKSHATRAS[nak_idx]
    return {
        "name": name,
        "lord": lord,
        "pada": pada,
        "deity": deity,
        "symbol": symbol,
        "classical_theme": theme,
        "index": nak_idx,
        "degree_in_nakshatra": nak_deg,
    }


def resolve_place(place: str) -> tuple[float, float, str]:
    """Resolve a place string to (lat, lon, tz_name)."""
    if not _GEO_AVAILABLE:
        raise HTTPException(
            status_code=400,
            detail="Geocoding not available. Install geopy + timezonefinder, "
                   "or pass lat/lon/tz directly in the request."
        )
    geolocator = Nominatim(user_agent="vedavision-celestial-noir", timeout=8)
    location = geolocator.geocode(place, timeout=8)
    if not location:
        raise HTTPException(status_code=400, detail=f"Could not geocode: {place}")
    tf = TimezoneFinder()
    tz_name = tf.timezone_at(lat=location.latitude, lng=location.longitude)
    return location.latitude, location.longitude, tz_name or "UTC"


def datetime_to_jd_ut(dt_local: datetime, tz_name: str) -> float:
    """Convert a local datetime + timezone name to Julian Day UT."""
    if _GEO_AVAILABLE:
        tz = pytz.timezone(tz_name)
        dt_aware = tz.localize(dt_local) if dt_local.tzinfo is None else dt_local
        dt_utc = dt_aware.astimezone(pytz.UTC)
    else:
        dt_utc = dt_local.replace(tzinfo=timezone.utc)

    return swe.julday(
        dt_utc.year, dt_utc.month, dt_utc.day,
        dt_utc.hour + dt_utc.minute / 60 + dt_utc.second / 3600
    )


def get_dignity(planet: str, sign: str) -> str:
    """Return the dignity label for a planet in a given sign."""
    if planet in EXALTATION_SIGNS and EXALTATION_SIGNS[planet] == sign:
        return "Exalted"
    if planet in DEBILITATION_SIGNS and DEBILITATION_SIGNS[planet] == sign:
        return "Debilitated"
    if planet in OWN_SIGNS and sign in OWN_SIGNS[planet]:
        return "Own Sign"
    return "Neutral/Friendly"


# ---------------------------------------------------------------------------
# Core chart calculation (unchanged from vedic-chart-explorer)
# ---------------------------------------------------------------------------

def calculate_planets(jd_ut: float, ayanamsa_key: str = "Lahiri") -> dict[str, dict]:
    """Calculate sidereal positions of all nine grahas."""
    swe.set_sid_mode(AYANAMSAS[ayanamsa_key], 0, 0)
    flags = swe.FLG_SIDEREAL | swe.FLG_SPEED

    positions = {}
    for name, planet_id in PLANETS.items():
        result, _ = swe.calc_ut(jd_ut, planet_id, flags)
        lon = result[0] % 360
        sign, deg_in_sign = degree_to_sign(lon)
        positions[name] = {
            "longitude": lon,
            "sign": sign,
            "degree_in_sign": deg_in_sign,
            "degree_str": format_degree(deg_in_sign),
            "retrograde": result[3] < 0,
        }

    # Ketu = Rahu + 180°
    rahu_lon = positions["Rahu"]["longitude"]
    ketu_lon = (rahu_lon + 180) % 360
    ketu_sign, ketu_deg = degree_to_sign(ketu_lon)
    positions["Ketu"] = {
        "longitude": ketu_lon,
        "sign": ketu_sign,
        "degree_in_sign": ketu_deg,
        "degree_str": format_degree(ketu_deg),
        "retrograde": True,
    }

    return positions


def calculate_lagna(jd_ut: float, lat: float, lon: float, ayanamsa_key: str = "Lahiri") -> dict:
    """Calculate the Ascendant (Lagna) — sidereal."""
    swe.set_sid_mode(AYANAMSAS[ayanamsa_key], 0, 0)
    houses, ascmc = swe.houses_ex(jd_ut, lat, lon, b'E', swe.FLG_SIDEREAL)
    asc_lon = ascmc[0] % 360
    sign, deg = degree_to_sign(asc_lon)
    return {
        "longitude": asc_lon,
        "sign": sign,
        "degree_in_sign": deg,
        "degree_str": format_degree(deg),
    }


def build_d1_houses(lagna_sign: str, planet_positions: dict) -> list[dict]:
    """Build the twelve D1 houses using Whole Sign system."""
    lagna_idx = SIGNS.index(lagna_sign)
    houses = []
    for i in range(12):
        sign = SIGNS[(lagna_idx + i) % 12]
        planets_here = [
            PLANET_ABBR[name] for name, pos in planet_positions.items()
            if pos["sign"] == sign
        ]
        houses.append({
            "num": i + 1,
            "sign": sign,
            "planets": planets_here,
        })
    return houses


def build_d10_houses(planet_positions: dict, lagna_long: float) -> list[dict]:
    """Build the D10 (Dashamsha) divisional chart."""
    def d10_sign_for(longitude: float) -> str:
        sign_idx = int(longitude // 30)
        deg_in_sign = longitude - sign_idx * 30
        part_idx = int(deg_in_sign // 3)  # 0..9
        modality = sign_idx % 3  # 0=movable, 1=fixed, 2=dual
        start_offset = {0: 0, 1: 8, 2: 4}[modality]
        d10_sign_idx = (sign_idx + start_offset + part_idx) % 12
        return SIGNS[d10_sign_idx]

    d10_lagna_sign = d10_sign_for(lagna_long)
    d10_lagna_idx = SIGNS.index(d10_lagna_sign)

    planet_d10_signs = {
        name: d10_sign_for(pos["longitude"])
        for name, pos in planet_positions.items()
    }

    houses = []
    for i in range(12):
        sign = SIGNS[(d10_lagna_idx + i) % 12]
        planets_here = [
            PLANET_ABBR[name] for name, ps in planet_d10_signs.items()
            if ps == sign
        ]
        houses.append({
            "num": i + 1,
            "sign": sign,
            "planets": planets_here,
        })
    return houses


def calculate_karakas(planet_positions: dict, d1_houses: list[dict]) -> dict:
    """Rank the seven karaka planets by degree within their sign (Jaimini)."""
    sign_to_house = {h["sign"]: h["num"] for h in d1_houses}

    karaka_inputs = []
    for name in KARAKA_PLANETS:
        pos = planet_positions[name]
        if name == "Rahu":
            deg = 30 - pos["degree_in_sign"]
        else:
            deg = pos["degree_in_sign"]
        karaka_inputs.append((name, deg, pos))

    karaka_inputs.sort(key=lambda x: -x[1])

    karakas = {}
    for (role_key, _label), (name, deg, pos) in zip(KARAKA_ROLES, karaka_inputs):
        karakas[role_key] = {
            "planet": PLANET_ABBR[name],
            "planet_name": name,
            "sign": pos["sign"],
            "house": sign_to_house.get(pos["sign"], 0),
            "degree": format_degree(deg if name != "Rahu" else 30 - deg),
        }
    return karakas


def calculate_vimshottari(moon_longitude: float, birth_jd_ut: float) -> dict:
    """Calculate current Vimshottari Mahadasha and Antardasha."""
    nak = longitude_to_nakshatra(moon_longitude)
    nak_size = 360 / 27
    portion_done = nak["degree_in_nakshatra"] / nak_size
    portion_remaining = 1 - portion_done

    nak_lord = nak["lord"]
    start_idx = next(i for i, (lord, _) in enumerate(VIMSHOTTARI_SEQ) if lord == nak_lord)

    current_jd = birth_jd_ut
    full_years = VIMSHOTTARI_SEQ[start_idx][1]
    remaining_years_first = full_years * portion_remaining
    today_jd = swe.julday(*_now_ut_components())

    dashas = []
    end_jd = current_jd + remaining_years_first * 365.25
    dashas.append({
        "lord": nak_lord,
        "start_jd": current_jd,
        "end_jd": end_jd,
        "years": remaining_years_first,
    })
    current_jd = end_jd

    seq_idx = (start_idx + 1) % len(VIMSHOTTARI_SEQ)
    for _ in range(len(VIMSHOTTARI_SEQ) + 2):
        lord, years = VIMSHOTTARI_SEQ[seq_idx]
        end_jd = current_jd + years * 365.25
        dashas.append({
            "lord": lord,
            "start_jd": current_jd,
            "end_jd": end_jd,
            "years": years,
        })
        current_jd = end_jd
        seq_idx = (seq_idx + 1) % len(VIMSHOTTARI_SEQ)
        if current_jd > today_jd + 365 * 20:
            break

    active_maha = next(d for d in dashas if d["start_jd"] <= today_jd < d["end_jd"])

    maha_lord = active_maha["lord"]
    maha_start_idx = next(i for i, (lord, _) in enumerate(VIMSHOTTARI_SEQ) if lord == maha_lord)
    maha_years_full = VIMSHOTTARI_SEQ[maha_start_idx][1]
    antar_start_jd = active_maha["start_jd"]
    active_antar = None
    for offset in range(len(VIMSHOTTARI_SEQ)):
        sub_idx = (maha_start_idx + offset) % len(VIMSHOTTARI_SEQ)
        sub_lord, sub_years_full = VIMSHOTTARI_SEQ[sub_idx]
        antar_duration_years = (sub_years_full * maha_years_full) / VIMSHOTTARI_TOTAL
        antar_end_jd = antar_start_jd + antar_duration_years * 365.25
        if offset == 0 and active_maha is dashas[0]:
            antar_duration_years *= portion_remaining
            antar_end_jd = antar_start_jd + antar_duration_years * 365.25
        if antar_start_jd <= today_jd < antar_end_jd:
            active_antar = {
                "lord": sub_lord,
                "start_jd": antar_start_jd,
                "end_jd": antar_end_jd,
            }
            break
        antar_start_jd = antar_end_jd

    return {
        "current_maha": {
            "lord": active_maha["lord"],
            "start": _jd_to_date_str(active_maha["start_jd"]),
            "end": _jd_to_date_str(active_maha["end_jd"]),
        },
        "current_antar": {
            "lord": active_antar["lord"] if active_antar else "Unknown",
            "start": _jd_to_date_str(active_antar["start_jd"]) if active_antar else "",
            "end": _jd_to_date_str(active_antar["end_jd"]) if active_antar else "",
        },
        "sequence": [
            {"lord": lord, "years": years, "active": lord == active_maha["lord"]}
            for lord, years in VIMSHOTTARI_SEQ
        ],
    }


def _now_ut_components() -> tuple[int, int, int, float]:
    """Return current UT as (year, month, day, hour_float) for swe.julday."""
    now = datetime.now(timezone.utc)
    return now.year, now.month, now.day, now.hour + now.minute / 60 + now.second / 3600


def _jd_to_date_str(jd: float) -> str:
    """Convert Julian Day to 'Mon YYYY' format."""
    y, m, d, _ = swe.revjul(jd)
    month_names = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return f"{month_names[m]} {y}"


def calculate_bnn_transits(natal_positions: dict, d1_houses: list[dict]) -> list[dict]:
    """Identify the most significant current Bhrigu Nandi Nadi transit linkages."""
    today_jd = swe.julday(*_now_ut_components())
    current_positions = calculate_planets(today_jd, "Lahiri")

    sign_to_house = {h["sign"]: h["num"] for h in d1_houses}

    transits = []
    for transit_planet in ["Jupiter", "Saturn", "Rahu"]:
        cur = current_positions[transit_planet]
        transit_sign = cur["sign"]
        natal_house = sign_to_house.get(transit_sign, 0)

        natal_contacts = []
        for natal_name, natal_pos in natal_positions.items():
            if natal_pos["sign"] == transit_sign:
                separation = abs(cur["longitude"] - natal_pos["longitude"])
                if separation > 180:
                    separation = 360 - separation
                if separation <= 8:
                    natal_contacts.append(natal_name)

        house_themes = {
            1: "the self and bodily vitality",
            2: "resources, speech, and family wealth",
            3: "courage, communication, and the immediate circle",
            4: "home, mother, and the foundation of inner peace",
            5: "creativity, children, and the intelligence of play",
            6: "service, health, and the field of daily work",
            7: "partnership and the encounter with the other",
            8: "transformation and what lies beneath the surface",
            9: "dharma, the teacher, and higher learning",
            10: "vocation and public action",
            11: "gains, networks, and the company of equals",
            12: "loss, liberation, and what is left behind",
        }
        theme = f"Activation of {house_themes.get(natal_house, 'this area of the chart')}"
        if natal_contacts:
            theme += f", with particular weight on the themes of natal {natal_contacts[0]}"

        natal_contact_str = f"{natal_house}th house"
        if natal_contacts:
            natal_contact_str += f" — {natal_contacts[0]}"

        transits.append({
            "transit": transit_planet,
            "transitSign": transit_sign,
            "natalContact": natal_contact_str,
            "theme": theme,
        })

    return transits


# ---------------------------------------------------------------------------
# VedaVision response-mapping helpers
# ---------------------------------------------------------------------------

def compute_wealth_score(d1_houses: list[dict], planets: dict) -> dict:
    """Compute a simple wealth score (0-100) for the VedaVision dashboard."""
    house_map = {h["num"]: h for h in d1_houses}
    sign_to_house_num = {h["sign"]: h["num"] for h in d1_houses}

    score = 40  # base

    # Jupiter house bonus
    jup_house = sign_to_house_num.get(planets["Jupiter"]["sign"], 0)
    if jup_house == 11:
        score += 20
    elif jup_house == 2:
        score += 15
    elif jup_house == 5:
        score += 10

    # Venus house bonus
    ven_house = sign_to_house_num.get(planets["Venus"]["sign"], 0)
    if ven_house in (2, 11):
        score += 10

    # Dhana yoga: 2nd lord conjunct 11th lord (same sign)
    house_2_sign = house_map[2]["sign"]
    house_11_sign = house_map[11]["sign"]
    lord_2 = SIGN_LORDS[house_2_sign]
    lord_11 = SIGN_LORDS[house_11_sign]
    if lord_2 in planets and lord_11 in planets:
        if planets[lord_2]["sign"] == planets[lord_11]["sign"]:
            score += 15

    parashari = min(score, 100)
    bnn_bonus = min(
        sum(1 for t in ["Jupiter", "Saturn", "Rahu"]
            if sign_to_house_num.get(planets[t]["sign"], 0) in (2, 11)) * 5,
        15
    )
    total = min(parashari + bnn_bonus, 100)

    return {"total": total, "parashari": parashari, "bnn": bnn_bonus}


def compute_chart_strength(planets: dict) -> int:
    """Return 0-100 score based on count of exalted/own-sign planets."""
    strong = 0
    for name, pos in planets.items():
        if name in ("Rahu", "Ketu"):
            continue
        dignity = get_dignity(name, pos["sign"])
        if dignity in ("Exalted", "Own Sign"):
            strong += 1
    return min(strong * 12, 100)


def detect_yogas(planets: dict, d1_houses: list[dict]) -> list[dict]:
    """Detect classical Parashari yogas, returned as reflection patterns."""
    sign_to_house_num = {h["sign"]: h["num"] for h in d1_houses}
    yogas = []

    # Kendras: houses 1, 4, 7, 10
    kendra_houses = {1, 4, 7, 10}

    moon_house = sign_to_house_num.get(planets["Moon"]["sign"], 0)
    jup_house = sign_to_house_num.get(planets["Jupiter"]["sign"], 0)

    # Gaja Kesari: Jupiter in kendra from Moon
    if moon_house and jup_house:
        relative_house = ((jup_house - moon_house) % 12) + 1
        if relative_house in kendra_houses:
            yogas.append({
                "name": "Gaja Kesari",
                "formation": f"Jupiter in house {jup_house}, Moon in house {moon_house} — kendra relationship",
                "effect": "A pattern associated with intellectual prominence, generosity, and a life of growing impact."
            })

    # Budhaditya: Sun and Mercury in same sign
    if planets["Sun"]["sign"] == planets["Mercury"]["sign"]:
        yogas.append({
            "name": "Budhaditya",
            "formation": f"Sun and Mercury conjunct in {planets['Sun']['sign']}",
            "effect": "A pattern associated with intelligence, communication skill, and a sharp analytical mind."
        })

    # Hamsa: Jupiter in own or exalted sign and in a kendra
    jup_dignity = get_dignity("Jupiter", planets["Jupiter"]["sign"])
    if jup_dignity in ("Exalted", "Own Sign") and jup_house in kendra_houses:
        yogas.append({
            "name": "Hamsa",
            "formation": f"Jupiter {jup_dignity.lower()} in {planets['Jupiter']['sign']} (house {jup_house})",
            "effect": "A pattern associated with wisdom, ethical conduct, and enduring reputation."
        })

    # Malavya: Venus in own or exalted sign and in a kendra
    ven_house = sign_to_house_num.get(planets["Venus"]["sign"], 0)
    ven_dignity = get_dignity("Venus", planets["Venus"]["sign"])
    if ven_dignity in ("Exalted", "Own Sign") and ven_house in kendra_houses:
        yogas.append({
            "name": "Malavya",
            "formation": f"Venus {ven_dignity.lower()} in {planets['Venus']['sign']} (house {ven_house})",
            "effect": "A pattern associated with aesthetic refinement, material ease, and sensory intelligence."
        })

    return yogas


def build_planet_table(planets: dict, d1_houses: list[dict]) -> list[dict]:
    """Build the planetTable array for the VedaVision contract."""
    sign_to_house_num = {h["sign"]: h["num"] for h in d1_houses}
    table = []
    for name in ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu"]:
        pos = planets[name]
        dignity = get_dignity(name, pos["sign"]) if name not in ("Rahu", "Ketu") else "—"
        notes = pos["degree_str"]
        if pos.get("retrograde") and name not in ("Rahu", "Ketu"):
            notes += " ℞"
        table.append({
            "planet": name,
            "skt": PLANET_SKT[name],
            "glyph": PLANET_GLYPHS[name],
            "sign": pos["sign"],
            "house": sign_to_house_num.get(pos["sign"], 0),
            "dignity": dignity,
            "color": PLANET_COLORS[name],
            "notes": notes,
        })
    return table


def map_to_vedavision_contract(
    req_name: str,
    req_dob: str,
    req_tob: str,
    req_pob: str,
    planets: dict,
    lagna: dict,
    d1_houses: list[dict],
    d10_houses: list[dict],
    nak: dict,
    karakas: dict,
    dasha_raw: dict,
    bnn: list[dict],
) -> dict:
    """Map all computed data to the VedaVision SAMPLE_CHART data contract shape."""

    # lagna block
    lagna_sign = lagna["sign"]
    lagna_block = {
        "sign": lagna_sign,
        "signEn": lagna_sign,
        "lord": SIGN_LORDS[lagna_sign],
        "degree": lagna["degree_str"],
    }

    # moonSign / sunSign
    moon_sign = planets["Moon"]["sign"]
    sun_sign = planets["Sun"]["sign"]

    # nakshatra block (adds theme alias)
    nak_block = {
        "name": nak["name"],
        "pada": nak["pada"],
        "lord": nak["lord"],
        "deity": nak["deity"],
        "symbol": nak["symbol"],
        "theme": nak["classical_theme"],
    }

    # houses — add id and short
    houses_out = []
    for h in d1_houses:
        houses_out.append({
            "id": h["num"],
            "sign": h["sign"],
            "short": h["sign"][:3],
            "planets": h["planets"],
        })

    d10_out = []
    for h in d10_houses:
        d10_out.append({
            "id": h["num"],
            "sign": h["sign"],
            "short": h["sign"][:3],
            "planets": h["planets"],
        })

    # dasha — map to contract shape with skt names
    current_block = {
        "planet": dasha_raw["current_maha"]["lord"],
        "skt": PLANET_SKT.get(dasha_raw["current_maha"]["lord"], dasha_raw["current_maha"]["lord"]),
        "start": dasha_raw["current_maha"]["start"],
        "end": dasha_raw["current_maha"]["end"],
    }
    antar_block = {
        "planet": dasha_raw["current_antar"]["lord"],
        "skt": PLANET_SKT.get(dasha_raw["current_antar"]["lord"], dasha_raw["current_antar"]["lord"]),
        "start": dasha_raw["current_antar"]["start"],
        "end": dasha_raw["current_antar"]["end"],
    }

    # AK / AmK for quick access
    ak_planet = karakas.get("atmakaraka", {}).get("planet_name", "")
    amk_planet = karakas.get("amatyakaraka", {}).get("planet_name", "")

    # derived fields
    wealth_score = compute_wealth_score(d1_houses, planets)
    chart_strength = compute_chart_strength(planets)
    yogas = detect_yogas(planets, d1_houses)
    planet_table = build_planet_table(planets, d1_houses)
    leadership_type = LEADERSHIP_MAP.get(ak_planet, "Founder")

    return {
        "native": {
            "name": req_name,
            "dob": req_dob,
            "tob": req_tob,
            "pob": req_pob,
        },
        "lagna": lagna_block,
        "moonSign": {"sign": moon_sign, "signEn": moon_sign},
        "sunSign": {"sign": sun_sign, "signEn": sun_sign},
        "nakshatra": nak_block,
        "houses": houses_out,
        "d10Houses": d10_out,
        "karakas": karakas,
        "dasha": {
            "current": current_block,
            "antardasha": antar_block,
        },
        "planetTable": planet_table,
        "wealthScore": wealth_score,
        "chartStrength": chart_strength,
        "yogas": yogas,
        "bnnTransits": bnn,
        "ak": ak_planet,
        "amk": amk_planet,
        "leadershipType": leadership_type,
    }


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

app = FastAPI(
    title="VedaVision — Celestial Noir API",
    description="Sidereal natal chart calculations using Swiss Ephemeris. Reflection, not prediction.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://vedavision-frontend.rishav414.workers.dev",
        "https://vedavision.pages.dev",
        "https://vedvision.pages.dev",
        "https://vedavision-frontend.pages.dev",
        "http://127.0.0.1:5500",
        "http://localhost:5500",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChartRequest(BaseModel):
    name: str = Field(default="Native")
    dob: str = Field(description="Birth date in YYYY-MM-DD format")
    tob: str = Field(description="Birth time in HH:MM (24-hour) format")
    pob: Optional[str] = Field(default=None, description="Place name — used if lat/lon not provided")
    lat: Optional[float] = Field(default=None)
    lon: Optional[float] = Field(default=None)
    tz: Optional[str] = Field(default=None, description="IANA timezone name, e.g. 'Asia/Kolkata'")
    ayanamsa: str = Field(default="Lahiri")
    approxTime: bool = Field(default=False)


@app.get("/health")
def health():
    return {"status": "ok", "version": "1.0"}


@app.get("/")
def root():
    return {
        "name": "VedaVision Celestial Noir API",
        "version": "1.0.0",
        "endpoints": ["/chart", "/health"],
        "docs": "/docs",
    }


@app.post("/chart")
def generate_chart(req: ChartRequest):
    """Generate a complete Vedic chart from birth data."""
    # Resolve location
    if req.lat is not None and req.lon is not None and req.tz is not None:
        lat, lon, tz_name = req.lat, req.lon, req.tz
    elif req.pob:
        lat, lon, tz_name = resolve_place(req.pob)
    else:
        raise HTTPException(
            status_code=400,
            detail="Provide either (pob) OR (lat, lon, tz)."
        )

    # Parse birth datetime
    try:
        dt_local = datetime.strptime(f"{req.dob} {req.tob}", "%Y-%m-%d %H:%M")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid date/time format: {e}")

    # Convert to JD UT
    jd_ut = datetime_to_jd_ut(dt_local, tz_name)

    # Compute everything
    planets = calculate_planets(jd_ut, req.ayanamsa)
    lagna = calculate_lagna(jd_ut, lat, lon, req.ayanamsa)
    d1_houses = build_d1_houses(lagna["sign"], planets)
    d10_houses = build_d10_houses(planets, lagna["longitude"])
    moon_long = planets["Moon"]["longitude"]
    nak = longitude_to_nakshatra(moon_long)
    karakas = calculate_karakas(planets, d1_houses)
    dasha_raw = calculate_vimshottari(moon_long, jd_ut)
    bnn = calculate_bnn_transits(planets, d1_houses)

    pob_str = req.pob or f"{lat:.4f}, {lon:.4f}"

    return map_to_vedavision_contract(
        req_name=req.name,
        req_dob=req.dob,
        req_tob=req.tob,
        req_pob=pob_str,
        planets=planets,
        lagna=lagna,
        d1_houses=d1_houses,
        d10_houses=d10_houses,
        nak=nak,
        karakas=karakas,
        dasha_raw=dasha_raw,
        bnn=bnn,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
