"""Reagendamento por franquia: espera até o horário de reset informado pelo harness."""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.jobs import RESET_DEFAULT_SECONDS, RESET_MAX_SECONDS, delay_until_reset

SP = ZoneInfo("America/Sao_Paulo")


def test_sem_horario_usa_padrao():
    assert delay_until_reset(None) == RESET_DEFAULT_SECONDS
    assert delay_until_reset("Session limit reached") == RESET_DEFAULT_SECONDS


def test_le_horario_e_fuso_da_mensagem():
    agora = datetime(2026, 9, 2, 21, 30, tzinfo=SP)
    msg = "You've hit your session limit · resets 10:30pm (America/Sao_Paulo)"
    assert delay_until_reset(msg, agora) == 3600 + 60  # 1h até 22:30 + folga


def test_reset_ja_passou_hoje_vai_para_amanha_com_teto():
    agora = datetime(2026, 9, 2, 23, 0, tzinfo=SP)
    msg = "session limit · resets 10:30pm (America/Sao_Paulo)"
    assert delay_until_reset(msg, agora) == RESET_MAX_SECONDS  # 23h30 até amanhã → teto 6h


def test_formatos_am_e_sem_minutos():
    agora = datetime(2026, 9, 2, 8, 0, tzinfo=SP)
    assert delay_until_reset("resets 9am (America/Sao_Paulo)", agora) == 3600 + 60
    assert delay_until_reset("resets at 12am (America/Sao_Paulo)", agora) == RESET_MAX_SECONDS
