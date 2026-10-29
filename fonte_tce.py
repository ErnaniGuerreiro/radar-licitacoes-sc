"""
Fonte TCE-SC: Farol TCE/SC > Licitações > "Oportunidades".

O painel é um app Qlik Sense (appOportunidades) alimentado pelo e-Sfinge: reúne os processos
licitatórios que municípios, autarquias etc. informam ao TCE-SC, mesmo os publicados só em
Diário Oficial, jornal regional ou internet (que muitas vezes NÃO estão no PNCP).

Como coleta: abre a página do painel num Chromium headless (Playwright) e roda a mesma
consulta que a própria página faz, lendo o app anônimo e público. Nada de login ou chave.
"""
import re
import unicodedata

from municipios_sc import OFICIAL, chave

URL = "https://paineistransparencia.tce.sc.gov.br/extensions/appOportunidades/index.html"
APP = "7be076b3-b34e-4a49-b4fa-2d83fcf051e3"

# ordem importa: é a ordem das colunas devolvidas
CAMPOS = ["identificador", "nome_ente", "nome_unidade", "descricao_modalidade_licitacao", "numero_edital",
          "descricao_objeto_licitacao", "data_abertura_certame", "data_publicacao", "nome_veiculo_comunicacao",
          "descricao_tipo_esfera", "regiao", "ASSOCIACAO", "indicativo_registro_preco"]
CAMPOS_ARQ = ["identificador", "descricao_natureza_arquivo_texto", "url_arquivo_sigma"]

JS = """
async ({app, campos, arq}) => {
  const qlik = await new Promise((ok, no) => require(['js/qlik'], ok, no));
  const a = qlik.openApp(app, {host: location.hostname, prefix: '/', port: 443, isSecure: true});
  const cubo = (f, top, h) => new Promise((res) => a.createCube({
    qDimensions: f.map((x) => ({qDef: {qFieldDefs: [x]}})), qMeasures: [],
    qInitialDataFetch: [{qTop: top, qLeft: 0, qHeight: h, qWidth: f.length}]}, res));
  const tudo = async (f) => {
    const total = (await cubo(f, 0, 1)).qHyperCube.qSize.qcy, por = Math.max(1, Math.floor(9000 / f.length)), rows = [];
    for (let t = 0; t < total; t += por) {
      const r = await cubo(f, t, Math.min(por, total - t));
      r.qHyperCube.qDataPages[0].qMatrix.forEach((m) => rows.push(m.map((c) => c.qText)));
    }
    return {total, rows};
  };
  return {principal: await tudo(campos), arquivos: await tudo(arq)};
}
"""


def sem_acento(s):
    return "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn")


def titulo(s):
    pequenas = {"de", "da", "do", "das", "dos", "e"}
    ps = (s or "").strip().lower().split()
    return " ".join(p if (i and p in pequenas) else p.capitalize() for i, p in enumerate(ps))


def data_iso(txt, fim_do_dia=False):
    m = re.match(r"(\d\d)/(\d\d)/(\d{4})", txt or "")
    if not m:
        return None
    d, mo, a = m.groups()
    return f"{a}-{mo}-{d}T{'23:59:00' if fim_do_dia else '00:00:00'}"


MODALIDADE = {"Pregão Eletrônico": "Pregão - Eletrônico", "Pregão Presencial": "Pregão - Presencial"}


def normalizar(principal, arquivos):
    """Agrupa as linhas (uma por publicação) em um registro por processo. Só esfera municipal."""
    editais = {}
    for ident, natureza, url in arquivos:
        if url and natureza.lower().startswith("texto de edital") and ident not in editais:
            editais[ident] = url
    por_id = {}
    for r in principal:
        (ident, ente, unidade, modal, numero, objeto, abertura, publicacao, veiculo, esfera, regiao, assoc, srp) = r
        if esfera != "Municipal":
            continue
        pub = data_iso(publicacao)
        if ident in por_id:
            ant = por_id[ident]
            if pub and (not ant["publicacao"] or pub < ant["publicacao"]):
                ant["publicacao"] = pub
            continue
        fim = data_iso(abertura, fim_do_dia=True)
        por_id[ident] = {
            "id": f"TCESC-{ident}", "fonte": "TCE-SC", "fingerprint": f"tce|{ident}",
            "municipio": OFICIAL.get(chave(ente)) or titulo(ente), "ibge": None, "orgao": unidade, "cnpj_orgao": None,
            "modalidade": MODALIDADE.get(modal, modal), "numero": numero, "processo": None,
            "objeto": (objeto or "").strip(), "valor_estimado": None, "publicacao": pub,
            "abertura_propostas": data_iso(abertura), "encerramento_propostas": fim, "prazo_aprox": True,
            "situacao": None, "srp": {"S": True, "N": False}.get((srp or "")[:1].upper()),
            "link_origem": None, "link_pncp": None, "link_edital": editais.get(ident),
            "regiao": None if regiao in ("-", "") else regiao,
            "associacao": None if assoc in ("-", "") else assoc,
            "veiculo": None if veiculo in ("-", "") else veiculo,
        }
    return list(por_id.values())


def coletar():
    """Devolve (registros, unidades_de_cobertura). Levanta exceção se o Chromium/Playwright faltar."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        nav = p.chromium.launch()
        try:
            pg = nav.new_page()
            pg.goto(URL, wait_until="networkidle", timeout=120_000)
            pg.wait_for_function("typeof require === 'function'", timeout=60_000)
            res = pg.evaluate(JS, {"app": APP, "campos": CAMPOS, "arq": CAMPOS_ARQ})
        finally:
            nav.close()
    pr, ar = res["principal"], res["arquivos"]
    unidades = [
        {"consulta": "Farol · Oportunidades (processos)", "esperado": pr["total"], "coletado": len(pr["rows"]),
         "completo": len(pr["rows"]) >= pr["total"] > 0, "erro": None},
        {"consulta": "Farol · Arquivos dos editais", "esperado": ar["total"], "coletado": len(ar["rows"]),
         "completo": len(ar["rows"]) >= ar["total"], "erro": None}]
    return normalizar(pr["rows"], ar["rows"]), unidades
