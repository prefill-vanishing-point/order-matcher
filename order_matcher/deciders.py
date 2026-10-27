"""The two things that can answer a Choice: Jev itself, and an offline stand-in.

Both take one order line and a list of options and return Jev's answer format:
the chosen option, a probability for every option, and a confidence.
"""
import json
import math
import os
import urllib.request
from collections import Counter
from dataclasses import dataclass
from typing import Protocol

from .data import Sku
from .parse import OrderLine, similarity

JEV_URL = "https://api.typesafe.ai/v1/systemone"
JEV_KEY_ENV = "TYPESAFE_API_KEY"
JEV_INSTRUCTIONS = ("A restaurant chef wrote this line in a produce order. Which catalog item "
                    "do they want, in the unit they asked for: case (cs), pound (lb, #) or "
                    "each (ea, bunch, pint)? If they give no unit, choose the unit this "
                    "customer orders most often. The number is how many; it doesn't matter here.")
# Offered to Jev with every list, because a Choice must otherwise pick one of the
# options even when the product the chef wants isn't among them.
NONE_OF_THESE = "NONE"
NONE_DESCRIPTION = ("None of these products. Choose this only if the chef wants a product that "
                    "isn't listed; a listed product in a different unit or pack size doesn't count.")


@dataclass(frozen=True)
class Option:
    sku: Sku
    count: int  # recent orders by this customer, or recent buyers across all customers
    note: str   # says which of the two `count` is, in words Jev can read

    @property
    def description(self) -> str:
        return f"{self.sku.description}. {self.note}."


@dataclass(frozen=True)
class Choice:
    choice: str                      # the chosen SKU, or NONE_OF_THESE
    confidence: float                # 0 to 1
    probabilities: dict[str, float]  # SKU -> probability, summing to about 1


class Decider(Protocol):
    """Jev can answer NONE_OF_THESE. The stand-in never does; it lowers its confidence instead."""

    name: str

    def choose(self, line: OrderLine, options: list[Option]) -> Choice: ...


def jev_confidence(probabilities: dict[str, float]) -> float:
    """Jev's confidence: 1 when all the probability is on one option, 0 for an even split.

    This is (n * top - 1) / (n - 1). It reproduces the 0.7 in the example in Jev's API docs.
    """
    n = len(probabilities)
    if n == 1:
        return 1.0
    top = max(probabilities.values())
    return max(0.0, (n * top - 1) / (n - 1))


def jev_request(line: OrderLine, options: list[Option], model: str = "jev-latest") -> dict:
    """The request body for one order line, as described at docs.typesafe.ai/api."""
    return {
        "model": model,
        "state": line.text,
        "questions": {
            "item": {
                "type": "choice",
                "instructions": JEV_INSTRUCTIONS,
                "criteria": {**{o.sku.sku: o.description for o in options},
                             NONE_OF_THESE: NONE_DESCRIPTION},
            }
        },
    }


class JevDecider:
    name = "jev"

    def __init__(self, api_key: str | None = None, model: str = "jev-latest", timeout: float = 30):
        self.api_key = api_key or os.environ.get(JEV_KEY_ENV)
        if not self.api_key:
            raise RuntimeError(f"Set {JEV_KEY_ENV} to your Jev API key, or use --decider local.")
        self.model = model
        self.timeout = timeout

    def choose(self, line: OrderLine, options: list[Option]) -> Choice:
        request = urllib.request.Request(
            JEV_URL,
            data=json.dumps(jev_request(line, options, self.model)).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            answer = json.load(response)["answers"]["item"]
        return Choice(answer["choice"], float(answer["confidence"]),
                      {k: float(v) for k, v in answer["probabilities"].items()})


class LocalDecider:
    """Offline stand-in for Jev, so the engine runs without an API key.

    It scores each option by string similarity, turns the scores into
    probabilities and computes confidence the way Jev does. It also lowers
    confidence when even the best option is a weak match, because then the right
    product probably isn't among the options. It knows no food vocabulary, so
    chef slang like "grass" for asparagus will beat it.
    """

    name = "local stand-in"

    def __init__(self, temperature: float = 0.05, weak_match: float = 0.7):
        self.temperature = temperature  # lower means more confident
        self.weak_match = weak_match    # name similarity below this pulls confidence down hard

    def choose(self, line: OrderLine, options: list[Option]) -> Choice:
        per_product = Counter()
        for o in options:
            per_product[o.sku.product] += o.count

        name_scores, scores = {}, {}
        for o in options:
            score = name_scores[o.sku.sku] = similarity(line.item, o.sku.name)
            if line.unit:
                score += 0.15 if o.sku.unit == line.unit else 0.0
            elif per_product[o.sku.product]:
                # No unit given: lean towards the unit this product is usually ordered in.
                score += 0.15 * o.count / per_product[o.sku.product]
            scores[o.sku.sku] = score

        top = max(scores.values())
        weights = {k: math.exp((v - top) / self.temperature) for k, v in scores.items()}
        total = sum(weights.values())
        probabilities = {k: w / total for k, w in weights.items()}
        choice = max(probabilities, key=probabilities.get)
        fit = 1 / (1 + math.exp(-(name_scores[choice] - self.weak_match) / 0.04))
        return Choice(choice, jev_confidence(probabilities) * fit, probabilities)
