import os
import re

import pandas as pd
import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse  # NOVO

DADOS_URL = os.getenv("DADOS_URL", "http://dados:5000")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

app = FastAPI(title="Serviço de Processamento")


# NOVO: mostra o link correto no terminal ao iniciar
@app.on_event("startup")
def mostrar_link():
    print("Documentação: http://localhost:5001/docs", flush=True)


# NOVO: a raiz redireciona para a documentação
@app.get("/", include_in_schema=False)
def raiz():
    return RedirectResponse("/docs")


def buscar_registros(dataset_id: int) -> list[dict]:
    """Busca todos os registros no Serviço de Dados, em lotes de 1000."""
    registros = []
    offset = 0
    while True:
        try:
            resp = requests.get(
                f"{DADOS_URL}/datasets/{dataset_id}/registros",
                params={"limit": 1000, "offset": offset},
                timeout=10,
            )
        except requests.RequestException:
            raise HTTPException(502, "Serviço de Dados indisponível")
        if resp.status_code == 404:
            raise HTTPException(404, "Dataset não encontrado")
        if resp.status_code != 200:
            raise HTTPException(502, "Erro ao consultar o Serviço de Dados")
        lote = resp.json()
        registros.extend(lote)
        if len(lote) < 1000:
            break
        offset += 1000
    return registros


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/analise/{dataset_id}")
def analisar(dataset_id: int):
    registros = buscar_registros(dataset_id)
    if not registros:
        raise HTTPException(404, "Dataset sem registros")

    df = pd.DataFrame(registros)
    n = len(df)
    colunas_id = [c for c in df.columns if c.lower() == "id"]

    colunas = {}
    linhas_com_problema = set()  # linhas com outlier ou formato inválido

    for col in df.columns:
        serie = df[col]
        nulos = int(serie.isna().sum())
        info = {"nulos": nulos, "pct_nulos": round(nulos / n * 100, 1)}

        # Inferência de tipo: numérico se >= 80% dos valores não nulos viram número
        nao_nulos = serie.dropna()
        convertidos = pd.to_numeric(nao_nulos, errors="coerce")
        if len(nao_nulos) > 0 and convertidos.notna().mean() >= 0.8:
            info["tipo"] = "numerico"
            if col not in colunas_id:
                numeros = pd.to_numeric(serie, errors="coerce")
                if numeros.notna().sum() >= 4:
                    q1, q3 = numeros.quantile(0.25), numeros.quantile(0.75)
                    iqr = q3 - q1
                    inf, sup = q1 - 1.5 * iqr, q3 + 1.5 * iqr
                    mascara = (numeros < inf) | (numeros > sup)
                    info["outliers"] = {
                        "quantidade": int(mascara.sum()),
                        "limites": [round(float(inf), 2), round(float(sup), 2)],
                        "valores": numeros[mascara].tolist(),
                    }
                    linhas_com_problema.update(df.index[mascara].tolist())
        else:
            info["tipo"] = "texto"

        if "email" in col.lower():
            invalidos = [
                i for i, v in serie.items()
                if pd.notna(v) and not EMAIL_RE.match(str(v))
            ]
            info["formato_invalido"] = {
                "quantidade": len(invalidos),
                "valores": [str(serie[i]) for i in invalidos],
            }
            linhas_com_problema.update(invalidos)

        colunas[col] = info

    # Duplicatas: ignora a coluna de id, senão nenhuma linha seria igual
    duplicadas = int(df.drop(columns=colunas_id).duplicated().sum())

    # Score de qualidade (0 a 100)
    total_nulos = int(df.isna().sum().sum())
    completude = 1 - total_nulos / (n * len(df.columns))
    unicidade = 1 - duplicadas / n
    validade = 1 - len(linhas_com_problema) / n
    score = round(100 * (0.4 * completude + 0.3 * unicidade + 0.3 * validade), 1)

    return {
        "dataset_id": dataset_id,
        "total_linhas": n,
        "total_colunas": len(df.columns),
        "duplicadas": duplicadas,
        "colunas": colunas,
        "dimensoes": {
            "completude": round(completude * 100, 1),
            "unicidade": round(unicidade * 100, 1),
            "validade": round(validade * 100, 1),
        },
        "score_qualidade": score,
    }