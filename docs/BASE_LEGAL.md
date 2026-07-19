# Base legal — teste de balanceamento (interesse legítimo)

Documento interno. Registra a análise exigida pela CNIL para usar
"intérêt légitime" (RGPD art. 6.1.f) como base legal do processamento do
histórico do grupo. Não é enviado a nenhum órgão — fica guardado para
eventual auditoria, e deve ser atualizado se o escopo do projeto mudar.

## 1. Interesse legítimo

O grupo repete as mesmas perguntas (visto, CAF, banco, saúde) há anos. O
bot centraliza esse conhecimento e responde 24/7, reduzindo o esforço
repetido dos membros mais antigos do grupo. É um projeto sem fins
lucrativos, a serviço da própria comunidade que gerou o dado.

## 2. Necessidade

O conhecimento útil está nas próprias mensagens trocadas ao longo dos
anos — não existe uma fonte sintética equivalente. O processamento é
limitado ao necessário para extrair pares pergunta/resposta; o texto
bruto e a identificação de quem escreveu não são necessários além dessa
etapa (ver retenção abaixo).

## 3. Proporcionalidade

O impacto em cada pessoa é baixo, dado que:

- A base final consultada pelo bot não guarda nome nem número de quem
  escreveu (`ingestion/load/qdrant.py`, lista fixa de campos permitidos).
- O histórico bruto e os arquivos intermediários (que ainda têm
  identificação) são apagados depois de um prazo definido, não retidos
  indefinidamente.
- Qualquer pessoa pode se opor e pedir remoção a qualquer momento, sem
  justificar, incluindo remoção retroativa (ver `PRIVACIDADE.md` e
  `ingestion/erase.py`).

## Revisão

Este documento deve ser revisado sempre que o escopo do projeto mudar
(novo canal, novo uso do dado, etc.).
