# Pipeline de Qualidade de Dados

Sistema de microsserviços para ingestão, análise e relatório de qualidade de datasets, orquestrado com Docker Compose.

## Serviços
- **Serviço de Dados**: armazena datasets e registros de ingestão.
- **Serviço de Processamento**: perfila os dados (nulos, duplicatas, outliers, tipos) e calcula o score de qualidade.
- **Serviço de Relatório**: orquestra os outros serviços e gera o relatório final.

## Integrantes
- Nicolas Alencar - 23012092