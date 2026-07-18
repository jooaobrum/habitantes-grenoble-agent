# Golden Dataset v2 — Review Doc

**66 candidates.** For each case, add your verdict on the `> Verdict:` line: `T` (approve as-is), `F` (drop), or `EDIT: <what to change>`.

Everything below is grounded: `kb` cases cite a real thread_id from the synthesized corpus that feeds the production Qdrant KB (`synthesis_results.jsonl`); `web`/`kb_web` facts were verified live via WebSearch on 2026-07-18, sources given in *Grounded in*. Two `kb_web` cases (marked ⚠️) have a KB anchor with `answer_confirmed=False` (community-sourced, not human-reviewed) — please look at those two extra carefully.

---

## A. KB-grounded cases

*Anchored to a real WhatsApp thread in `artifacts/chat-19012021-20022026/synthesis_results.jsonl` — the same corpus that feeds the production Qdrant KB. Graded on retrieval (thread_id) + answer content.*

### 1. `bank-basic-01`  —  Banking & Finance  ·  basic/regression
**Q:** Qual é o endereço pra mandar minha declaração de imposto de renda por correio aqui em Grenoble?

**Ground truth:** Centre des finances publiques, 38 Av. Rhin et Danube, 38100 Grenoble.

**Keywords:** Centre des finances publiques, 38 Av. Rhin et Danube, 38100 Grenoble, correio
**Thread IDs:** 1923
**Grounded in:** synthesis_results#thread-1923 (confirmed, conf=1.0)
**Notes:** Simple factual address lookup.

> Verdict: T

### 2. `bank-basic-02`  —  Banking & Finance  ·  basic/regression
**Q:** Quais bancos franceses vocês recomendam pra eu abrir conta?

**Ground truth:** BNP Paribas e Boursorama são recomendados. Boursorama exige passaporte europeu ou visto de longa duração (não o titre de 1 ano); alternativa é abrir conta virtual na La Poste primeiro, pegar o RIB, e depois usar isso pra abrir no Boursorama.

**Keywords:** BNP Paribas, Boursorama, La Poste, RIB, passaporte europeu, visto de longa duração
**Thread IDs:** 1512
**Grounded in:** synthesis_results#thread-1512 (confirmed, conf=0.9)


> Verdict: Edit: T, but Revolut é similar ao boursorama e bastante confiavel.


### 3. `bank-edge-01`  —  Banking & Finance  ·  edge/capability
**Q:** É obrigatório informar o CPF (tax ID) pra abrir conta no N26 na França? Minha amiga está tentando e não está funcionando.

**Ground truth:** Não é obrigatório informar o CPF/tax ID para abrir conta no N26 na França. É necessário um endereço europeu válido. O app pede telefone, mas dá pra usar e-mail e solicitar número novo pelo próprio app.

**Keywords:** N26, tax ID, CPF, não é obrigatório, endereço europeu, RIB francês
**Thread IDs:** 1470
**Grounded in:** synthesis_results#thread-1470 (confirmed, conf=0.9)
**Notes:** Multi-part troubleshooting question, tests nuanced retrieval.

> Verdict: T

### 4. `daily-basic-01`  —  Daily Life & Services  ·  basic/regression
**Q:** Onde eu compro adaptador de tomada de 3 pinos padrão francês no centro de Grenoble?

**Ground truth:** Na FNAC, perto da Victor Hugo, no centro de Grenoble. Preço em torno de 12 euros.

**Keywords:** FNAC, Victor Hugo, adaptador, 12 euros
**Thread IDs:** 2075
**Grounded in:** synthesis_results#thread-2075 (confirmed, conf=1.0)

> Verdict: T

### 5. `daily-basic-02`  —  Daily Life & Services  ·  basic/regression
**Q:** Onde eu descarto remédios vencidos aqui em Grenoble?

**Ground truth:** Nas farmácias de Grenoble. Retire as caixas e papéis, entregando só o mínimo de embalagem junto com o remédio.

**Keywords:** farmácias, medicamentos vencidos, descarte
**Thread IDs:** 537
**Grounded in:** synthesis_results#thread-537 (confirmed, conf=1.0)

> Verdict: T

### 6. `daily-edge-01`  —  Daily Life & Services  ·  edge/capability
**Q:** Como funciona a questão do combustível quando eu alugo carro pelo Getaround? Devolvo com o tanque cheio?

**Ground truth:** No Getaround o carro pode ser entregue com qualquer nível de combustível; você devolve com o mesmo nível recebido. Devolver com mais gera reembolso, com menos gera cobrança. Recomenda-se fotografar o carro e o nível de combustível ao pegar e devolver.

**Keywords:** getaround, combustível, reembolso, fotos, mesmo nível
**Thread IDs:** 2504
**Grounded in:** synthesis_results#thread-2504 (confirmed, conf=0.95)

> Verdict: T

### 7. `docs-basic-01`  —  Documents & Bureaucracy  ·  basic/regression
**Q:** Minha prima perdeu o passaporte aqui na França. Ela consegue voltar pro Brasil só com o RG?

**Ground truth:** Ela precisa registrar boletim de ocorrência na delegacia local e depois contatar o consulado brasileiro pra pedir autorização de retorno ao Brasil. O RG sozinho não basta pra voo internacional.

**Keywords:** boletim de ocorrência, delegacia, consulado, autorização de retorno, RG não é suficiente
**Thread IDs:** 1121
**Grounded in:** synthesis_results#thread-1121 (confirmed, conf=1.0)

> Verdict: T

### 8. `docs-basic-02`  —  Documents & Bureaucracy  ·  basic/regression
**Q:** Pra legalizar documento brasileiro aqui, qual é a ordem certa: apostila primeiro ou tradução juramentada primeiro?

**Ground truth:** Primeiro a apostila, depois a tradução juramentada.

**Keywords:** apostila, tradução juramentada, ordem, primeiro a apostila
**Thread IDs:** 2516
**Grounded in:** synthesis_results#thread-2516 (confirmed, conf=0.9)

> Verdict: T

### 9.  `docs-edge-01`  —  Documents & Bureaucracy  ·  edge/capability
**Q:** Um tradutor juramentado reconhecido no Brasil serve pra traduzir minha CNH na troca pelo permis de conduire francês, ou precisa ser tradutor daqui?

**Ground truth:** A tradução precisa ser feita por tradutor habilitado na França. Se for feita fora da França, precisa ser apostilada/legalizada. Em geral, traduções juramentadas feitas no Brasil são aceitas se apostiladas.

**Keywords:** tradutor habilitado, apostilada, legalizada, permis de conduire, CNH
**Thread IDs:** 1738
**Grounded in:** synthesis_results#thread-1738 (confirmed, conf=0.9)

> Verdict: T

### 10. `food-basic-01`  —  Food & Restaurants  ·  basic/regression
**Q:** Onde eu compro polvilho doce e polvilho azedo em Grenoble?

**Ground truth:** Na Tienda Latina e no supermercado NOSSO em Grenoble.

**Keywords:** Tienda Latina, NOSSO, polvilho
**Thread IDs:** 2624
**Grounded in:** synthesis_results#thread-2624 (confirmed, conf=1.0)

> Verdict: T, Edit: mas deve verificar disponibilidade.

### 11. `food-basic-02`  —  Food & Restaurants  ·  basic/regression
**Q:** Onde eu acho azeite de dendê em Grenoble?

**Ground truth:** No Le Carré Asiatique, em Saint Martin d'Hères.

**Keywords:** Le Carré Asiatique, Saint Martin d'Hères, azeite de dendê
**Thread IDs:** 1281
**Grounded in:** synthesis_results#thread-1281 (confirmed, conf=1.0)

> Verdict: T, mas no NOSSO também deve ter, geralmente.

### 12. `hair-basic-01`  —  Hair & Beauty  ·  basic/regression
**Q:** Alguém indica cabeleireiro em Grenoble que saiba cortar cabelo cacheado?

**Ground truth:** Salão Interlude, na rue Thiers — peça pra cortar com o Frank.

**Keywords:** Interlude, rue Thiers, Frank, cacheado
**Thread IDs:** 2342
**Grounded in:** synthesis_results#thread-2342 (confirmed, conf=0.95)

> Verdict: Edit: Salao Interlude, entre outros que podem ser encontrados ao redor da Victor Hugo. Ache na internet.

### 13. `hair-basic-02`  —  Hair & Beauty  ·  basic/regression
**Q:** Onde eu acho secador de cabelo com difusor em Grenoble?

**Ground truth:** Em lojas de perfumaria, e também em supermercados como Lidl (preços mais acessíveis).

**Keywords:** perfumaria, Lidl, secador, difusor
**Thread IDs:** 409
**Grounded in:** synthesis_results#thread-409 (confirmed, conf=1.0)

> Verdict: T, na normal também acha.

### 14. `health-basic-01`  —  Health & Insurance  ·  basic/regression
**Q:** Tem farmácia aberta aos domingos em Grenoble? Como acho uma de plantão?

**Ground truth:** Consulte as farmácias de plantão pelo site pharmanity.com/blog/pharmacie-de-garde-grenoble, que lista as farmácias abertas em regime de plantão.

**Keywords:** pharmacie de garde, pharmanity.com, domingo, plantão
**Thread IDs:** 2447
**Grounded in:** synthesis_results#thread-2447 (confirmed, conf=1.0)

> Verdict: T. Geralmente a da Foch esta aberta, mas o ideal é consultar o site.

### 15. `health-basic-02`  —  Health & Insurance  ·  basic/regression
**Q:** Como acho um médecin traitant em Grenoble que esteja aceitando pacientes novos?

**Ground truth:** Fique de olho no Doctolib, às vezes aparecem vagas abertas de generalistas. Também vale tentar contato direto com médicos; não precisa dizer que é a primeira consulta.

**Keywords:** médecin traitant, Doctolib, novos pacientes, vagas
**Thread IDs:** 2334
**Grounded in:** synthesis_results#thread-2334 (confirmed, conf=0.95)

> Verdict: T, indicacao tambem funciona.

### 16. `health-edge-01`  —  Health & Insurance  ·  edge/capability
**Q:** Preciso passar pelo médico generalista antes de consultar um endocrinologista pelo sistema público, ou posso ir direto?

**Ground truth:** Sim, para consultar um endocrinologista pelo sistema público é necessário ter carta de encaminhamento do médico generalista. Sem isso, a consulta é cobrada integralmente sem reembolso pela seguridade social.

**Keywords:** encaminhamento, médecin généraliste, endocrinologista, reembolso, seguridade social
**Thread IDs:** 1802
**Grounded in:** synthesis_results#thread-1802 (confirmed, conf=0.95)
**Notes:** Tests the parcours de soins coordonnés rule, a common point of confusion.

> Verdict: T, Edit: sécurité sociale

### 17. `housing-basic-01`  —  Housing & CAF  ·  basic/regression
**Q:** Meu Visale venceu, dá pra renovar ou preciso pedir tudo de novo?

**Ground truth:** O Visale não pode ser renovado. É necessário fazer uma nova solicitação, seguindo o mesmo procedimento da primeira vez.

**Keywords:** Visale, não pode ser renovado, nova solicitação, garantia
**Thread IDs:** 1418
**Grounded in:** synthesis_results#thread-1418 (confirmed, conf=1.0)

> Verdict: T

### 18. `housing-basic-02`  —  Housing & CAF  ·  basic/regression
**Q:** A CAF aceita a certidão de nascimento com tradução juramentada que eu já fiz no Brasil, ou preciso refazer aqui na França?

**Ground truth:** A CAF aceitou a certidão de nascimento com tradução juramentada feita no Brasil, sem precisar refazer na França.

**Keywords:** CAF, certidão de nascimento, tradução juramentada, Brasil, aceitou
**Thread IDs:** 480
**Grounded in:** synthesis_results#thread-480 (confirmed, conf=0.9)

> Verdict: T

### 19. `housing-edge-01`  —  Housing & CAF  ·  edge/capability
**Q:** Como faço pra conseguir o abonnement pastel (desconto no transporte) pelo site da CAF?

**Ground truth:** Dá pra solicitar pelo site da CAF. Para conseguir o abonnement pastel por 2,50€/mês, vá ao ponto de venda Alsace Lorraine com seu Avis d'imposition, comprovando que é estudante ou baixa renda, e leve o comprovante de recebimento da CAF do mês anterior.

**Keywords:** abonnement pastel, Alsace Lorraine, Avis d'imposition, 2,50 euros, CAF
**Thread IDs:** 1151
**Grounded in:** synthesis_results#thread-1151 (confirmed, conf=0.9)
**Notes:** Multi-step niche procedure, good capability test.

> Verdict: T

### 20. `integ-basic-01`  —  Integration & Language  ·  basic/regression
**Q:** Vale mais a pena fazer o curso intensivo do CUEF na UGA ou outro curso de francês em Grenoble?

**Ground truth:** O CUEF na UGA é considerado o melhor. Oferece cursos intensivos como o DUEF (4 meses), mais barato que o curso intensivo tradicional e com diploma reconhecido em toda a França.

**Keywords:** CUEF, UGA, DUEF, diploma reconhecido, 4 meses
**Thread IDs:** 2848
**Grounded in:** synthesis_results#thread-2848 (confirmed, conf=0.9)

> Verdict: T: o melhor de acordo com o Grupo. O melhor para estudantes talvez.

### 21. `integ-basic-02`  —  Integration & Language  ·  basic/regression
**Q:** Tem algum site confiável pra corrigir texto em francês que não seja um tradutor?

**Ground truth:** Bonpatron pra correção de texto em francês. Reverso também é boa opção pra parágrafos.

**Keywords:** Bonpatron, Reverso, correção, gramática
**Thread IDs:** 178
**Grounded in:** synthesis_results#thread-178 (confirmed, conf=1.0)

> Verdict: T: chatgpt, qualquer IA. Questao antiga, possivelmente

### 22. `market-basic-01`  —  Marketplace & Buy/Sell  ·  basic/regression
**Q:** Que site vocês recomendam pra comprar eletrônico usado na França?

**Ground truth:** Back Market (backmarket.fr).

**Keywords:** Back Market, eletrônicos usados
**Thread IDs:** 2294
**Grounded in:** synthesis_results#thread-2294 (confirmed, conf=1.0)

> Verdict: T: edit: Leboncoin tambem

### 23. `market-basic-02`  —  Marketplace & Buy/Sell  ·  basic/regression
**Q:** Onde eu compro móveis e eletrodomésticos pra mobiliar meu apê em Grenoble?

**Ground truth:** Móveis: Ikea, Leboncoin ou marketplaces de usados. Eletrodomésticos: grandes supermercados como Leclerc e Carrefour, ou lojas especializadas como Boulanger.

**Keywords:** Ikea, Leboncoin, Leclerc, Carrefour, Boulanger
**Thread IDs:** 2457
**Grounded in:** synthesis_results#thread-2457 (confirmed, conf=0.95)

> Verdict: T

### 24. `safety-basic-01`  —  Neighbourhood & Safety  ·  basic/regression
**Q:** Quais lugares em Grenoble são considerados mais perigosos pra mulher andar sozinha à noite?

**Ground truth:** Locais como o Parc Paul Mistral à noite e áreas próximas à gare podem apresentar mais risco. Recomenda-se evitar esses locais sozinha à noite.

**Keywords:** Parc Paul Mistral, gare, à noite, cautela
**Thread IDs:** 1251
**Grounded in:** synthesis_results#thread-1251 (confirmed, conf=0.9)

> Verdict: T: Saint Bruno também

### 25. `safety-basic-02`  —  Neighbourhood & Safety  ·  basic/regression
**Q:** É tranquilo andar à noite em Grenoble ou tem muito problema de segurança?

**Ground truth:** Grenoble é relativamente tranquila comparada ao Brasil. Existem locais melhores de evitar à noite, mas em geral é seguro circular sem preocupação excessiva.

**Keywords:** relativamente tranquila, evitar à noite, seguro circular
**Thread IDs:** 282
**Grounded in:** synthesis_results#thread-282 (confirmed, conf=0.9)

> Verdict: T

### 26. `nightlife-basic-01`  —  Nightlife & Events  ·  basic/regression
**Q:** A feira de Natal de Grenoble funciona até quando, mesmo perto do Natal?

**Ground truth:** Funciona diariamente das 10h às 21h até o dia 24 de dezembro.

**Keywords:** feira de Natal, 10h às 21h, 24 de dezembro, diariamente
**Thread IDs:** 2811
**Grounded in:** synthesis_results#thread-2811 (confirmed, conf=0.9)
**Notes:** Note: specific dates are event-year-bound (marché de Noël happens every year but exact 2026 dates should be re-verified if reused long-term).

> Verdict: T

### 27. `nightlife-basic-02`  —  Nightlife & Events  ·  basic/regression
**Q:** As casinhas de madeira que estão montando na Victor Hugo são do Marché de Noël? Já abriu?

**Ground truth:** Sim, são do Marché de Noël, que abre no dia 24 de novembro.

**Keywords:** Marché de Noël, Victor Hugo, 24 de novembro
**Thread IDs:** 1056
**Grounded in:** synthesis_results#thread-1056 (confirmed, conf=1.0)
**Notes:** Same date caveat as above.

> Verdict: T: Edit: questao pontual. Nao é util para atualidade. Deveria buscar na internet a data e julgar se é util ou nao.

### 28. `pets-basic-01`  —  Pets & Animals  ·  basic/regression
**Q:** Como faço o passaporte europeu do meu cachorro na França, já tenho o certificado veterinário internacional do Brasil?

**Ground truth:** Leve o animal a um veterinário local com o certificado veterinário internacional (CVI) emitido no Brasil. O veterinário registra o cachorro no sistema francês e emite o passaporte europeu.

**Keywords:** veterinário, CVI, passaporte europeu, registro
**Thread IDs:** 1392
**Grounded in:** synthesis_results#thread-1392 (confirmed, conf=0.9)

> Verdict: T

### 29. `pets-basic-02`  —  Pets & Animals  ·  basic/regression
**Q:** Tem alguma loja tipo Cobasi ou Petz em Grenoble?

**Ground truth:** Tem uma loja parecida no bairro Comboire.

**Keywords:** Comboire, loja de pets
**Thread IDs:** 1454
**Grounded in:** synthesis_results#thread-1454 (confirmed, conf=0.9)

> Verdict: Edit: Existe ha Animalis no centro. Procure na internet se ha poucos contextos relacionado ao grupo.

### 30. `phone-basic-01`  —  Phone & Telecom  ·  basic/regression
**Q:** Como funciona o cancelamento da internet da Free e a devolução do roteador?

**Ground truth:** Cancele pelo site (de preferência no navegador modo computador). A Free manda por e-mail as instruções pra devolução do roteador, geralmente via point relais, sem precisar ir a uma loja.

**Keywords:** Free, cancelamento, roteador, point relais
**Thread IDs:** 2367
**Grounded in:** synthesis_results#thread-2367 (confirmed, conf=0.9)

> Verdict: T

### 31. `phone-basic-02`  —  Phone & Telecom  ·  basic/regression
**Q:** Qual é a melhor solução de chip pra eu passar um mês na Europa?

**Ground truth:** Symma Mobile: cerca de 10€ por 1 mês, 40GB pra França + 10GB pra resto da Europa. Vendido em lojas de informática, como no centro comercial Saint Bruno.

**Keywords:** Symma Mobile, 40 GB, Saint Bruno, pré-pago
**Thread IDs:** 1403
**Grounded in:** synthesis_results#thread-1403 (confirmed, conf=0.9)

> Verdict: T: Symma Mobile foi indicada no grupo mas uma pesquisa na web melhoria o resultado. Free, SFR, todas com cartao pre pago sao ok.

### 32. `phone-edge-01`  —  Phone & Telecom  ·  edge/capability
**Q:** O plano B&You da Bouygues cobra a mais por usar dados móveis na Suíça?

**Ground truth:** Sim, o B&You (linha low-cost da Bouygues) cobra pelo uso de dados na Suíça. É preciso checar no site oficial quais países estão incluídos na cobertura do plano.

**Keywords:** B&You, Suíça, dados móveis, cobra
**Thread IDs:** 2271
**Grounded in:** synthesis_results#thread-2271 (confirmed, conf=0.9)

> Verdict: T

### 33. `ski-basic-01`  —  Ski & Trekking  ·  basic/regression
**Q:** Qual é a diferença entre o forfait de esqui jeune e o adulte?

**Ground truth:** O passe jeune é pra quem tem até 26 anos; o adulte é pra maiores de 26. A escolha depende da idade, e o jeune costuma ter preço reduzido.

**Keywords:** passe jeune, até 26 anos, passe adulte, idade
**Thread IDs:** 1070
**Grounded in:** synthesis_results#thread-1070 (confirmed, conf=0.9)

> Verdict: T

### 34. `ski-basic-02`  —  Ski & Trekking  ·  basic/regression
**Q:** Quanto tempo leva pra subir a Bastilha a pé e onde começa a trilha?

**Ground truth:** A trilha pode começar pelo Jardim Dauphinois. A subida a pé leva de 30 a 45 minutos, dependendo do ritmo.

**Keywords:** Jardim Dauphinois, 30 a 45 minutos, trilha, Bastilha
**Thread IDs:** 1506
**Grounded in:** synthesis_results#thread-1506 (confirmed, conf=0.9)

> Verdict: T: Jardin Dauphinois ou Fonte do Leao ao lado da Vieux Manoir.

### 35. `sports-basic-01`  —  Sports & Activities  ·  basic/regression
**Q:** Tem piscina em Grenoble com aula de natação ou nado livre pra adulto?

**Ground truth:** Les Dauphins e Bulle d'O oferecem opções de natação adulta, incluindo aulas e nado livre.

**Keywords:** Les Dauphins, Bulle d'O, natação adulta, nado livre
**Thread IDs:** 1538
**Grounded in:** synthesis_results#thread-1538 (confirmed, conf=0.9)

> Verdict: T

### 36. `sports-basic-02`  —  Sports & Activities  ·  basic/regression
**Q:** Como eu consigo o certificado médico pra praticar esporte em Grenoble?

**Ground truth:** Se for estudante, pode fazer a avaliação no Centre de Santé da UGA. Caso contrário, peça ao seu médecin traitant.

**Keywords:** Centre de Santé UGA, médecin traitant, estudante
**Thread IDs:** 905
**Grounded in:** synthesis_results#thread-905 (confirmed, conf=0.9)

> Verdict: T

### 37. `travel-basic-01`  —  Travel & Transport  ·  basic/regression
**Q:** Preciso pagar a vinheta suíça pra ir de carro até o aeroporto de Genebra?

**Ground truth:** Não é necessário pagar a vignette suíça pra ir de carro ao aeroporto de Genebra, desde que evite a autoroute (rodovia com placas verdes) na Suíça.

**Keywords:** vignette, Suíça, aeroporto de Genebra, autoroute, não é necessário
**Thread IDs:** 2117
**Grounded in:** synthesis_results#thread-2117 (confirmed, conf=1.0)

> Verdict: T

### 38. `travel-basic-02`  —  Travel & Transport  ·  basic/regression
**Q:** Qual é o melhor aeroporto pra chegar em Grenoble vindo de Guarulhos (São Paulo)?

**Ground truth:** Lyon Saint-Exupéry é o mais próximo e a melhor opção pra maioria dos horários. Tem FlixBus saindo quase toda hora do aeroporto pra Grenoble. Se a chegada for de madrugada em Genebra, o transporte até Grenoble pode não ser viável economicamente.

**Keywords:** Lyon Saint-Exupéry, FlixBus, aeroporto, Genebra
**Thread IDs:** 2608
**Grounded in:** synthesis_results#thread-2608 (confirmed, conf=0.95)

> Verdict: T

### 39. `travel-edge-01`  —  Travel & Transport  ·  edge/capability
**Q:** É mais complicado chegar ao centro de Paris saindo do aeroporto de Orly do que do Charles de Gaulle?

**Ground truth:** Ambos são acessíveis via transporte público (RER B), mas em Orly hoje é necessário completar com metrô, o que torna o trajeto um pouco menos direto que o CDG.

**Keywords:** Orly, Charles de Gaulle, RER B, metrô, menos direto
**Thread IDs:** 1879
**Grounded in:** synthesis_results#thread-1879 (confirmed, conf=0.9)

> Verdict: T: Se nao me engano, 14 euros o bilhete. Procurar na web talvez pra confirmar.

### 40. `univ-basic-01`  —  University & Studies  ·  basic/regression
**Q:** A taxa CVEC dá pra pagar em dinheiro presencialmente ou é só online?

**Ground truth:** A CVEC normalmente deve ser paga online pelo site oficial. Se tiver dificuldade, o CROUS pode orientar sobre alternativas, mas pagamento presencial em dinheiro não é o procedimento padrão.

**Keywords:** CVEC, online, CROUS, não é padrão
**Thread IDs:** 2652
**Grounded in:** synthesis_results#thread-2652 (confirmed, conf=0.95)
**Notes:** No amount given in KB — see univ-kbweb-01 for the current 2025-2026 amount (105€).

> Verdict: T

### 41. `univ-basic-02`  —  University & Studies  ·  basic/regression
**Q:** Quais são os feriados de abril e maio na UGA? Dia 8 e 9 de maio são os dois feriados?

**Ground truth:** 8 e 9 de maio são feriados nacionais, e a UGA também observa esses feriados.

**Keywords:** UGA, feriados nacionais, 8 de maio, 9 de maio
**Thread IDs:** 1711
**Grounded in:** synthesis_results#thread-1711 (confirmed, conf=0.9)
**Notes:** Note: national holiday dates are fixed annually by the French calendar — true for the year in question, verify if reused as-is in a future year.

> Verdict: T

### 42. `univ-edge-01`  —  University & Studies  ·  edge/capability
**Q:** Quanto custa pra se preparar e fazer a prova teórica da carteira de motorista na França?

**Ground truth:** Dá pra se preparar barato usando plataformas online como a Ornikar (cerca de 0,99€/mês). A prova teórica exige acertar 35 de 40 questões, com 20 segundos por questão.

**Keywords:** Ornikar, prova teórica, 35 de 40, carteira de motorista
**Thread IDs:** 1667
**Grounded in:** synthesis_results#thread-1667 (confirmed, conf=0.9)
**Notes:** Price (0,99€/mês) may be a promo rate — flag as possibly time-sensitive, but not verified outdated.

> Verdict: T: Edit 2,99 o mes

### 43. `visa-basic-01`  —  Visa & Residency  ·  basic/regression
**Q:** Alguém sabe qual é o e-mail da OFII em Grenoble? Preciso mandar um documento pra eles.

**Ground truth:** O e-mail da OFII em Grenoble é bai-grenoble@ofii.fr.

**Keywords:** OFII, e-mail, bai-grenoble@ofii.fr, Grenoble
**Thread IDs:** 1948
**Grounded in:** synthesis_results#thread-1948 (confirmed, conf=1.0)
**Notes:** Simple factual lookup, high-confidence confirmed KB entry.

> Verdict:

### 44. `visa-basic-02`  —  Visa & Residency  ·  basic/regression
**Q:** Como e onde eu compro o timbre fiscal pro meu titre de séjour?

**Ground truth:** O timbre fiscal para o titre de séjour pode ser adquirido online pelo site oficial do governo francês (service-public.fr). Alguns recomendam pagar via Wise por ser mais barato.

**Keywords:** timbre fiscal, titre de séjour, service-public.fr, online, Wise
**Thread IDs:** 1265
**Grounded in:** synthesis_results#thread-1265 (confirmed, conf=1.0)
**Notes:** Note: does NOT include the amount — see visa-kbweb-01 for the current price, which changed materially in 2026.

> Verdict: T: Edit: 250 €
Le coût pour le renouvellement d'un titre de séjour a également augmenté : le montant du timbre fiscal est fixé à 250 € depuis le 1er mai, contre 225 € avant. Le tarif minoré, qui s'applique dans les mêmes situations que pour une première délivrance, est fixé à 100 € depuis le 1er mai, contre 75 € précédemment.

### 45. `visa-edge-01`  —  Visa & Residency  ·  edge/capability
**Q:** Meu récépissé venceu e não tem nenhuma vaga de RDV pra retirar o titre de séjour em Isère. Tem algum jeito de conseguir uma data urgente?

**Ground truth:** Se o récépissé estiver expirado e não houver vaga, envie um e-mail para pref-rdv-sejour@isere.gouv.fr explicando a situação (sem vagas, ou mais de um mês desde a aprovação sem SMS). A resposta inicial costuma dizer que não dá pra agendar por e-mail, mas depois de alguns dias costumam enviar uma data.

**Keywords:** récépissé expirado, sem vaga, pref-rdv-sejour@isere.gouv.fr, urgência, titre de séjour
**Thread IDs:** 1252
**Grounded in:** synthesis_results#thread-1252 (confirmed, conf=0.95)
**Notes:** Carried over from v1 (was already well-grounded); kept almost verbatim.

> Verdict: T

### 46. `visa-edge-02`  —  Visa & Residency  ·  edge/capability
**Q:** Meu visto VLSTS Salarié foi emitido depois de 2020 e não vem escrito a referência regulamentar. Que referência eu coloco no formulário de validação?

**Ground truth:** Para validar o visto VLSTS Salarié emitido após 2020, informe a referência regulamentar CESEDA R-431. A opção CESEDA R-311 vale só para vistos antigos.

**Keywords:** CESEDA R-431, VLSTS Salarié, validação, prefeitura, CESEDA R-311
**Thread IDs:** 1789
**Grounded in:** synthesis_results#thread-1789 (confirmed, conf=0.95)
**Notes:** Niche/technical — good capability test, low general knowledge overlap.

> Verdict: T

### 47. `work-basic-01`  —  Work & Internship  ·  basic/regression
**Q:** Tem algum jeito online de calcular quanto fica o salário líquido de um bruto de 1786 euros na França?

**Ground truth:** Use uma calculadora online como salaire-brut-en-net.fr, que considera os descontos obrigatórios pra estimar o líquido.

**Keywords:** salaire-brut-en-net.fr, salário líquido, calculadora
**Thread IDs:** 1933
**Grounded in:** synthesis_results#thread-1933 (confirmed, conf=0.9)

> Verdict: T

### 48. `work-basic-02`  —  Work & Internship  ·  basic/regression
**Q:** Meu patrão não pagou meu salário depois que meu CDD terminou. O que eu faço?

**Ground truth:** Recorra ao tribunal Prud'hommes, responsável por conflitos trabalhistas na França. Reúna todas as provas do contrato e das tentativas de contato com o empregador.

**Keywords:** Prud'hommes, tribunal, CDD, provas, contrato
**Thread IDs:** 2773
**Grounded in:** synthesis_results#thread-2773 (confirmed, conf=0.9)

> Verdict: T

### 49. `work-edge-01`  —  Work & Internship  ·  edge/capability
**Q:** Pro visto 'passport talent', o diploma em si é obrigatório ou a attestation de réussite (certificado de conclusão) já serve?

**Ground truth:** Para o passport talent, o diploma em si é obrigatório — a attestation de réussite não é aceita, já que diplomas podem demorar até dois anos pra serem emitidos.

**Keywords:** passport talent, diploma, attestation de réussite, não é aceita
**Thread IDs:** 257
**Grounded in:** synthesis_results#thread-257 (confirmed, conf=0.9)
**Notes:** Common point of confusion between diploma and attestation de réussite.

> Verdict: Edit: Attestation de réussite é valida.


## B. KB ↔ Web cases

*The KB has a real anchor, but it's stale or missing a number/date that only web search can supply or correct. These are the highest-value capability cases — verify the web fact especially carefully.*

### 50. `bank-kbweb-01` ⚠️  —  Banking & Finance  ·  edge/capability
**Q:** Qual é o valor atual do bônus de boas-vindas do Boursorama pra quem abre conta?

**Ground truth:** Até 160€ (código BRSOPE160), com boosts pontuais que já chegaram a 220€ em determinados períodos — valor mudou desde a época em que a KB registrou 150€. Sempre confirmar no site oficial pois o valor varia por período.

**Keywords:** 160 euros, BRSOPE160, bônus, boas-vindas
**Thread IDs:** 1017
**Grounded in:** KB thread-1017 (answer_confirmed=FALSE, conf=0.9 — explicit '150 euros' + code JAOL1582) + WebSearch 2026-07-18: comparabanques.fr, primebanque.fr (up to 160€, code BRSOPE160)
**Notes:** FLAG: KB anchor is answer_confirmed=FALSE (community-sourced, not human-reviewed) — please double-check before approving. The KB gives a specific stale number (150€) AND a stale promo code (JAOL1582) — good test that the agent doesn't just repeat outdated numbers/codes verbatim.

> Verdict: Edit: tipical thing that may change over time, search on internet

### 51. `travel-kbweb-01`  —  Travel & Transport  ·  edge/capability
**Q:** O Ouigo vai direto de Paris pra Grenoble ou eu preciso trocar de trem no meio do caminho?

**Ground truth:** Hoje existe serviço direto Paris↔Grenoble regularmente (não só no inverno): de ~26 trens diários, cerca de 7-8 são diretos, incluindo os OUIGO. Os demais ainda fazem conexão em Lyon-Part-Dieu. Isso é mais amplo do que a informação registrada na KB, que descrevia o Ouigo direto como restrito ao inverno.

**Keywords:** OUIGO, direto, Lyon, TGV, baldeação
**Thread IDs:** 206, 229
**Grounded in:** KB thread-206 (answer_confirmed=FALSE, conf=0.9 — 'Ouigo direto só no inverno, fora disso baldeação') + thread-229 (confirmed, conf=0.9, sobre documento a levar) + WebSearch 2026-07-18: trainline.com, sncf-connect.com (direct OUIGO/TGV service year-round in 2026)
**Notes:** HIGH VALUE case, but flag: the KB anchor (thread-206) is answer_confirmed=FALSE (community-sourced, not human-reviewed) — please double-check this one specifically before approving. Still a strong illustration of why info_might_be_outdated / web fallback matters.

> Verdict: T

### 52. `univ-kbweb-01`  —  University & Studies  ·  edge/capability
**Q:** Qual é o valor exato da taxa CVEC pra esse ano letivo?

**Ground truth:** 105€ para o ano letivo 2025-2026 (pago em cvec.etudiant.gouv.fr). Bolsistas, alunos Erasmus e alguns outros perfis são isentos.

**Keywords:** CVEC, 105 euros, cvec.etudiant.gouv.fr, isentos, bolsistas
**Thread IDs:** 2652
**Grounded in:** KB thread-2652 (confirmed, no amount given) + WebSearch 2026-07-18: mes-allocs.fr, droit-finances.commentcamarche.com (105€ for 2025-2026)
**Notes:** KB chunk is retrievable but incomplete (no amount) — tests whether agent supplements with web_search_grenoble rather than leaving the number out.

> Verdict: T: edit: accept the notes suggestion.

### 53. `visa-kbweb-01`  —  Visa & Residency  ·  edge/capability
**Q:** Quanto custa hoje o timbre fiscal pra primeira emissão do titre de séjour?

**Ground truth:** 350€ para a primeira emissão (era 225€) — aumento em vigor desde 1º de maio de 2026 (Lei de Finanças 2026, art. 128). Taxa normal foi de 200€ para 300€; taxa reduzida de 50€ para 100€.

**Keywords:** 350 euros, aumentou, 1º de maio de 2026, timbre fiscal
**Thread IDs:** 1265
**Grounded in:** KB thread-1265 (confirmed, mentions timbre fiscal but no amount) + WebSearch 2026-07-18: service-public.gouv.fr, prefecturedepolice.interieur.gouv.fr, karlwaheed.fr (350€ since 2026-05-01)
**Notes:** HIGH VALUE: major, recent regulatory fee change (nearly doubled) — a case where an un-updated KB (or model's training-data knowledge) would badly mislead a user on cost.

> Verdict: T


## C. Web-only cases

*No KB anchor — pure factual/current Grenoble info. Verified live via WebSearch on 2026-07-18. Graded on whether the agent used `web_search_grenoble` and got the fact right.*

### 54. `web-basic-01`  —  Daily Life & Services  ·  basic/regression
**Q:** Quantos habitantes tem Grenoble hoje em dia?

**Ground truth:** ~155.000-156.000 habitantes na cidade de Grenoble (2025, dados INSEE); a população da cidade vem em leve declínio nos últimos anos em favor das comunas vizinhas.

**Keywords:** 155, 156 mil, habitantes, Grenoble, INSEE
**Grounded in:** WebSearch 2026-07-18: bien-dans-ma-ville.fr, INSEE, placegrenet.fr (~155,254-156,140 hab. 2025)
**Notes:** Not in KB. Tests whether the agent reaches for web_search_grenoble for factual/current info per its tool description.

> Verdict: T

### 55. `web-basic-03`  —  Travel & Transport  ·  basic/regression
**Q:** Quantas linhas de tram tem em Grenoble hoje?

**Ground truth:** 5 linhas de tram (A, B, C, D e E), rede gerida pelo SMMAG (que substituiu o SMTC em 2020).

**Keywords:** 5 linhas, A, B, C, D, tram, SMMAG
**Grounded in:** WebSearch 2026-07-18: fr.wikipedia.org/Tramway_de_Grenoble, smmag.fr
**Notes:** Not in KB (the KB only has qualitative transit tips, no line count).

> Verdict: T

### 56. `web-basic-02`  —  Work & Internship  ·  basic/regression
**Q:** Qual é o valor do SMIC por hora agora?

**Ground truth:** 12,31€/hora bruto desde 1º de junho de 2026 (~1.867,02€/mês bruto para 35h semanais).

**Keywords:** SMIC, 12,31, hora, bruto
**Grounded in:** WebSearch 2026-07-18: info.gouv.fr, urssaf.fr (SMIC horaire brut 12,31€ from 2026-06-01)
**Notes:** Current-fact test; SMIC is revised ~1-2x/year so this needs periodic re-verification to stay a regression case.

> Verdict: T


## D. Negative cases

*Two families: (D1) out-of-scope — not about Grenoble, should be refused/redirected. (D2) empty-KB / unknowable — a real Grenoble topic but with no retrievable answer or asking for live/personal data; the agent must NOT fabricate specifics.*

### 57. `neg-empty-01`  —  Health & Insurance  ·  edge/capability
**Q:** Alguém sabe se o Dr. Fabiano Almeida da Rue das Estrelas em Grenoble ainda está aceitando pacientes novos?

**Ground truth:** N/A — fabricated doctor/street name, no real match in KB or web. The agent must NOT invent an answer; it should say it doesn't have this specific information rather than fabricating a doctor or address.

**Grounded in:** constructed negative (fictitious entity, tests anti-hallucination fallback)
**Notes:** Fictitious name/street chosen to guarantee empty retrieval; verify no accidental real-world match before finalizing.

> Verdict: T

### 58. `neg-empty-05`  —  Housing & CAF  ·  edge/capability
**Q:** Quantos dias exatos falta pra minha CAF processar meu pedido de auxílio-moradia?

**Ground truth:** N/A — user-specific case status, not knowable from KB (general community history) or web. Agent should explain typical process/timelines from KB patterns without inventing a specific personal ETA.

**Grounded in:** constructed negative (personal case status, tests that general KB patterns aren't presented as a personal guarantee)
**Notes:** Subtler than neg-empty-03/04: tests that the agent gives general info without pretending it's the user's specific case status.

> Verdict: T

### 59. `neg-empty-02`  —  Visa & Residency  ·  edge/capability
**Q:** Qual é o tempo de espera exato agora, hoje, pra conseguir um RDV na prefeitura de Grenoble pra renovação de titre de séjour?

**Ground truth:** N/A — real-time queue/wait data that neither the KB (static community history) nor web_search (not a live queue API) can know precisely. Agent should give general guidance (based on KB patterns) but must not invent a specific current wait time as if it were live data.

**Grounded in:** constructed negative (unknowable live data, tests anti-hallucination fallback)
**Notes:** Distinguish from visa-edge-01: that case has a real KB-grounded workaround; this one asks for a live number nobody has.

> Verdict: T

### 60. `neg-empty-03`  —  (no category — negative case)  ·  basic/regression
**Q:** Qual é meu número de dossiê na ANEF?

**Ground truth:** N/A — personal/account-specific data the bot has no access to. Must not fabricate a dossier number.

**Grounded in:** constructed negative (personal data the bot cannot know)

> Verdict: T

### 61. `neg-empty-04`  —  (no category — negative case)  ·  basic/regression
**Q:** Quantas pessoas estão no grupo do WhatsApp Habitantes de Grenoble hoje?

**Ground truth:** N/A — live internal community data not available to KB or web tools. Must not invent a member count.

**Grounded in:** constructed negative (live data outside any tool's reach)

> Verdict: T

### 62. `neg-oos-01`  —  (no category — negative case)  ·  basic/regression
**Q:** Qual é a capital da Alemanha?

**Ground truth:** N/A — out of scope. The agent should identify this as unrelated to Grenoble and decline/redirect, not answer general world trivia.

**Grounded in:** constructed negative (intent=out_of_scope)
**Notes:** Tests the out_of_scope intent branch in intent.py.

> Verdict: T

### 63. `neg-oos-02`  —  (no category — negative case)  ·  basic/regression
**Q:** Como faço pra tirar visto de estudante pra estudar em Lisboa, Portugal?

**Ground truth:** N/A — out of scope. Different country/city, not Grenoble, even though topically similar (visa/study).

**Grounded in:** constructed negative (intent=out_of_scope)
**Notes:** Tests that topical similarity (visa/study) doesn't fool the classifier when the location isn't Grenoble.

> Verdict: T

### 64. `neg-oos-03`  —  (no category — negative case)  ·  basic/regression
**Q:** Você pode escrever um poema curto sobre o outono pra mim?

**Ground truth:** N/A — out of scope. Generic creative request unrelated to Grenoble.

**Grounded in:** constructed negative (intent=out_of_scope)

> Verdict: T

### 65. `neg-oos-04`  —  (no category — negative case)  ·  basic/regression
**Q:** Qual é o melhor bairro pra morar em Paris perto da Torre Eiffel?

**Ground truth:** N/A — out of scope. Another French city (Paris), not Grenoble.

**Grounded in:** constructed negative (intent=out_of_scope)
**Notes:** Same-country-different-city trap — checks the classifier isn't just keying on 'França'.

> Verdict: T

### 66. `neg-oos-05`  —  (no category — negative case)  ·  basic/regression
**Q:** Como faço um bolo de chocolate sem farinha?

**Ground truth:** N/A — out of scope. General cooking question, not a Grenoble community/local topic.

**Grounded in:** constructed negative (intent=out_of_scope)

> Verdict: T
