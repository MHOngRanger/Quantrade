"""Avellaneda-Stoikov quote model."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Quote:
    reservation_price: float
    bid: float
    ask: float
    spread: float


def reservation_price(
    mid: float,
    inventory: float,
    gamma: float,
    sigma2: float,
    tau: float,
) -> float:
    """Inventory-adjusted fair price."""
    return float(mid - inventory * gamma * sigma2 * tau)


def optimal_spread(gamma: float, sigma2: float, tau: float, kappa: float) -> float:
    """Symmetric optimal spread approximation."""
    risk_term = gamma * sigma2 * tau
    liquidity_term = (2.0 / gamma) * np.log1p(gamma / kappa) if gamma > 0 else 2.0 / kappa
    return float(max(risk_term + liquidity_term, 0.0))


def make_quote(
    mid: float,
    inventory: float,
    *,
    gamma: float = 0.1,
    sigma2: float = 1e-6,
    tau: float = 1.0,
    kappa: float = 1.5,
    tick_size: float = 0.01,
) -> Quote:
    """Return bid/ask quotes around an inventory-adjusted reservation price."""
    reserve = reservation_price(mid, inventory, gamma, sigma2, tau)
    spread = optimal_spread(gamma, sigma2, tau, kappa)
    bid = np.floor((reserve - spread / 2) / tick_size) * tick_size
    ask = np.ceil((reserve + spread / 2) / tick_size) * tick_size
    if bid >= ask:
        ask = bid + tick_size
    return Quote(
        reservation_price=float(reserve),
        bid=float(bid),
        ask=float(ask),
        spread=float(ask - bid),
    )

