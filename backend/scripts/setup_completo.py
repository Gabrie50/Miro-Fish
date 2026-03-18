#!/usr/bin/env python
"""
BAC BO 完整初始化脚本。
"""

import json
import logging
import os
import sys
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import RodadaBacBo, SessionLocal, init_db, salvar_rodada
from app.services.bacbo_service import BacBoService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def setup_completo():
    print("\n" + "=" * 60)
    print("🚀 CONFIGURAÇÃO COMPLETA DO MIROFISH PARA BAC BO")
    print("=" * 60)

    print("\n📦 1. Inicializando banco de dados...")
    init_db()

    print("\n📂 2. Carregando dados do arquivo rodadas.json...")
    caminho_json = Path(__file__).parent.parent / "data" / "bacbo" / "rodadas.json"
    if not caminho_json.exists():
        print(f"❌ Arquivo não encontrado: {caminho_json}")
        print("Por favor, coloque seu arquivo rodadas.json em backend/data/bacbo/")
        return

    with caminho_json.open("r", encoding="utf-8") as arquivo:
        dados = json.load(arquivo)
    print(f"✅ Carregadas {len(dados)} rodadas do arquivo")

    print("\n💾 3. Salvando dados no banco...")
    db = SessionLocal()
    try:
        for item in dados:
            salvar_rodada(db, item)
        print("✅ Dados salvos com sucesso!")
    finally:
        db.close()

    print("\n🧠 4. Treinando modelo com as 7 camadas da tese...")
    service = BacBoService()
    modelo = service.treinar_modelo()
    if "erro" in modelo:
        print(f"❌ {modelo['erro']}")
        return

    print("\n📊 RESULTADO DO TREINAMENTO:")
    print(f"   Total de rodadas: {modelo['total_rodadas']}")
    print(
        "   Distribuição: "
        f"PLAYER {modelo['distribuicao_resultados']['PLAYER']}% | "
        f"BANKER {modelo['distribuicao_resultados']['BANKER']}% | "
        f"TIE {modelo['distribuicao_resultados']['TIE']}%"
    )
    print(f"   Acurácia teórica: {modelo['acuracia_teorica']}%")

    print("\n🔮 5. Testando previsão...")
    db = SessionLocal()
    try:
        ultimas = db.query(RodadaBacBo).order_by(RodadaBacBo.data_hora.desc()).limit(5).all()
        ultimas_dict = [
            {"id": rodada.id, "resultado": rodada.resultado, "soma": rodada.soma}
            for rodada in reversed(ultimas)
        ]
        previsao = service.prever_proxima_rodada(ultimas_dict)
        print(f"   Últimos resultados: {[item['resultado'] for item in ultimas_dict]}")
        print(f"   Previsão: {previsao['previsao']} (confiança: {previsao['confianca'] * 100:.1f}%)")
        print(f"   Probabilidades: {previsao['probabilidades']}")
    finally:
        db.close()

    print("\n" + "=" * 60)
    print("✅ CONFIGURAÇÃO COMPLETA FINALIZADA!")
    print("=" * 60)
    print("\nAPIs disponíveis:")
    print("  GET  /api/bacbo/latest         - Último resultado")
    print("  GET  /api/bacbo/historical     - Histórico paginado")
    print("  POST /api/bacbo/sync           - Sincroniza da API")
    print("  POST /api/bacbo/train          - Treina modelo")
    print("  POST /api/bacbo/predict        - Faz previsão")
    print("  GET  /api/bacbo/stats          - Estatísticas")
    print("  GET  /api/bacbo/analyze/wave21 - Análise onda 21")
    print("  GET  /api/bacbo/analyze/streaks - Análise streaks")


if __name__ == "__main__":
    setup_completo()
