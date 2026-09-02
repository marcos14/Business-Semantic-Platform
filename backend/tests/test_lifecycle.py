import pytest

from app.kernel.errors import InvalidTransitionError
from app.kernel.ir.envelope import LifecycleStatus as S
from app.kernel.lifecycle import (
    TRANSITIONS,
    is_system_only,
    requires_authority,
    validate_transition,
)


def test_caminho_automatico_valido():
    # §99: CANDIDATE → ... → AUTO_APPROVED → CANONICAL
    validate_transition(S.CANDIDATE, S.CORROBORATING)
    validate_transition(S.CORROBORATING, S.READY_FOR_EVALUATION)
    validate_transition(S.READY_FOR_EVALUATION, S.AUTO_APPROVED)
    validate_transition(S.AUTO_APPROVED, S.CANONICAL)


def test_caminho_humano_valido():
    # §100: READY → NEEDS_HUMAN_REVIEW → IN_REVIEW → DECISION_PENDING → CANONICAL
    validate_transition(S.READY_FOR_EVALUATION, S.NEEDS_HUMAN_REVIEW)
    validate_transition(S.NEEDS_HUMAN_REVIEW, S.IN_REVIEW)
    validate_transition(S.IN_REVIEW, S.DECISION_PENDING)
    validate_transition(S.DECISION_PENDING, S.CANONICAL)


def test_transicoes_invalidas():
    with pytest.raises(InvalidTransitionError):
        validate_transition(S.CANDIDATE, S.CANONICAL)  # pular o funil
    with pytest.raises(InvalidTransitionError):
        validate_transition(S.REJECTED, S.CANDIDATE)  # terminal
    with pytest.raises(InvalidTransitionError):
        validate_transition(S.SUPERSEDED, S.CANONICAL)  # terminal
    with pytest.raises(InvalidTransitionError):
        validate_transition(S.CANONICAL, S.REJECTED)  # canonical só supersede (§74)


def test_todos_os_estados_mapeados():
    assert set(TRANSITIONS) == set(S)


def test_guards():
    assert requires_authority(S.CANONICAL)
    assert requires_authority(S.SUPERSEDED)
    assert not requires_authority(S.IN_REVIEW)
    assert is_system_only(S.AUTO_APPROVED)
    assert not is_system_only(S.CANONICAL)


def test_estados_terminais():
    assert TRANSITIONS[S.REJECTED] == frozenset()
    assert TRANSITIONS[S.SUPERSEDED] == frozenset()
