import csv
import html
import io
import os

import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response  # NOVO

DADOS_URL = os.getenv("DADOS_URL", "http://dados:5000")
PROCESSAMENTO_URL = os.getenv("PROCESSAMENTO_URL", "http://processamento:5001")

app = FastAPI(title="Serviço de Relatório")


# NOVO: mostra os links corretos no terminal ao iniciar
@app.on_event("startup")
def mostrar_link():
    print("Relatório (exemplo): http://localhost:8000/relatorio/1", flush=True)
    print("Documentação: http://localhost:8000/docs", flush=True)


# NOVO: a raiz redireciona para a documentação
@app.get("/", include_in_schema=False)
def raiz():
    return RedirectResponse("/docs")


def chamar(url: str, params: dict | None = None):
    """Chama outro microsserviço via HTTP e traduz os erros."""
    try:
        resp = requests.get(url, params=params, timeout=15)
    except requests.RequestException:
        raise HTTPException(502, f"Serviço indisponível: {url}")
    if resp.status_code == 404:
        raise HTTPException(404, "Dataset não encontrado")
    if resp.status_code != 200:
        raise HTTPException(502, f"Erro ao consultar {url}")
    return resp.json()


def classificar(score: float) -> str:
    if score >= 90:
        return "Excelente"
    if score >= 75:
        return "Boa"
    if score >= 60:
        return "Regular"
    return "Crítica"


def recomendacoes(a: dict) -> list[str]:
    recs = []
    for col, info in a["colunas"].items():
        if info["nulos"] > 0:
            recs.append(f"Tratar valores nulos em '{col}' ({info['nulos']} ocorrência(s)).")
        out = info.get("outliers", {})
        if out.get("quantidade", 0) > 0:
            recs.append(f"Investigar outliers em '{col}': {out['valores']}.")
        inv = info.get("formato_invalido", {})
        if inv.get("quantidade", 0) > 0:
            recs.append(f"Corrigir formato inválido em '{col}': {inv['valores']}.")
    if a["duplicadas"] > 0:
        recs.append(f"Remover {a['duplicadas']} linha(s) duplicada(s).")
    return recs or ["Nenhum problema encontrado."]


def montar_relatorio(dataset_id: int) -> dict:
    # 1) Serviço de Dados: metadados do dataset
    datasets = chamar(f"{DADOS_URL}/datasets")
    ds = next((d for d in datasets if d["id"] == dataset_id), None)
    if ds is None:
        raise HTTPException(404, "Dataset não encontrado")

    # 2) Serviço de Processamento: análise de qualidade
    analise = chamar(f"{PROCESSAMENTO_URL}/analise/{dataset_id}")

    # 3) Serviço de Dados: amostra dos registros
    amostra = chamar(f"{DADOS_URL}/datasets/{dataset_id}/registros", {"limit": 5})

    return {
        "dataset": ds,
        "classificacao": classificar(analise["score_qualidade"]),
        "analise": analise,
        "recomendacoes": recomendacoes(analise),
        "amostra": amostra,
    }


def render_html(r: dict) -> str:
    e = html.escape
    ds, a = r["dataset"], r["analise"]

    linhas_cols = ""
    for nome, info in a["colunas"].items():
        out = info.get("outliers", {}).get("quantidade", "-")
        inv = info.get("formato_invalido", {}).get("quantidade", "-")
        linhas_cols += (
            f"<tr><td>{e(nome)}</td><td>{e(info['tipo'])}</td>"
            f"<td>{info['nulos']} ({info['pct_nulos']}%)</td>"
            f"<td>{out}</td><td>{inv}</td></tr>"
        )

    cabecalho = ""
    linhas_amostra = ""
    if r["amostra"]:
        chaves = list(r["amostra"][0].keys())
        cabecalho = "".join(f"<th>{e(k)}</th>" for k in chaves)
        for reg in r["amostra"]:
            linhas_amostra += "<tr>" + "".join(
                f"<td>{e(str(reg.get(k))) if reg.get(k) is not None else '<i>nulo</i>'}</td>"
                for k in chaves
            ) + "</tr>"

    recs = "".join(f"<li>{e(x)}</li>" for x in r["recomendacoes"])
    d = a["dimensoes"]

    return f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8">
<title>Relatório de Qualidade - {e(ds['nome'])}</title>
<style>
body{{font-family:Arial,sans-serif;max-width:900px;margin:30px auto;color:#222;padding:0 16px}}
h1{{margin-bottom:0}} .sub{{color:#666;margin-top:4px}}
.score{{font-size:48px;font-weight:bold;margin:10px 0}}
.cards{{display:flex;gap:12px;flex-wrap:wrap}}
.card{{border:1px solid #ddd;border-radius:8px;padding:12px 18px;min-width:140px}}
table{{border-collapse:collapse;width:100%;margin:10px 0 24px}}
th,td{{border:1px solid #ddd;padding:6px 10px;text-align:left}} th{{background:#f3f3f3}}
</style></head><body>
<h1>Relatório de Qualidade de Dados</h1>
<p class="sub">Dataset: {e(ds['nome'])} (id {ds['id']}) &middot; {a['total_linhas']} linhas &middot; {a['total_colunas']} colunas</p>
<div class="score">{a['score_qualidade']} / 100 &mdash; {r['classificacao']}</div>
<div class="cards">
<div class="card">Completude<br><b>{d['completude']}%</b></div>
<div class="card">Unicidade<br><b>{d['unicidade']}%</b></div>
<div class="card">Validade<br><b>{d['validade']}%</b></div>
<div class="card">Duplicadas<br><b>{a['duplicadas']}</b></div>
</div>
<h2>Análise por coluna</h2>
<table><tr><th>Coluna</th><th>Tipo</th><th>Nulos</th><th>Outliers</th><th>Formato inválido</th></tr>{linhas_cols}</table>
<h2>Recomendações</h2><ul>{recs}</ul>
<h2>Amostra dos dados</h2>
<table><tr>{cabecalho}</tr>{linhas_amostra}</table>
</body></html>"""


def render_csv(r: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["coluna", "tipo", "nulos", "pct_nulos", "outliers", "formato_invalido"])
    for nome, info in r["analise"]["colunas"].items():
        w.writerow([
            nome,
            info["tipo"],
            info["nulos"],
            info["pct_nulos"],
            info.get("outliers", {}).get("quantidade", ""),
            info.get("formato_invalido", {}).get("quantidade", ""),
        ])
    return buf.getvalue()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/relatorio/{dataset_id}")
def relatorio(dataset_id: int, formato: str = Query("html", pattern="^(html|json|csv)$")):
    r = montar_relatorio(dataset_id)
    if formato == "json":
        return JSONResponse(r)
    if formato == "csv":
        return Response(
            render_csv(r),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=relatorio_{dataset_id}.csv"},
        )
    return HTMLResponse(render_html(r))