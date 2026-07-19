# Privacidade — histórico do grupo e o bot

Este documento explica, de forma simples, o que o bot faz com o histórico
de mensagens do grupo. Pode ser copiado/colado no grupo.

## O que é coletado

O histórico de mensagens exportado do grupo do WhatsApp (texto, autor,
data/hora).

## O que é feito com isso

1. O histórico bruto é processado para identificar pares de pergunta e
   resposta.
2. Esses pares passam por uma etapa de reescrita, que produz uma versão
   resumida e sem identificação de quem escreveu.
3. Só essa versão final — sem nome ou número de ninguém — entra na base
   que o bot consulta para responder.

## O que fica guardado, e por quanto tempo

- **Base final do bot** (perguntas e respostas, sem autor): fica indefinidamente, é o que o bot usa para responder.
- **Histórico bruto e arquivos intermediários** (usados só durante o processamento, ainda contêm nome/número): apagados depois de um prazo definido, não ficam para sempre.
- **Registro de conversas com o bot** (pergunta feita, resposta dada): guardado por 30 dias, depois apagado automaticamente.

## Base legal

O tratamento se apoia em interesse legítimo (ajudar a comunidade a
encontrar respostas), com as salvaguardas acima. Detalhes em
[`BASE_LEGAL.md`](./BASE_LEGAL.md).

## Como pedir a remoção das suas mensagens

Mande uma mensagem direto para quem administra o bot pedindo a remoção.
Não é preciso justificar, e pode ser feito a qualquer momento — inclusive
sobre mensagens antigas já processadas.
