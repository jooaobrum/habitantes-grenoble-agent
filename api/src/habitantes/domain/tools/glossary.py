"""Domain glossary for Habitantes de Grenoble knowledge base.

Each entry maps a *normalized* term (lowercase, no accents) to a short
human-readable description.  The normalized form is what gets matched
against the query at runtime; the description is purely documentary.

Built from corpus analysis of 2,853 KB entries (2021-2026).

Usage
-----
    from habitantes.domain.glossary import TERM_KEYS, GLOSSARY
    # TERM_KEYS: tuple[str] sorted longest-first for greedy matching
    # GLOSSARY : dict[normalized_term, description]
"""

# ── Glossary ──────────────────────────────────────────────────────────────────
# Key   : normalized term (lowercase + no diacritics) — used for matching
# Value : canonical label + one-line description in PT
# Multi-word entries must appear before their sub-terms (longest-first sort
# is applied automatically via TERM_KEYS below).

GLOSSARY: dict[str, str] = {
    # ── Government / Administrative ──────────────────────────────────────────
    "securite sociale": "Sécurité Sociale — sistema de seguridade social (SS)",
    "pole emploi": "Pôle Emploi / France Travail — serviço público de emprego",
    "france travail": "France Travail — novo nome do Pôle Emploi desde 2024",
    "prefecture de l isere": "Préfecture de l'Isère — administração regional de Grenoble",
    "prefecture": "Préfecture — administração regional (equivalente a prefeitura/governo estadual)",
    "caisse primaire assurance maladie": "CPAM — fundo primário de seguro saúde",
    "caisse allocations familiales": "CAF — fundo de benefícios familiares e auxílio-moradia",
    "office francais immigration integration": "OFII — órgão de imigração e integração",
    "agence nationale titres securises": "ANTS — agência de documentos seguros (passaporte, CNH)",
    "cpam": "Caisse Primaire d'Assurance Maladie — seguro saúde obrigatório",
    "ofii": "Office Français de l'Immigration et de l'Intégration",
    "ants": "Agence Nationale des Titres Sécurisés — documentos oficiais",
    "caf": "Caisse d'Allocations Familiales — APL e benefícios sociais",
    "urssaf": "URSSAF — agência de contribuições sociais (autônomos e empresas)",
    "anef": "ANEF — portal online para gestão de títulos de residência",
    "campus france": "Campus France — agência para admissão de estudantes internacionais",
    "consulado brasileiro": "Consulado do Brasil em Marselha — atende a região de Grenoble",
    "consulado brasil": "Consulado do Brasil em Marselha",
    "receita federal": "Receita Federal — autoridade fiscal brasileira",
    "impots": "Impôts.gouv.fr — declaração e pagamento de impostos na França",
    "service public": "Service-Public.fr — portal oficial de serviços governamentais",
    # ── Documents / Legal statuses ───────────────────────────────────────────
    "titre de sejour": "Titre de séjour — título/permissão de residência (TS)",
    "carte de sejour": "Carte de séjour — cartão de residência (sinônimo de titre de séjour)",
    "recepisse": "Récépissé — comprovante temporário emitido durante o processo de renovação do TS",
    "carte vitale": "Carte Vitale — cartão do seguro saúde francês",
    "permis de conduire": "Permis de conduire — carteira de motorista francesa",
    "acte de naissance": "Acte de naissance — certidão de nascimento",
    "justificatif de domicile": "Justificatif de domicile — comprovante de residência",
    "relevé identité bancaire": "RIB — dados bancários franceses (agência + conta)",
    "rib": "Relevé d'Identité Bancaire — identificação bancária para transferências",
    "iban": "IBAN — número de conta bancária internacional",
    "cnh": "CNH — Carteira Nacional de Habilitação brasileira",
    "passeport talent": "Passeport Talent — visto para trabalhadores altamente qualificados",
    "pacs": "PACS — Pacte Civil de Solidarité — união civil francesa",
    "contrat duree indeterminee": "CDI — contrato de trabalho permanente",
    "contrat duree determinee": "CDD — contrato de trabalho temporário",
    "cdi": "CDI — Contrat à Durée Indéterminée — contrato permanente",
    "cdd": "CDD — Contrat à Durée Déterminée — contrato temporário",
    "chomage": "Chômage — seguro-desemprego (allocations chômage)",
    # ── Banks / Fintech ───────────────────────────────────────────────────────
    "boursorama": "Boursorama Banque — banco digital francês com promoções para novos clientes",
    "n26": "N26 — banco digital alemão, popular entre expatriados",
    "revolut": "Revolut — carteira digital multi-moeda para transferências internacionais",
    "wise": "Wise (ex-TransferWise) — serviço de transferência internacional de dinheiro",
    "lydia": "Lydia — aplicativo francês de pagamentos e split de contas",
    "hello bank": "Hello Bank — banco online subsidiário do BNP Paribas",
    "bnp paribas": "BNP Paribas — grande banco tradicional francês",
    "societe generale": "Société Générale — grande banco tradicional francês",
    "credit mutuel": "Crédit Mutuel — banco mútuo francês",
    "pcs neosurf": "PCS/Neosurf — cupons pré-pagos (frequentemente usados em golpes de aluguel)",
    "leboncoin": "LeBonCoin — maior marketplace de segunda mão da França",
    # ── Universities / Education ──────────────────────────────────────────────
    "universite grenoble alpes": "UGA — Université Grenoble Alpes — principal universidade de Grenoble",
    "uga": "Université Grenoble Alpes — principal universidade de Grenoble",
    "ensag": "ENSAG — École Nationale Supérieure d'Architecture de Grenoble",
    "polytech grenoble": "Polytech Grenoble — escola de engenharia da UGA",
    "polytech": "Polytech Grenoble — escola de engenharia",
    "grenoble ecole management": "GEM — Grenoble École de Management — escola de negócios",
    "gem": "Grenoble École de Management — escola de negócios (não faz parte da UGA)",
    "centre universitaire etudes francaises": "CUEF — Centro de cursos intensivos de francês da UGA",
    "cuef": "CUEF — Centre Universitaire d'Études Françaises — cursos de francês na UGA",
    "duef": "DUEF — Diplôme Universitaire d'Études Françaises",
    "crous": "CROUS — Centro regional de habitação e serviços estudantis (restaurante universitário, bolsas)",
    "alliance francaise": "Alliance Française — escola e centro cultural de língua francesa",
    "cvec": "CVEC — Contribution Vie Étudiante et de Campus — taxa estudantil obrigatória anual",
    # ── Housing ───────────────────────────────────────────────────────────────
    "aide personnalisee logement": "APL — Aide Personnalisée au Logement — auxílio-moradia da CAF",
    "apl": "APL — Aide Personnalisée au Logement — benefício da CAF para ajuda com aluguel",
    "visale": "Visale — garantia de aluguel gratuita do governo para inquilinos sem fiador francês",
    "diagnostic performance energetique": "DPE — certificado de eficiência energética do imóvel",
    "dpe": "DPE — Diagnostic de Performance Énergétique — classe energética do imóvel",
    "depot garantie": "Dépôt de garantie — caução / depósito de segurança no aluguel",
    "action logement": "Action Logement — suporte habitacional para trabalhadores com vínculo empregatício",
    # ── Health ────────────────────────────────────────────────────────────────
    "mutuelle": "Mutuelle — plano de saúde complementar ao CPAM (cobre o que a SS não paga)",
    "doctolib": "Doctolib — plataforma online de agendamento médico",
    "medecin traitant": "Médecin traitant — médico de família / clínico geral cadastrado no CPAM",
    "chu grenoble": "CHU Grenoble Alpes — hospital universitário (urgências)",
    "ameli": "Ameli — portal online de gestão do seguro saúde (CPAM)",
    "100 sante": "100% Santé — programa de cobertura total para óculos, dentista e audição",
    "swisscare": "Swisscare — seguro saúde para viagem / período inicial antes do CPAM",
    # ── Transport ─────────────────────────────────────────────────────────────
    "tag": "TAG — Transports de l'Agglomération Grenobloise — ônibus e tram de Grenoble",
    "transisere": "Transisère — ônibus regionais do departamento de Isère",
    "sncf": "SNCF — ferroviária nacional francesa",
    "ouigo": "Ouigo — marca low-cost da SNCF para trajetos de trem baratos",
    "flixbus": "FlixBus — ônibus de longa distância (alternativa barata ao trem)",
    "getaround": "GetAround — plataforma de aluguel de carros compartilhados",
    "aeroport lyon": "Aéroport de Lyon Saint-Exupéry — aeroporto mais próximo de Grenoble",
    "gare grenoble": "Gare de Grenoble — estação central de trem",
    # ── Work / Professional ───────────────────────────────────────────────────
    "alternance": "Alternance — programa de estudo-trabalho (alterna períodos na empresa e na escola)",
    "auto entrepreneur": "Auto-entrepreneur — regime simplificado de trabalhador autônomo na França",
    "micro entrepreneur": "Micro-entrepreneur — sinônimo de auto-entrepreneur",
    "siret": "SIRET — número de registro de empresa / CNPJ francês",
    "stage": "Stage — estágio profissional (não remunerado ou com gratificação)",
    # ── Language / Exams ──────────────────────────────────────────────────────
    "tcf": "TCF — Test de Connaissance du Français — exame oficial de proficiência em francês",
    "delf": "DELF — Diplôme d'Études en Langue Française — diploma de francês (A1 a B2)",
    "dalf": "DALF — Diplôme Approfondi de Langue Française — diploma avançado (C1/C2)",
    "fle": "FLE — Français Langue Étrangère — ensino de francês para estrangeiros",
    # ── Telecom ───────────────────────────────────────────────────────────────
    "forfait": "Forfait — plano de telefonia móvel ou internet",
    "freebox": "Freebox — caixa de internet da operadora Free",
    # ── Food / Shopping ───────────────────────────────────────────────────────
    "requeijao": "Requeijão — produto brasileiro (difícil de encontrar em Grenoble)",
    "acai": "Açaí — produto brasileiro típico",
    "decathlon": "Décathlon — loja de artigos esportivos (esqui, trilha, etc.)",
    "grand frais": "Grand Frais — supermercado especializado em produtos frescos e internacionais",
    "carrefour": "Carrefour — rede de supermercados presente em Grenoble e região",
    "lidl": "Lidl — supermercado de desconto",
    "fnac": "FNAC — loja de eletrônicos, livros e ingressos",
    # ── Landmarks / Neighbourhoods ────────────────────────────────────────────
    "bastille": "La Bastille — monumento histórico com teleférico e vista panorâmica de Grenoble",
    "chartreuse": "Massif de la Chartreuse — maciço montanhoso ao norte de Grenoble (trilhas, esqui)",
    "chamrousse": "Chamrousse — estação de esqui mais próxima de Grenoble",
    "les deux alpes": "Les Deux Alpes — estação de esqui nos Alpes (± 1h30 de Grenoble)",
    "saint martin d heres": "Saint-Martin-d'Hères — município universitário adjacente a Grenoble",
    "echirolles": "Échirolles — município ao sul de Grenoble com o maior Carrefour da região",
    "meylan": "Meylan — município residencial a leste de Grenoble (tecnopolo)",
    "fontaine": "Fontaine — município a oeste de Grenoble",
    # ── Common chat abbreviations ─────────────────────────────────────────────
    "rdv": "RDV — rendez-vous — consulta ou agendamento",
}

# Derived tuple sorted longest-first — used for greedy matching in extract_key_terms
TERM_KEYS: tuple[str, ...] = tuple(sorted(GLOSSARY.keys(), key=len, reverse=True))
