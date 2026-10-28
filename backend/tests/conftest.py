import pytest

from app.providers import DeterministicFallbackProvider, ProviderChain
from app.validation import SafetyValidator, default_world


@pytest.fixture
def world():
    return default_world()


@pytest.fixture
def validator(world):
    return SafetyValidator(world)


@pytest.fixture
def fallback():
    return DeterministicFallbackProvider()


@pytest.fixture
def chain():
    return ProviderChain([])
