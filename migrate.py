# migrate.py

import crud
import schemas
from data_manager import DataManager
from database import SessionLocal

print("데이터 마이그레이션을 시작합니다...")

# 1. 데이터 소스(JSON)와 목적지(DB)를 준비합니다.
db = SessionLocal()
local_data_manager = DataManager()

# 2. 로컬 JSON 파일에서 ManagedProcess 목록을 가져옵니다.
local_processes = local_data_manager.managed_processes
print(f"JSON 파일에서 {len(local_processes)}개의 프로세스 데이터를 찾았습니다.")

migrated_count = 0
skipped_count = 0

# 3. 각 프로세스를 순회하며 DB로 옮깁니다.
for process in local_processes:
    # 3-1. DB에 이미 같은 ID의 데이터가 있는지 확인합니다.
    existing_process = crud.get_process_by_id(db, process_id=process.id)
    
    if existing_process:
        # 이미 존재하면 건너뜁니다.
        # print(f"'{process.name}' (ID: {process.id}) 프로세스는 이미 DB에 존재하므로 건너뜁니다.")
        skipped_count += 1
        continue
    
    # 3-2. 기존 객체를 API 입력 형식(Pydantic 모델)으로 변환합니다.
    # 이렇게 하면 기존 CRUD 로직을 재사용할 수 있습니다.
    process_schema = schemas.ProcessCreateSchema(
        name=process.name,
        monitoring_path=process.monitoring_path,
        launch_path=process.launch_path,
        server_reset_time_str=process.server_reset_time_str,
        user_cycle_hours=process.user_cycle_hours,
        mandatory_times_str=process.mandatory_times_str,
        is_mandatory_time_enabled=process.is_mandatory_time_enabled
        # last_played_timestamp, original_launch_path 등 필요한 모든 필드를 추가
    )
    
    # 3-3. CRUD 함수를 사용해 DB에 새로운 프로세스를 생성합니다.
    crud.create_process(db, process=process_schema)
    print(f"✅ '{process.name}' (ID: {process.id}) 프로세스를 DB로 마이그레이션했습니다.")
    migrated_count += 1

print("\n마이그레이션 완료!")
print(f"총 {migrated_count}개의 데이터가 DB로 옮겨졌습니다.")
print(f"{skipped_count}개의 데이터는 이미 존재하여 건너뛰었습니다.")

# 4. 각 웹 바로가기를 순회하며 DB로 옮깁니다.
for shortcut in local_data_manager.web_shortcuts:
    existing_shortcut = crud.get_shortcut_by_id(db, shortcut_id=shortcut.id)
    if existing_shortcut:
        # 이미 존재하면 건너뜁니다.
        # print(f"'{shortcut.name}' (ID: {shortcut.id}) 웹 바로 가기는 이미 DB에 존재하므로 건너뜁니다.")
        skipped_count += 1
        continue

    shortcut_schema = schemas.WebShortcutCreate(
        name=shortcut.name,
        url=shortcut.url,
        refresh_time_str=shortcut.refresh_time_str,
        last_reset_timestamp=shortcut.last_reset_timestamp
    )
    crud.create_shortcut(db, shortcut=shortcut_schema)
    print(f"✅ '{shortcut.name}' (ID: {shortcut.id}) 웹 바로 가기를 DB로 마이그레이션했습니다.")
    migrated_count += 1

print("\n마이그레이션 완료!")
print(f"총 {migrated_count}개의 데이터가 DB로 옮겨졌습니다.")
print(f"{skipped_count}개의 데이터는 이미 존재하여 건너뛰었습니다.")

local_settings = local_data_manager.global_settings
print(f"\n[GlobalSettings] JSON 파일에서 설정을 불러왔습니다.")

settings_schema = schemas.GlobalSettingsSchema(**local_settings.to_dict())
crud.update_settings(db, settings=settings_schema)

print(f"-> GlobalSettings를 DB에 업데이트했습니다.")


# 5. 마무리
print("\n모든 데이터 마이그레이션이 완료되었습니다!")
db.close()
