"""실행 중 GUI/API 없이 기존 명조 연결을 이동하고 선택 파일의 수명을 검증한다."""
from __future__ import annotations

from types import MethodType

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.data import crud, models
from src.utils.wuwa_config import WuwaConfig


pytestmark = pytest.mark.usefixtures('resource_test_isolation')
ACCOUNT = 'waveplate@Asia@799900001'
OTHER = 'waveplate@Asia@799900002'
# collection은 클래스 정의만 읽는다. 공용 차단 이후 명시적 tmp 인스턴스에만 원본을 결합한다.
ORIGINAL = {name: getattr(WuwaConfig, name) for name in (
    'load_selected_resource_key', 'save_account', 'clear_account', 'exists', 'remove_created_account')}


def temp_config(tmp_path):
    config = WuwaConfig(config_dir=tmp_path / 'provider-config')
    assert config.config_path.is_relative_to(tmp_path)
    for name, function in ORIGINAL.items():
        setattr(config, name, MethodType(function, config))
    return config


@pytest.fixture
def legacy(tmp_path):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        db.add(models.GlobalSettings(id=1, media_auto_bgm=False))
        db.add(models.Process(id='legacy-game', name='기존 명조', monitoring_path='/fixture/wuwa.exe', launch_path='/fixture/wuwa.exe',
                              resource_tracking_enabled=True, resource_provider='wuwa', resource_key=ACCOUNT,
                              resource_current=240, resource_max=240, resource_reserve_current=120,
                              resource_reserve_max=480, resource_updated_at=1700000000, resource_status='ok'))
        db.add(models.Process(id='other-game', name='다른 게임', monitoring_path='/fixture/other.exe', launch_path='/fixture/other.exe',
                              resource_tracking_enabled=True, resource_provider='nikke_blablalink', resource_key='nikke_outpost_storage',
                              resource_percent=42.0))
        db.add(models.ProcessSession(id=11, process_id='legacy-game', process_name='기존 명조', start_timestamp=1699996400,
                                    end_timestamp=1700000000, session_duration=3600, resource_percent_at_end=50,
                                    session_status='closed'))
        db.commit()
    yield sessions, temp_config(tmp_path)
    engine.dispose()


def snapshot(db):
    def rows(model):
        return [{column.name: getattr(row, column.name) for column in model.__table__.columns}
                for row in db.query(model).order_by(model.id)]
    return {'settings': rows(models.GlobalSettings), 'sessions': rows(models.ProcessSession),
            'other': {column.name: getattr(db.get(models.Process, 'other-game'), column.name)
                      for column in models.Process.__table__.columns},
            'ids': [row.id for row in db.query(models.Process).order_by(models.Process.id)]}


def test_offline_unique_legacy_migration_preserves_values_ids_sessions_settings_and_is_idempotent(legacy):
    sessions, config = legacy
    assert not config.exists()
    with sessions() as db:
        before = snapshot(db)
        result = crud.configure_wuwa_link(db, migrate=True, config=config)
        assert result['connected'] and result['migrated'] and result['normalized_count'] == 1
        row = db.get(models.Process, 'legacy-game')
        assert (row.resource_key, row.resource_current, row.resource_reserve_current) == ('waveplate', 240, 120)
        assert snapshot(db) == before
        assert config.load_selected_resource_key() == ACCOUNT
        stored = config.config_path.read_bytes()
        second = crud.configure_wuwa_link(db, migrate=True, config=config)
        assert second['normalized_count'] == second['cleared_count'] == 0 and not second['migrated']
        assert config.config_path.read_bytes() == stored and snapshot(db) == before


def test_explicit_null_persists_on_reopen_and_never_relinks_legacy_account(legacy, tmp_path):
    sessions, config = legacy
    assert config.clear_account() and config.exists()
    reopened = temp_config(tmp_path)
    assert reopened.exists() and reopened.load_selected_resource_key() is None
    with sessions() as db:
        before = snapshot(db)
        result = crud.configure_wuwa_link(db, migrate=True, config=reopened)
        assert not result['connected']
        row = db.get(models.Process, 'legacy-game')
        assert row.resource_key == 'waveplate' and row.resource_current is None and row.resource_reserve_current is None
        assert reopened.exists() and reopened.load_selected_resource_key() is None and snapshot(db) == before


def test_ambiguous_legacy_accounts_require_selection_and_preserve_history(legacy):
    sessions, config = legacy
    with sessions() as db:
        db.add(models.Process(id='legacy-second', name='두 번째 명조', monitoring_path='/fixture/second.exe', launch_path='/fixture/second.exe',
                              resource_tracking_enabled=True, resource_provider='wuwa', resource_key=OTHER,
                              resource_current=100, resource_max=240))
        db.commit()
        before = snapshot(db)
        result = crud.configure_wuwa_link(db, migrate=True, config=config)
        assert result['selection_required'] and not result['connected']
        assert config.exists() and config.load_selected_resource_key() is None
        for row in db.query(models.Process).filter(models.Process.resource_provider == 'wuwa'):
            assert row.resource_key == 'waveplate' and row.resource_current is None
        assert snapshot(db) == before


def test_failed_commit_restores_absent_config_and_legacy_data_before_retry(legacy, monkeypatch):
    sessions, config = legacy
    with sessions() as db:
        before = snapshot(db)
        with monkeypatch.context() as scoped:
            def fail(): raise RuntimeError('fixture commit failure')
            scoped.setattr(db, 'commit', fail)
            with pytest.raises(RuntimeError, match='fixture commit failure'):
                crud.configure_wuwa_link(db, migrate=True, config=config)
        assert not config.exists()
        row = db.get(models.Process, 'legacy-game')
        assert (row.resource_key, row.resource_current, row.resource_reserve_current) == (ACCOUNT, 240, 120)
        assert snapshot(db) == before
        result = crud.configure_wuwa_link(db, migrate=True, config=config)
        assert result['connected'] and config.load_selected_resource_key() == ACCOUNT


def test_temp_config_restart_roundtrip_distinguishes_absence_selected_and_explicit_null(tmp_path):
    config = temp_config(tmp_path)
    assert not config.exists() and config.load_selected_resource_key() is None
    assert config.save_account(ACCOUNT)
    reopened = temp_config(tmp_path)
    assert reopened.exists() and reopened.load_selected_resource_key() == ACCOUNT
    assert reopened.clear_account()
    again = temp_config(tmp_path)
    assert again.exists() and again.load_selected_resource_key() is None
    assert config.config_path.read_text().strip() == '{"selected_resource_key": null}'


def test_default_config_io_is_blocked_before_any_explicit_temp_instance():
    config = WuwaConfig()
    for method, arguments in [('exists', ()), ('load_selected_resource_key', ()),
                              ('save_account', (ACCOUNT,)), ('clear_account', ()), ('remove_created_account', ())]:
        with pytest.raises(AssertionError, match='실제 인증'):
            getattr(config, method)(*arguments)
