from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()

# Pydantic 모델 정의
class Homework(BaseModel):
    subject: str
    title: str
    due_date: str

fake_homeworks_db = [
    {"id": 1, "subject": "수학", "title": "1단원 연습문제 풀기", "due_date": "2025-09-24"},
    {"id": 2, "subject": "과학", "title": "실험 보고서 작성", "due_date": "2025-09-26"},
    {"id": 3, "subject": "파이썬", "title": "FastAPI 프로젝트 시작하기", "due_date": "2025-09-30"},
]

# 기본 주소 ("/") API - 기존과 동일
@app.get("/")
def read_root():
    return {"message": "연습용 예제 프로젝트임"}

# 과제 목록을 보여주는 API
@app.get("/homeworks")
def get_homeworks():
    return fake_homeworks_db

# 과제를 추가하는 API
@app.post("/homeworks")
def create_homework(homework: Homework):

    new_id = fake_homeworks_db[-1]["id"] + 1
    complete_homework = {"id": new_id, **homework.dict()}
    fake_homeworks_db.append(complete_homework)

    return complete_homework

@app.get("/homeworks/{homework_id}")
def get_homework(homework_id: int):
    for homework in fake_homeworks_db:
        if homework["id"] == homework_id:
            return homework
        
    return None

@app.delete("/homeworks/{homework_id}")
def delete_homework(homework_id: int):
    for index, homework in enumerate(fake_homeworks_db):
        if homework["id"] == homework_id:
            fake_homeworks_db.pop(index)
            return {"message": "과제가 삭제되었습니다."}
        
    raise HTTPException(status_code=404, detail="과제를 찾을 수 없습니다.")

@app.put("/homeworks/{homework_id}")
def update_homework(homework_id: int, updated_homework: Homework):
    for index, homework in enumerate(fake_homeworks_db):
        if homework["id"] == homework_id:
            updated_data = {"id": homework_id, **updated_homework.dict()}
            fake_homeworks_db[index] = updated_data
            return updated_data
        
    raise HTTPException(status_code=404, detail="과제를 찾을 수 없습니다.")