from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional

import models
from database import SessionLocal, engine

models.Base.metadata.create_all(bind=engine)

class ProcessSchema(BaseModel):
    id: str
    name: str
    monitoring_path: str
    launch_path: str
    server_reset_time_str: Optional[str] = None
    user_cycle_hours: Optional[int] = 24
    mandatory_times_str: Optional[List[str]] = None
    is_mandatory_time_enabled: bool = False
    last_played_timestamp: Optional[float] = None
    original_launch_path: Optional[str] = None

class ProcessCreateSchema(BaseModel):
    name: str
    monitoring_path: str
    launch_path: str
    server_reset_time_str: Optional[str] = None
    user_cycle_hours: Optional[int] = 24
    mandatory_times_str: Optional[List[str]] = None
    is_mandatory_time_enabled: bool = False

from data_manager import DataManager
from data_models import ManagedProcess

app = FastAPI()
data_manager = DataManager()

@app.get("/processes", response_model=List[ProcessSchema])
def get_processes():
    return data_manager.managed_processes

@app.post("/processes", response_model=ProcessSchema, status_code=201)
def create_process(process_data: ProcessCreateSchema):
    process_dict = process_data.dict()
    new_process = ManagedProcess(**process_dict)
    data_manager.add_process(new_process)
    return new_process

@app.delete("/processes/{process_id}")
def delete_process(process_id: str):
    # DataManager의 삭제 메서드를 직접 호출합니다.
    # 이 메서드는 성공 시 True, 실패 시 False를 반환합니다.
    success = data_manager.remove_process(process_id)
    
    if success:
        return {"message": "프로세스가 삭제되었습니다."}
    else:
        raise HTTPException(status_code=404, detail="프로세스를 찾을 수 없습니다.")

@app.put("/processes/{process_id}", response_model=ProcessSchema)
# 입력받는 모델을 ProcessCreateSchema로 변경
def update_process(process_id: str, process_data: ProcessCreateSchema):
    # 1. 수정할 프로세스가 존재하는지 먼저 확인합니다.
    target_process = data_manager.get_process_by_id(process_id)
    if not target_process:
        raise HTTPException(status_code=404, detail="프로세스를 찾을 수 없습니다.")

    # 2. 입력받은 데이터(Pydantic 모델)를 딕셔너리로 변환합니다.
    update_data_dict = process_data.dict()
    
    # 3. 기존 객체의 내용을 새 내용으로 업데이트합니다.
    #    id는 기존 값을 그대로 유지합니다.
    for key, value in update_data_dict.items():
        setattr(target_process, key, value)
        
    # 4. DataManager의 업데이트 메서드를 호출하여 파일에 저장합니다.
    data_manager.update_process(target_process)
    
    return target_process
