"""
BAC BO 数据库配置与模型定义。
"""

import os
from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, Integer, String, Text, create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///mirofish_bacbo.db")

engine_kwargs = {
    "pool_pre_ping": True,
}

if not DATABASE_URL.startswith("sqlite"):
    engine_kwargs.update(
        {
            "pool_size": 10,
            "max_overflow": 20,
        }
    )

engine = create_engine(DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class RodadaBacBo(Base):
    """存储 BAC BO 真实历史轮次。"""

    __tablename__ = "rodadas_bacbo"

    id = Column(String(50), primary_key=True)
    data_hora = Column(DateTime, nullable=False)
    player_score = Column(Integer, nullable=False)
    banker_score = Column(Integer, nullable=False)
    soma = Column(Integer, nullable=False)
    resultado = Column(String(10), nullable=False)
    dados_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class PrevisaoMiroFish(Base):
    """存储 MiroFish 预测记录。"""

    __tablename__ = "previsoes_mirofish"

    id = Column(Integer, primary_key=True, autoincrement=True)
    rodada_anterior_id = Column(String(50), nullable=True)
    resultado_anterior = Column(String(10), nullable=True)
    soma_anterior = Column(Integer, nullable=True)
    previsao = Column(String(10), nullable=False)
    probabilidades = Column(JSON, nullable=False)
    confianca = Column(Float, nullable=False)
    resultado_real = Column(String(10), nullable=True)
    acertou = Column(Boolean, nullable=True)
    modelo_versao = Column(String(50), default="7-camadas-v1")
    created_at = Column(DateTime, default=datetime.utcnow)


class ModeloTreinado(Base):
    """存储训练好的模型版本。"""

    __tablename__ = "modelos_treinados"

    id = Column(Integer, primary_key=True, autoincrement=True)
    versao = Column(String(50), nullable=False, unique=True)
    matriz_transicao = Column(JSON, nullable=False)
    distribuicao_resultados = Column(JSON, nullable=False)
    regras_por_soma = Column(JSON, nullable=False)
    tese_completa = Column(Text, nullable=False)
    acuracia_treinamento = Column(Float)
    total_rodadas = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)


class AnaliseEstatistica(Base):
    """存储聚合统计分析。"""

    __tablename__ = "analises_estatisticas"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tipo_analise = Column(String(50), nullable=False)
    parametros = Column(JSON, nullable=False)
    resultados = Column(JSON, nullable=False)
    periodo_inicio = Column(DateTime)
    periodo_fim = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)


def get_db():
    """生成数据库会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """创建所有表。"""
    Base.metadata.create_all(bind=engine)
    print("✅ Banco de dados BAC BO inicializado com sucesso!")


def salvar_rodada(db: Session, rodada: dict):
    """插入新轮次；若已存在则直接返回。"""
    existente = db.query(RodadaBacBo).filter(RodadaBacBo.id == rodada["id"]).first()
    if existente:
        return existente

    data_hora_raw = rodada["data_hora"]
    if data_hora_raw.endswith("Z"):
        data_hora_raw = data_hora_raw.replace("Z", "+00:00")

    nova_rodada = RodadaBacBo(
        id=rodada["id"],
        data_hora=datetime.fromisoformat(data_hora_raw),
        player_score=rodada["player_score"],
        banker_score=rodada["banker_score"],
        soma=rodada["soma"],
        resultado=rodada["resultado"],
        dados_json=rodada["dados_json"],
    )
    db.add(nova_rodada)
    db.commit()
    return nova_rodada
