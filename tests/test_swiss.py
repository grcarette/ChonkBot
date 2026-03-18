# tests/test_swiss.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from data.swiss import get_tier, SwissMethodsMixin

def test_get_tier_tier1():
    tier, points = get_tier(2100)
    assert tier == 1
    assert points == 2

def test_get_tier_tier2():
    tier, points = get_tier(1500)
    assert tier == 2
    assert points == 1

def test_get_tier_tier2_boundary():
    tier, points = get_tier(1400)
    assert tier == 2
    assert points == 1

def test_get_tier_tier3():
    tier, points = get_tier(1399)
    assert tier == 3
    assert points == 0

def test_get_tier_exactly_2000():
    tier, points = get_tier(2000)
    assert tier == 2
    assert points == 1