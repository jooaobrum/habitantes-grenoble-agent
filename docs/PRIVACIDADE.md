# Privacidade — histórico do grupo e o bot

Este documento explica o que o bot faz com o histórico de mensagens do
grupo.

## O que é coletado

O histórico de mensagens exportado do grupo do WhatsApp (texto, autor,
data/hora).

## O que é feito com isso

O mesmo histórico alimenta duas bases que o bot consulta:

**Base de perguntas e respostas**

1. O histórico bruto é processado para identificar pares de pergunta e
   resposta.
2. Esses pares passam por uma etapa de reescrita, que produz uma versão
   resumida e sem identificação de quem escreveu.
3. Só essa versão final — sem nome ou número de ninguém — entra na base
   que o bot consulta para responder.

**Base de Sugestões (indicações da comunidade)**

Para responder a pedidos como "quem indica um dentista?" ou "onde compro
massa de pastel?", o bot também guarda as indicações que a comunidade fez
de negócios, lugares e produtos. Elas são buscadas em qualquer mensagem do
histórico, inclusive opiniões soltas ("fui no X e gostei"), não só em
respostas a perguntas.

1. Antes de o texto ir para qualquer serviço externo, o nome de cada
   autor é trocado por um código (M1, M2...) e números de telefone são
   removidos do texto.
2. Cada opinião sobre um negócio, lugar ou produto vira uma "menção":
   nome do negócio, tipo, se foi positiva ou negativa, o que foi indicado
   e uma frase reescrita com o motivo. A menção não guarda quem escreveu.
3. As menções são somadas por negócio. O que entra na base que o bot
   consulta é: o nome do negócio, quantas pessoas indicaram (👍) e quantas
   criticaram (👎), a data da última menção, o que foi indicado e um resumo
   reescrito. Nenhuma mensagem é copiada e nenhum nome ou número de quem
   escreveu é guardado.
4. O bot mostra essas informações a quem pergunta: nome, contagem de 👍/👎,
   data da última menção e uma linha de contexto. Opiniões negativas
   aparecem apenas como contagem, nunca como texto. Negócios com mais
   críticas do que indicações não são oferecidos.

Não são guardados contatos, endereços, horários nem preços.

Pessoas físicas, bancos, operadoras de telefone, aplicativos, associações e
serviços públicos não entram como sugestões.

### Negócios de membros do grupo e contatos divulgados

Quando um membro divulga no grupo um negócio próprio (por exemplo, com nome
comercial e perfil profissional em rede social, site ou página de
reservas), o bot pode listá-lo como "negócio de membro do grupo —
divulgação própria", sempre identificado como tal. Isso só acontece se
houver uma identidade de negócio além do nome ou do telefone pessoal do
membro — o nome e o número pessoais não são publicados — e se pelo menos
outro membro do grupo também o tiver indicado: a própria divulgação não
conta como indicação.

Contatos de negócios que foram postados no grupo para divulgação (por
exemplo, o perfil comercial ou o link de reservas citados no texto) podem
aparecer no histórico bruto e nos arquivos intermediários, que têm prazo
para ser apagados (ver abaixo). Esses contatos de divulgação não são
guardados como campo na base de Sugestões, que não tem contato, endereço ou
telefone.

## Serviços de terceiros

O texto das mensagens é enviado a serviços externos durante o processamento:

- **OpenRouter** e **OpenAI**: reescrita dos pares de pergunta e resposta,
  extração e agrupamento das indicações da base de Sugestões (já com os
  autores trocados por códigos) e geração de embeddings.
- **TypeSafe** (classificador Jev, acessado via OpenRouter): recebe a
  pergunta e a resposta para classificar tema, relevância, se a informação
  está desatualizada e se precisa de revisão; na base de Sugestões, recebe
  trechos da conversa (com autores trocados por códigos) para responder
  apenas se há ou não uma indicação ali.

## O que fica guardado, e por quanto tempo

As bases finais do bot (perguntas e respostas, e Sugestões, ambas sem
autor) ficam indefinidamente — é o que o bot usa para responder. O
histórico bruto e os arquivos intermediários usados durante o
processamento ainda contêm nome e número de quem escreveu; são apagados
depois de um prazo definido, não ficam guardados para sempre. Os arquivos
intermediários da base de Sugestões (menções e sugestões) não têm autor,
mas seguem o mesmo prazo. O registro de conversas com o bot (pergunta
feita, resposta dada) é guardado por 30 dias e depois apagado
automaticamente.

## Base legal

O tratamento se apoia em interesse legítimo (ajudar a comunidade a
encontrar respostas e indicações), com as salvaguardas acima. Detalhes em
[`BASE_LEGAL.md`](./BASE_LEGAL.md).

## Como pedir a remoção das suas mensagens

Mande uma mensagem direto para quem administra o bot pedindo a remoção.
Não é preciso justificar, e pode ser feito a qualquer momento — inclusive
sobre mensagens antigas já processadas. A remoção vale também para as
indicações que você escreveu: as mensagens são retiradas do histórico, os
arquivos intermediários das duas bases são apagados e a base de Sugestões
é reconstruída a partir do histórico já sem as suas mensagens.

## Como pedir para um negócio não aparecer como sugestão

Se você é dono ou dona de um negócio e não quer que ele seja indicado pelo
bot, mande uma mensagem direto para quem administra o bot com o nome do
negócio. Não é preciso justificar. O nome entra numa lista de exclusão que
é aplicada a cada reconstrução da base de Sugestões, antes de qualquer
contagem, então o negócio deixa de ser oferecido.
