import csv
import io
import os
import time

from fastapi import FastAPI, File, HTTPException, UploadFile
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, create_engine, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class Dataset(Base):
    __tablename__ = "datasets"
    id = Column(Integer, primary_key=True)
    nome = Column(String, nullable=False)
    criado_em = Column(DateTime, server_default=func.now())


class Registro(Base):
    __tablename__ = "registros"
    id = Column(Integer, primary_key=True)
    dataset_id = Column(
        Integer, ForeignKey("datasets.id", ondelete="CASCADE"), index=True
    )
    dados = Column(JSONB, nullable=False)


# Espera o banco ficar pronto antes de criar as tabelas
for _ in range(10):
    try:
        Base.metadata.create_all(engine)
        break
    except OperationalError:
        time.sleep(2)

app = FastAPI(title="Serviço de Dados")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/datasets", status_code=201)
async def criar_dataset(arquivo: UploadFile = File(...)):
    if not arquivo.filename.endswith(".csv"):
        raise HTTPException(400, "Envie um arquivo .csv")

    conteudo = (await arquivo.read()).decode("utf-8")
    linhas = list(csv.DictReader(io.StringIO(conteudo)))
    if not linhas:
        raise HTTPException(400, "CSV vazio")

    with SessionLocal() as db:
        ds = Dataset(nome=arquivo.filename)
        db.add(ds)
        db.flush()
        for linha in linhas:
            # string vazia vira None (nulo de verdade)
            dados = {k: (v if v != "" else None) for k, v in linha.items()}
            db.add(Registro(dataset_id=ds.id, dados=dados))
        db.commit()
        return {"id": ds.id, "nome": ds.nome, "total_registros": len(linhas)}


@app.get("/datasets")
def listar_datasets():
    with SessionLocal() as db:
        resultado = (
            db.query(Dataset.id, Dataset.nome, Dataset.criado_em, func.count(Registro.id))
            .outerjoin(Registro, Registro.dataset_id == Dataset.id)
            .group_by(Dataset.id)
            .all()
        )
        return [
            {"id": i, "nome": n, "criado_em": c, "total_registros": t}
            for i, n, c, t in resultado
        ]


@app.get("/datasets/{dataset_id}/registros")
def listar_registros(dataset_id: int, limit: int = 1000, offset: int = 0):
    with SessionLocal() as db:
        if not db.get(Dataset, dataset_id):
            raise HTTPException(404, "Dataset não encontrado")
        registros = (
            db.query(Registro.dados)
            .filter(Registro.dataset_id == dataset_id)
            .order_by(Registro.id)
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [r[0] for r in registros]