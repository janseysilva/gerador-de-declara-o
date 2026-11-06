"""Servidor que imita o Gier (só os endereços que o programa usa), com nomes INVENTADOS.

Uso: python testes/gier_falso.py 8765   e depois   GIER_BASE=http://127.0.0.1:8765
Entra com qualquer usuário e a senha "x". A 3ª turma devolve erro de propósito.
"""
import json, os, sys, tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pdf_gier_exemplo as ex

TURMAS = [{"id": 501, "descricao": "PE II -TURMA-E", "nomes": ex.NOMES[:3]},
          {"id": 502, "descricao": "PE I -TURMA-B", "nomes": ex.NOMES[3:]},
          {"id": 503, "descricao": "PE I -TURMA-Z (com erro)", "nomes": []}]
REGISTRO = []
NOMES_MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro",
               "Outubro", "Novembro", "Dezembro"]
DIAS = {"Agosto": 20, "Setembro": 19, "Outubro": 9}
FALHOU_UMA_VEZ = set()      # a 2ª turma responde 502 uma vez ao listar componentes, como o Gier de verdade

PAGINA_348 = """<html><head><title>Relatório de Frequência Diária</title></head><body>
<input type="hidden" value="27212" id="hdfIdEstrutura"><input type="hidden" value="999" id="hdfIPessoa">
<input type="hidden" value="USUARIO TESTE" id="hdfNomeUsuario">
<form id="formRelatorio"><div class="inv-grupo-campos">
<input type="hidden" id="IdRelatorio" data-parametro="IdRelatorio" value="348">
<input type="hidden" id="IdEscola" value="703">
<input type="hidden" id="Parametros" value="AnoLetivo;Mes;IdTurma;IdDisciplina;CompensacaoFalta">
<input type="hidden" data-id="24" data-descricao="Estrutura" data-parametro="IdEstrutura" value="27212">
<input type="hidden" data-id="25" data-descricao="Usuario" data-parametro="IdUsuario" value="999">
<input type="hidden" data-id="6" data-descricao="Escola" data-parametro="IdEscolas" value="703">
<input type="hidden" data-id="1" data-descricao="AnoLetivo" data-parametro="AnoLetivo" value="2026">
<input type="hidden" data-id="2" data-descricao="Escola" data-parametro="IdEscola" value="703">
<input type="hidden" data-id="19" data-descricao="Etapa/Modalidade" data-parametro="IdModalidade" value="">
<input type="hidden" data-id="3" data-descricao="Turma" data-parametro="IdTurma" value="">
<input type="hidden" data-id="78" data-descricao="TIPO DE FREQUENCIA" data-parametro="IdTipoComponente" value="">
<input type="hidden" data-id="15" data-descricao="Componente Curricular" data-parametro="IdDisciplina" value="">
<input type="hidden" data-id="11" data-descricao="Mes" data-parametro="mes" value="">
<div data-valor="-1" data-descricao="Todos"></div><div data-valor="1" data-descricao="Janeiro"></div>
<div data-valor="2" data-descricao="Fevereiro"></div><div data-valor="3" data-descricao="Março"></div>
<div data-valor="4" data-descricao="Abril"></div><div data-valor="5" data-descricao="Maio"></div>
<div data-valor="6" data-descricao="Junho"></div><div data-valor="7" data-descricao="Julho"></div>
<div data-valor="8" data-descricao="Agosto"></div><div data-valor="9" data-descricao="Setembro"></div>
<div data-valor="10" data-descricao="Outubro"></div><div data-valor="11" data-descricao="Novembro"></div>
<div data-valor="12" data-descricao="Dezembro"></div>
<input type="hidden" data-id="79" data-descricao="COMPENSAÇÃO DE FALTA" data-parametro="CompensacaoFalta" value="">
</div></form><h1>Relatório de Frequência Diária (Gier de teste)</h1>
</body></html>"""

PAGINA_LOGIN = """<html><body><h1>Login do Gier (teste)</h1><form method="post" action="/Login.aspx">
<input type="hidden" name="__VIEWSTATE" value="abc"><span id="lblErro">%s</span>
<input name="txtLogin"><input type="password" name="txtSenha1"><input type="submit" name="btnAcessar" value="Acessar">
</form></body></html>"""

PAGINA_HOME = """<html><head><title>Gier - Início</title></head><body><h1>Início do Gier (teste)</h1></body></html>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _tem(self, cookie):
        return cookie + "=" in (self.headers.get("Cookie") or "")

    def _logado(self):
        return self._tem(".AspNetCore.Cookies")

    def _enviar(self, corpo, tipo="text/html; charset=utf-8", status=200, extra=None):
        if isinstance(corpo, str):
            corpo = corpo.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self):
        REGISTRO.append(("GET", self.path))
        if self.path.startswith("/Relatorio/RelatorioFiltro/348"):
            if not self._logado():
                return self._enviar("", status=302, extra={"Location": "/Login"})
            return self._enviar(PAGINA_348)
        if self.path.startswith("/Login"):
            return self._enviar(PAGINA_LOGIN % "")
        if self.path.startswith("/Home"):
            return self._enviar(PAGINA_HOME)
        if self.path.startswith("/swap.aspx"):
            if not self._tem(".ASPXAUTH"):
                return self._enviar("", status=302, extra={"Location": "/login.aspx"})
            base = "http://" + self.headers["Host"]
            return self._enviar("<script>ChamarControlador('%s/Conta/Passagem', '{\"a\":1}', true);</script>" % base)
        if self.path.startswith("/Conta/Passagem"):
            return self._enviar("ok")
        if self.path.startswith("/relatorio/verificar-processamento"):
            return self._enviar(json.dumps({"processaJob": False}), "application/json")
        self._enviar("nada", status=404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        corpo = self.rfile.read(n)
        REGISTRO.append(("POST", self.path))
        if self.path == "/Login.aspx":
            if b"txtSenha1=x&" not in corpo + b"&":
                return self._enviar(PAGINA_LOGIN % "Usuário ou senha incorretos.")
            return self._enviar("", status=302, extra={"Location": "/Home", "Set-Cookie": ".ASPXAUTH=1; Path=/"})
        if self.path == "/Conta/LoginAuto":
            return self._enviar('{"success": true}', "application/json",
                                extra={"Set-Cookie": ".AspNetCore.Cookies=1; Path=/"})
        if not self._logado():
            return self._enviar("sem login", status=401)
        d = json.loads(corpo or b"{}")
        if self.path == "/Relatorio/RelatorioFiltro/PesquisarOpcoes":
            f = {}
            for x in d["Filtros"]:
                f.setdefault(x["Parametro"], x["Valor"])
            el = d["Elemento"]
            if el == "Etapa/Modalidade":
                assert f.get("AnoLetivo") == "2026" and f.get("IdEscola") == "703", f
                r = [{"id": 1, "descricao": "Educação Infantil"}]
            elif el == "Turma":
                assert f.get("IdModalidade") == "1", f
                r = [{"id": t["id"], "descricao": t["descricao"]} for t in TURMAS]
            elif el == "TIPO DE FREQUENCIA":
                r = [{"id": 2, "descricao": "FREQUÊNCIA POR COMPONENTE"}, {"id": 1, "descricao": "FREQUÊNCIA DIÁRIA"}]
            elif el == "Componente Curricular":
                if f.get("IdTurma") == "502" and "502" not in FALHOU_UMA_VEZ:
                    FALHOU_UMA_VEZ.add("502")
                    return self._enviar("bad gateway", status=502)
                # como no Gier de verdade: Educação Física vem primeiro, nos dois tipos; o programa deve ignorá-la
                r = [{"id": 208, "descricao": "EDUCAÇÃO FÍSICA"}, {"id": 549, "descricao": "EDUCAÇÃO INFANTIL"}]
            else:
                r = []
            return self._enviar(json.dumps(r), "application/json")
        if self.path == "/relatorio/imprimir":
            p = {x["Descricao"]: x["Valor"] for x in d["parametros"]}
            assert d["id"] == "348" and p["IdDisciplina"] == "549", p
            t = next(t for t in TURMAS if str(t["id"]) == p["IdTurma"])
            if not t["nomes"]:
                return self._enviar("erro interno", status=500)
            tmp = tempfile.mktemp(suffix=".pdf")
            if p["Mes"] == "-1":
                meses = [(m, DIAS[m]) for m in DIAS]
            else:
                pedidos = [NOMES_MESES[int(c) - 1] for c in p["Mes"].split(", ")]
                meses = [(m, DIAS.get(m, 0)) for m in pedidos]
            ex.gerar(tmp, t["descricao"], t["nomes"], meses)
            dados = open(tmp, "rb").read(); os.remove(tmp)
            return self._enviar(dados, "application/pdf")
        self._enviar("nada", status=404)


if __name__ == "__main__":
    porta = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    ThreadingHTTPServer(("127.0.0.1", porta), H).serve_forever()
