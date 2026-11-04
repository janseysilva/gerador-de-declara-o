"""
Busca a frequência no Gier sozinha (botão "Atualizar frequência do Gier").

Como funciona:
  1. Abre o Chrome (ou o Edge, se não houver Chrome) numa janela só do programa,
     já na página do relatório "Acompanhamento Diário" (relatório 348).
  2. A pessoa entra com usuário e senha. O programa não vê nem guarda a senha:
     só espera a página do relatório aparecer.
  3. De dentro da página já logada, faz as mesmas chamadas que a própria página
     do Gier faz (veja RelatorioFiltro.js e relatorio-imprimir.js do Gier):
       POST /Relatorio/RelatorioFiltro/PesquisarOpcoes  -> etapas, turmas...
       GET  /relatorio/verificar-processamento          -> se vai para a fila
       POST /relatorio/imprimir                         -> o PDF
     e devolve o PDF de cada turma, com todos os meses.

O navegador é controlado pelo "DevTools Protocol" (o mesmo que os testes de
site usam), com a pasta de perfil própria do programa: o login pode ficar
lembrado de uma vez para a outra.
"""
import base64
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

GIER_BASE = os.environ.get("GIER_BASE", "https://app-manaus-mvc-prd-frontend-001.azurewebsites.net")
ID_RELATORIO = "348"


class Cancelado(Exception):
    pass


class ErroGier(Exception):
    pass


def url_relatorio():
    return GIER_BASE.rstrip("/") + "/Relatorio/RelatorioFiltro/" + ID_RELATORIO


# ---------------------------------------------------------------------------
# Achar o navegador
# ---------------------------------------------------------------------------

def _caminhos_registro(exe):
    if not sys.platform.startswith("win"):
        return []
    caminhos = []
    try:
        import winreg
        chave = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths" + "\\" + exe
        for raiz in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(raiz, chave) as k:
                    caminhos.append(winreg.QueryValue(k, None))
            except OSError:
                pass
    except Exception:
        pass
    return caminhos


def achar_navegador():
    """(nome, caminho) do Chrome ou, se não houver, do Edge. None se não achar."""
    if os.environ.get("GIER_NAVEGADOR"):
        return "Navegador", os.environ["GIER_NAVEGADOR"]
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    local = os.environ.get("LOCALAPPDATA", "")
    chrome = _caminhos_registro("chrome.exe") + [
        os.path.join(pf, r"Google\Chrome\Application\chrome.exe"),
        os.path.join(pf86, r"Google\Chrome\Application\chrome.exe"),
        os.path.join(local, r"Google\Chrome\Application\chrome.exe"),
    ]
    edge = _caminhos_registro("msedge.exe") + [
        os.path.join(pf86, r"Microsoft\Edge\Application\msedge.exe"),
        os.path.join(pf, r"Microsoft\Edge\Application\msedge.exe"),
    ]
    for nome, lista in (("Chrome", chrome), ("Edge", edge)):
        for caminho in lista:
            if caminho and os.path.isfile(caminho):
                return nome, caminho
    return None


# ---------------------------------------------------------------------------
# Conversa com o navegador (DevTools Protocol)
# ---------------------------------------------------------------------------

def _porta_livre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Navegador:
    def __init__(self, caminho_exe, pasta_perfil, url):
        os.makedirs(pasta_perfil, exist_ok=True)
        self.porta = _porta_livre()
        args = [caminho_exe,
                "--remote-debugging-port={}".format(self.porta),
                "--remote-allow-origins=*",
                "--user-data-dir={}".format(pasta_perfil),
                "--no-first-run", "--no-default-browser-check",
                "--disable-features=Translate",
                "--new-window", url]
        if os.environ.get("GIER_NAVEGADOR_EXTRA"):          # usado nos testes (Linux)
            args[1:1] = os.environ["GIER_NAVEGADOR_EXTRA"].split()
        criar = 0x08000000 if sys.platform.startswith("win") else 0   # CREATE_NO_WINDOW
        self.processo = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                         creationflags=criar)
        self._ws = None
        self._ws_url = None
        self._id = 0
        fim = time.time() + 30
        while time.time() < fim:
            try:
                self._json("/json/version")
                return
            except Exception:
                if self.processo.poll() is not None:
                    raise ErroGier("O navegador fechou logo ao abrir.")
                time.sleep(0.3)
        raise ErroGier("O navegador não respondeu.")

    def _json(self, caminho):
        with urllib.request.urlopen("http://127.0.0.1:{}{}".format(self.porta, caminho), timeout=5) as r:
            return json.loads(r.read().decode("utf-8"))

    def abas(self):
        try:
            return [t for t in self._json("/json/list") if t.get("type") == "page"]
        except Exception:
            if self.processo.poll() is not None:
                raise Cancelado("A janela do navegador foi fechada.")
            return []

    def fechado(self):
        return self.processo.poll() is not None

    def usar_aba(self, aba):
        import websocket
        url = aba["webSocketDebuggerUrl"]
        if url == self._ws_url and self._ws is not None:
            return
        self._fechar_ws()
        self._ws = websocket.create_connection(url, timeout=10, suppress_origin=True)
        self._ws_url = url

    def _fechar_ws(self):
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass
        self._ws = None
        self._ws_url = None

    def comando(self, metodo, params=None, espera=30):
        import websocket
        self._id += 1
        meu = self._id
        self._ws.send(json.dumps({"id": meu, "method": metodo, "params": params or {}}))
        fim = time.time() + espera
        while True:
            restante = fim - time.time()
            if restante <= 0:
                raise ErroGier("O Gier demorou demais para responder.")
            self._ws.settimeout(min(restante, 5))
            try:
                msg = json.loads(self._ws.recv())
            except websocket.WebSocketTimeoutException:
                continue
            except Exception:
                self._fechar_ws()
                if self.fechado():
                    raise Cancelado("A janela do navegador foi fechada.")
                raise ErroGier("Perdi a conexão com a página do Gier.")
            if msg.get("id") == meu:
                if "error" in msg:
                    raise ErroGier(msg["error"].get("message", "erro do navegador"))
                return msg.get("result", {})

    def avaliar(self, expressao, espera=30):
        r = self.comando("Runtime.evaluate", {"expression": expressao, "awaitPromise": True,
                                              "returnByValue": True}, espera=espera)
        if r.get("exceptionDetails"):
            det = r["exceptionDetails"]
            texto = (det.get("exception") or {}).get("description") or det.get("text") or "erro"
            raise ErroGier("Erro na página do Gier: " + texto.splitlines()[0])
        return (r.get("result") or {}).get("value")

    def ir_para(self, url):
        self.comando("Page.navigate", {"url": url})

    def fechar(self):
        try:
            if self._ws is not None:
                self.comando("Browser.close", espera=5)
        except Exception:
            pass
        self._fechar_ws()
        try:
            self.processo.wait(timeout=5)
        except Exception:
            try:
                self.processo.terminate()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# O que roda dentro da página do Gier (mesmas chamadas da página)
# ---------------------------------------------------------------------------

JS_ESTADO = r"""(() => {
  const r = document.getElementById('IdRelatorio');
  const p = document.getElementById('hdfIPessoa');
  return {rel: r ? r.value : null, pessoa: p ? p.value : null, url: location.href,
          pronto: document.readyState};
})()"""

JS_FUNCOES = r"""
window.__decl = window.__decl || {};
__decl.base = function (sobrescrever) {
  const lista = [];
  const usados = new Set();
  document.querySelectorAll('[data-parametro]').forEach(h => {
    const p = h.dataset.parametro;
    let v = (p in sobrescrever) ? String(sobrescrever[p]) : (h.value || '');
    usados.add(p);
    v.split(',').forEach(x => lista.push({Parametro: p, Valor: x}));
  });
  Object.keys(sobrescrever).forEach(p => {
    if (!usados.has(p)) lista.push({Parametro: p, Valor: String(sobrescrever[p])});
  });
  return lista;
};
__decl.opcoes = async function (elemento, sobrescrever) {
  const r = await fetch('/Relatorio/RelatorioFiltro/PesquisarOpcoes', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({Elemento: elemento, Filtros: __decl.base(sobrescrever)})
  });
  if (!r.ok) throw new Error('PesquisarOpcoes ' + elemento + ': ' + r.status);
  return await r.json();
};
__decl.valor = function (param, padrao) {
  const h = document.querySelector('[data-parametro="' + param + '"][data-id]') ||
            document.querySelector('[data-parametro="' + param + '"]');
  return (h && h.value) ? h.value : padrao;
};
__decl.sem = function (t) {
  return String(t || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toUpperCase();
};
__decl.ordenar = function (lista, preferidos) {
  const nota = o => { const d = __decl.sem(o.descricao); const i = preferidos.findIndex(p => d.includes(p));
                      return i < 0 ? preferidos.length : i; };
  return (lista || []).slice().sort((a, b) => nota(a) - nota(b));
};
true
"""

JS_TURMAS = r"""(async () => {
  const ano = __decl.valor('AnoLetivo', String(new Date().getFullYear()));
  const escola = __decl.valor('IdEscola', (document.getElementById('IdEscola') || {}).value || '');
  const fixos = {AnoLetivo: ano, IdEscola: escola};
  const etapas = await __decl.opcoes('Etapa/Modalidade', fixos);
  const turmas = [];
  for (const e of etapas) {
    const ts = await __decl.opcoes('Turma', Object.assign({}, fixos, {IdModalidade: e.id}));
    ts.forEach(t => turmas.push({etapa: e.id, etapa_nome: e.descricao, id: t.id, nome: t.descricao}));
  }
  return {ano: ano, escola: escola, turmas: turmas};
})()"""

JS_PDF = r"""(async (args) => {
  const fixos = {AnoLetivo: args.ano, IdEscola: args.escola, IdModalidade: args.etapa, IdTurma: args.turma};
  // tipo de frequência e componente: procura o "AULA DIA" (o mesmo do relatório feito à mão)
  const tipos = __decl.ordenar(await __decl.opcoes('TIPO DE FREQUENCIA', fixos), ['DIARI', 'DIA', 'GERAL']);
  if (!tipos.length) return {erro: 'o Gier não mostrou o tipo de frequência'};
  let tipo = null, disc = null;
  for (const t of tipos) {
    const discs = __decl.ordenar(await __decl.opcoes('Componente Curricular',
                                 Object.assign({}, fixos, {IdTipoComponente: t.id})), ['AULA DIA', 'DIA']);
    if (!discs.length) continue;
    if (!tipo) { tipo = t; disc = discs[0]; }
    if (__decl.sem(discs[0].descricao).includes('AULA DIA')) { tipo = t; disc = discs[0]; break; }
  }
  if (!disc) return {erro: 'o Gier não mostrou o componente curricular'};

  const v = await fetch('/relatorio/verificar-processamento?idRelatorio=348');
  let fila = false;
  if (v.ok) { try { fila = (await v.json()).processaJob === true; } catch (e) {} }

  const p = [
    {Descricao: 'AnoLetivo', Valor: String(args.ano)},
    {Descricao: 'IdTurma', Valor: String(args.turma)},
    {Descricao: 'IdDisciplina', Valor: String(disc.id)},
    {Descricao: 'Mes', Valor: '-1'},
    {Descricao: 'CompensacaoFalta', Valor: '1'},
    {Descricao: 'DataReferencia', Valor: new Date().toISOString().split('T')[0]},
    {Descricao: 'IdEstrutura', Valor: document.getElementById('hdfIdEstrutura').value},
    {Descricao: 'IdUsuario', Valor: document.getElementById('hdfIPessoa').value},
  ];
  const info = {tipo: tipo.descricao, disciplina: disc.descricao};
  if (fila) return {fila: true, info: info};
  p.push({Descricao: 'nomeusuario', Valor: (document.getElementById('hdfNomeUsuario') || {}).value || ''});
  p.push({Descricao: 'urlorigem', Valor: window.location.origin.toLowerCase() + ' '});
  const r = await fetch('/relatorio/imprimir', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({id: '348', nome: 'Relatório GIER', parametros: p, tipo: '0'})
  });
  if (!r.ok) return {erro: 'imprimir: ' + r.status, info: info};
  const bytes = new Uint8Array(await r.arrayBuffer());
  let bin = '';
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return {pdf: btoa(bin), info: info};
})(%s)"""


# ---------------------------------------------------------------------------
# O passo a passo inteiro (roda numa thread; avisa o andamento por `avisar`)
# ---------------------------------------------------------------------------

def buscar_frequencia(pasta_perfil, pasta_pdfs, avisar, cancelado, minutos_login=10):
    """
    Devolve (lista de caminhos de PDF, lista de problemas).
    avisar(texto) mostra o andamento; cancelado() -> True para parar.
    """
    nav_info = achar_navegador()
    if not nav_info:
        raise ErroGier("Não achei o Google Chrome nem o Microsoft Edge neste computador.")
    nome_nav, exe = nav_info
    avisar("Abrindo o {}...".format(nome_nav))
    nav = Navegador(exe, pasta_perfil, url_relatorio())
    try:
        # 1. Espera o login (a pessoa digita usuário e senha na janela)
        avisar("Entre com o seu usuário e senha do Gier na janela do {}.".format(nome_nav))
        fim = time.time() + minutos_login * 60
        aba_ok = None
        ultimo_ir = 0
        while aba_ok is None:
            if cancelado():
                raise Cancelado("Cancelado.")
            if time.time() > fim:
                raise ErroGier("Passaram {} minutos sem entrar no Gier.".format(minutos_login))
            for aba in nav.abas():
                if not aba.get("url", "").lower().startswith(GIER_BASE.lower()):
                    continue
                try:
                    nav.usar_aba(aba)
                    estado = nav.avaliar(JS_ESTADO, espera=10) or {}
                except ErroGier:
                    continue
                if estado.get("rel") == ID_RELATORIO and estado.get("pronto") == "complete":
                    aba_ok = aba
                    break
                # já logado, mas em outra página do Gier: vai para o relatório
                if estado.get("pessoa") not in (None, "", "0") and time.time() - ultimo_ir > 8:
                    nav.ir_para(url_relatorio())
                    ultimo_ir = time.time()
            if aba_ok is None:
                time.sleep(1.5)

        # 2. Lista as turmas
        avisar("Entrou no Gier. Procurando as turmas...")
        nav.avaliar(JS_FUNCOES)
        dados = nav.avaliar(JS_TURMAS, espera=60) or {}
        turmas = dados.get("turmas") or []
        if not turmas:
            raise ErroGier("O Gier não mostrou nenhuma turma para esta escola.")

        # 3. Um PDF por turma, com todos os meses
        os.makedirs(pasta_pdfs, exist_ok=True)
        caminhos, problemas = [], []
        for n, t in enumerate(turmas, 1):
            if cancelado():
                raise Cancelado("Cancelado.")
            avisar("Baixando a frequência: turma {} de {} ({})".format(n, len(turmas), t["nome"]))
            args = json.dumps({"ano": dados["ano"], "escola": dados["escola"], "etapa": t["etapa"],
                               "turma": t["id"]})
            try:
                nav.avaliar(JS_FUNCOES)
                r = nav.avaliar(JS_PDF % args, espera=240) or {}
            except ErroGier as erro:
                problemas.append("{}: {}".format(t["nome"], erro))
                continue
            if r.get("fila"):
                problemas.append("{}: o Gier mandou o relatório para a fila de processamento".format(t["nome"]))
                continue
            if not r.get("pdf"):
                problemas.append("{}: {}".format(t["nome"], r.get("erro") or "sem PDF"))
                continue
            dados_pdf = base64.b64decode(r["pdf"])
            if not dados_pdf.startswith(b"%PDF"):
                problemas.append("{}: o Gier não devolveu um PDF".format(t["nome"]))
                continue
            nome_arq = "".join(c if c.isalnum() else "_" for c in t["nome"]).strip("_") or "turma"
            caminho = os.path.join(pasta_pdfs, "{:02d}_{}.pdf".format(n, nome_arq))
            with open(caminho, "wb") as f:
                f.write(dados_pdf)
            caminhos.append(caminho)
        return caminhos, problemas
    finally:
        nav.fechar()
