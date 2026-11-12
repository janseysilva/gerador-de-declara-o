# -*- coding: utf-8 -*-
"""
Aviso de versão nova.

Ao abrir, o programa pergunta ao GitHub qual é a última versão publicada. Se for maior que a que está
rodando, aparece uma faixa com o botão "Baixar". O programa NUNCA baixa nem instala nada sozinho: o botão só
abre o link no navegador, e quem instala é a pessoa.

Como funciona a pergunta: o endereço ".../releases/latest" do GitHub redireciona para ".../releases/tag/v2.13-build30";
a versão é lida desse endereço final (sem login e sem o limite da API do GitHub). Qualquer falha (sem internet,
GitHub fora do ar, endereço inesperado) simplesmente não mostra aviso nenhum.

Para o aviso funcionar, toda versão publicada precisa ter número MAIOR que a anterior em VERSAO_PROGRAMA
(declaracoes_escolares.py): o aviso compara só o número da versão, não o número do "build".
"""
import re
import threading
import urllib.request

REPOSITORIO = "https://github.com/janseysilva/gerador-de-declara-o"
URL_ULTIMA = REPOSITORIO + "/releases/latest"
URL_BAIXAR = REPOSITORIO + "/releases/latest/download/Instalador_DeclaracoesEscolares.exe"


def _numeros(versao):
    """'2.12' -> (2, 12, 0): três números, para comparar 2.10 com 2.9 do jeito certo."""
    partes = [int(p) for p in re.findall(r"\d+", versao or "")][:3]
    return tuple(partes + [0] * (3 - len(partes))) if partes else ()


def mais_nova(publicada, atual):
    """True só se a versão publicada for MAIOR que a que está rodando."""
    a, b = _numeros(publicada), _numeros(atual)
    return bool(a) and bool(b) and a > b


def versao_publicada(timeout=8):
    """A última versão publicada ('2.13'), ou None se não deu para saber."""
    try:
        pedido = urllib.request.Request(URL_ULTIMA, method="HEAD", headers={"User-Agent": "DeclaracoesEscolares"})
        with urllib.request.urlopen(pedido, timeout=timeout) as resposta:
            final = resposta.geturl()
    except Exception:
        return None
    achou = re.search(r"/tag/v?(\d+(?:\.\d+)*)", final or "")
    return achou.group(1) if achou else None


class Conferencia:
    """Pergunta ao GitHub em segundo plano (a janela não trava). Quem chamou olha .pronta e .nova."""

    def __init__(self, atual):
        self.atual = atual
        self.pronta = False
        self.nova = None            # '2.13' quando existe versão mais nova que a atual
        threading.Thread(target=self._rodar, daemon=True).start()

    def _rodar(self):
        try:
            publicada = versao_publicada()
            if publicada and mais_nova(publicada, self.atual):
                self.nova = publicada
        except Exception:
            pass
        finally:
            self.pronta = True
