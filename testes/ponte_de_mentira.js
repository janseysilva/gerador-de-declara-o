// Servidor de mentira para testar a ponte de acessos SEM usar o Google.
//
// Carrega o código REAL de PONTE_ACESSOS_DECLARACOES.gs.txt dentro de um "vm" com versões de
// mentira dos serviços do Google (planilha, e-mail, relógio...) e responde por HTTP do mesmo
// jeito que o aplicativo da Web publicado. Só serve para os testes.
//
//     node testes/ponte_de_mentira.js PORTA
//
// Rotas extras (só dos testes):  GET /_emails  GET /_planilha  GET /_avancar?minutos=N
const fs = require("fs");
const http = require("http");
const path = require("path");
const vm = require("vm");
const crypto = require("crypto");

const porta = parseInt(process.argv[2] || "8799", 10);
const codigo = fs.readFileSync(path.join(__dirname, "..", "PONTE_ACESSOS_DECLARACOES.gs.txt"), "utf8");

let deslocamentoMs = 0;                 // "avançar o relógio" nos testes (prazos e travas)
const DataReal = Date;
class DataFalsa extends DataReal {
  constructor(...a) { if (a.length === 0) super(DataReal.now() + deslocamentoMs); else super(...a); }
  static now() { return DataReal.now() + deslocamentoMs; }
}

const emails = [];
const linhas = [];                      // a planilha: linhas[0] é o cabeçalho

function celula(r, c) { return linhas[r - 1] ? linhas[r - 1][c - 1] : ""; }
function intervalo(r, c, nr, nc) {
  nr = nr || 1; nc = nc || 1;
  const o = {
    getValues() {
      const saida = [];
      for (let i = 0; i < nr; i++) {
        const lin = [];
        for (let j = 0; j < nc; j++) { const v = celula(r + i, c + j); lin.push(v === undefined ? "" : v); }
        saida.push(lin);
      }
      return saida;
    },
    getValue() { const v = celula(r, c); return v === undefined ? "" : v; },
    setValue(v) { while (linhas.length < r) linhas.push([]); linhas[r - 1][c - 1] = v; return o; },
    setValues(vs) {
      for (let i = 0; i < vs.length; i++) for (let j = 0; j < vs[i].length; j++) {
        while (linhas.length < r + i) linhas.push([]); linhas[r + i - 1][c + j - 1] = vs[i][j];
      }
      return o;
    },
  };
  for (const n of ["setFontWeight", "setBackground", "setFontColor", "setNumberFormat"]) o[n] = () => o;
  return o;
}
const aba = {
  getLastRow() { return linhas.length; },
  getMaxRows() { return Math.max(linhas.length, 1000); },
  getRange: (r, c, nr, nc) => intervalo(r, c, nr, nc),
  clear() { linhas.length = 0; },
  setFrozenRows() {},
  appendRow(l) { linhas.push(l.slice()); },
  deleteRow(n) { linhas.splice(n - 1, 1); },
};

const ctx = {
  console,
  Date: DataFalsa,
  Math, JSON, String, Number, Array, Object, RegExp, parseInt, isNaN,
  SpreadsheetApp: { openById: () => ({ getSheetByName: () => aba, insertSheet: () => aba }) },
  LockService: { getScriptLock: () => ({ waitLock() {}, releaseLock() {} }) },
  ContentService: {
    MimeType: { JSON: "json" },
    createTextOutput: (t) => ({ texto: t, setMimeType() { return this; } }),
  },
  MailApp: {
    sendEmail(para, assunto, corpo) { emails.push({ para, assunto, corpo }); },
    getRemainingDailyQuota: () => 100,
  },
  Session: { getScriptTimeZone: () => "America/Manaus", getEffectiveUser: () => ({ getEmail: () => "dono@exemplo.com" }) },
  Utilities: {
    getUuid: () => crypto.randomUUID(),
    DigestAlgorithm: { SHA_256: "sha256" },
    Charset: { UTF_8: "utf8" },
    computeDigest: (alg, texto) => Array.from(crypto.createHash("sha256").update(texto, "utf8").digest()).map(b => (b > 127 ? b - 256 : b)),
    formatDate: (d, tz, fmt) => new DataReal(d).toLocaleDateString("sv-SE", { timeZone: "America/Manaus" }),
  },
};
vm.createContext(ctx);
vm.runInContext(codigo, ctx);
vm.runInContext('ID_PLANILHA = "teste"; EMAIL_ADMIN = "admin@exemplo.com";', ctx);
const mensagem = vm.runInContext("preparar()", ctx);
console.log("preparar:", mensagem);

function corpoDe(req) {
  return new Promise((ok) => { let s = ""; req.on("data", d => s += d); req.on("end", () => ok(s)); });
}

http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://x");
  const responder = (obj) => { res.writeHead(200, { "Content-Type": "application/json" }); res.end(JSON.stringify(obj)); };
  if (url.pathname === "/_emails") return responder(emails);
  if (url.pathname === "/_planilha") return responder(linhas);
  if (url.pathname === "/_avancar") { deslocamentoMs += parseFloat(url.searchParams.get("minutos") || "0") * 60000; return responder({ ok: true }); }
  if (req.method === "POST") {
    const corpo = await corpoDe(req);
    ctx.__e = { postData: { contents: corpo } };
    const saida = vm.runInContext("doPost(__e)", ctx);
    res.writeHead(200, { "Content-Type": "application/json" });
    return res.end(saida.texto);
  }
  const saida = vm.runInContext("doGet({})", ctx);
  res.writeHead(200, { "Content-Type": "application/json" });
  res.end(saida.texto);
}).listen(porta, "127.0.0.1", () => console.log("pronto " + porta));
