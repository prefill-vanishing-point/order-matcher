"""Load the catalog, customers, purchase history and labelled orders from data/."""
import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@dataclass(frozen=True)
class Sku:
    sku: str          # e.g. "BAN-CS"
    product: str      # e.g. "BAN"; every unit of the same product shares it
    name: str         # e.g. "Bananas"
    unit: str         # CS (case), LB (pound) or EA (each, bunch or pint)
    description: str  # e.g. "Bananas, case (40 lb)"


@dataclass(frozen=True)
class Purchase:
    customer_id: str
    day: date
    sku: str


class Catalog:
    def __init__(self, skus: Iterable[Sku]):
        self._skus = {s.sku: s for s in skus}
        self._variants = {(s.product, s.unit): s for s in self._skus.values()}

    def __getitem__(self, sku_id: str) -> Sku:
        return self._skus[sku_id]

    def __len__(self) -> int:
        return len(self._skus)

    def __iter__(self):
        return iter(self._skus.values())

    def get(self, sku_id: str) -> Sku | None:
        return self._skus.get(sku_id)

    def variant(self, product: str, unit: str) -> Sku | None:
        """The same product sold in another unit, if the catalog has it."""
        return self._variants.get((product, unit))


class History:
    def __init__(self, purchases: Iterable[Purchase]):
        self._by_customer: dict[str, list[Purchase]] = defaultdict(list)
        for p in purchases:
            self._by_customer[p.customer_id].append(p)

    @property
    def next_day(self) -> date:
        """The day after the last purchase: the default date for a new order."""
        return max(p.day for ps in self._by_customer.values() for p in ps) + timedelta(days=1)

    def counts(self, customer_id: str, as_of: date, days: int) -> Counter[str]:
        """How many times the customer ordered each SKU in the `days` before `as_of`."""
        start = as_of - timedelta(days=days)
        return Counter(p.sku for p in self._by_customer.get(customer_id, [])
                       if start <= p.day < as_of)

    def buyers(self, as_of: date, days: int) -> Counter[str]:
        """How many different customers ordered each SKU in the `days` before `as_of`."""
        start = as_of - timedelta(days=days)
        result: Counter[str] = Counter()
        for purchases in self._by_customer.values():
            result.update({p.sku for p in purchases if start <= p.day < as_of})
        return result


def _rows(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def load(data_dir: Path = DATA_DIR) -> tuple[Catalog, History, dict[str, str]]:
    catalog = Catalog(Sku(r["sku"], r["product"], r["name"], r["unit"], r["description"])
                      for r in _rows(data_dir / "catalog.csv"))
    history = History(Purchase(r["customer_id"], date.fromisoformat(r["date"]), r["sku"])
                      for r in _rows(data_dir / "purchases.csv"))
    customers = {r["customer_id"]: r["name"] for r in _rows(data_dir / "customers.csv")}
    return catalog, history, customers


def load_orders(name: str, data_dir: Path = DATA_DIR) -> list[dict]:
    """Labelled orders: `name` is "dev" or "test"."""
    with open(data_dir / f"orders_{name}.jsonl", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]
