"""
BAC BO API 路由。
"""

from datetime import datetime, timedelta

from flask import jsonify, request
from sqlalchemy import func

from app.database import RodadaBacBo, SessionLocal
from app.services.bacbo_service import BacBoService

from . import bacbo_bp

service = BacBoService()


@bacbo_bp.route("/api/bacbo/sync", methods=["POST"])
def sync_historical():
    data = request.get_json(silent=True) or {}
    limit = data.get("limit", 500)
    total = service.sincronizar_historico(limit)
    return jsonify({"status": "ok", "message": f"Sincronizadas até {limit} rodadas", "total": total})


@bacbo_bp.route("/api/bacbo/latest", methods=["GET"])
def get_latest():
    db = SessionLocal()
    try:
        ultima = db.query(RodadaBacBo).order_by(RodadaBacBo.data_hora.desc()).first()
        if ultima:
            return jsonify(
                {
                    "id": ultima.id,
                    "data_hora": ultima.data_hora.isoformat(),
                    "player_score": ultima.player_score,
                    "banker_score": ultima.banker_score,
                    "soma": ultima.soma,
                    "resultado": ultima.resultado,
                    "fonte": "banco",
                }
            )
    finally:
        db.close()
    return jsonify(service.get_latest_game())


@bacbo_bp.route("/api/bacbo/historical", methods=["GET"])
def get_historical():
    limit = request.args.get("limit", 100, type=int)
    offset = request.args.get("offset", 0, type=int)
    rodadas = service.get_rodadas_banco(limit, offset)
    return jsonify({"total": len(rodadas), "offset": offset, "limit": limit, "items": rodadas})


@bacbo_bp.route("/api/bacbo/train", methods=["POST"])
def train_model():
    return jsonify(service.treinar_modelo())


@bacbo_bp.route("/api/bacbo/predict", methods=["POST"])
def predict():
    data = request.get_json(silent=True) or {}
    ultimas_rodadas = data.get("ultimas_rodadas", [])
    if not ultimas_rodadas:
        db = SessionLocal()
        try:
            rodadas = db.query(RodadaBacBo).order_by(RodadaBacBo.data_hora.desc()).limit(10).all()
            ultimas_rodadas = [
                {
                    "id": rodada.id,
                    "resultado": rodada.resultado,
                    "soma": rodada.soma,
                    "data_hora": rodada.data_hora.isoformat(),
                }
                for rodada in reversed(rodadas)
            ]
        finally:
            db.close()
    return jsonify(service.prever_proxima_rodada(ultimas_rodadas))


@bacbo_bp.route("/api/bacbo/stats", methods=["GET"])
def get_stats():
    db = SessionLocal()
    try:
        total = db.query(func.count(RodadaBacBo.id)).scalar()
        distribuicao = (
            db.query(RodadaBacBo.resultado, func.count(RodadaBacBo.resultado).label("count"))
            .group_by(RodadaBacBo.resultado)
            .all()
        )
        desde = datetime.now() - timedelta(days=1)
        ultimas_24h = db.query(func.count(RodadaBacBo.id)).filter(RodadaBacBo.data_hora >= desde).scalar()
        return jsonify(
            {
                "total_rodadas": total,
                "ultimas_24h": ultimas_24h,
                "distribuicao": {resultado: count for resultado, count in distribuicao},
                "modelo_ativo": service.modelo_atual["versao"] if service.modelo_atual else None,
            }
        )
    finally:
        db.close()


@bacbo_bp.route("/api/bacbo/analyze/wave21", methods=["GET"])
def analyze_wave21():
    db = SessionLocal()
    try:
        rodadas = db.query(RodadaBacBo).order_by(RodadaBacBo.data_hora).all()
        return jsonify(service._detectar_onda_21(rodadas))
    finally:
        db.close()


@bacbo_bp.route("/api/bacbo/analyze/streaks", methods=["GET"])
def analyze_streaks():
    db = SessionLocal()
    try:
        rodadas = db.query(RodadaBacBo).order_by(RodadaBacBo.data_hora).all()
        return jsonify(service._analisar_streaks(rodadas))
    finally:
        db.close()
