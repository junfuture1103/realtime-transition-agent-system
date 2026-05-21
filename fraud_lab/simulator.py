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
BASE_CATEGORY_WEIGHTS = {
    "grocery_pos": 1.35,
    "gas_transport": 1.12,
    "shopping_net": 0.72,
    "shopping_pos": 0.95,
    "misc_net": 0.42,
    "misc_pos": 0.7,
    "entertainment": 0.62,
    "food_dining": 1.18,
    "health_fitness": 0.52,
    "home": 0.5,
    "kids_pets": 0.44,
    "personal_care": 0.58,
    "travel": 0.28,
}
RISKY_CATEGORIES = ["shopping_net", "misc_net", "travel", "shopping_pos"]
CATEGORY_AMOUNT_PROFILES = {
    "grocery_pos": {"median": 46, "sigma": 0.43, "min": 1.8, "max": 520, "tail": 0.025, "tail_mult": (1.9, 5.0)},
    "gas_transport": {"median": 39, "sigma": 0.38, "min": 4.0, "max": 360, "tail": 0.018, "tail_mult": (1.8, 4.5)},
    "shopping_net": {"median": 94, "sigma": 0.72, "min": 3.5, "max": 4200, "tail": 0.105, "tail_mult": (2.0, 8.0)},
    "shopping_pos": {"median": 78, "sigma": 0.58, "min": 2.5, "max": 2800, "tail": 0.055, "tail_mult": (2.0, 6.0)},
    "misc_net": {"median": 112, "sigma": 0.76, "min": 1.0, "max": 3800, "tail": 0.12, "tail_mult": (2.2, 9.0)},
    "misc_pos": {"median": 52, "sigma": 0.55, "min": 2.0, "max": 1600, "tail": 0.04, "tail_mult": (1.9, 5.5)},
    "entertainment": {"median": 64, "sigma": 0.58, "min": 3.0, "max": 1400, "tail": 0.045, "tail_mult": (1.8, 5.5)},
    "food_dining": {"median": 34, "sigma": 0.46, "min": 2.0, "max": 720, "tail": 0.025, "tail_mult": (1.8, 4.8)},
    "health_fitness": {"median": 58, "sigma": 0.54, "min": 3.0, "max": 1900, "tail": 0.035, "tail_mult": (2.0, 5.6)},
    "home": {"median": 88, "sigma": 0.72, "min": 4.0, "max": 5600, "tail": 0.085, "tail_mult": (2.2, 7.5)},
    "kids_pets": {"median": 44, "sigma": 0.5, "min": 2.0, "max": 1300, "tail": 0.032, "tail_mult": (1.8, 5.0)},
    "personal_care": {"median": 30, "sigma": 0.45, "min": 1.5, "max": 620, "tail": 0.022, "tail_mult": (1.8, 4.2)},
    "travel": {"median": 270, "sigma": 0.88, "min": 8.0, "max": 9500, "tail": 0.15, "tail_mult": (2.0, 9.5)},
}
CATEGORY_AMOUNT_MEDIANS = {
    category: int(profile["median"]) for category, profile in CATEGORY_AMOUNT_PROFILES.items()
}
CATEGORY_MERCHANTS = {
    "grocery_pos": [
        "fraud_Kilback LLC",
        "fraud_FreshCart Market",
        "fraud_GreenValley Foods",
        "fraud_Neighborhood Grocers",
        "fraud_Orchard Basket",
        "fraud_Riverbend Market",
        "fraud_Corner Pantry",
        "fraud_Sunrise Provisions",
    ],
    "gas_transport": [
        "fraud_Rau and Sons",
        "fraud_MetroFuel Stop",
        "fraud_Interstate Petro",
        "fraud_Liberty Gas",
        "fraud_QuickMile Fuel",
        "fraud_Northstar Service",
        "fraud_Highway Express Gas",
        "fraud_Bayfront AutoFuel",
    ],
    "shopping_net": [
        "fraud_Berge LLC",
        "fraud_DigitalCart Hub",
        "fraud_NovaDirect Online",
        "fraud_ApexOutlet Net",
        "fraud_ParcelTree Shop",
        "fraud_CloudShelf Retail",
        "fraud_LumenMarket Online",
        "fraud_EverCart Global",
    ],
    "shopping_pos": [
        "fraud_Hackett Group",
        "fraud_UrbanStyle Retail",
        "fraud_Maple Street Apparel",
        "fraud_SilverLine Goods",
        "fraud_TownSquare Electronics",
        "fraud_Cedar Home Store",
        "fraud_Ridgeview Outlet",
        "fraud_Harbor Mall Co",
    ],
    "misc_net": [
        "fraud_Bahringer Group",
        "fraud_VaultPay Digital",
        "fraud_PlayForge Online",
        "fraud_GlobalTicket Net",
        "fraud_StreamPilot Services",
        "fraud_CivicPermit Web",
        "fraud_RapidLicense Online",
        "fraud_ByteWave Marketplace",
    ],
    "misc_pos": [
        "fraud_Goyette Inc",
        "fraud_Stationery Barn",
        "fraud_KeyStone Hardware",
        "fraud_Riverside Books",
        "fraud_Campus Copy Center",
        "fraud_Artisan Supply",
        "fraud_Garden Gate Store",
        "fraud_CityHall Kiosk",
    ],
    "entertainment": [
        "fraud_Aurora Cinema",
        "fraud_LiveStage Tickets",
        "fraud_Parkside Bowling",
        "fraud_BlueNote Club",
        "fraud_Summit Events",
        "fraud_Neon Arcade",
        "fraud_Cascade Theater",
        "fraud_GameGrid Lounge",
    ],
    "food_dining": [
        "fraud_Harbor Deli",
        "fraud_Peppercorn Bistro",
        "fraud_MainStreet Cafe",
        "fraud_Copper Spoon",
        "fraud_RedOak Grill",
        "fraud_LateNight Tacos",
        "fraud_Brookside Bakery",
        "fraud_Saffron Table",
    ],
    "health_fitness": [
        "fraud_VitalCare Pharmacy",
        "fraud_GlassWell Clinic",
        "fraud_FitNation Studio",
        "fraud_PulseGym",
        "fraud_Clearwater Dental",
        "fraud_Optima Health Shop",
        "fraud_MotionWorks PT",
        "fraud_WellPath Labs",
    ],
    "home": [
        "fraud_HomeHarbor Supply",
        "fraud_NorthPoint Furniture",
        "fraud_ElmStreet Appliances",
        "fraud_Anchor Plumbing",
        "fraud_BrightNest Decor",
        "fraud_ToolHouse Depot",
        "fraud_Solaris Hardware",
        "fraud_Meadow Home Co",
    ],
    "kids_pets": [
        "fraud_TinySteps Store",
        "fraud_PawsAndPlay",
        "fraud_LittleOak Toys",
        "fraud_PetValley Clinic",
        "fraud_Kiddo Corner",
        "fraud_HappyTails Supply",
        "fraud_BabyNest Goods",
        "fraud_BrightPup Grooming",
    ],
    "personal_care": [
        "fraud_SageSalon",
        "fraud_ClearSkin Studio",
        "fraud_CityBarber Works",
        "fraud_BloomBeauty Supply",
        "fraud_MellowSpa",
        "fraud_NovaCosmetics",
        "fraud_WellGroomed",
        "fraud_HerbalCare Shop",
    ],
    "travel": [
        "fraud_SkyBridge Travel",
        "fraud_HotelHarbor",
        "fraud_RouteRunner Rail",
        "fraud_CoastalCar Rental",
        "fraud_AeroLink Booking",
        "fraud_StayPoint Suites",
        "fraud_MountainPass Tours",
        "fraud_GlobalCruise Desk",
    ],
}
MERCHANTS = sorted({merchant for merchants in CATEGORY_MERCHANTS.values() for merchant in merchants})
JOBS = [
    "Accountant",
    "Attorney",
    "Barista",
    "Business analyst",
    "Chef",
    "Construction manager",
    "Consultant",
    "Customer support",
    "Data analyst",
    "Designer",
    "Developer",
    "Driver",
    "Electrician",
    "Engineer",
    "Executive assistant",
    "Financial advisor",
    "Freelancer",
    "Health technician",
    "Hospital administrator",
    "HR specialist",
    "Insurance agent",
    "Marketing manager",
    "Mechanic",
    "Medical assistant",
    "Nurse",
    "Operations manager",
    "Pharmacist",
    "Police officer",
    "Product manager",
    "Real estate agent",
    "Research scientist",
    "Restaurant manager",
    "Retail manager",
    "Retired",
    "Sales",
    "Software architect",
    "Student",
    "Teacher",
    "Truck dispatcher",
    "Warehouse supervisor",
]
CITIES = [
    ("Birmingham", "AL", 35203, 33.5207, -86.8025, 212237),
    ("Mobile", "AL", 36602, 30.6954, -88.0399, 187041),
    ("Phoenix", "AZ", 85004, 33.4484, -112.0740, 1608139),
    ("Tucson", "AZ", 85701, 32.2226, -110.9747, 542629),
    ("Los Angeles", "CA", 90012, 34.0522, -118.2437, 3898747),
    ("San Diego", "CA", 92101, 32.7157, -117.1611, 1386932),
    ("San Jose", "CA", 95113, 37.3382, -121.8863, 971233),
    ("Sacramento", "CA", 95814, 38.5816, -121.4944, 524943),
    ("Denver", "CO", 80202, 39.7392, -104.9903, 715522),
    ("Boulder", "CO", 80302, 40.01499, -105.27055, 105485),
    ("Miami", "FL", 33130, 25.7617, -80.1918, 442241),
    ("Orlando", "FL", 32801, 28.5383, -81.3792, 307573),
    ("Tampa", "FL", 33602, 27.9506, -82.4572, 384959),
    ("Atlanta", "GA", 30303, 33.7490, -84.3880, 498715),
    ("Savannah", "GA", 31401, 32.0809, -81.0912, 147780),
    ("Chicago", "IL", 60602, 41.8781, -87.6298, 2746388),
    ("Indianapolis", "IN", 46204, 39.7684, -86.1581, 887642),
    ("Boston", "MA", 2108, 42.3601, -71.0589, 675647),
    ("Baltimore", "MD", 21202, 39.2904, -76.6122, 585708),
    ("Detroit", "MI", 48226, 42.3314, -83.0458, 639111),
    ("Minneapolis", "MN", 55401, 44.9778, -93.2650, 429954),
    ("Kansas City", "MO", 64106, 39.0997, -94.5786, 508090),
    ("St Louis", "MO", 63101, 38.6270, -90.1994, 301578),
    ("Charlotte", "NC", 28202, 35.2271, -80.8431, 874579),
    ("Raleigh", "NC", 27601, 35.7796, -78.6382, 467665),
    ("Omaha", "NE", 68102, 41.2565, -95.9345, 486051),
    ("Las Vegas", "NV", 89101, 36.1699, -115.1398, 641903),
    ("Newark", "NJ", 7102, 40.7357, -74.1724, 311549),
    ("Albuquerque", "NM", 87102, 35.0844, -106.6504, 564559),
    ("New York", "NY", 10007, 40.7128, -74.0060, 8804190),
    ("Buffalo", "NY", 14202, 42.8864, -78.8784, 278349),
    ("Columbus", "OH", 43215, 39.9612, -82.9988, 905748),
    ("Cleveland", "OH", 44114, 41.4993, -81.6944, 372624),
    ("Oklahoma City", "OK", 73102, 35.4676, -97.5164, 681054),
    ("Tulsa", "OK", 74103, 36.1540, -95.9928, 413066),
    ("Portland", "OR", 97204, 45.5152, -122.6784, 652503),
    ("Philadelphia", "PA", 19106, 39.9526, -75.1652, 1603797),
    ("Pittsburgh", "PA", 15222, 40.4406, -79.9959, 302971),
    ("Nashville", "TN", 37219, 36.1627, -86.7816, 689447),
    ("Memphis", "TN", 38103, 35.1495, -90.0490, 633104),
    ("Dallas", "TX", 75201, 32.7767, -96.7970, 1304379),
    ("Austin", "TX", 78701, 30.2672, -97.7431, 974447),
    ("Houston", "TX", 77002, 29.7604, -95.3698, 2304580),
    ("San Antonio", "TX", 78205, 29.4241, -98.4936, 1434625),
    ("Salt Lake City", "UT", 84111, 40.7608, -111.8910, 200133),
    ("Seattle", "WA", 98101, 47.6062, -122.3321, 737015),
    ("Spokane", "WA", 99201, 47.6588, -117.4260, 228989),
    ("Madison", "WI", 53703, 43.0731, -89.4012, 269840),
    ("Milwaukee", "WI", 53202, 43.0389, -87.9065, 577222),
]
CUSTOMER_PROFILES = []


def build_customer_profiles(size: int = 80, seed: int = 20260519) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    profiles = []
    for index in range(max(1, size)):
        city, state, zip_code, lat, long, city_pop = rng.choice(CITIES)
        normal_categories = _weighted_sample_categories(rng, k=rng.randint(5, 9))
        online_bias = rng.betavariate(1.8, 2.4)
        travel_propensity = rng.betavariate(1.1, 6.5)
        preferred_by_category = {
            category: rng.sample(CATEGORY_MERCHANTS[category], k=rng.randint(2, min(5, len(CATEGORY_MERCHANTS[category]))))
            for category in CATEGORIES
        }
        preferred_merchants = sorted({merchant for values in preferred_by_category.values() for merchant in values})
        balance_mean = _clamp(rng.lognormvariate(math_log(4200), 0.92), 280, 95000)
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
                "balance_mean": balance_mean,
                "balance_volatility": rng.uniform(0.16, 0.54),
                "normal_categories": normal_categories,
                "category_weights": _profile_category_weights(rng, normal_categories, online_bias, travel_propensity),
                "preferred_by_category": preferred_by_category,
                "preferred_merchants": preferred_merchants,
                "frequency_weight": rng.choices([1, 2, 3, 5, 8, 13, 21], weights=[34, 24, 17, 12, 7, 4, 2], k=1)[0],
                "spend_scale": _clamp(rng.lognormvariate(math_log(1.0), 0.46), 0.38, 4.6),
                "distance_scale": rng.uniform(0.55, 2.3),
                "high_value_tolerance": rng.betavariate(1.6, 3.4),
                "merchant_loyalty": rng.betavariate(5.5, 2.0),
                "online_bias": online_bias,
                "travel_propensity": travel_propensity,
                "night_owl": rng.random() < 0.16,
                "income_cycle_day": rng.choice([1, 5, 15, 20, 25, 28]),
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
    attack_style = "legit"

    if fraud:
        attack_style = rng.choices(
            [
                "card_testing",
                "account_takeover",
                "geo_jump",
                "low_and_slow",
                "merchant_mimicry",
                "subscription_abuse",
                "cashout_burst",
            ],
            weights=[0.16, 0.18, 0.18, 0.17, 0.13, 0.08, 0.10],
            k=1,
        )[0]
        if attack_style == "card_testing":
            category = rng.choice(["shopping_net", "misc_net", "personal_care"])
            amount = _sample_amount(rng, category, profile, fraud=True, severity=rng.uniform(0.12, 0.75), sigma_boost=0.28)
            amount = round(_clamp(amount, 1.0, 185.0), 2)
        elif attack_style == "merchant_mimicry":
            category = rng.choice(["grocery_pos", "gas_transport", "shopping_pos", "food_dining", "personal_care"])
            amount = _sample_amount(rng, category, profile, fraud=True, severity=rng.uniform(1.25, 4.0), sigma_boost=0.14)
        elif attack_style == "low_and_slow":
            category = _choose_contextual_category(rng, profile, trans_time, unusual=False)
            amount = _sample_amount(rng, category, profile, fraud=True, severity=rng.uniform(0.7, 2.4), sigma_boost=0.08)
        elif attack_style == "subscription_abuse":
            category = rng.choice(["misc_net", "entertainment", "personal_care", "health_fitness"])
            amount = _sample_amount(rng, category, profile, fraud=True, severity=rng.uniform(0.55, 2.6), sigma_boost=0.18)
        elif attack_style == "cashout_burst":
            category = rng.choice(["shopping_net", "travel", "misc_net", "home"])
            amount = _sample_amount(rng, category, profile, fraud=True, severity=rng.uniform(2.8, 8.5), sigma_boost=0.24)
        elif attack_style == "geo_jump":
            category = rng.choice(RISKY_CATEGORIES + ["gas_transport", "home"])
            amount = _sample_amount(rng, category, profile, fraud=True, severity=rng.uniform(1.6, 6.2), sigma_boost=0.2)
        else:
            category = rng.choice(RISKY_CATEGORIES + ["home", "health_fitness"])
            amount = _sample_amount(rng, category, profile, fraud=True, severity=rng.uniform(2.0, 7.5), sigma_boost=0.22)
        hour = _fraud_hour(rng, attack_style)
        distance = _fraud_distance(rng, profile, category, attack_style)
        if not preserve_time:
            trans_time = _with_hour(rng, trans_time, hour)
    else:
        unusual_but_legit = rng.random() < (
            0.055 + (0.12 * float(profile.get("travel_propensity", 0.0))) + (0.025 * float(profile.get("online_bias", 0.0)))
        )
        category = _choose_contextual_category(rng, profile, trans_time, unusual=unusual_but_legit)
        severity = rng.uniform(1.2, 4.4) if unusual_but_legit else rng.uniform(0.72, 1.42)
        amount = _sample_amount(
            rng,
            category,
            profile,
            fraud=False,
            severity=severity,
            sigma_boost=0.12 if unusual_but_legit else 0.0,
        )
        hour = _normal_hour(rng, profile, category, unusual=unusual_but_legit)
        distance = _normal_distance(rng, profile, category, unusual=unusual_but_legit)
        if not preserve_time:
            trans_time = _with_hour(rng, trans_time, hour)

    merchant = _choose_merchant(rng, profile, category, fraud=bool(fraud), attack_style=attack_style)
    merch_lat, merch_long = _offset_location(lat, long, distance, rng)
    old_balance = _sample_old_balance(rng, profile, trans_time, category, amount)
    new_balance = max(0, round(old_balance - amount, 2))
    cc_num = profile["cc_num"]
    trans_num = hashlib.md5(
        f"{cc_num}-{trans_time.isoformat()}-{merchant}-{category}-{amount}-{rng.getrandbits(32)}".encode()
    ).hexdigest()
    payload = {
        "trans_date_trans_time": trans_time.strftime("%Y-%m-%d %H:%M:%S"),
        "cc_num": cc_num,
        "merchant": merchant,
        "category": category,
        "amt": amount,
        "gender": profile["gender"],
        "city": city,
        "state": state,
        "zip": zip_code,
        "lat": round(lat + rng.uniform(-0.035, 0.035) * float(profile.get("distance_scale", 1.0)), 6),
        "long": round(long + rng.uniform(-0.035, 0.035) * float(profile.get("distance_scale", 1.0)), 6),
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


def _choose_contextual_category(
    rng: random.Random,
    profile: dict[str, Any],
    trans_time: datetime,
    unusual: bool,
) -> str:
    weights = dict(profile.get("category_weights") or {})
    for category in CATEGORIES:
        weights.setdefault(category, BASE_CATEGORY_WEIGHTS[category])
        weights[category] *= _category_time_multiplier(category, trans_time, profile)
    if unusual:
        for category in ["shopping_net", "shopping_pos", "misc_net", "home", "travel"]:
            weights[category] *= rng.uniform(2.0, 4.8)
    return _weighted_choice(rng, list(weights.items()))


def _choose_merchant(
    rng: random.Random,
    profile: dict[str, Any],
    category: str,
    fraud: bool,
    attack_style: str,
) -> str:
    category_pool = CATEGORY_MERCHANTS.get(category, MERCHANTS)
    preferred_by_category = profile.get("preferred_by_category") or {}
    preferred_pool = preferred_by_category.get(category) or profile.get("preferred_merchants") or category_pool
    if fraud:
        if attack_style in {"merchant_mimicry", "low_and_slow"} and rng.random() < 0.74:
            return rng.choice(preferred_pool)
        if attack_style == "card_testing" and rng.random() < 0.88:
            return rng.choice(CATEGORY_MERCHANTS.get(category, category_pool))
        if rng.random() < 0.28:
            return rng.choice(preferred_pool)
        return rng.choice(category_pool)
    if rng.random() < float(profile.get("merchant_loyalty", 0.65)):
        return rng.choice(preferred_pool)
    return rng.choice(category_pool)


def _sample_amount(
    rng: random.Random,
    category: str,
    profile: dict[str, Any],
    *,
    fraud: bool,
    severity: float,
    sigma_boost: float,
) -> float:
    amount_profile = CATEGORY_AMOUNT_PROFILES[category]
    time_factor = _category_amount_time_factor(category, profile)
    median = float(amount_profile["median"]) * float(profile.get("spend_scale", 1.0)) * time_factor * severity
    sigma = float(amount_profile["sigma"]) + sigma_boost
    amount = rng.lognormvariate(math_log(median), sigma)
    tail_probability = float(amount_profile["tail"]) * (1.35 if fraud else 1.0)
    if rng.random() < tail_probability:
        low, high = amount_profile["tail_mult"]
        amount *= rng.uniform(float(low), float(high))
    limit_multiplier = 1.6 if fraud else 1.0
    amount = _clamp(amount, float(amount_profile["min"]), float(amount_profile["max"]) * limit_multiplier)
    return round(amount, 2)


def _category_amount_time_factor(category: str, profile: dict[str, Any]) -> float:
    factor = 1.0
    if category.endswith("_net"):
        factor *= 0.88 + float(profile.get("online_bias", 0.5)) * 0.42
    if category == "travel":
        factor *= 0.85 + float(profile.get("travel_propensity", 0.2)) * 1.45
    if category in {"home", "shopping_pos", "shopping_net"}:
        factor *= 0.9 + float(profile.get("high_value_tolerance", 0.35)) * 0.5
    return _clamp(factor, 0.55, 2.25)


def _category_time_multiplier(category: str, moment: datetime, profile: dict[str, Any]) -> float:
    hour = moment.hour
    weekday = moment.weekday()
    weekend = weekday >= 5
    multiplier = 1.0
    if category == "food_dining" and (11 <= hour <= 13 or 17 <= hour <= 21):
        multiplier *= 2.1
    if category == "gas_transport" and (6 <= hour <= 9 or 16 <= hour <= 19):
        multiplier *= 1.45
    if category in {"shopping_pos", "entertainment", "kids_pets"} and weekend:
        multiplier *= 1.55
    if category in {"shopping_net", "misc_net"} and (hour >= 20 or hour <= 2):
        multiplier *= 1.25 + float(profile.get("online_bias", 0.5))
    if category == "travel" and weekend:
        multiplier *= 1.35 + float(profile.get("travel_propensity", 0.2))
    if category in {"grocery_pos", "personal_care"} and 8 <= hour <= 20:
        multiplier *= 1.18
    if moment.month in {11, 12} and category in {"shopping_net", "shopping_pos", "travel"}:
        multiplier *= 1.28
    if moment.day in {1, 5, 15, 20, 25, 28} and category in {"grocery_pos", "home", "shopping_pos"}:
        multiplier *= 1.12
    return multiplier


def _normal_distance(rng: random.Random, profile: dict[str, Any], category: str, unusual: bool) -> float:
    scale = float(profile.get("distance_scale", 1.0))
    if category.endswith("_net"):
        distance = rng.lognormvariate(math_log(16), 0.95) * scale
        if rng.random() < 0.11:
            distance += rng.uniform(80, 520) * scale
    elif category == "travel":
        if rng.random() < float(profile.get("travel_propensity", 0.15)) + 0.08:
            distance = rng.uniform(120, 1700) * scale
        else:
            distance = rng.uniform(18, 260) * scale
    elif category == "gas_transport":
        distance = rng.lognormvariate(math_log(18), 0.78) * scale
    elif category in {"shopping_pos", "home", "entertainment"}:
        distance = rng.lognormvariate(math_log(12), 0.8) * scale
    else:
        distance = rng.lognormvariate(math_log(7), 0.74) * scale
    if unusual:
        distance *= rng.uniform(2.2, 7.5)
    return _clamp(distance, 0.2, 1850.0 if unusual else 900.0)


def _fraud_distance(rng: random.Random, profile: dict[str, Any], category: str, attack_style: str) -> float:
    scale = float(profile.get("distance_scale", 1.0))
    if attack_style == "card_testing":
        return rng.uniform(5, 620) * scale
    if attack_style == "low_and_slow":
        return rng.uniform(8, 280) * scale
    if attack_style == "merchant_mimicry":
        return rng.uniform(18, 520) * scale
    if attack_style == "subscription_abuse":
        return rng.uniform(12, 940) * scale
    if attack_style == "cashout_burst":
        return rng.uniform(90, 1900) * scale
    if attack_style == "geo_jump":
        return rng.uniform(260, 2500) * scale
    if category == "travel":
        return rng.uniform(220, 2600) * scale
    return rng.uniform(120, 2100) * scale


def _sample_old_balance(
    rng: random.Random,
    profile: dict[str, Any],
    trans_time: datetime,
    category: str,
    amount: float,
) -> float:
    mean = float(profile.get("balance_mean", 3500.0))
    volatility = float(profile.get("balance_volatility", 0.28))
    old_balance = rng.lognormvariate(math_log(mean), 0.25 + volatility)
    if trans_time.day in {int(profile.get("income_cycle_day", 1)), 1, 15, 25, 28}:
        old_balance *= rng.uniform(1.04, 1.38)
    if category in {"home", "travel", "shopping_net"} and amount > old_balance * 0.62:
        old_balance += amount * rng.uniform(0.35, 1.7)
    if rng.random() < 0.025:
        old_balance *= rng.uniform(1.8, 5.5)
    return round(_clamp(old_balance, 18.0, 950000.0), 2)


def _weighted_sample_categories(rng: random.Random, k: int) -> list[str]:
    available = [
        (category, BASE_CATEGORY_WEIGHTS[category] * rng.uniform(0.7, 1.35))
        for category in CATEGORIES
    ]
    selected: list[str] = []
    for _ in range(min(k, len(available))):
        category = _weighted_choice(rng, available)
        selected.append(category)
        available = [(item, weight) for item, weight in available if item != category]
    return selected


def _profile_category_weights(
    rng: random.Random,
    normal_categories: list[str],
    online_bias: float,
    travel_propensity: float,
) -> dict[str, float]:
    weights = {}
    for category in CATEGORIES:
        weight = BASE_CATEGORY_WEIGHTS[category] * rng.uniform(0.62, 1.58)
        if category in normal_categories:
            weight *= rng.uniform(2.4, 5.5)
        else:
            weight *= rng.uniform(0.08, 0.42)
        if category.endswith("_net"):
            weight *= 0.6 + (online_bias * 1.65)
        if category == "travel":
            weight *= 0.6 + (travel_propensity * 2.8)
        weights[category] = weight
    return weights


def _weighted_choice(rng: random.Random, weighted_items: list[tuple[str, float]]) -> str:
    items = [(item, max(0.0, float(weight))) for item, weight in weighted_items]
    total = sum(weight for _, weight in items)
    if total <= 0:
        return rng.choice([item for item, _ in items])
    marker = rng.random() * total
    cumulative = 0.0
    for item, weight in items:
        cumulative += weight
        if cumulative >= marker:
            return item
    return items[-1][0]


def _normal_hour(rng: random.Random, profile: dict[str, Any], category: str, unusual: bool) -> int:
    if unusual:
        return rng.choice([rng.randint(6, 23), 0, 1])
    if category.endswith("_net") and rng.random() < float(profile.get("online_bias", 0.4)):
        return rng.choice([rng.randint(8, 23), 0, 1])
    if category == "food_dining":
        return rng.choice([rng.randint(11, 13), rng.randint(17, 21)])
    if category == "gas_transport":
        return rng.choice([rng.randint(6, 9), rng.randint(15, 20), rng.randint(10, 14)])
    if bool(profile.get("night_owl")) and rng.random() < 0.18:
        return rng.choice([22, 23, 0, 1])
    return rng.randint(7, 22)


def _fraud_hour(rng: random.Random, attack_style: str) -> int:
    if attack_style in {"card_testing", "cashout_burst", "account_takeover", "geo_jump"}:
        return rng.choice([0, 1, 2, 3, 4, 23, rng.randint(8, 22)])
    if attack_style == "low_and_slow":
        return rng.choice([rng.randint(8, 22), 23, 0, 1])
    return rng.choice([rng.randint(7, 23), 0, 1, 2])


def _with_hour(rng: random.Random, trans_time: datetime, hour: int) -> datetime:
    return trans_time.replace(hour=hour, minute=rng.randint(0, 59), second=rng.randint(0, 59))


def _offset_location(lat: float, long: float, distance_km: float, rng: random.Random) -> tuple[float, float]:
    bearing = rng.uniform(0, 360)
    delta_lat = (distance_km / 111.0) * math_cos(bearing)
    denominator = max(20.0, 111.0 * abs(math_cos(lat)))
    delta_long = (distance_km / denominator) * math_sin(bearing)
    return max(-89.9, min(89.9, lat + delta_lat)), max(-179.9, min(179.9, long + delta_long))


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


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
