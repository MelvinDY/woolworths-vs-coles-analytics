"""Brand tier: is this a store brand or a name brand?

The one place in the repo that answers that question, because v3 splits every
backfill measure by it and a second definition living somewhere else is how the
two halves of a split quietly stop adding up.

Why the split matters
---------------------
Private label and national brand are not two samples of the same thing. A
national brand is the *same physical good* on both shelves, so a gap between the
chains is a pricing decision about an identical product. A store brand is only
ever a substitute — Coles Tasty Cheese and Woolworths Tasty Cheese are different
products from different suppliers, and a gap between them is as much a recipe,
pack and sourcing difference as a pricing one.

Mixing them makes the headline measure ambiguous. A parity rate over the pooled
set answers neither "how hard do they match each other on the same product" nor
"how differently do they price their own ranges", and v2's aisle finding is
exactly the kind of result that could be produced by nothing more than a
changing private-label share across aisles.

Two mechanisms, deliberately kept apart
---------------------------------------
`OWN_BRAND_FIELDS` is matched against the retailer's own `brand` *field*, which
the live collector gets from the retailer APIs. It is frozen: v2's matcher uses
it, docs/reconciliation.md promises no published pair moved, and widening it
would move pairs.

`OWN_BRAND_PREFIXES` is matched against the leading tokens of a product *name*,
because the Hot Prices backfill carries no brand field at all (see PRD-v3 §5.1).
It is a different mechanism answering the same question, so it gets its own
vocabulary and its own tests.

Both lists are deliberately conservative. A store brand this module fails to
recognise is counted as a name brand, which dilutes the name-brand group and
makes any store-vs-name difference *harder* to detect. That is the safe
direction to be wrong in: the error works against the hypothesis rather than
for it. Being wrong the other way — calling a national brand a store brand —
would manufacture the finding, so the lists contain only unambiguous names.
"""

from __future__ import annotations

import re

NATIONAL = "national_brand"
OWN = "own_brand"

# Matched against the retailer-supplied `brand` field. FROZEN — see module
# docstring. matching/match_products.py imports this and v2's accepted pairs
# depend on it exactly as written.
OWN_BRAND_FIELDS: dict[str, set[str]] = {
    "woolworths": {"woolworths", "essentials", "macro", "macro organic"},
    "coles": {"coles", "coles simply", "coles finest", "coles natures kitchen", "coles kitchen"},
}

# Matched against the leading tokens of a product name, for sources with no
# brand field. Longest first so 'coles simply' wins over 'coles' when both
# would match — the tier is the same either way, but the recorded prefix should
# be the most specific one that applies.
OWN_BRAND_PREFIXES: dict[str, tuple[str, ...]] = {
    "woolworths": (
        "woolworths",       # covers Woolworths Gold, Woolworths Bakery, Woolworths Free From
        "essentials",
        "macro",            # covers Macro Organic, Macro Free Range
        "homebrand",        # retired, still present in older history
        "the odd bunch",
        "delicious nutritious",
    ),
    "coles": (
        "coles",            # covers Coles Simply / Finest / Organic / Kitchen / Bakery / Perform
        "smart buy",        # retired, still present in older history
        "you'll love coles",
        "urban coffee culture",
    ),
}


def norm_text(s: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace.

    Identical to matching/match_products.norm_text. Duplicated as the canonical
    copy here rather than imported from there, because that module imports this
    one and the dependency has to point one way.
    """
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def is_own_brand_field(retailer: str, brand: str) -> bool:
    """Store-brand test against a retailer-supplied brand field. v2's rule."""
    return norm_text(brand) in OWN_BRAND_FIELDS.get(retailer, set())


def own_brand_prefix(retailer: str, name: str) -> str | None:
    """Return the store-brand prefix a product name starts with, or None.

    Anchored at the start of the name on purpose. 'Coles Tasty Cheese' is a
    store brand; 'Birds Eye Chips For Coles Bakery' is not, and an unanchored
    contains-test would call it one.
    """
    n = norm_text(name)
    for prefix in sorted(OWN_BRAND_PREFIXES.get(retailer, ()), key=len, reverse=True):
        p = norm_text(prefix)
        if n == p or n.startswith(p + " "):
            return p
    return None


def brand_tier_from_name(retailer: str, name: str) -> str:
    """'own_brand' or 'national_brand', derived from the product name."""
    return OWN if own_brand_prefix(retailer, name) else NATIONAL


def brand_token_from_name(retailer: str, name: str) -> str:
    """The token used as a brand proxy when no brand field exists.

    For a store brand this is the matched prefix, so 'Coles Simply Baked Beans'
    and 'Coles Baked Beans' agree on 'coles' rather than disagreeing on
    'coles simply'. For everything else it is the first token of the name,
    which is where Hot Prices puts the brand — 'Cadbury Favourites ...',
    'Huggies Gentle Cleanse ...'.

    A first token is a proxy, not a brand field, and PRD-v3 FR-4 requires the
    derivation to be published alongside any match set built on it.
    """
    prefix = own_brand_prefix(retailer, name)
    if prefix:
        return prefix.split(" ")[0]
    n = norm_text(name)
    return n.split(" ")[0] if n else ""


def strip_own_brand(retailer: str, name: str) -> str:
    """Product name with its store-brand prefix removed.

    Used only when scoring a store brand against the *other* chain's store
    brand. 'Woolworths Jasmine Rice' and 'Coles Jasmine Rice' describe the same
    good, and leaving the retailer token in place penalises the very comparison
    the own-brand tier exists to make.
    """
    n = norm_text(name)
    prefix = own_brand_prefix(retailer, name)
    if prefix and n.startswith(prefix + " "):
        return n[len(prefix) + 1:]
    return n
