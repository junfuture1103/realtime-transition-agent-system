from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta
from typing import Any


CATEGORIES = [
    "grocery_pos",
    "gas_transport",
    "shopping_net",
    "shopping_pos",
    "misc_net",
    "misc_pos",
    "entertainment",
    "food_dining",
    "health_fitness",
    "home",
    "kids_pets",
    "personal_care",
    "travel",
]
RISKY_CATEGORIES = ["shopping_net", "misc_net", "travel"]
MERCHANTS = [
    "fraud_Kilback LLC",
    "fraud_Rau and Sons",
    "fraud_Berge LLC",
    "fraud_Hackett Group",
    "fraud_Bahringer Group",
    "fraud_Goyette Inc",
]
JOBS = ["Engineer", "Teacher", "Nurse", "Sales", "Driver", "Developer", "Designer", "Accountant", "Student", "Retired"]
CITIES = [
    ("Birmingham", "AL", 35203, 33.5207, -86.8025, 212237),
    ("Phoenix", "AZ", 85004, 33.4484, -112.0740, 1608139),
    ("San Jose", "CA", 95113, 37.3382, -121.8863, 971233),
    ("Denver", "CO", 80202, 39.7392, -104.9903, 715522),
    ("Miami", "FL", 33130, 25.7617, -80.1918, 442241),
    ("Columbus", "OH", 43215, 39.9612, -82.9988, 905748),
    ("Portland", "OR", 97204, 45.5152, -122.6784, 652503),
    ("Dallas", "TX", 75201, 32.7767, -96.7970, 1304379),
    ("Austin", "TX", 78701, 30.2672, -97.7431, 974447),
    ("Seattle", "WA", 98101, 47.6062, -122.3321, 737015),
]


def generate_transaction(rng: random.Random, fraud: bool | None = None) -> tuple[dict[str, Any], int]:
    if fraud is None:
        fraud = rng.random() < 0.08

    city, state, zip_code, lat, long, city_pop = rng.choice(CITIES)
    base_time = datetime(2020, 6, 21, 0, 0, 0) + timedelta(minutes=rng.randint(0, 525_600))
    if fraud:
        category = rng.choice(RISKY_CATEGORIES + ["gas_transport", "shopping_pos"])
        amount = round(rng.lognormvariate(5.85, 0.8), 2)
        amount = max(65.0, min(amount, 3500.0))
        hour = rng.choice([0, 1, 2, 3, 4, 23, rng.randint(8, 22)])
        trans_time = base_time.replace(hour=hour, minute=rng.randint(0, 59), second=rng.randint(0, 59))
        distance = rng.uniform(280, 1800)
    else:
        category = rng.choice([item for item in CATEGORIES if item not in {"misc_net", "travel"}])
        amount = round(rng.lognormvariate(3.55, 0.65), 2)
        amount = max(1.0, min(amount, 650.0))
        trans_time = base_time.replace(hour=rng.randint(7, 22), minute=rng.randint(0, 59), second=rng.randint(0, 59))
        distance = rng.uniform(1, 140)

    merch_lat, merch_long = _offset_location(lat, long, distance, rng)
    old_balance = round(rng.uniform(250, 9000), 2)
    new_balance = max(0, round(old_balance - amount, 2))
    cc_num = str(4_000_000_000_000_000 + rng.randint(10_000_000_000, 9_999_999_999_999))
    trans_num = hashlib.md5(f"{cc_num}-{trans_time.isoformat()}-{amount}".encode()).hexdigest()
    payload = {
        "trans_date_trans_time": trans_time.strftime("%Y-%m-%d %H:%M:%S"),
        "cc_num": cc_num,
        "merchant": rng.choice(MERCHANTS),
        "category": category,
        "amt": amount,
        "gender": rng.choice(["F", "M"]),
        "city": city,
        "state": state,
        "zip": zip_code,
        "lat": round(lat + rng.uniform(-0.04, 0.04), 6),
        "long": round(long + rng.uniform(-0.04, 0.04), 6),
        "city_pop": city_pop,
        "job": rng.choice(JOBS),
        "dob": _random_dob(rng),
        "trans_num": trans_num,
        "unix_time": int(trans_time.timestamp()),
        "merch_lat": round(merch_lat, 6),
        "merch_long": round(merch_long, 6),
        "old_balance": old_balance,
        "new_balance": new_balance,
        "is_fraud": bool(fraud),
    }
    return payload, int(fraud)


def generate_seed_dataset(size: int = 420, fraud_rate: float = 0.12) -> list[dict[str, Any]]:
    rng = random.Random(20260515)
    rows = []
    for _ in range(size):
        payload, label = generate_transaction(rng, fraud=rng.random() < fraud_rate)
        rows.append({"payload": payload, "label": label, "label_source": "seed_kaggle_style_synthetic"})
    return rows


def generate_batch(count: int, fraud_rate: float) -> list[dict[str, Any]]:
    rng = random.Random()
    count = max(1, min(count, 250))
    fraud_rate = max(0, min(float(fraud_rate), 1))
    result = []
    for _ in range(count):
        payload, label = generate_transaction(rng, fraud=rng.random() < fraud_rate)
        result.append({"payload": payload, "label": label, "label_source": "simulator_ground_truth"})
    return result


def _offset_location(lat: float, long: float, distance_km: float, rng: random.Random) -> tuple[float, float]:
    bearing = rng.uniform(0, 360)
    delta_lat = (distance_km / 111.0) * math_cos(bearing)
    denominator = max(20.0, 111.0 * abs(math_cos(lat)))
    delta_long = (distance_km / denominator) * math_sin(bearing)
    return max(-89.9, min(89.9, lat + delta_lat)), max(-179.9, min(179.9, long + delta_long))


def math_sin(degrees: float) -> float:
    import math

    return math.sin(math.radians(degrees))


def math_cos(degrees: float) -> float:
    import math

    return math.cos(math.radians(degrees))


def _random_dob(rng: random.Random) -> str:
    year = rng.randint(1945, 2002)
    month = rng.randint(1, 12)
    day = rng.randint(1, 28)
    return f"{year:04d}-{month:02d}-{day:02d}"
