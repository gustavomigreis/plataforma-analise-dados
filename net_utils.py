"""
Utilitário compartilhado para chamadas HTTP a APIs externas (IBGE, Comex
Stat, Banco Central), com retry automático em falhas transitórias de rede
(timeout, erro de conexão, falha de resolução de DNS) — observadas de forma
esporádica no ambiente de produção (Render, plano free), especialmente logo
após o serviço "acordar" de um período de inatividade.
"""
import time
import requests


def request_com_retry(metodo, url, tentativas=3, espera_inicial=1.5, **kwargs):
    """
    Executa uma requisição HTTP (requests.get ou requests.post) com retry
    exponencial em caso de falha de rede (ConnectionError, Timeout — o que
    inclui falhas de resolução de DNS, já que o requests as embrulha em
    ConnectionError).

    metodo: 'get' ou 'post'
    url: URL da requisição
    tentativas: número máximo de tentativas antes de desistir
    espera_inicial: segundos de espera antes da 2ª tentativa (dobra a cada retry)
    **kwargs: repassado para requests.get/post (json, params, timeout, etc.)
    """
    func = getattr(requests, metodo)
    ultimo_erro = None

    for tentativa in range(1, tentativas + 1):
        try:
            return func(url, **kwargs)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            ultimo_erro = e
            if tentativa < tentativas:
                time.sleep(espera_inicial * (2 ** (tentativa - 1)))

    raise ultimo_erro
