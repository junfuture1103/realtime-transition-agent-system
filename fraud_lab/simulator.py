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
CATEGORY_AMOUNT_MEDIANS = {
    "grocery_pos": 48,
    "gas_transport": 38,
    "shopping_net": 92,
    "shopping_pos": 76,
    "misc_net": 110,
    "misc_pos": 52,
    "entertainment": 64,
    "food_dining": 34,
    "health_fitness": 58,
    "home": 86,
    "kids_pets": 44,
    "personal_care": 29,
    "travel": 260,
}
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
CUSTOMER_PROFILES = []


def build_customer_profiles(size: int = 80, seed: int = 20260519) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    profiles = []
    for index in range(max(1, size)):
        city, state, zip_code, lat, long, city_pop = rng.choice(CITIES)
        normal_categories = rng.sample(CATEGORIES, k=rng.randint(4, 7))
        profiles.append(
            {
                "cc_num": str(4_000_000_000_000_000 + index * 10_000_000_000 + rng.randint(100_000, 999_999)),
                "gender": rng.choice(["F", "M"]),
                "city": city,
                "state": state,
                "zip": zip_code,
                "lat": lat,
                "long": long,
                "city_pop": city_pop,
                "job": rng.choice(JOBS),
                "dob": _random_dob(rng),
                "balance_mean": rng.uniform(900, 12000),
                "normal_categories": normal_categories,
                "preferred_merchants": rng.sample(MERCHANTS, k=rng.randint(2, min(4, len(MERCHANTS)))),
                "frequency_weight": rng.choices([1, 2, 3, 5, 8, 13], weights=[42, 24, 16, 10, 6, 2], k=1)[0],
                "online_bias": rng.random(),
                "night_owl": rng.random() < 0.16,
            }
        )
    return profiles


def generate_transaction(rng: random.Random, fraud: bool | None = None) -> tuple[dict[str, Any], int]:
    if fraud is None:
        fraud = rng.random() < 0.08

    profile = rng.choice(CUSTOMER_PROFILES)
    base_time = datetime(2020, 6, 21, 0, 0, 0) + timedelta(minutes=rng.randint(0, 525_600))
    return generate_transaction_for_profile(rng, profile, base_time, fraud=fraud, preserve_time=False)


def generate_transaction_for_profile(
    rng: random.Random,
    profile: dict[str, Any],
    trans_time: datetime,
    fraud: bool | None = None,
    preserve_time: bool = True,
) -> tuple[dict[str, Any], int]:
    if fraud is None:
        fraud = rng.random() < 0.08

    city = profile["city"]
    state = profile["state"]
    zip_code = profile["zip"]
    lat = float(profile["lat"])
    long = float(profile["long"])
    city_pop = profile["city_pop"]
    if fraud:
        attack_style = rng.choices(
            ["card_not_present", "geo_jump", "low_and_slow", "merchant_mimicry"],
            weights=[0.34, 0.24, 0.26, 0.16],
            k=1,
        )[0]
        if attack_style == "low_and_slow":
            category = rng.choice(profile["normal_categories"])
            median = CATEGORY_AMOUNT_MEDIANS[category] * rng.uniform(0.8, 2.4)
            amount = round(rng.lognormvariate(math_log(median), 0.52), 2)
            amount = max(8.0, min(amount, 720.0))
            hour = rng.choice([rng.randint(8, 22), 23, 0, 1])
            distance = rng.uniform(15, 260)
        elif attack_style == "merchant_mimicry":
            category = rng.choice(["grocery_pos", "gas_transport", "shopping_pos", "food_dining"])
            median = CATEGORY_AMOUNT_MEDIANS[category] * rng.uniform(1.2, 3.5)
            amount = round(rng.lognormvariate(math_log(median), 0.6), 2)
            amount = max(18.0, min(amount, 950.0))
            hour = rng.choice([rng.randint(7, 22), 2, 3, 4])
            distance = rng.uniform(30, 420)
        elif attack_style == "geo_jump":
            category = rng.choice(RISKY_CATEGORIES + ["shopping_pos", "gas_transport"])
            median = CATEGORY_AMOUNT_MEDIANS[category] * rng.uniform(1.6, 5.0)
            amount = round(rng.lognormvariate(math_log(median), 0.68), 2)
            amount = max(45.0, min(amount, 2200.0))
            hour = rng.choice([0, 1, 2, 3, 4, 23, rng.randint(8, 22)])
            distance = rng.uniform(240, 1800)
        else:
            category = rng.choice(RISKY_CATEGORIES + ["gas_transport", "shopping_pos"])
            median = CATEGORY_AMOUNT_MEDIANS[category] * rng.uniform(2.0, 7.0)
            amount = round(rng.lognormvariate(math_log(median), 0.72), 2)
            amount = max(55.0, min(amount, 3200.0))
            hour = rng.choice([0, 1, 2, 3, 4, 23, rng.randint(8, 22)])
            distance = rng.uniform(80, 1100)
        if not preserve_time:
            trans_time = trans_time.replace(hour=hour, minute=rng.randint(0, 59), second=rng.randint(0, 59))
    else:
        unusual_but_legit = rng.random() < 0.09
        category = rng.choice(RISKY_CATEGORIES + ["shopping_pos"]) if unusual_but_legit else rng.choice(profile["normal_categories"])
        median = CATEGORY_AMOUNT_MEDIANS[category]
        if unusual_but_legit:
            amount = round(rng.lognormvariate(math_log(median * rng.uniform(1.4, 4.2)), 0.7), 2)
            amount = max(12.0, min(amount, 1800.0))
            hour = rng.choice([rng.randint(7, 23), 0, 1])
            distance = rng.uniform(90, 850)
        else:
            amount = round(rng.lognormvariate(math_log(median), 0.5), 2)
            amount = max(1.0, min(amount, 720.0))
            hour = rng.randint(7, 22)
            distance = rng.uniform(1, 170)
        if not preserve_time:
            trans_time = trans_time.replace(hour=hour, minute=rng.randint(0, 59), second=rng.randint(0, 59))

    merch_lat, merch_long = _offset_location(lat, long, distance, rng)
    old_balance = round(max(50, rng.gauss(float(profile["balance_mean"]), float(profile["balance_mean"]) * 0.25)), 2)
    new_balance = max(0, round(old_balance - amount, 2))
    cc_num = profile["cc_num"]
    trans_num = hashlib.md5(f"{cc_num}-{trans_time.isoformat()}-{amount}".encode()).hexdigest()
    payload = {
        "trans_date_trans_time": trans_time.strftime("%Y-%m-%d %H:%M:%S"),
        "cc_num": cc_num,
        "merchant": rng.choice(profile.get("preferred_merchants") or MERCHANTS),
        "category": category,
        "amt": amount,
        "gender": profile["gender"],
        "city": city,
        "state": state,
        "zip": zip_code,
        "lat": round(lat + rng.uniform(-0.04, 0.04), 6),
        "long": round(long + rng.uniform(-0.04, 0.04), 6),
        "city_pop": city_pop,
        "job": profile["job"],
        "dob": profile["dob"],
        "trans_num": trans_num,
        "unix_time": int(trans_time.timestamp()),
        "merch_lat": round(merch_lat, 6),
        "merch_long": round(merch_long, 6),
        "old_balance": old_balance,
        "new_balance": new_balance,
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
        payload, _label = generate_transaction(rng, fraud=rng.random() < fraud_rate)
        result.append({"payload": payload})
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


def math_log(value: float) -> float:
    import math

    return math.log(max(value, 1.0))


def _random_dob(rng: random.Random) -> str:
    year = rng.randint(1945, 2002)
    month = rng.randint(1, 12)
    day = rng.randint(1, 28)
    return f"{year:04d}-{month:02d}-{day:02d}"


CUSTOMER_PROFILES = build_customer_profiles()
