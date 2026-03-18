"""
BAC BO 采集、训练与预测服务。
"""

import json
import logging
import threading
from datetime import datetime
from typing import Callable

import requests
import websocket
from sqlalchemy.orm import Session

from app.config import Config
from app.database import (
    AnaliseEstatistica,
    ModeloTreinado,
    PrevisaoMiroFish,
    RodadaBacBo,
    SessionLocal,
    salvar_rodada,
)

logger = logging.getLogger(__name__)


class BacBoService:
    """BAC BO 全量服务。"""

    def __init__(self):
        self.api_url = Config.BACBO_API_URL
        self.latest_url = Config.BACBO_LATEST_URL
        self.ws_url = Config.BACBO_WS_URL

        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "MiroFish-BACBO/1.0",
                "Accept": "application/json",
            }
        )

        self.tese = self._carregar_tese()
        self.modelo_atual = None
        self.carregar_modelo_mais_recente()

    def _carregar_tese(self) -> dict:
        return {
            "versao": "7-camadas-v1",
            "camadas": {
                "1_rng_base": {"descricao": "4 dados (2 player, 2 banker), cada 1-6", "regras": {}},
                "2_onda_21": {
                    "descricao": "Onda senoidal a cada 21 rodadas",
                    "formula": "onda = 0.1 * sin(2 * pi * rodada / 21)",
                    "desvio_maximo": 0.1,
                },
                "3_ciclo_20": {"descricao": "Reset completo a cada 20 rodadas", "regras": {}},
                "4_memoria_streak": {
                    "descricao": "Reversão após 3+ vitórias",
                    "limiar_streak": 3,
                    "fator_correcao": 0.05,
                },
                "5_equilibrio_longo": {
                    "descricao": "Controle de equilíbrio 50/50",
                    "limiar_diferenca": 5,
                    "fator_ajuste": 0.01,
                },
                "6_padrao_gemeo": {"descricao": "Números migram entre rodadas", "fator_migracao": 0.3},
                "7_padrao_72": {
                    "descricao": "7:2 após duplo TIE",
                    "gatilho": ["TIE", "TIE"],
                    "proporcao": 0.777,
                    "duracao": 9,
                },
            },
            "matriz_transicao_teorica": {
                "PLAYER": {"PLAYER": 41.9, "BANKER": 45.5, "TIE": 12.5},
                "BANKER": {"PLAYER": 45.1, "BANKER": 43.1, "TIE": 11.9},
                "TIE": {"PLAYER": 46.1, "BANKER": 39.1, "TIE": 14.7},
            },
            "regras_por_soma": {
                "4-5": {"tendencia": "BANKER", "prob_min": 46, "prob_max": 48},
                "6-8": {"tendencia": "PLAYER", "prob_min": 47, "prob_max": 49},
                "9": {"tendencia": "EQUILIBRIO", "prob_min": 45, "prob_max": 45},
                "10-13": {"tendencia": "BANKER", "prob_min": 46, "prob_max": 50},
                "14-18": {"tendencia": "PLAYER", "prob_min": 45, "prob_max": 49},
                "19-21": {"tendencia": "BANKER", "prob_min": 46, "prob_max": 49},
                "22-24": {"tendencia": "PLAYER", "prob_min": 46, "prob_max": 50},
            },
            "regra_de_ouro": {"condicao": "empate_com_soma_6", "probabilidade_player": 52},
        }

    def get_latest_game(self) -> dict:
        try:
            response = self.session.get(self.latest_url, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            logger.error("Erro ao buscar último jogo: %s", exc)
            return {}

    def get_historical_games(self, limit: int = 100) -> list[dict]:
        try:
            response = self.session.get(self.api_url, params={"limit": limit}, timeout=10)
            response.raise_for_status()
            return response.json().get("items", [])
        except Exception as exc:
            logger.error("Erro ao buscar histórico: %s", exc)
            return []

    def stream_websocket(self, callback: Callable):
        def on_message(_, message):
            try:
                data = json.loads(message)
                callback(self._formatar_rodada(data))
            except Exception as exc:
                logger.error("Erro WebSocket: %s", exc)

        ws = websocket.WebSocketApp(
            self.ws_url,
            on_message=on_message,
            on_error=lambda _, error: logger.error("WS error: %s", error),
        )
        thread = threading.Thread(target=ws.run_forever, daemon=True)
        thread.start()
        return ws

    def _formatar_rodada(self, data: dict) -> dict:
        player_score = data.get("playerScore", 0)
        banker_score = data.get("bankerScore", 0)
        return {
            "id": data.get("id"),
            "player_score": player_score,
            "banker_score": banker_score,
            "resultado": (
                "PLAYER"
                if player_score > banker_score
                else "BANKER" if banker_score > player_score else "TIE"
            ),
            "soma": player_score + banker_score,
            "data_hora": data.get("settledAt"),
            "dados_completos": data,
        }

    def sincronizar_historico(self, limit: int = 500):
        db = SessionLocal()
        try:
            dados = self.get_historical_games(limit)
            for item in dados:
                rodada = self._formatar_rodada(item.get("data", {}))
                rodada["id"] = item.get("id", rodada["id"])
                rodada["dados_json"] = item
                if rodada["id"] and rodada["data_hora"]:
                    salvar_rodada(db, rodada)
            logger.info("✅ Sincronizadas %s rodadas", len(dados))
            return len(dados)
        finally:
            db.close()

    def get_rodadas_banco(self, limit: int = 100, offset: int = 0) -> list[dict]:
        db = SessionLocal()
        try:
            rodadas = (
                db.query(RodadaBacBo)
                .order_by(RodadaBacBo.data_hora.desc())
                .limit(limit)
                .offset(offset)
                .all()
            )
            return [
                {
                    "id": rodada.id,
                    "data_hora": rodada.data_hora.isoformat(),
                    "player_score": rodada.player_score,
                    "banker_score": rodada.banker_score,
                    "soma": rodada.soma,
                    "resultado": rodada.resultado,
                }
                for rodada in rodadas
            ]
        finally:
            db.close()

    def treinar_modelo(self, db: Session | None = None) -> dict:
        close_db = db is None
        db = db or SessionLocal()
        try:
            rodadas = db.query(RodadaBacBo).order_by(RodadaBacBo.data_hora).all()
            if len(rodadas) < 10:
                return {"erro": "Poucos dados para treinamento"}

            matriz = {
                "PLAYER": {"PLAYER": 0, "BANKER": 0, "TIE": 0},
                "BANKER": {"PLAYER": 0, "BANKER": 0, "TIE": 0},
                "TIE": {"PLAYER": 0, "BANKER": 0, "TIE": 0},
            }
            for indice in range(len(rodadas) - 1):
                atual = rodadas[indice].resultado
                proxima = rodadas[indice + 1].resultado
                matriz[atual][proxima] += 1

            for estado, transicoes in matriz.items():
                total = sum(transicoes.values())
                if total > 0:
                    for chave in transicoes:
                        matriz[estado][chave] = round(transicoes[chave] / total * 100, 1)

            total = len(rodadas)
            distribuicao = {
                "PLAYER": round(sum(1 for rodada in rodadas if rodada.resultado == "PLAYER") / total * 100, 1),
                "BANKER": round(sum(1 for rodada in rodadas if rodada.resultado == "BANKER") / total * 100, 1),
                "TIE": round(sum(1 for rodada in rodadas if rodada.resultado == "TIE") / total * 100, 1),
            }

            soma_stats = {}
            for soma in range(4, 25):
                rodadas_soma = [rodada for rodada in rodadas if rodada.soma == soma]
                if rodadas_soma:
                    player = sum(1 for rodada in rodadas_soma if rodada.resultado == "PLAYER")
                    banker = sum(1 for rodada in rodadas_soma if rodada.resultado == "BANKER")
                    total_soma = len(rodadas_soma)
                    soma_stats[str(soma)] = {
                        "player_pct": round(player / total_soma * 100, 1),
                        "banker_pct": round(banker / total_soma * 100, 1),
                        "total": total_soma,
                    }

            onda_stats = self._detectar_onda_21(rodadas)
            streak_stats = self._analisar_streaks(rodadas)
            padrao72_stats = self._analisar_padrao_72(rodadas)

            modelo = {
                "versao": f"7-camadas-{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                "total_rodadas": total,
                "matriz_transicao_real": matriz,
                "matriz_transicao_teorica": self.tese["matriz_transicao_teorica"],
                "distribuicao_resultados": distribuicao,
                "analise_por_soma": soma_stats,
                "onda_21": onda_stats,
                "streaks": streak_stats,
                "padrao_72": padrao72_stats,
                "acuracia_teorica": self._calcular_acuracia_teorica(matriz),
                "tese_utilizada": self.tese,
            }

            novo_modelo = ModeloTreinado(
                versao=modelo["versao"],
                matriz_transicao=matriz,
                distribuicao_resultados=distribuicao,
                regras_por_soma=soma_stats,
                tese_completa=json.dumps(self.tese, ensure_ascii=False, indent=2),
                acuracia_treinamento=modelo["acuracia_teorica"],
                total_rodadas=total,
            )
            db.add(novo_modelo)
            db.add(
                AnaliseEstatistica(
                    tipo_analise="treinamento_modelo",
                    parametros={"versao": modelo["versao"]},
                    resultados={
                        "onda_21": onda_stats,
                        "streaks": streak_stats,
                        "padrao_72": padrao72_stats,
                    },
                )
            )
            db.commit()
            self.modelo_atual = modelo
            logger.info("✅ Modelo treinado: versão %s", modelo["versao"])
            return modelo
        finally:
            if close_db:
                db.close()

    def _detectar_onda_21(self, rodadas: list) -> dict:
        if len(rodadas) < 21:
            return {"detectado": False, "motivo": "poucos_dados"}
        ciclos = []
        for indice in range(0, len(rodadas) - 20, 21):
            ciclo = rodadas[indice : indice + 21]
            player_count = sum(1 for rodada in ciclo if rodada.resultado == "PLAYER")
            ciclos.append(player_count / 21 * 100)
        return {
            "detectado": True,
            "num_ciclos": len(ciclos),
            "variacao_media": max(ciclos) - min(ciclos) if ciclos else 0,
            "amplitude_esperada": 10,
        }

    def _analisar_streaks(self, rodadas: list) -> dict:
        streaks = {"PLAYER": [], "BANKER": []}
        atual = None
        count = 0
        for rodada in rodadas:
            if rodada.resultado == atual and rodada.resultado in ["PLAYER", "BANKER"]:
                count += 1
            else:
                if atual in streaks and count >= 3:
                    streaks[atual].append(count)
                atual = rodada.resultado if rodada.resultado in ["PLAYER", "BANKER"] else None
                count = 1
        if atual in streaks and count >= 3:
            streaks[atual].append(count)
        return {
            "player_max": max(streaks["PLAYER"]) if streaks["PLAYER"] else 0,
            "banker_max": max(streaks["BANKER"]) if streaks["BANKER"] else 0,
            "media_player": sum(streaks["PLAYER"]) / len(streaks["PLAYER"]) if streaks["PLAYER"] else 0,
            "media_banker": sum(streaks["BANKER"]) / len(streaks["BANKER"]) if streaks["BANKER"] else 0,
        }

    def _analisar_padrao_72(self, rodadas: list) -> dict:
        detectados = 0
        for indice in range(len(rodadas) - 2):
            if rodadas[indice].resultado == "TIE" and rodadas[indice + 1].resultado == "TIE":
                nao_ties = [rodada for rodada in rodadas[indice + 2 : indice + 11] if rodada.resultado != "TIE"]
                if len(nao_ties) >= 3:
                    detectados += 1
        return {"detectado": detectados > 0, "total_ocorrencias": detectados}

    def _calcular_acuracia_teorica(self, matriz_real: dict) -> float:
        total = 0
        acertos = 0
        teorica = self.tese["matriz_transicao_teorica"]
        for estado, transicoes in matriz_real.items():
            for proximo, valor in transicoes.items():
                if estado in teorica and proximo in teorica[estado]:
                    if abs(valor - teorica[estado][proximo]) < 5:
                        acertos += 1
                    total += 1
        return round(acertos / total * 100, 1) if total else 0

    def prever_proxima_rodada(self, ultimas_rodadas: list[dict]) -> dict:
        if not self.modelo_atual:
            self.treinar_modelo()
        if not self.modelo_atual:
            return {"erro": "Modelo não treinado"}

        db = SessionLocal()
        try:
            ultimo = ultimas_rodadas[-1] if ultimas_rodadas else None
            base_probs = (
                self.modelo_atual["matriz_transicao_real"].get(ultimo["resultado"], {})
                if ultimo
                else self.modelo_atual["distribuicao_resultados"]
            )
            base_probs = dict(base_probs)

            if ultimo and "soma" in ultimo:
                soma_stats = self.modelo_atual.get("analise_por_soma", {}).get(str(ultimo["soma"]), {})
                if soma_stats:
                    base_probs = {
                        "PLAYER": soma_stats.get("player_pct", base_probs.get("PLAYER", 33)),
                        "BANKER": soma_stats.get("banker_pct", base_probs.get("BANKER", 33)),
                        "TIE": 100 - (soma_stats.get("player_pct", 0) + soma_stats.get("banker_pct", 0)),
                    }

            if len(ultimas_rodadas) >= 3:
                streak = self._detectar_streak(ultimas_rodadas[-3:])
                if streak and streak["tamanho"] >= 3:
                    oposta = "BANKER" if streak["cor"] == "PLAYER" else "PLAYER"
                    for chave in list(base_probs.keys()):
                        if chave == oposta:
                            base_probs[chave] = min(base_probs.get(chave, 0) + 5, 100)
                        elif chave == streak["cor"]:
                            base_probs[chave] = max(base_probs.get(chave, 0) - 5, 0)

            if (
                len(ultimas_rodadas) >= 2
                and ultimas_rodadas[-2]["resultado"] == "TIE"
                and ultimas_rodadas[-1]["resultado"] == "TIE"
            ):
                tendencia_anterior = self._detectar_tendencia(ultimas_rodadas[:-2])
                if tendencia_anterior:
                    base_probs = {
                        tendencia_anterior: 77.7,
                        "BANKER" if tendencia_anterior == "PLAYER" else "PLAYER": 22.3,
                        "TIE": 0,
                    }

            total = sum(base_probs.values())
            if total > 0:
                base_probs = {chave: round(valor / total * 100, 1) for chave, valor in base_probs.items()}

            previsao = max(base_probs, key=lambda chave: base_probs[chave])
            confianca = base_probs[previsao] / 100

            nova_previsao = PrevisaoMiroFish(
                rodada_anterior_id=ultimo["id"] if ultimo else None,
                resultado_anterior=ultimo["resultado"] if ultimo else None,
                soma_anterior=ultimo["soma"] if ultimo else None,
                previsao=previsao,
                probabilidades=base_probs,
                confianca=confianca,
                modelo_versao=self.modelo_atual["versao"],
            )
            db.add(nova_previsao)
            db.commit()

            return {
                "previsao": previsao,
                "probabilidades": base_probs,
                "confianca": confianca,
                "modelo_versao": self.modelo_atual["versao"],
                "id_previsao": nova_previsao.id,
            }
        finally:
            db.close()

    def _detectar_streak(self, rodadas: list[dict]) -> dict | None:
        if len(rodadas) < 3:
            return None
        primeira = rodadas[0]["resultado"]
        if primeira not in ["PLAYER", "BANKER"]:
            return None
        if any(rodada["resultado"] != primeira for rodada in rodadas[1:]):
            return None
        return {"cor": primeira, "tamanho": len(rodadas)}

    def _detectar_tendencia(self, rodadas: list[dict]) -> str | None:
        if not rodadas:
            return None
        player_count = sum(1 for rodada in rodadas if rodada["resultado"] == "PLAYER")
        banker_count = sum(1 for rodada in rodadas if rodada["resultado"] == "BANKER")
        if player_count > banker_count * 1.5:
            return "PLAYER"
        if banker_count > player_count * 1.5:
            return "BANKER"
        return None

    def carregar_modelo_mais_recente(self):
        db = SessionLocal()
        try:
            modelo = db.query(ModeloTreinado).order_by(ModeloTreinado.created_at.desc()).first()
            if modelo:
                self.modelo_atual = {
                    "versao": modelo.versao,
                    "matriz_transicao_real": modelo.matriz_transicao,
                    "distribuicao_resultados": modelo.distribuicao_resultados,
                    "analise_por_soma": modelo.regras_por_soma,
                    "total_rodadas": modelo.total_rodadas,
                }
                logger.info("✅ Modelo carregado: %s", modelo.versao)
        finally:
            db.close()
