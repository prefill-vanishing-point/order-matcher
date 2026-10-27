"""Generate the synthetic data in data/.

Writes a produce catalog, 40 restaurants, five months of purchase history and
two sets of labelled orders: a small dev set for tuning and a held-out test set
for the accuracy check. Seeded, so every run produces the same files.

    python scripts/generate_data.py
"""
import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path

SEED = 7
ORDER_DATE = date(2026, 10, 26)
HISTORY_DAYS = 150  # longer than the 90-day window, so some purchases fall outside it
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# code, catalog name, case pack, units sold, how chefs write it
PRODUCTS = [
    # Fruit
    ("BAN", "Bananas", "40 lb", "CS LB", "bananas|banana|bananna"),
    ("AVO", "Avocados, Hass", "48 ct", "CS EA", "avocados|avos|hass avocados|avacados"),
    ("LEM", "Lemons", "115 ct", "CS EA", "lemons|lemon|lemmons"),
    ("LIM", "Limes", "40 lb", "CS LB", "limes|lime"),
    ("ORA", "Oranges, navel", "72 ct", "CS EA", "oranges|navel oranges|navels"),
    ("STR", "Strawberries", "8 x 1 lb", "CS", "strawberries|strawbs|strawberrys"),
    ("BLU", "Blueberries", "12 x 6 oz", "CS", "blueberries|blues"),
    ("RAS", "Raspberries", "12 x 6 oz", "CS", "raspberries|razz"),
    ("APG", "Apples, Granny Smith", "100 ct", "CS LB", "granny smith|green apples|granny apples"),
    ("APF", "Apples, Fuji", "100 ct", "CS LB", "fuji apples|fujis"),
    ("PIN", "Pineapples", "7 ct", "CS EA", "pineapples|pineapple|pines"),
    ("MAN", "Mangoes", "9 ct", "CS EA", "mangos|mangoes|mango"),
    ("WAT", "Watermelon, seedless", "4 ct", "CS EA", "watermelon|seedless watermelon"),
    ("GRP", "Grapes, red seedless", "18 lb", "CS LB", "red grapes|grapes"),
    ("CAN", "Cantaloupe", "12 ct", "CS EA", "cantaloupe|cantelope|melons"),
    # Greens
    ("KAL", "Kale, green", "24 bunches", "CS EA", "kale|green kale|curly kale"),
    ("KAD", "Kale, lacinato (dino)", "24 bunches", "CS EA", "dino kale|lacinato kale|tuscan kale|black kale"),
    ("SPN", "Spinach, baby", "4 lb", "CS LB", "baby spinach|spinach"),
    ("ARU", "Arugula, baby", "3 lb", "CS LB", "arugula|baby arugula|rocket"),
    ("ROH", "Lettuce, romaine hearts", "12 x 3 ct", "CS", "romaine hearts|hearts of romaine"),
    ("ROM", "Lettuce, romaine", "24 ct", "CS EA", "romaine|romaine heads|romaine lettuce"),
    ("ICE", "Lettuce, iceberg", "24 ct", "CS EA", "iceberg|iceberg lettuce|head lettuce"),
    ("MIX", "Spring mix (mesclun)", "3 lb", "CS LB", "spring mix|mixed greens|mesclun"),
    # Tomatoes, onions, roots
    ("TOR", "Tomatoes, roma", "25 lb", "CS LB", "roma tomatoes|romas|roma toms|plum tomatoes"),
    ("TOV", "Tomatoes, on the vine", "15 lb", "CS LB", "vine tomatoes|tomatoes on the vine|tov"),
    ("TOC", "Tomatoes, cherry", "12 pints", "CS EA", "cherry tomatoes|cherry toms"),
    ("TOH", "Tomatoes, heirloom", "10 lb", "CS LB", "heirloom tomatoes|heirlooms"),
    ("ONY", "Onions, yellow", "50 lb", "CS LB", "yellow onions|onions|yellow onion"),
    ("ONR", "Onions, red", "25 lb", "CS LB", "red onions|red onion"),
    ("ONW", "Onions, white", "50 lb", "CS LB", "white onions|white onion"),
    ("SHA", "Shallots", "10 lb", "CS LB", "shallots|shallot"),
    ("GAR", "Garlic, peeled", "5 lb", "CS LB", "peeled garlic|garlic|garlic cloves"),
    ("SCA", "Onions, green (scallions)", "48 bunches", "CS EA", "green onions|scallions|scallion"),
    ("LEK", "Leeks", "12 bunches", "CS EA", "leeks|leek"),
    ("POR", "Potatoes, russet", "50 lb", "CS LB", "russet potatoes|russets|bakers|idaho potatoes"),
    ("POY", "Potatoes, Yukon gold", "50 lb", "CS LB", "yukon gold potatoes|yukon golds|yukons"),
    ("POF", "Potatoes, fingerling", "10 lb", "CS LB", "fingerlings|fingerling potatoes"),
    ("SWP", "Sweet potatoes", "40 lb", "CS LB", "sweet potatoes|yams"),
    ("CAR", "Carrots, jumbo", "50 lb", "CS LB", "carrots|jumbo carrots"),
    ("CRB", "Carrots, baby peeled", "5 lb", "CS LB", "baby carrots"),
    ("BEE", "Beets, red", "25 lb", "CS LB", "beets|red beets"),
    ("RAD", "Radishes, red", "24 bunches", "CS EA", "radishes|red radishes"),
    ("GIN", "Ginger root", "30 lb", "CS LB", "ginger|ginger root"),
    # Other vegetables
    ("CEL", "Celery", "24 ct", "CS EA", "celery"),
    ("CUC", "Cucumbers", "24 ct", "CS EA", "cucumbers|cukes"),
    ("CUE", "Cucumbers, English", "12 ct", "CS EA", "english cucumbers|english cukes|hothouse cukes"),
    ("ZUC", "Squash, zucchini", "20 lb", "CS LB", "zucchini|zukes|zuchini"),
    ("SQY", "Squash, yellow", "20 lb", "CS LB", "yellow squash"),
    ("BPG", "Peppers, green bell", "25 lb", "CS LB", "green peppers|green bells|green bell peppers"),
    ("BPR", "Peppers, red bell", "25 lb", "CS LB", "red peppers|red bells|red bell peppers"),
    ("JAL", "Peppers, jalapeno", "10 lb", "CS LB", "jalapeños|jalapenos|jalepenos"),
    ("SER", "Peppers, serrano", "10 lb", "CS LB", "serranos|serrano chiles"),
    ("POB", "Peppers, poblano", "10 lb", "CS LB", "poblanos|pasillas|poblano chiles"),
    ("BRO", "Broccoli crowns", "20 lb", "CS LB", "broccoli|broc crowns|broccoli crowns"),
    ("BRL", "Broccolini", "18 bunches", "CS EA", "broccolini|baby broccoli"),
    ("CAU", "Cauliflower", "12 ct", "CS EA", "cauliflower|cauli"),
    ("BRS", "Brussels sprouts", "25 lb", "CS LB", "brussels sprouts|brussels|brussel sprouts"),
    ("ASP", "Asparagus", "11 lb", "CS LB", "asparagus|grass|sparagus"),
    ("GRB", "Beans, green", "25 lb", "CS LB", "green beans|string beans"),
    ("HAV", "Beans, haricots verts", "10 lb", "CS LB", "haricots verts|french beans|haricot vert"),
    ("COR", "Corn, yellow", "48 ears", "CS EA", "corn|yellow corn|corn on the cob"),
    ("CAB", "Cabbage, green", "50 lb", "CS LB", "green cabbage|cabbage"),
    ("CBR", "Cabbage, red", "50 lb", "CS LB", "red cabbage|purple cabbage"),
    ("NAP", "Cabbage, napa", "50 lb", "CS LB", "napa cabbage|napa|nappa"),
    ("BOK", "Bok choy, baby", "20 lb", "CS LB", "baby bok choy|bok choy|shanghai bok choy"),
    ("EGG", "Eggplant", "25 lb", "CS LB", "eggplant|eggplants|aubergine"),
    ("FEN", "Fennel", "24 ct", "CS EA", "fennel|fennel bulbs"),
    # Mushrooms
    ("MCR", "Mushrooms, crimini (baby bella)", "10 lb", "CS LB", "crimini|cremini|baby bellas|brown mushrooms"),
    ("MWB", "Mushrooms, white button", "10 lb", "CS LB", "button mushrooms|white mushrooms|buttons"),
    ("MSH", "Mushrooms, shiitake", "3 lb", "CS LB", "shiitake|shitake|shiitakes"),
    ("MPO", "Mushrooms, portobello", "5 lb", "CS LB", "portobellos|portabellas|portobello caps"),
    # Herbs
    ("CIL", "Cilantro", "60 bunches", "CS EA", "cilantro|coriander|cilentro"),
    ("PAR", "Parsley, Italian flat-leaf", "60 bunches", "CS EA", "italian parsley|flat leaf parsley|parsley"),
    ("PAC", "Parsley, curly", "60 bunches", "CS EA", "curly parsley"),
    ("BAS", "Basil", "1 lb", "LB", "basil|sweet basil|genovese basil"),
    ("BAT", "Basil, Thai", "1 lb", "LB", "thai basil"),
    ("MNT", "Mint", "12 bunches", "CS EA", "mint|spearmint"),
    ("ROS", "Rosemary", "12 bunches", "CS EA", "rosemary"),
    ("THY", "Thyme", "12 bunches", "CS EA", "thyme|fresh thyme"),
    ("CHI", "Chives", "12 bunches", "CS EA", "chives"),
    ("DIL", "Dill", "12 bunches", "CS EA", "dill"),
    ("LGR", "Lemongrass", "10 lb", "CS LB", "lemongrass|lemon grass"),
]
BY_CODE = {p[0]: p for p in PRODUCTS}

NAME_FIRST = ["Harbor", "Juniper", "Olive", "Saffron", "Copper", "Driftwood", "Marigold",
              "Cedar", "Ember", "Fig", "Lantern", "Tidewater", "Mesa", "Paloma", "Coral",
              "Sage", "Willow", "Anchor", "Citrus", "Hearth"]
NAME_SECOND = ["Kitchen", "Bistro", "Taqueria", "Grill", "Cafe", "Trattoria", "Cantina",
               "Table", "Noodle Bar", "Oyster Bar"]

QTY = {"CS": [1, 1, 1, 2, 2, 3, 4], "LB": [2, 3, 5, 5, 10, 10, 15, 20, 25],
       "EA": [2, 3, 4, 6, 6, 10, 12, 24]}


def each_label(pack):
    if pack.endswith("bunches"):
        return "bunch"
    if pack.endswith("pints"):
        return "pint"
    return "each"


def description(name, pack, unit):
    if unit == "CS":
        return f"{name}, case ({pack})"
    if unit == "LB":
        return f"{name}, per lb"
    return f"{name}, {each_label(pack)}"


def units_of(code):
    return BY_CODE[code][3].split()


def make_profiles(rng, customer_ids):
    """Decide what each restaurant buys and in which unit it usually buys it."""
    profiles = {}
    for cid in customer_ids:
        codes = rng.sample(sorted(BY_CODE), rng.randint(15, 35))
        usual = {}
        for code in codes:
            units = units_of(code)
            usual[code] = "CS" if "CS" in units and rng.random() < 0.65 else rng.choice(units)
        # The first few products stopped being ordered more than 90 days ago.
        profiles[cid] = {"products": codes, "lapsed": set(codes[:rng.randint(2, 4)]), "usual": usual}
    return profiles


def make_purchases(rng, profiles):
    rows = []
    for cid, profile in profiles.items():
        for code in profile["products"]:
            usual = profile["usual"][code]
            every = {usual: rng.randint(3, 14)}  # days between orders
            others = [u for u in units_of(code) if u != usual]
            if others and rng.random() < 0.25:
                every[rng.choice(others)] = rng.randint(20, 45)
            for unit, gap in every.items():
                day = rng.randint(95, 110) if code in profile["lapsed"] else rng.randint(1, gap)
                while day <= HISTORY_DAYS:
                    rows.append({"customer_id": cid,
                                 "date": (ORDER_DATE - timedelta(days=day)).isoformat(),
                                 "sku": f"{code}-{unit}", "qty": rng.choice(QTY[unit])})
                    day += max(2, gap + rng.randint(-1, 2))
    rows.sort(key=lambda r: (r["date"], r["customer_id"], r["sku"]))
    return rows


def add_typo(rng, text):
    words = text.split()
    long_words = [i for i, w in enumerate(words) if len(w) > 4]
    if not long_words:
        return text
    i = rng.choice(long_words)
    w = words[i]
    j = rng.randrange(1, len(w) - 2)
    op = rng.choice(["swap", "drop", "double"])
    if op == "swap":
        w = w[:j] + w[j + 1] + w[j] + w[j + 2:]
    elif op == "drop":
        w = w[:j] + w[j + 1:]
    else:
        w = w[:j] + w[j] + w[j:]
    words[i] = w
    return " ".join(words)


def unit_word(rng, unit, pack, qty):
    one = qty == 1
    if unit == "CS":
        return rng.choice(["cs", "case"] if one else ["cs", "cases", "cases"])
    if unit == "LB":
        return rng.choice(["lb", "pound", "#"] if one else ["lb", "lbs", "pounds", "#"])
    label = each_label(pack)
    if label == "bunch":
        return rng.choice(["bunch", "bu"] if one else ["bunches", "bunches", "bu"])
    if label == "pint":
        return rng.choice(["pint", "pt"] if one else ["pints", "pt"])
    return rng.choice(["ea", "each"])


def render_line(rng, product, unit, show_unit):
    """Write one order line the way a chef might text it."""
    _, _, pack, _, aliases = product
    item = rng.choice(aliases.split("|"))
    if rng.random() < 0.12:
        item = add_typo(rng, item)
    qty = rng.choice(QTY[unit])
    if not show_unit:
        text = rng.choice(["{q} {item}", "{item} x{q}", "{item} {q}"]).format(q=qty, item=item)
    elif unit == "CS" and qty == 1 and rng.random() < 0.4:
        text = rng.choice(["a case of {item}", "case {item}", "cs {item}"]).format(item=item)
    else:
        u = unit_word(rng, unit, pack, qty)
        if u == "#":
            formats = ["{q}# {item}", "{item} {q}#"]
        else:
            formats = ["{q} {u} {item}", "{q} {u} of {item}", "{item} {q} {u}"]
            if len(u) <= 3:
                formats.append("{q}{u} {item}")
        text = rng.choice(formats).format(q=qty, u=u, item=item)
    r = rng.random()
    if r < 0.08:
        text = text.upper()
    elif r < 0.2:
        text = text[0].upper() + text[1:]
    return text, qty


def make_orders(rng, prefix, count, profiles):
    recent_anywhere = {code for p in profiles.values() for code in p["products"]
                       if code not in p["lapsed"]}
    orders = []
    for n in range(1, count + 1):
        cid = rng.choice(sorted(profiles))
        profile = profiles[cid]
        active = [c for c in profile["products"] if c not in profile["lapsed"]]
        lapsed = sorted(profile["lapsed"])
        new = sorted(recent_anywhere - set(profile["products"]))
        size = rng.randint(3, 12)
        lines, used = [], set()
        while len(lines) < size:
            r = rng.random()
            # Mostly things this restaurant buys now; some it stopped buying, some it never has.
            pool = active if r < 0.85 else lapsed if r < 0.92 else new
            code = rng.choice(pool) if pool else None
            if code is None or code in used:
                continue
            used.add(code)
            units = units_of(code)
            usual = profile["usual"].get(code)
            unit = usual if usual and (rng.random() < 0.85 or len(units) == 1) else rng.choice(units)
            # A chef only leaves the unit out when it's the one they always order.
            show_unit = code not in active or unit != usual or rng.random() < 0.7
            text, qty = render_line(rng, BY_CODE[code], unit, show_unit)
            lines.append({"text": text, "sku": f"{code}-{unit}", "qty": qty})
        sep = rng.choice([", ", "\n"])
        orders.append({"order_id": f"{prefix}{n:03d}", "customer_id": cid,
                       "date": ORDER_DATE.isoformat(),
                       "text": sep.join(line["text"] for line in lines), "lines": lines})
    return orders


def write_csv(name, fields, rows):
    with open(DATA_DIR / name, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_jsonl(name, rows):
    with open(DATA_DIR / name, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main():
    rng = random.Random(SEED)
    DATA_DIR.mkdir(exist_ok=True)

    catalog = [{"sku": f"{code}-{unit}", "product": code, "name": name, "unit": unit,
                "description": description(name, pack, unit)}
               for code, name, pack, units, _ in PRODUCTS for unit in units.split()]
    write_csv("catalog.csv", ["sku", "product", "name", "unit", "description"], catalog)

    names = rng.sample([f"{a} {b}" for a in NAME_FIRST for b in NAME_SECOND], 40)
    customers = {f"C{i:03d}": name for i, name in enumerate(names, 1)}
    write_csv("customers.csv", ["customer_id", "name"],
              [{"customer_id": k, "name": v} for k, v in customers.items()])

    profiles = make_profiles(rng, customers)
    purchases = make_purchases(rng, profiles)
    write_csv("purchases.csv", ["customer_id", "date", "sku", "qty"], purchases)

    dev = make_orders(rng, "D", 30, profiles)
    test = make_orders(rng, "T", 100, profiles)
    write_jsonl("orders_dev.jsonl", dev)
    write_jsonl("orders_test.jsonl", test)

    print(f"{len(catalog)} SKUs, {len(customers)} customers, {len(purchases)} purchases")
    print(f"dev: {len(dev)} orders, {sum(len(o['lines']) for o in dev)} lines")
    print(f"test: {len(test)} orders, {sum(len(o['lines']) for o in test)} lines")


if __name__ == "__main__":
    main()
