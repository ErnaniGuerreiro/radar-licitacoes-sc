#!/usr/bin/env python3
"""
Coletor v3 - Licitações de MUNICÍPIOS de Santa Catarina.

Princípios desta versão (corrigem os problemas da v2):
  * NENHUMA falha é silenciosa. Cada consulta (modalidade x dia) é registrada com
    o total que a API disse ter ("esperado") e o que foi de fato baixado ("coletado").
  * Falha numa consulta não apaga nada: tudo o que já foi visto fica no banco
    (SQLite) e o painel é gerado a partir do BANCO, não só da última rodada.
  * Cada fonte informa seu estado real: ok / parcial / falhou / nao_implementada.
    Fonte sem coletor NUNCA aparece como "ok".

Saídas em dados/:  licitacoes.json  resumo.json  status.json  eventos.json  historico.sqlite

Uso:   python coletor.py              (rodada incremental: últimos 3 dias + todas as abertas)
       python coletor.py --dias 45    (carga inicial / reforço)
"""
import argparse, hashlib, json, os, re, sqlite3, time
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

from categorias import classificar

UF = "SC"
PAGE_SIZE = 50
PAUSA = 0.25
DIR = Path(__file__).parent
DADOS = DIR / "dados"
DB = DADOS / "historico.sqlite"
S = requests.Session()
S.headers["User-Agent"] = "radar-licitacoes-sc/3.0"

# Tabela de domínio "Modalidade de contratação" do PNCP
MODALIDADES = {1: "Leilão - Eletrônico", 2: "Diálogo Competitivo", 3: "Concurso",
               4: "Concorrência - Eletrônica", 5: "Concorrência - Presencial",
               6: "Pregão - Eletrônico", 7: "Pregão - Presencial", 8: "Dispensa",
               9: "Inexigibilidade", 10: "Manifestação de Interesse",
               11: "Pré-qualificação", 12: "Credenciamento", 13: "Leilão - Presencial"}

class ErroAPI(Exception):
    pass


def agora():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def http_get(url, params, tentativas=6):
    """GET com retentativas. Se esgotar, LEVANTA erro (nunca devolve 'vazio' em silêncio)."""
    ultimo = "?"
    for i in range(tentativas):
        try:
            r = S.get(url, params=params, timeout=90)
        except requests.RequestException as e:
            ultimo = repr(e); time.sleep(min(60, 2 ** i)); continue
        if r.status_code == 204:
            return None
        if r.status_code in (429, 500, 502, 503, 504):
            ultimo = f"HTTP {r.status_code}"; time.sleep(min(60, 2 ** i)); continue
        if 400 <= r.status_code < 500:
            raise ErroAPI(f"HTTP {r.status_code} (parâmetro recusado?): {r.text[:200]}")
        try:
            return r.json()
        except ValueError:
            ultimo = "resposta não era JSON"; time.sleep(min(60, 2 ** i))
    raise ErroAPI(f"esgotou {tentativas} tentativas ({ultimo})")


def fingerprint(cnpj, numero, ano):
    num = re.sub(r"\D", "", str(numero or "")).lstrip("0")
    cn = re.sub(r"\D", "", str(cnpj or ""))
    return f"{cn}|{num}|{ano}"


# ============================================================ fontes
class Fonte:
    nome = "?"
    implementada = True
    motivo = ""

    def coletar(self, dias):
        """Devolve (registros, unidades) onde unidades = lista de dicts de cobertura."""
        raise NotImplementedError


class PNCP(Fonte):
    nome = "PNCP"
    base = "https://pncp.gov.br/api/consulta/v1"

    def _unidade(self, rota, params, rotulo):
        regs, esperado, erro, pg = [], None, None, 1
        try:
            while True:
                d = http_get(f"{self.base}/{rota}", {**params, "pagina": pg, "tamanhoPagina": PAGE_SIZE})
                if not d or not d.get("data"):
                    break
                if esperado is None:
                    esperado = d.get("totalRegistros")
                regs.extend(d["data"])
                if pg >= d.get("totalPaginas", 1):
                    break
                pg += 1
                time.sleep(PAUSA)
        except ErroAPI as e:
            erro = str(e)
        completo = erro is None and (esperado is None or len(regs) >= esperado)
        info = {"consulta": rotulo, "esperado": esperado if esperado is not None else len(regs),
                "coletado": len(regs), "completo": completo, "erro": erro}
        return regs, info

    def _norm(self, c):
        org, uni = c.get("orgaoEntidade") or {}, c.get("unidadeOrgao") or {}
        return {
            "id": c.get("numeroControlePNCP"), "fonte": self.nome,
            "fingerprint": fingerprint(org.get("cnpj"), c.get("numeroCompra"), c.get("anoCompra")),
            "municipio": uni.get("municipioNome"), "ibge": uni.get("codigoIbge"),
            "orgao": org.get("razaoSocial"), "cnpj_orgao": org.get("cnpj"),
            "modalidade": c.get("modalidadeNome"), "numero": c.get("numeroCompra"),
            "processo": c.get("processo"), "objeto": (c.get("objetoCompra") or "").strip(),
            "valor_estimado": c.get("valorTotalEstimado"),
            "publicacao": c.get("dataPublicacaoPncp"),
            "abertura_propostas": c.get("dataAberturaProposta"),
            "encerramento_propostas": c.get("dataEncerramentoProposta"),
            "situacao": c.get("situacaoCompraNome"), "srp": c.get("srp"),
            "link_origem": c.get("linkSistemaOrigem"),
            "link_pncp": (f"https://pncp.gov.br/app/editais/{org.get('cnpj')}/{c.get('anoCompra')}/{c.get('sequencialCompra')}"
                          if org.get("cnpj") else None),
        }

    def coletar(self, dias):
        regs, unidades = {}, []

        def absorver(lista):
            for c in lista:
                if (c.get("orgaoEntidade") or {}).get("esferaId") == "M":  # só municipal
                    r = self._norm(c)
                    regs[r["id"]] = r

        fim = (date.today() + timedelta(days=500)).strftime("%Y%m%d")
        for cod, nome in MODALIDADES.items():   # 1) tudo que ainda recebe propostas
            lista, info = self._unidade("contratacoes/proposta",
                                        {"dataFinal": fim, "uf": UF, "codigoModalidadeContratacao": cod},
                                        f"abertas · {nome}")
            absorver(lista); unidades.append(info)
        for k in range(dias + 1):               # 2) publicadas nos últimos N dias, dia a dia
            dia = (date.today() - timedelta(days=k)).strftime("%Y%m%d")
            for cod, nome in MODALIDADES.items():
                lista, info = self._unidade("contratacoes/publicacao",
                                            {"dataInicial": dia, "dataFinal": dia, "uf": UF,
                                             "codigoModalidadeContratacao": cod},
                                            f"{dia[6:]}/{dia[4:6]} · {nome}")
                absorver(lista); unidades.append(info)
        return list(regs.values()), unidades


class TCESC(Fonte):
    nome = "TCE-SC (Farol · Oportunidades)"

    def coletar(self, dias):
        import fonte_tce          # exige: pip install playwright && playwright install chromium
        return fonte_tce.coletar()


class DOMSC(Fonte):
    nome = "DOM/SC"
    implementada = False
    motivo = ("Sem coletor próprio. Boa parte do que sai no Diário Oficial dos Municípios já chega pelo Farol "
              "(veículo de publicação informado pelo município ao TCE-SC).")

    def coletar(self, dias): return [], []


class Plataformas(Fonte):
    nome = "Plataformas (BLL, Licitanet, Compras Públicas, Betha...)"
    implementada = False
    motivo = "Coletor ainda não implementado. Parte do que elas publicam já chega via PNCP."

    def coletar(self, dias): return [], []


FONTES = [PNCP(), TCESC(), DOMSC(), Plataformas()]

# ============================================================ histórico
MONITORADOS = ["valor_estimado", "encerramento_propostas", "abertura_propostas", "situacao", "objeto", "modalidade"]


def abrir_db():
    DADOS.mkdir(exist_ok=True)
    db = sqlite3.connect(DB)
    db.execute("""CREATE TABLE IF NOT EXISTS licitacoes(
        id TEXT PRIMARY KEY, fingerprint TEXT, dados TEXT, hash TEXT,
        first_seen TEXT, last_seen TEXT, last_changed TEXT)""")
    db.execute("CREATE TABLE IF NOT EXISTS eventos(quando TEXT, tipo TEXT, id TEXT, municipio TEXT, resumo TEXT)")
    cols = [r[1] for r in db.execute("PRAGMA table_info(licitacoes)")]
    if "ativa" in cols:      # banco criado pela v2: segue funcionando
        pass
    return db


def h(r):
    return hashlib.sha1(json.dumps({k: r.get(k) for k in MONITORADOS}, sort_keys=True, default=str).encode()).hexdigest()


def sincronizar(db, registros):
    ts, eventos = agora(), []
    for r in registros:
        r["categoria"] = classificar(r.get("objeto"))
        antigo = db.execute("SELECT dados, hash FROM licitacoes WHERE id=?", (r["id"],)).fetchone()
        novo = h(r)
        if antigo is None:
            r["visto_em"] = ts
            ativa_col = "ativa" in [c[1] for c in db.execute("PRAGMA table_info(licitacoes)")]
            if ativa_col:
                db.execute("INSERT INTO licitacoes(id,fingerprint,dados,hash,first_seen,last_seen,last_changed,ativa) VALUES(?,?,?,?,?,?,?,1)",
                           (r["id"], r["fingerprint"], json.dumps(r, ensure_ascii=False), novo, ts, ts, ts))
            else:
                db.execute("INSERT INTO licitacoes VALUES(?,?,?,?,?,?,?)",
                           (r["id"], r["fingerprint"], json.dumps(r, ensure_ascii=False), novo, ts, ts, ts))
            eventos.append(("NOVA", r, f"{r.get('modalidade')} - {(r.get('objeto') or '')[:140]}"))
        elif antigo[1] != novo:
            ant = json.loads(antigo[0])
            mud = [k for k in MONITORADOS if ant.get(k) != r.get(k)]
            r["visto_em"] = ant.get("visto_em") or ts
            r["alterado_em"] = ts
            r["mudancas"] = mud
            db.execute("UPDATE licitacoes SET dados=?, hash=?, last_seen=?, last_changed=? WHERE id=?",
                       (json.dumps(r, ensure_ascii=False), novo, ts, ts, r["id"]))
            eventos.append(("ALTERADA", r, "Mudou: " + ", ".join(mud)))
        else:
            db.execute("UPDATE licitacoes SET last_seen=? WHERE id=?", (ts, r["id"]))
    for tipo, r, resumo in eventos:
        db.execute("INSERT INTO eventos VALUES(?,?,?,?,?)", (ts, tipo, r["id"], r.get("municipio"), resumo))
    db.commit()
    return eventos


# ============================================================ alertas
def radares_de(w):
    """Aceita o formato novo {"radares": [...]} e o antigo (um filtro só)."""
    if "radares" in w:
        return w["radares"]
    return [dict(nome="Meu radar", **{k: v for k, v in w.items() if not k.startswith("_")})]


def bate(r, rd):
    if rd.get("municipios") and (r.get("municipio") or "").lower() not in [m.lower() for m in rd["municipios"]]:
        return False
    if rd.get("categorias") and r.get("categoria") not in rd["categorias"]:
        return False
    if rd.get("modalidades") and r.get("modalidade") not in rd["modalidades"]:
        return False
    if (r.get("valor_estimado") or 0) < rd.get("valor_minimo", 0):
        return False
    kws = [k.lower() for k in rd.get("palavras_chave", [])]
    return not kws or any(k in (r.get("objeto") or "").lower() for k in kws)


def notificar(texto):
    tok, chat, hook = os.getenv("TELEGRAM_TOKEN"), os.getenv("TELEGRAM_CHAT_ID"), os.getenv("WEBHOOK_URL")
    try:
        if tok and chat:
            S.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                   json={"chat_id": chat, "text": texto[:4000], "disable_web_page_preview": True}, timeout=30)
        if hook:
            S.post(hook, json={"text": texto}, timeout=30)
    except requests.RequestException as e:
        print("falha ao notificar:", e)


def alertar(eventos, w, maximo_por_radar=8):
    """Uma mensagem-resumo por radar (nunca uma por licitação)."""
    agora_l = datetime.now()
    abertos = []
    for tipo, r, resumo in eventos:
        fim = (r.get("encerramento_propostas") or "")[:19]
        try:
            if fim and datetime.fromisoformat(fim) >= agora_l:   # só o que ainda dá tempo de participar
                abertos.append((tipo, r, fim))
        except ValueError:
            pass
    for rd in radares_de(w):
        achados = [(t, r, f) for t, r, f in abertos if bate(r, rd)]
        if not achados:
            continue
        linhas = []
        for t, r, f in achados[:maximo_por_radar]:
            v = r.get("valor_estimado")
            linhas.append(f"{'🆕' if t == 'NOVA' else '✏️'} {r['municipio']} · {r['modalidade']} · {'R$ {:,.0f}'.format(v) if v else 'valor n/i'} · até {f[8:10]}/{f[5:7]}\n   {(r.get('objeto') or '')[:110]}\n   {r.get('link_pncp') or r.get('link_edital') or ''}")
        mais = f"\n… e mais {len(achados) - maximo_por_radar}" if len(achados) > maximo_por_radar else ""
        notificar(f"📡 Radar “{rd.get('nome', 'sem nome')}”: {len(achados)} novidade(s)\n\n" + "\n\n".join(linhas) + mais)


def _sem_acento(s):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn")


def _classe(modalidade):
    m = _sem_acento(modalidade).lower()
    for chave_, nome in (("pregao", "pregao"), ("concorr", "concorrencia"), ("leilao", "leilao"), ("credenc", "cred"),
                         ("dispensa", "dispensa"), ("inexig", "inexig")):
        if chave_ in m:
            return nome
    return "outra"


def chave_cruzada(r):
    """Mesmo processo em fontes diferentes: município + tipo + número + ano."""
    m = re.search(r"(\d+)\s*[/.\-]\s*(\d{4})", r.get("numero") or "")
    if m:
        num, ano = m.group(1).lstrip("0"), m.group(2)
    else:
        num = re.sub(r"\D", "", str(r.get("numero") or "")).lstrip("0")
        ano = (r.get("fingerprint") or "").split("|")[-1] if r.get("fonte") == "PNCP" else ""
    mun = " ".join(_sem_acento(r.get("municipio")).upper().replace("'", "").split())
    return f"{mun}|{_classe(r.get('modalidade'))}|{num}|{ano}"


EXTRAS = ("link_edital", "regiao", "associacao", "veiculo")


def fundir(grupo):
    """PNCP é a base (tem valor e CNPJ); o Farol acrescenta edital, região, associação e veículo."""
    base = dict(sorted(grupo, key=lambda r: r.get("fonte") != "PNCP")[0])
    for r in grupo:
        for k in EXTRAS:
            if r.get(k) and not base.get(k):
                base[k] = r[k]
    base["fontes"] = sorted({r["fonte"] for r in grupo})
    vistos = [r["visto_em"] for r in grupo if r.get("visto_em")]
    if vistos:
        base["visto_em"] = min(vistos)
    alts = [r for r in grupo if r.get("alterado_em")]
    if alts:
        ult = max(alts, key=lambda r: r["alterado_em"])
        base["alterado_em"], base["mudancas"] = ult["alterado_em"], ult.get("mudancas", [])
    if base["fonte"] != "PNCP":
        base.setdefault("prazo_aprox", True)
    elif any(r.get("prazo_aprox") for r in grupo) and not base.get("encerramento_propostas"):
        base["encerramento_propostas"] = next(r["encerramento_propostas"] for r in grupo if r.get("prazo_aprox"))
        base["prazo_aprox"] = True
    return base


# ============================================================ exportação
def exportar(db, status_fontes, cobertura, eventos_novos):
    corte_prazo = (datetime.now() - timedelta(days=3)).isoformat(timespec="seconds")
    corte_pub = (datetime.now() - timedelta(days=15)).isoformat(timespec="seconds")
    grupos = {}
    for (dados,) in db.execute("SELECT dados FROM licitacoes"):
        r = json.loads(dados)
        prazo = r.get("encerramento_propostas")
        if prazo and prazo >= corte_prazo:
            pass                                   # com prazo vigente (ou recém-vencido)
        elif not prazo and (r.get("publicacao") or "") >= corte_pub:
            r["sem_prazo"] = True                  # contratação direta recente (opcional no painel)
        else:
            continue
        grupos.setdefault(chave_cruzada(r), []).append(r)
    todas = [fundir(g) if len(g) > 1 else {**g[0], "fontes": [g[0]["fonte"]]} for g in grupos.values()]
    todas.sort(key=lambda r: r.get("encerramento_propostas") or "9999")

    serie = Counter()
    for (dados,) in db.execute("SELECT dados FROM licitacoes"):
        p = (json.loads(dados).get("publicacao") or "")[:10]
        if p >= (date.today() - timedelta(days=45)).isoformat():
            serie[p] += 1
    ev = [dict(zip(("quando", "tipo", "id", "municipio", "resumo"), x))
          for x in db.execute("SELECT * FROM eventos ORDER BY quando DESC LIMIT 300")]
    total_db = db.execute("SELECT COUNT(*) FROM licitacoes").fetchone()[0]
    primeira = db.execute("SELECT MIN(first_seen) FROM licitacoes").fetchone()[0]

    (DADOS / "licitacoes.json").write_text(json.dumps(todas, ensure_ascii=False), encoding="utf-8")
    (DADOS / "eventos.json").write_text(json.dumps(ev, ensure_ascii=False), encoding="utf-8")
    (DADOS / "resumo.json").write_text(json.dumps({
        "atualizado_em": agora(), "registros_no_historico": total_db, "primeira_coleta_em": primeira,
        "publicacoes_por_dia": dict(sorted(serie.items())), "novos_nesta_rodada": eventos_novos}, ensure_ascii=False, indent=1), encoding="utf-8")
    (DADOS / "status.json").write_text(json.dumps({
        "atualizado_em": agora(), "fontes": status_fontes, "cobertura": cobertura}, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(todas)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=int, default=3, help="reconsultar publicações dos últimos N dias")
    a = ap.parse_args()
    w = json.loads((DIR / "watchlist.json").read_text(encoding="utf-8"))
    db = abrir_db()

    primeira_carga = db.execute("SELECT COUNT(*) FROM licitacoes").fetchone()[0] == 0
    status, todas_unid, eventos = [], [], []
    for f in FONTES:
        if not f.implementada:
            status.append({"nome": f.nome, "estado": "nao_implementada", "mensagem": f.motivo, "registros": 0})
            continue
        try:
            regs, unid = f.coletar(a.dias)
        except Exception as e:                      # fonte inteira fora do ar
            status.append({"nome": f.nome, "estado": "falhou", "mensagem": str(e), "registros": 0})
            continue
        todas_unid += unid
        ok = sum(u["completo"] for u in unid)
        estado = "ok" if ok == len(unid) else ("parcial" if ok else "falhou")
        status.append({"nome": f.nome, "estado": estado, "registros": len(regs),
                       "mensagem": f"{ok} de {len(unid)} consultas completas", "ultima_execucao": agora()})
        eventos += sincronizar(db, regs)

    esperado = sum(u["esperado"] for u in todas_unid)
    coletado = sum(min(u["coletado"], u["esperado"]) for u in todas_unid)
    cobertura = {
        "consultas": len(todas_unid), "consultas_completas": sum(u["completo"] for u in todas_unid),
        "registros_esperados": esperado, "registros_coletados": coletado,
        "percentual": round(100 * coletado / esperado, 1) if esperado else None,
        "falhas": [u for u in todas_unid if not u["completo"]][:25]}
    if primeira_carga:
        print("carga inicial: alertas desligados nesta rodada (para não enviar milhares de mensagens)")
    else:
        alertar(eventos, w)
    n = exportar(db, status, cobertura, Counter(t for t, _, _ in eventos))
    c = Counter(t for t, _, _ in eventos)
    print(f"{n} no painel | novas {c['NOVA']} | alteradas {c['ALTERADA']} | "
          f"cobertura {cobertura['percentual']}% ({cobertura['consultas_completas']}/{cobertura['consultas']} consultas completas)")
    for u in cobertura["falhas"][:5]:
        print("  falha:", u["consulta"], "-", u["erro"] or f"veio {u['coletado']} de {u['esperado']}")
    if not any(s["estado"] in ("ok", "parcial") for s in status):
        raise SystemExit("nenhuma fonte respondeu")


if __name__ == "__main__":
    main()
