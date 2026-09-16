import json
from typing import List, Dict
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

DATABASE_URL = "sqlite:///./max_logic.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password = Column(String)

Base.metadata.create_all(bind=engine)

app = FastAPI(title="ML Secrets Server")

class UserAuth(BaseModel):
    username: str
    password: str

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, username: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[username] = websocket

    def disconnect(self, username: str):
        if username in self.active_connections:
            del self.active_connections[username]

    async def broadcast(self, message: dict):
        payload = json.dumps(message)
        for connection in self.active_connections.values():
            await connection.send_text(payload)

    async def send_direct(self, target_user: str, message: dict):
        if target_user in self.active_connections:
            await self.active_connections[target_user].send_text(json.dumps(message))

manager = ConnectionManager()

@app.post("/register")
def register(user: UserAuth):
    db = SessionLocal()
    if db.query(User).filter(User.username == user.username).first():
        db.close()
        raise HTTPException(status_code=400, detail="Usuário já existe.")
    db.add(User(username=user.username, password=user.password))
    db.commit()
    db.close()
    return {"message": "Sucesso"}

@app.post("/login")
def login(user: UserAuth):
    db = SessionLocal()
    db_user = db.query(User).filter(User.username == user.username, User.password == user.password).first()
    db.close()
    if not db_user:
        raise HTTPException(status_code=401, detail="Credenciais inválidas.")
    return {"message": "Sucesso", "username": user.username}

@app.websocket("/ws/chat/{username}")
async def websocket_endpoint(websocket: WebSocket, username: str):
    await manager.connect(username, websocket)
    await manager.broadcast({"type": "system", "content": f"📢 {username} entrou no grupo!"})
    try:
        while True:
            raw_data = await websocket.receive_text()
            data = json.loads(raw_data)
            data["sender"] = username
            
            # Encaminhamento por tipo de mensagem
            if data.get("type") in ["text", "sticker", "reaction", "poll_create", "poll_vote"]:
                await manager.broadcast(data)
            elif data.get("type") in ["call_offer", "call_answer", "ice_candidate"]:
                await manager.send_direct(data.get("target"), data)
    except WebSocketDisconnect:
        manager.disconnect(username)
        await manager.broadcast({"type": "system", "content": f"📢 {username} saiu do grupo."})
