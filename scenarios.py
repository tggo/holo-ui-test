"""
Scenarios, each expressed two ways:
  steps  — explicit step list for the harness (backends A & B)
  goal   — natural-language goal for the full Claude agent (backend C)
  expect — substring that must appear in the page when the task succeeded

Targets are local self-contained pages so the benchmark times the *models*,
not a CDN.
"""
from dataclasses import dataclass
from pathlib import Path

from harness import Goto, Type, Click, Assert

_DIR = Path(__file__).parent / "demo_site"


def _uri(name: str) -> str:
    return (_DIR / name).resolve().as_uri()


@dataclass
class Scenario:
    name: str
    url: str
    steps: list
    goal: str
    expect: str


# ---- example 1: trivial single search box ----------------------------------
_Q = "wireless router"
SIMPLE = Scenario(
    name="simple-search",
    url=_uri("index.html"),
    steps=[
        Goto(_uri("index.html")),
        Type("the search text input box near the top", _Q),
        Click("the blue Search button"),
        Assert(f"Results for: {_Q}"),
    ],
    goal=(f"Search for '{_Q}' using the search box at the top of the page and "
          f"submit so results appear."),
    expect=f"Results for: {_Q}",
)

# ---- example 2: multi-step e-commerce checkout -----------------------------
# Exercises: nav between views, disambiguating ONE of four identical
# "Add to cart" buttons by product, and a 3-field checkout form.
CHECKOUT = Scenario(
    name="checkout-flow",
    url=_uri("shop.html"),
    steps=[
        Goto(_uri("shop.html")),
        Click("the 'Products' link in the top navigation bar"),
        Click("the 'Add to cart' button inside the Mechanical Keyboard product card"),
        Click("the 'Cart' link in the top navigation bar"),
        Click("the 'Proceed to checkout' button"),
        Type("the 'Full name' input field", "Ruslan Test"),
        Type("the 'Email' input field", "ruslan@example.com"),
        Type("the 'Shipping address' input field", "123 Demo Street"),
        Click("the 'Place order' button"),
        Assert("Order confirmed"),
    ],
    goal=("In this shop: open Products, add the **Mechanical Keyboard** (not any "
          "other product) to the cart, go to the Cart, proceed to checkout, then "
          "fill Full name='Ruslan Test', Email='ruslan@example.com', Shipping "
          "address='123 Demo Street', and click Place order."),
    expect="Order confirmed",
)

ALL = {s.name: s for s in (SIMPLE, CHECKOUT)}
DEFAULT = CHECKOUT.name
