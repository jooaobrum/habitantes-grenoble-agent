# Base legal — teste de balanceamento (interesse legítimo)

Este é um registro interno da análise exigida pela CNIL para usar
"intérêt légitime" (RGPD art. 6.1.f) como base legal do processamento do
histórico do grupo. Não é enviado a nenhum órgão; fica guardado para
eventual auditoria e deve ser atualizado se o escopo do projeto mudar.

## 1. Interesse legítimo

O grupo repete as mesmas perguntas (visto, CAF, banco, saúde) há anos. O
bot centraliza esse conhecimento e responde 24/7, reduzindo o esforço
repetido dos membros mais antigos do grupo. O mesmo vale para os pedidos
de indicação ("quem indica um dentista?"), que se repetem e cujas
respostas estão espalhadas pelo histórico. É um projeto sem fins
lucrativos, a serviço da própria comunidade que gerou o dado.

## 2. Necessidade

O conhecimento útil está nas próprias mensagens trocadas ao longo dos
anos — não existe uma fonte sintética equivalente. O processamento é
limitado ao necessário para extrair pares pergunta/resposta e as
indicações da comunidade (negócios, lugares e produtos); o texto
bruto e a identificação de quem escreveu não são necessários além dessa
etapa (ver retenção abaixo).

## 3. Proporcionalidade

O impacto em cada pessoa é baixo, dado que:

- As bases finais consultadas pelo bot não guardam nome nem número de quem
  escreveu: a de perguntas e respostas (`ingestion/load/qdrant.py`, lista
  fixa de campos permitidos) e a de Sugestões (`ingestion/load/suggestions.py`;
  os modelos de menção e de cluster não têm campo de autor). Antes de o texto
  chegar ao LLM de extração, autores viram códigos e telefones são removidos.
- Opiniões negativas sobre negócios aparecem apenas como contagem, nunca
  como texto; negócios com mais críticas do que indicações não são oferecidos.
- Um negócio de membro do grupo só é listado com identidade de negócio
  além do nome ou telefone pessoal e com ao menos uma indicação de outro
  membro, e é sempre identificado como tal.
- Donos de negócios podem pedir para não serem listados
  (`config/suggestion_exclusions.txt`, aplicada a cada reconstrução).
- O histórico bruto e os arquivos intermediários (que ainda têm
  identificação) são apagados depois de um prazo definido, não retidos
  indefinidamente.
- Qualquer pessoa pode se opor e pedir remoção a qualquer momento, sem
  justificar, incluindo remoção retroativa, que também apaga os arquivos
  derivados de Sugestões e reconstrói essa base (ver `PRIVACIDADE.md` e
  `ingestion/erase.py`).

## Revisão

Este documento deve ser revisado sempre que o escopo do projeto mudar
(novo canal, novo uso do dado, etc.).
